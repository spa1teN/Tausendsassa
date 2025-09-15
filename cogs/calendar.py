# cogs/calendar.py

import asyncio
import json
import yaml
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Union
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.config import config
from core.http_client import http_client
from core.retry_handler import retry_handler
from core.cache_manager import cache_manager
from core.timezone_util import get_current_time

try:
    from icalendar import Calendar, Event as ICalEvent
    import recurring_ical_events
except ImportError:
    print("Missing required dependencies for calendar functionality:")
    print("pip install icalendar recurring-ical-events")
    exit(1)


class CalendarConfig:
    """Configuration for a single calendar"""
    
    def __init__(self, text_channel_id: int, voice_channel_id: int, ical_url: str, 
                 blacklist: List[str] = None, whitelist: List[str] = None, last_message_id: Optional[int] = None,
                 reminder_role_id: Optional[int] = None):
        self.text_channel_id = text_channel_id
        self.voice_channel_id = voice_channel_id 
        self.ical_url = ical_url
        self.blacklist = blacklist or []
        self.whitelist = whitelist or []
        self.last_message_id = last_message_id
        self.created_events: List[int] = []  # Discord event IDs
        self.event_title_to_id: Dict[str, int] = {}  # Map event titles to Discord event IDs
        self.last_sync = None
        self.current_week_start = None  # Track which week the last message belongs to
        self.reminder_role_id = reminder_role_id  # Role to ping for reminders (optional)
        self.sent_reminders: Dict[str, datetime] = {}  # Track sent reminders to avoid duplicates
        
    def to_dict(self) -> dict:
        return {
            'text_channel_id': self.text_channel_id,
            'voice_channel_id': self.voice_channel_id,
            'ical_url': self.ical_url,
            'blacklist': self.blacklist,
            'whitelist': self.whitelist,
            'last_message_id': self.last_message_id,
            'created_events': self.created_events,
            'event_title_to_id': self.event_title_to_id,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'current_week_start': self.current_week_start.isoformat() if self.current_week_start else None,
            'reminder_role_id': self.reminder_role_id,
            'sent_reminders': {k: v.isoformat() for k, v in self.sent_reminders.items()}
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CalendarConfig':
        config = cls(
            text_channel_id=data['text_channel_id'],
            voice_channel_id=data['voice_channel_id'],
            ical_url=data['ical_url'],
            blacklist=data.get('blacklist', []),
            whitelist=data.get('whitelist', []),
            last_message_id=data.get('last_message_id'),
            reminder_role_id=data.get('reminder_role_id')
        )
        config.created_events = data.get('created_events', [])
        config.event_title_to_id = data.get('event_title_to_id', {})
        if data.get('last_sync'):
            config.last_sync = datetime.fromisoformat(data['last_sync'])
        if data.get('current_week_start'):
            config.current_week_start = datetime.fromisoformat(data['current_week_start'])
        # Load sent reminders
        sent_reminders_data = data.get('sent_reminders', {})
        config.sent_reminders = {k: datetime.fromisoformat(v) for k, v in sent_reminders_data.items()}
        return config


class CalendarConfigModal(discord.ui.Modal):
    """Modal for editing calendar blacklist and whitelist"""
    
    def __init__(self, cog: 'CalendarCog', guild_id: int, calendar_id: str, calendar_config: 'CalendarConfig'):
        super().__init__(title=f"Edit Calendar: {calendar_id}")
        self.cog = cog
        self.guild_id = guild_id
        self.calendar_id = calendar_id
        self.calendar_config = calendar_config
        
        # Add blacklist field
        self.blacklist_field = discord.ui.TextInput(
            label="Blacklist Terms (comma separated)",
            placeholder="term1, term2, term3",
            default=", ".join(calendar_config.blacklist),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )
        self.add_item(self.blacklist_field)
        
        # Add whitelist field
        self.whitelist_field = discord.ui.TextInput(
            label="Whitelist Terms (comma separated)",
            placeholder="term1, term2, term3",
            default=", ".join(calendar_config.whitelist),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )
        self.add_item(self.whitelist_field)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        await interaction.response.defer()
        
        try:
            # Parse new blacklist
            blacklist_text = self.blacklist_field.value.strip()
            new_blacklist = [term.strip() for term in blacklist_text.split(',') if term.strip()] if blacklist_text else []
            
            # Parse new whitelist
            whitelist_text = self.whitelist_field.value.strip()
            new_whitelist = [term.strip() for term in whitelist_text.split(',') if term.strip()] if whitelist_text else []
            
            # Update calendar config
            self.calendar_config.blacklist = new_blacklist
            self.calendar_config.whitelist = new_whitelist
            
            # Save to disk
            self.cog._save_guild_calendars(self.guild_id)
            
            # Create success embed
            embed = discord.Embed(
                title="✅ Calendar Configuration Updated",
                color=0x00ff00
            )
            embed.add_field(name="Calendar ID", value=self.calendar_id, inline=False)
            
            if new_blacklist:
                embed.add_field(
                    name="Blacklisted Terms", 
                    value=", ".join(f"`{term}`" for term in new_blacklist), 
                    inline=False
                )
            else:
                embed.add_field(name="Blacklisted Terms", value="None", inline=False)
            
            if new_whitelist:
                embed.add_field(
                    name="Whitelisted Terms", 
                    value=", ".join(f"`{term}`" for term in new_whitelist), 
                    inline=False
                )
            else:
                embed.add_field(name="Whitelisted Terms", value="None", inline=False)
            
            embed.set_footer(text="Changes will take effect at the next hourly sync.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.cog.log.info(f"Updated calendar config for {self.calendar_id} in guild {self.guild_id}")
            
        except Exception as e:
            self.cog.log.error(f"Error updating calendar config: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while updating the calendar configuration: {str(e)}",
                ephemeral=True
            )


class CalendarConfigView(discord.ui.View):
    """View for configuring calendars with dropdown selection"""
    
    def __init__(self, cog: 'CalendarCog', guild_id: int, calendars: Dict[str, 'CalendarConfig']):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.calendars = calendars
        
        # Create dropdown options
        options = []
        for cal_id, cal_config in calendars.items():
            # Get channel names for display
            guild = cog.bot.get_guild(guild_id)
            text_channel = guild.get_channel(cal_config.text_channel_id) if guild else None
            text_name = text_channel.name if text_channel else f"Channel {cal_config.text_channel_id}"
            
            # Create a readable description
            description = f"Posts to #{text_name}"
            if len(cal_config.blacklist) > 0 or len(cal_config.whitelist) > 0:
                filter_count = len(cal_config.blacklist) + len(cal_config.whitelist)
                description += f" • {filter_count} filter terms"
            
            options.append(discord.SelectOption(
                label=cal_id,
                value=cal_id,
                description=description[:100]  # Discord limit
            ))
        
        # Add the dropdown
        self.calendar_select = discord.ui.Select(
            placeholder="Select a calendar to configure...",
            options=options[:25]  # Discord limit
        )
        self.calendar_select.callback = self.calendar_selected
        self.add_item(self.calendar_select)
    
    async def calendar_selected(self, interaction: discord.Interaction):
        """Handle calendar selection for configuration"""
        selected_calendar = self.calendar_select.values[0]
        calendar_config = self.calendars[selected_calendar]
        
        # Create detailed embed with calendar information
        guild = self.cog.bot.get_guild(self.guild_id)
        text_channel = guild.get_channel(calendar_config.text_channel_id) if guild else None
        voice_channel = guild.get_channel(calendar_config.voice_channel_id) if guild else None
        
        embed = discord.Embed(
            title=f"📅 Calendar Configuration: {selected_calendar}",
            color=0x5865F2
        )
        
        # Basic info
        embed.add_field(name="Calendar ID", value=selected_calendar, inline=True)
        embed.add_field(name="Text Channel", value=text_channel.mention if text_channel else f"Channel {calendar_config.text_channel_id}", inline=True)
        embed.add_field(name="Voice Channel", value=voice_channel.mention if voice_channel else f"Channel {calendar_config.voice_channel_id}", inline=True)
        embed.add_field(name="iCal URL", value=calendar_config.ical_url, inline=False)
        
        # Filter terms
        if calendar_config.blacklist:
            embed.add_field(
                name="Blacklisted Terms", 
                value=", ".join(f"`{term}`" for term in calendar_config.blacklist), 
                inline=False
            )
        else:
            embed.add_field(name="Blacklisted Terms", value="None", inline=False)
        
        if calendar_config.whitelist:
            embed.add_field(
                name="Whitelisted Terms", 
                value=", ".join(f"`{term}`" for term in calendar_config.whitelist), 
                inline=False
            )
        else:
            embed.add_field(name="Whitelisted Terms", value="None", inline=False)
        
        # Reminder role info
        if calendar_config.reminder_role_id:
            role = guild.get_role(calendar_config.reminder_role_id) if guild else None
            if role:
                embed.add_field(
                    name="Reminder Role",
                    value=role.mention,
                    inline=True
                )
            else:
                embed.add_field(
                    name="Reminder Role",
                    value=f"Role {calendar_config.reminder_role_id} (not found)",
                    inline=True
                )
        else:
            embed.add_field(
                name="Reminder Role",
                value="None (no role pings)",
                inline=True
            )
        
        # Last sync info
        if calendar_config.last_sync:
            embed.add_field(
                name="Last Sync", 
                value=f"<t:{int(calendar_config.last_sync.timestamp())}:R>", 
                inline=True
            )
        
        # Statistics
        embed.add_field(
            name="Discord Events Created", 
            value=str(len(calendar_config.created_events)), 
            inline=True
        )
        
        # Create view with edit button
        view = discord.ui.View(timeout=300)
        edit_button = discord.ui.Button(
            label="Edit Filters",
            style=discord.ButtonStyle.primary,
            emoji="✏️"
        )
        
        async def edit_button_callback(button_interaction):
            modal = CalendarConfigModal(self.cog, self.guild_id, selected_calendar, calendar_config)
            await button_interaction.response.send_modal(modal)
        
        edit_button.callback = edit_button_callback
        view.add_item(edit_button)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CalendarRemoveView(discord.ui.View):
    """View for removing calendars with dropdown selection"""
    
    def __init__(self, cog: 'CalendarCog', guild_id: int, calendars: Dict[str, CalendarConfig]):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for cal_id, cal_config in calendars.items():
            # Get channel names for display
            guild = cog.bot.get_guild(guild_id)
            text_channel = guild.get_channel(cal_config.text_channel_id) if guild else None
            text_name = text_channel.name if text_channel else f"Channel {cal_config.text_channel_id}"
            
            # Create a readable description
            description = f"Posts to #{text_name}"
            if len(cal_config.blacklist) > 0:
                description += f" • {len(cal_config.blacklist)} blacklisted terms"
            
            options.append(discord.SelectOption(
                label=cal_id,
                value=cal_id,
                description=description[:100]  # Discord limit
            ))
        
        # Add the dropdown
        self.calendar_select = discord.ui.Select(
            placeholder="Select a calendar to remove...",
            options=options[:25]  # Discord limit
        )
        self.calendar_select.callback = self.calendar_selected
        self.add_item(self.calendar_select)
    
    async def calendar_selected(self, interaction: discord.Interaction):
        """Handle calendar selection for removal"""
        # Defer response to avoid timeout
        await interaction.response.defer()
        
        selected_calendar = self.calendar_select.values[0]
        
        # Remove the calendar
        success = await self.cog.remove_calendar(self.guild_id, selected_calendar)
        
        if success:
            embed = discord.Embed(
                title="✅ Calendar Removed",
                description=f"Calendar `{selected_calendar}` has been successfully removed.",
                color=0x00ff00
            )
        else:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to remove calendar `{selected_calendar}`.",
                color=0xff0000
            )
        
        await interaction.edit_original_response(embed=embed, view=None)


class CalendarCog(commands.Cog):
    """Cog for managing iCal calendar integration with Discord events and summaries"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("calendar")
        
        # Create config directory
        self.config_base = Path(__file__).parents[1] / "config"
        self.config_base.mkdir(exist_ok=True)
        
        # Per-guild calendar configurations
        self.guild_calendars: Dict[int, Dict[str, CalendarConfig]] = {}
        
        # Load existing configurations
        self._load_all_guild_configs()
        
        # Start the update task
        self.calendar_update_task.start()
        
        # Start event status monitoring task
        self.event_status_task.start()
        
        # Start reminder task
        self.reminder_task.start()
        
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.calendar_update_task.cancel()
        self.event_status_task.cancel()
        self.reminder_task.cancel()
    
    def _load_all_guild_configs(self):
        """Load calendar configurations for all guilds"""
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                self._load_guild_calendars(guild_id)
    
    def _load_guild_calendars(self, guild_id: int):
        """Load calendar configurations for a specific guild"""
        guild_config_file = self.config_base / str(guild_id) / "calendars.yaml"
        
        if guild_config_file.exists():
            try:
                with open(guild_config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                    
                self.guild_calendars[guild_id] = {}
                for cal_id, cal_data in data.items():
                    self.guild_calendars[guild_id][cal_id] = CalendarConfig.from_dict(cal_data)
                    
                self.log.info(f"Loaded {len(data)} calendars for guild {guild_id}")
            except Exception as e:
                self.log.error(f"Failed to load calendars for guild {guild_id}: {e}")
                self.guild_calendars[guild_id] = {}
        else:
            self.guild_calendars[guild_id] = {}
    
    def _save_guild_calendars(self, guild_id: int):
        """Save calendar configurations for a specific guild"""
        guild_config_dir = self.config_base / str(guild_id)
        guild_config_dir.mkdir(exist_ok=True)
        
        guild_config_file = guild_config_dir / "calendars.yaml"
        
        try:
            data = {}
            if guild_id in self.guild_calendars:
                for cal_id, cal_config in self.guild_calendars[guild_id].items():
                    data[cal_id] = cal_config.to_dict()
            
            with open(guild_config_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
                
            self.log.info(f"Saved {len(data)} calendars for guild {guild_id}")
        except Exception as e:
            self.log.error(f"Failed to save calendars for guild {guild_id}: {e}")

    @app_commands.command(name="cal_add", description="Add an iCal calendar for weekly summaries and Discord events")
    @app_commands.describe(
        calendar_id="Unique identifier for this calendar",
        text_channel="Text channel where weekly summaries will be posted",
        voice_channel="Voice channel to use as location for Discord events", 
        ical_url="URL to the iCal calendar file",
        blacklist="Comma-separated list of terms to exclude from events (optional)",
        whitelist="Comma-separated list of terms to include events (optional)",
        reminder_role="Role to ping in reminders 1 hour before events (optional)"
    )
    async def cal_add(
        self, 
        interaction: discord.Interaction,
        calendar_id: str,
        text_channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel,
        ical_url: str,
        blacklist: Optional[str] = None,
        whitelist: Optional[str] = None,
        reminder_role: Optional[discord.Role] = None
    ):
        """Add a new iCal calendar for tracking"""
        
        # Permission check - admin only
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return
        
        # Defer response immediately to avoid timeout
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Validate URL format
            if not ical_url.startswith(('http://', 'https://')):
                await interaction.followup.send(
                    "❌ Please provide a valid HTTP/HTTPS URL for the iCal file.",
                    ephemeral=True
                )
                return
            
            # Parse blacklist and whitelist
            blacklist_terms = []
            if blacklist:
                blacklist_terms = [term.strip() for term in blacklist.split(',') if term.strip()]
            
            whitelist_terms = []
            if whitelist:
                whitelist_terms = [term.strip() for term in whitelist.split(',') if term.strip()]
            
            # Test the iCal URL (with shorter timeout to avoid Discord interaction timeout)
            try:
                session = await http_client.get_session()
                async with session.get(ical_url, timeout=10) as response:
                    if response.status != 200:
                        await interaction.followup.send(
                            f"❌ Could not access iCal URL (HTTP {response.status})",
                            ephemeral=True
                        )
                        return
                    
                    content = await response.text()
                    # Try to parse the calendar to validate format
                    Calendar.from_ical(content)
                    
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error accessing or parsing iCal file: {str(e)}",
                    ephemeral=True
                )
                return
            
            # Ensure guild calendars dict exists
            guild_id = interaction.guild_id
            if guild_id not in self.guild_calendars:
                self.guild_calendars[guild_id] = {}
            
            # Check if calendar ID already exists
            if calendar_id in self.guild_calendars[guild_id]:
                await interaction.followup.send(
                    f"❌ A calendar with ID `{calendar_id}` already exists. Please choose a different ID.",
                    ephemeral=True
                )
                return
            
            # Create new calendar config
            calendar_config = CalendarConfig(
                text_channel_id=text_channel.id,
                voice_channel_id=voice_channel.id,
                ical_url=ical_url,
                blacklist=blacklist_terms,
                whitelist=whitelist_terms,
                reminder_role_id=reminder_role.id if reminder_role else None
            )
            
            # Save to memory and disk
            self.guild_calendars[guild_id][calendar_id] = calendar_config
            self._save_guild_calendars(guild_id)
            
            # Create success embed
            embed = discord.Embed(
                title="✅ Calendar Added Successfully",
                color=0x00ff00
            )
            embed.add_field(name="Calendar ID", value=calendar_id, inline=True)
            embed.add_field(name="Text Channel", value=text_channel.mention, inline=True)
            embed.add_field(name="Voice Channel", value=voice_channel.mention, inline=True)
            embed.add_field(name="iCal URL", value=ical_url, inline=False)
            
            if blacklist_terms:
                embed.add_field(
                    name="Blacklisted Terms", 
                    value=", ".join(f"`{term}`" for term in blacklist_terms), 
                    inline=False
                )
            
            if whitelist_terms:
                embed.add_field(
                    name="Whitelisted Terms", 
                    value=", ".join(f"`{term}`" for term in whitelist_terms), 
                    inline=False
                )
            
            if reminder_role:
                embed.add_field(
                    name="Reminder Role",
                    value=reminder_role.mention,
                    inline=True
                )
            else:
                embed.add_field(
                    name="Reminder Role",
                    value="None (no role pings)",
                    inline=True
                )
            
            embed.set_footer(text="The calendar will be synced automatically every hour. Reminders are sent 1 hour before events.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Trigger an immediate sync for this calendar
            await self._sync_calendar(guild_id, calendar_id, calendar_config)
            
            self.log.info(f"Added calendar {calendar_id} for guild {guild_id}")
            
        except Exception as e:
            self.log.error(f"Error adding calendar: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while adding the calendar: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="cal_remove", description="Remove an existing iCal calendar")
    async def cal_remove(self, interaction: discord.Interaction):
        """Remove an existing iCal calendar"""
        
        # Permission check - admin only
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return
        
        guild_id = interaction.guild_id
        
        # Check if there are any calendars to remove
        if guild_id not in self.guild_calendars or not self.guild_calendars[guild_id]:
            await interaction.response.send_message(
                "❌ No calendars found for this server. Use `/cal_add` to add one first.",
                ephemeral=True
            )
            return
        
        # Create the removal view with dropdown
        view = CalendarRemoveView(self, guild_id, self.guild_calendars[guild_id])
        
        embed = discord.Embed(
            title="📅 Remove Calendar",
            description="Select a calendar to remove from the dropdown below:",
            color=0xff9900
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="cal_config", description="Configure existing calendar filters and settings")
    async def cal_config(self, interaction: discord.Interaction):
        """Configure an existing iCal calendar"""
        
        # Permission check - admin only
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return
        
        guild_id = interaction.guild_id
        
        # Check if there are any calendars to configure
        if guild_id not in self.guild_calendars or not self.guild_calendars[guild_id]:
            await interaction.response.send_message(
                "❌ No calendars found for this server. Use `/cal_add` to add one first.",
                ephemeral=True
            )
            return
        
        # Create the configuration view with dropdown
        view = CalendarConfigView(self, guild_id, self.guild_calendars[guild_id])
        
        embed = discord.Embed(
            title="📅 Calendar Configuration",
            description="Select a calendar to view details and edit filters:",
            color=0x5865F2
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def remove_calendar(self, guild_id: int, calendar_id: str) -> bool:
        """Remove a calendar and clean up associated data"""
        try:
            if guild_id not in self.guild_calendars or calendar_id not in self.guild_calendars[guild_id]:
                return False
            
            calendar_config = self.guild_calendars[guild_id][calendar_id]
            
            # Delete the last summary message if it exists
            if calendar_config.last_message_id:
                try:
                    guild = self.bot.get_guild(guild_id)
                    channel = guild.get_channel(calendar_config.text_channel_id) if guild else None
                    if channel:
                        message = await channel.fetch_message(calendar_config.last_message_id)
                        await message.delete()
                except Exception as e:
                    self.log.warning(f"Could not delete last message for calendar {calendar_id}: {e}")
            
            # Delete created Discord events
            if calendar_config.created_events:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    for event_id in calendar_config.created_events:
                        try:
                            event = await guild.fetch_scheduled_event(event_id)
                            await event.delete()
                        except Exception as e:
                            self.log.warning(f"Could not delete Discord event {event_id}: {e}")
            
            # Remove from memory and save to disk
            del self.guild_calendars[guild_id][calendar_id]
            self._save_guild_calendars(guild_id)
            
            self.log.info(f"Removed calendar {calendar_id} from guild {guild_id}")
            return True
            
        except Exception as e:
            self.log.error(f"Error removing calendar {calendar_id}: {e}")
            return False

    @tasks.loop(hours=1)
    async def calendar_update_task(self):
        """Task that runs every hour to sync all calendars"""
        self.log.info("Starting calendar sync task")
        
        for guild_id, calendars in self.guild_calendars.items():
            for calendar_id, calendar_config in calendars.items():
                try:
                    await self._sync_calendar(guild_id, calendar_id, calendar_config)
                except Exception as e:
                    self.log.error(f"Error syncing calendar {calendar_id} in guild {guild_id}: {e}")
        
        self.log.info("Calendar sync task completed")

    @calendar_update_task.before_loop
    async def before_calendar_update(self):
        """Wait for bot to be ready before starting the task"""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def event_status_task(self):
        """Task that runs every 5 minutes to monitor and update Discord event statuses"""
        now = datetime.now(timezone.utc)
        events_started = 0
        events_ended = 0
        events_cleaned = 0
        
        for guild_id, calendars in self.guild_calendars.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
                
            for calendar_id, calendar_config in calendars.items():
                for event_id in calendar_config.created_events.copy():
                    try:
                        discord_event = await guild.fetch_scheduled_event(event_id)
                        
                        # Check if event should be started
                        if (discord_event.status == discord.EventStatus.scheduled and 
                            discord_event.start_time <= now):
                            
                            # Start the event
                            await discord_event.start()
                            self.log.info(f"🟢 Auto-started Discord event: {discord_event.name} in {guild.name}")
                            events_started += 1
                        
                        # Check if event should be ended
                        elif (discord_event.status == discord.EventStatus.active and 
                              discord_event.end_time and discord_event.end_time <= now):
                            
                            # End the event
                            await discord_event.end()
                            self.log.info(f"🔴 Auto-ended Discord event: {discord_event.name} in {guild.name}")
                            events_ended += 1
                        
                    except discord.NotFound:
                        # Event was deleted, remove from our tracking
                        calendar_config.created_events.remove(event_id)
                        # Also remove from title mapping
                        for title, mapped_id in list(calendar_config.event_title_to_id.items()):
                            if mapped_id == event_id:
                                del calendar_config.event_title_to_id[title]
                                break
                        # Save updated config
                        self._save_guild_calendars(guild_id)
                        events_cleaned += 1
                    except discord.HTTPException as e:
                        if "Channel already has an active event" in str(e):
                            # This is expected when trying to start overlapping events
                            # Just log at debug level to reduce log noise
                            self.log.debug(f"Event {event_id} cannot start due to active event in channel: {e}")
                        else:
                            self.log.warning(f"HTTP error managing event status for event {event_id}: {e}")
                    except Exception as e:
                        self.log.warning(f"Error managing event status for event {event_id}: {e}")
        
        # Log summary if any events were managed
        if events_started > 0 or events_ended > 0 or events_cleaned > 0:
            self.log.info(f"📅 Event status check completed: {events_started} started, {events_ended} ended, {events_cleaned} cleaned up")

    @event_status_task.before_loop
    async def before_event_status(self):
        """Wait for bot to be ready before starting the event status task"""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def reminder_task(self):
        """Task that runs every 15 minutes to send reminders for upcoming events (1 hour before)"""
        now = datetime.now(timezone.utc)
        reminder_time = now + timedelta(hours=1)
        reminders_sent = 0
        
        for guild_id, calendars in self.guild_calendars.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
                
            for calendar_id, calendar_config in calendars.items():
                try:
                    # Fetch latest calendar events
                    events = await self._fetch_calendar_events(calendar_config.ical_url)
                    if not events:
                        continue
                    
                    # Filter events
                    filtered_events = self._filter_events(events, calendar_config.blacklist, calendar_config.whitelist)
                    
                    # Check for events starting in about 1 hour
                    for event in filtered_events:
                        event_start = event.get('start')
                        if not event_start:
                            continue
                        
                        # Convert to datetime if needed
                        if not isinstance(event_start, datetime):
                            event_start = datetime.combine(event_start, datetime.min.time())
                        
                        # Ensure timezone-aware datetime
                        if event_start.tzinfo is None:
                            event_start = event_start.replace(tzinfo=timezone.utc)
                        
                        # Check if event starts within the next hour (45-75 minutes from now)
                        time_until_event = event_start - now
                        if timedelta(minutes=45) <= time_until_event <= timedelta(minutes=75):
                            
                            # Generate unique reminder key
                            reminder_key = f"{calendar_id}_{event['title']}_{event_start.isoformat()}"
                            
                            # Check if reminder was already sent
                            if reminder_key in calendar_config.sent_reminders:
                                # Check if reminder was sent recently (within last 2 hours to avoid duplicates)
                                if now - calendar_config.sent_reminders[reminder_key] < timedelta(hours=2):
                                    continue
                            
                            # Send reminder
                            success = await self._send_event_reminder(guild_id, calendar_config, event, event_start)
                            if success:
                                calendar_config.sent_reminders[reminder_key] = now
                                self._save_guild_calendars(guild_id)
                                reminders_sent += 1
                    
                except Exception as e:
                    self.log.error(f"Error processing reminders for calendar {calendar_id} in guild {guild_id}: {e}")
        
        # Log summary if any reminders were sent
        if reminders_sent > 0:
            self.log.info(f"📢 Sent {reminders_sent} event reminders")
        
        # Clean up old sent reminders (older than 7 days)
        await self._cleanup_old_reminders()

    @reminder_task.before_loop
    async def before_reminder_task(self):
        """Wait for bot to be ready before starting the reminder task"""
        await self.bot.wait_until_ready()

    async def _sync_calendar(self, guild_id: int, calendar_id: str, calendar_config: CalendarConfig):
        """Sync a single calendar - fetch events, post summary, create Discord events"""
        self.log.info(f"Syncing calendar {calendar_id} for guild {guild_id}")
        
        try:
            # Fetch and parse calendar
            events = await self._fetch_calendar_events(calendar_config.ical_url)
            
            if events is None:
                self.log.warning(f"Failed to fetch calendar events for {calendar_id}")
                return
            
            # Filter events by blacklist and get this week's events
            filtered_events = self._filter_events(events, calendar_config.blacklist, calendar_config.whitelist)
            weekly_events, week_start = self._get_weekly_events(filtered_events)
            
            # Post or update weekly summary
            await self._post_weekly_summary(guild_id, calendar_config, weekly_events, week_start)
            
            # Manage Discord events
            await self._manage_discord_events(guild_id, calendar_config, weekly_events)
            
            # Update last sync time
            calendar_config.last_sync = datetime.now(timezone.utc)
            self._save_guild_calendars(guild_id)
            
        except Exception as e:
            self.log.error(f"Error in _sync_calendar for {calendar_id}: {e}")

    async def _fetch_calendar_events(self, ical_url: str) -> Optional[List[dict]]:
        """Fetch and parse iCal calendar events"""
        try:
            # Use retry handler for reliability
            async def fetch_ical():
                session = await http_client.get_session()
                timeout = config.http_timeout
                async with session.get(ical_url, timeout=timeout) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    return await response.text()
            
            content = await retry_handler.execute_with_retry(
                f"fetch_ical_{ical_url}",
                fetch_ical
            )
            
            # Parse calendar
            cal = Calendar.from_ical(content)
            
            # Get events for the next 4 weeks (to catch recurring events)
            start_date = datetime.now()
            end_date = start_date + timedelta(weeks=4)
            
            # Try using recurring_ical_events with error handling for timezone issues
            try:
                events = recurring_ical_events.of(cal).between(start_date, end_date)
            except Exception as e:
                self.log.warning(f"Error parsing recurring events, falling back to basic parsing: {e}")
                # Fallback to basic event parsing without recurring support
                events = []
                for component in cal.walk():
                    if component.name == "VEVENT":
                        events.append(component)
            
            # Convert to our format
            parsed_events = []
            for event in events:
                try:
                    # Handle both recurring_ical_events format and raw icalendar format
                    if hasattr(event, 'get'):
                        # recurring_ical_events format
                        title = str(event.get('SUMMARY', 'No Title'))
                        start = event.get('DTSTART').dt if event.get('DTSTART') else None
                        end = event.get('DTEND').dt if event.get('DTEND') else None
                        description = str(event.get('DESCRIPTION', ''))
                        location = str(event.get('LOCATION', ''))
                    else:
                        # Raw icalendar component format
                        title = str(event.get('summary', 'No Title'))
                        start = event.get('dtstart').dt if event.get('dtstart') else None
                        end = event.get('dtend').dt if event.get('dtend') else None
                        description = str(event.get('description', ''))
                        location = str(event.get('location', ''))
                    
                    parsed_events.append({
                        'title': title,
                        'start': start,
                        'end': end,
                        'description': description,
                        'location': location
                    })
                except Exception as e:
                    self.log.warning(f"Error parsing individual event: {e}")
                    continue
            
            return parsed_events
            
        except Exception as e:
            # Log more detailed error information
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "Unknown error"
            
            # Add more context for timeout errors
            if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
                self.log.error(f"Timeout fetching calendar from {ical_url} (configured timeout: {config.http_timeout}s): {error_type}: {error_msg}")
            else:
                self.log.error(f"Error fetching calendar from {ical_url}: {error_type}: {error_msg}")
            return None

    def _filter_events(self, events: List[dict], blacklist: List[str], whitelist: List[str] = None) -> List[dict]:
        """Filter events based on blacklist and whitelist terms
        
        Logic:
        - If both blacklist and whitelist contain matching terms, blacklist prevails
        - If only whitelist is used, only events with whitelisted terms are included
        - If only blacklist is used, events with blacklisted terms are excluded
        - If neither list is provided, all events are included
        """
        if not blacklist and not whitelist:
            return events
        
        whitelist = whitelist or []
        
        filtered = []
        for event in events:
            title = event.get('title', '').lower()
            
            # Check blacklist first (has priority)
            is_blacklisted = any(term.lower() in title for term in blacklist) if blacklist else False
            
            # If blacklisted, exclude regardless of whitelist
            if is_blacklisted:
                continue
            
            # If whitelist is provided, check if event matches whitelist
            if whitelist:
                is_whitelisted = any(term.lower() in title for term in whitelist)
                if is_whitelisted:
                    filtered.append(event)
                # If not whitelisted and whitelist exists, exclude
            else:
                # No whitelist, so include (since it's not blacklisted)
                filtered.append(event)
        
        return filtered

    def _get_weekly_events(self, events: List[dict]) -> tuple[List[dict], datetime]:
        """Get events for the current week (Monday to Sunday)"""
        now = datetime.now()
        
        # Calculate start of current week (Monday)
        days_since_monday = now.weekday()
        week_start = now - timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate end of current week (Sunday)
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        weekly_events = []
        for event in events:
            event_start = event.get('start')
            if event_start:
                # Handle both datetime and date objects
                if hasattr(event_start, 'date'):
                    event_date = event_start.date()
                else:
                    event_date = event_start
                
                # Convert to datetime for comparison
                if isinstance(event_date, datetime):
                    event_datetime = event_date
                else:
                    event_datetime = datetime.combine(event_date, datetime.min.time())
                
                if week_start <= event_datetime <= week_end:
                    weekly_events.append(event)
        
        # Sort by start time
        weekly_events.sort(key=lambda x: x.get('start', datetime.min))
        return weekly_events, week_start

    async def _post_weekly_summary(self, guild_id: int, calendar_config: CalendarConfig, events: List[dict], week_start: datetime):
        """Post or update the weekly summary message"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(calendar_config.text_channel_id)
        if not channel:
            return
        
        # Create summary embed
        embed = self._create_summary_embed(events, calendar_config, guild_id)
        
        # Check if we're in a new week compared to the last message
        is_new_week = (calendar_config.current_week_start is None or 
                      calendar_config.current_week_start != week_start)
        
        if is_new_week or not calendar_config.last_message_id:
            # Delete old message if it exists for new week
            if calendar_config.last_message_id:
                try:
                    old_message = await channel.fetch_message(calendar_config.last_message_id)
                    await old_message.delete()
                except Exception as e:
                    self.log.warning(f"Could not delete old summary message: {e}")
            
            # Post new message for new week
            try:
                message = await channel.send(embed=embed)
                calendar_config.last_message_id = message.id
                calendar_config.current_week_start = week_start
                self.log.info(f"Posted new weekly summary to {channel.name} (message ID: {message.id})")
            except Exception as e:
                self.log.error(f"Error posting weekly summary: {e}")
        else:
            # Update existing message within the same week
            try:
                old_message = await channel.fetch_message(calendar_config.last_message_id)
                await old_message.edit(embed=embed)
                self.log.info(f"Updated weekly summary in {channel.name} (message ID: {calendar_config.last_message_id})")
            except Exception as e:
                self.log.warning(f"Could not update existing message, posting new one: {e}")
                # Fallback to posting new message
                try:
                    message = await channel.send(embed=embed)
                    calendar_config.last_message_id = message.id
                    calendar_config.current_week_start = week_start
                    self.log.info(f"Posted new weekly summary (fallback) to {channel.name} (message ID: {message.id})")
                except Exception as e2:
                    self.log.error(f"Error posting fallback weekly summary: {e2}")

    def _create_summary_embed(self, events: List[dict], calendar_config: CalendarConfig, guild_id: int) -> discord.Embed:
        """Create an embed for the weekly summary"""
        from core.timezone_util import to_guild_timezone
        
        embed = discord.Embed(
            title="📅 Weekly Calendar Summary",
            color=0x5865F2
        )
        
        if not events:
            embed.description = "No events scheduled for this week."
            return embed
        
        # Group events by day
        days = {}
        for event in events:
            event_start = event.get('start')
            if event_start:
                # Convert to guild timezone for display
                if isinstance(event_start, datetime):
                    guild_start = to_guild_timezone(event_start, guild_id)
                    day = guild_start.date()
                else:
                    day = event_start
                
                if isinstance(day, datetime):
                    day = day.date()
                
                day_str = day.strftime("%A, %B %d")
                
                if day_str not in days:
                    days[day_str] = []
                days[day_str].append(event)
        
        # Add fields for each day
        for day_str, day_events in days.items():
            event_text = ""
            for event in day_events:
                title = event.get('title', 'No Title')
                start = event.get('start')
                
                if start:
                    if isinstance(start, datetime):
                        # Convert to guild timezone for display
                        guild_start = to_guild_timezone(start, guild_id)
                        time_str = guild_start.strftime("%H:%M")
                    elif hasattr(start, 'strftime'):
                        time_str = start.strftime("%H:%M")
                    else:
                        time_str = "All day"
                else:
                    time_str = "Time TBD"
                
                # Check if we have a Discord event link for this title
                if title in calendar_config.event_title_to_id:
                    discord_event_id = calendar_config.event_title_to_id[title]
                    # Create clickable Discord event link
                    event_link = f"https://discord.com/events/{guild_id}/{discord_event_id}"
                    event_text += f"• **{time_str}** - [{title}]({event_link})\n"
                else:
                    event_text += f"• **{time_str}** - {title}\n"
            
            embed.add_field(
                name=day_str,
                value=event_text or "No events",
                inline=False
            )
        
        # Use guild timezone for footer timestamp
        now_guild = to_guild_timezone(datetime.now(timezone.utc), guild_id)
        embed.set_footer(text=f"Last updated: {now_guild.strftime('%Y-%m-%d %H:%M')}")
        return embed

    async def _manage_discord_events(self, guild_id: int, calendar_config: CalendarConfig, events: List[dict]):
        """Create, update, or delete Discord events based on calendar events"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        voice_channel = guild.get_channel(calendar_config.voice_channel_id)
        if not voice_channel:
            return
        
        # Get existing Discord events for this calendar
        existing_events = {}
        for event_id in calendar_config.created_events.copy():
            try:
                discord_event = await guild.fetch_scheduled_event(event_id)
                existing_events[discord_event.name] = discord_event
                # Update mapping for existing event
                calendar_config.event_title_to_id[discord_event.name] = discord_event.id
            except Exception:
                # Event no longer exists, remove from our list
                calendar_config.created_events.remove(event_id)
        
        # Track events we want to keep
        events_to_keep = set()
        
        # Create/update Discord events
        for event in events:
            event_title = event.get('title', 'No Title')
            event_start = event.get('start')
            event_end = event.get('end')
            event_desc = event.get('description', '')
            
            if not event_start:
                continue
            
            # Convert to datetime if needed
            if not isinstance(event_start, datetime):
                event_start = datetime.combine(event_start, datetime.min.time())
            if event_end and not isinstance(event_end, datetime):
                event_end = datetime.combine(event_end, datetime.min.time())
            
            # Ensure timezone-aware datetimes
            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=timezone.utc)
            if event_end and event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=timezone.utc)
            
            # Default end time if not provided (1 hour after start)
            if not event_end:
                event_end = event_start + timedelta(hours=1)
            
            events_to_keep.add(event_title)
            
            # Check if Discord event already exists
            if event_title in existing_events:
                # Update existing event if needed
                discord_event = existing_events[event_title]
                try:
                    if (discord_event.start_time != event_start or 
                        discord_event.end_time != event_end or 
                        discord_event.description != event_desc):
                        
                        await discord_event.edit(
                            start_time=event_start,
                            end_time=event_end,
                            description=event_desc[:1000]  # Discord limit
                        )
                        self.log.info(f"Updated Discord event: {event_title}")
                except Exception as e:
                    self.log.warning(f"Could not update Discord event {event_title}: {e}")
            else:
                # Create new Discord event
                try:
                    discord_event = await guild.create_scheduled_event(
                        name=event_title,
                        start_time=event_start,
                        end_time=event_end,
                        description=event_desc[:1000],  # Discord limit
                        entity_type=discord.EntityType.voice,
                        channel=voice_channel,
                        privacy_level=discord.PrivacyLevel.guild_only
                    )
                    calendar_config.created_events.append(discord_event.id)
                    calendar_config.event_title_to_id[event_title] = discord_event.id
                    self.log.info(f"Created Discord event: {event_title}")
                except Exception as e:
                    self.log.error(f"Could not create Discord event {event_title}: {e}")
        
        # Remove Discord events that no longer exist in calendar
        for event_title, discord_event in existing_events.items():
            if event_title not in events_to_keep:
                try:
                    await discord_event.delete()
                    if discord_event.id in calendar_config.created_events:
                        calendar_config.created_events.remove(discord_event.id)
                    # Remove from title mapping
                    if event_title in calendar_config.event_title_to_id:
                        del calendar_config.event_title_to_id[event_title]
                    self.log.info(f"Deleted Discord event: {event_title}")
                except Exception as e:
                    self.log.warning(f"Could not delete Discord event {event_title}: {e}")

    async def _send_event_reminder(self, guild_id: int, calendar_config: CalendarConfig, event: dict, event_start: datetime) -> bool:
        """Send a reminder message for an upcoming event"""
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False
            
            channel = guild.get_channel(calendar_config.text_channel_id)
            if not channel:
                return False
            
            # Create reminder embed
            from core.timezone_util import to_guild_timezone
            
            embed = discord.Embed(
                title="📢 Event Reminder",
                color=0xffa500  # Orange color
            )
            
            # Convert to guild timezone for display
            guild_start = to_guild_timezone(event_start, guild_id)
            
            embed.add_field(
                name="Event",
                value=event.get('title', 'No Title'),
                inline=False
            )
            
            embed.add_field(
                name="Starts at",
                value=f"<t:{int(event_start.timestamp())}:F> ({guild_start.strftime('%H:%M')})",
                inline=True
            )
            
            embed.add_field(
                name="Time until start",
                value=f"<t:{int(event_start.timestamp())}:R>",
                inline=True
            )
            
            if event.get('description'):
                description = event['description'][:500]  # Truncate if too long
                embed.add_field(
                    name="Description",
                    value=description,
                    inline=False
                )
            
            if event.get('location'):
                embed.add_field(
                    name="Location",
                    value=event['location'],
                    inline=False
                )
            
            # Add Discord event link if available
            event_title = event.get('title', 'No Title')
            if event_title in calendar_config.event_title_to_id:
                discord_event_id = calendar_config.event_title_to_id[event_title]
                event_link = f"https://discord.com/events/{guild_id}/{discord_event_id}"
                embed.add_field(
                    name="Discord Event",
                    value=f"[View Event]({event_link})",
                    inline=True
                )
            
            embed.set_footer(text="Event starts in approximately 1 hour")
            
            # Prepare message content with role ping if configured
            content = None
            if calendar_config.reminder_role_id:
                role = guild.get_role(calendar_config.reminder_role_id)
                if role:
                    content = f"{role.mention} Event starting soon!"
                else:
                    self.log.warning(f"Reminder role {calendar_config.reminder_role_id} not found in guild {guild_id}")
            
            # Send the reminder
            await channel.send(content=content, embed=embed)
            
            self.log.info(f"Sent reminder for event '{event_title}' in guild {guild_id}")
            return True
            
        except Exception as e:
            self.log.error(f"Error sending event reminder: {e}")
            return False

    async def _cleanup_old_reminders(self):
        """Clean up old sent reminders to prevent memory growth"""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=7)
            cleaned_count = 0
            
            for guild_id, calendars in self.guild_calendars.items():
                for calendar_id, calendar_config in calendars.items():
                    # Remove old reminders
                    old_keys = [key for key, timestamp in calendar_config.sent_reminders.items() 
                               if timestamp < cutoff_time]
                    
                    for key in old_keys:
                        del calendar_config.sent_reminders[key]
                        cleaned_count += 1
                    
                    # Save if changes were made
                    if old_keys:
                        self._save_guild_calendars(guild_id)
            
            if cleaned_count > 0:
                self.log.info(f"Cleaned up {cleaned_count} old reminder entries")
                
        except Exception as e:
            self.log.error(f"Error cleaning up old reminders: {e}")


async def setup(bot):
    await bot.add_cog(CalendarCog(bot))