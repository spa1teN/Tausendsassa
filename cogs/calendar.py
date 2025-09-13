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
                 blacklist: List[str] = None, whitelist: List[str] = None, last_message_id: Optional[int] = None):
        self.text_channel_id = text_channel_id
        self.voice_channel_id = voice_channel_id 
        self.ical_url = ical_url
        self.blacklist = blacklist or []
        self.whitelist = whitelist or []
        self.last_message_id = last_message_id
        self.created_events: List[int] = []  # Discord event IDs
        self.event_title_to_id: Dict[str, int] = {}  # Map event titles to Discord event IDs
        self.last_sync = None
        
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
            'last_sync': self.last_sync.isoformat() if self.last_sync else None
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CalendarConfig':
        config = cls(
            text_channel_id=data['text_channel_id'],
            voice_channel_id=data['voice_channel_id'],
            ical_url=data['ical_url'],
            blacklist=data.get('blacklist', []),
            whitelist=data.get('whitelist', []),
            last_message_id=data.get('last_message_id')
        )
        config.created_events = data.get('created_events', [])
        config.event_title_to_id = data.get('event_title_to_id', {})
        if data.get('last_sync'):
            config.last_sync = datetime.fromisoformat(data['last_sync'])
        return config


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
        
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.calendar_update_task.cancel()
    
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
        whitelist="Comma-separated list of terms to include events (optional)"
    )
    async def cal_add(
        self, 
        interaction: discord.Interaction,
        calendar_id: str,
        text_channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel,
        ical_url: str,
        blacklist: Optional[str] = None,
        whitelist: Optional[str] = None
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
                whitelist=whitelist_terms
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
            
            embed.set_footer(text="The calendar will be synced automatically every hour.")
            
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
            weekly_events = self._get_weekly_events(filtered_events)
            
            # Post or update weekly summary
            await self._post_weekly_summary(guild_id, calendar_config, weekly_events)
            
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
                async with session.get(ical_url, timeout=15) as response:
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
            self.log.error(f"Error fetching calendar from {ical_url}: {e}")
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

    def _get_weekly_events(self, events: List[dict]) -> List[dict]:
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
        return weekly_events

    async def _post_weekly_summary(self, guild_id: int, calendar_config: CalendarConfig, events: List[dict]):
        """Post or update the weekly summary message"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(calendar_config.text_channel_id)
        if not channel:
            return
        
        # Create summary embed
        embed = self._create_summary_embed(events, calendar_config, guild_id)
        
        # Delete old message if it exists
        if calendar_config.last_message_id:
            try:
                old_message = await channel.fetch_message(calendar_config.last_message_id)
                await old_message.delete()
            except Exception as e:
                self.log.warning(f"Could not delete old summary message: {e}")
        
        # Post new message
        try:
            message = await channel.send(embed=embed)
            calendar_config.last_message_id = message.id
            self.log.info(f"Posted weekly summary to {channel.name} (message ID: {message.id})")
        except Exception as e:
            self.log.error(f"Error posting weekly summary: {e}")

    def _create_summary_embed(self, events: List[dict], calendar_config: CalendarConfig, guild_id: int) -> discord.Embed:
        """Create an embed for the weekly summary"""
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
                if hasattr(event_start, 'date'):
                    day = event_start.date()
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
                    if hasattr(start, 'strftime'):
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
        
        embed.set_footer(text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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


async def setup(bot):
    await bot.add_cog(CalendarCog(bot))