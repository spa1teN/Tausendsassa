# cogs/calendar.py

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
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


class CalendarConfigModal(discord.ui.Modal):
    """Modal for editing calendar blacklist and whitelist"""

    def __init__(self, cog: 'CalendarCog', guild_id: int, calendar_id: str, calendar):
        super().__init__(title=f"Edit Calendar: {calendar_id}")
        self.cog = cog
        self.guild_id = guild_id
        self.calendar_id = calendar_id
        self.calendar = calendar

        # Add blacklist field
        self.blacklist_field = discord.ui.TextInput(
            label="Blacklist Terms (comma separated)",
            placeholder="term1, term2, term3",
            default=", ".join(calendar.blacklist or []),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )
        self.add_item(self.blacklist_field)

        # Add whitelist field
        self.whitelist_field = discord.ui.TextInput(
            label="Whitelist Terms (comma separated)",
            placeholder="term1, term2, term3",
            default=", ".join(calendar.whitelist or []),
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

            # Update calendar in database
            if self.cog.bot.db:
                await self.cog.bot.db.calendars.update_filters(
                    self.calendar.id,
                    blacklist=new_blacklist,
                    whitelist=new_whitelist
                )

            # Update cache
            self.calendar.blacklist = new_blacklist
            self.calendar.whitelist = new_whitelist

            # Create success embed
            embed = discord.Embed(
                title="Calendar Configuration Updated",
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
                f"An error occurred while updating the calendar configuration: {str(e)}",
                ephemeral=True
            )


class CalendarConfigView(discord.ui.View):
    """View for configuring calendars with dropdown selection"""

    def __init__(self, cog: 'CalendarCog', guild_id: int, calendars: List):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.calendars = {cal.calendar_id: cal for cal in calendars}

        # Create dropdown options
        options = []
        for cal in calendars:
            guild = cog.bot.get_guild(guild_id)
            text_channel = guild.get_channel(cal.text_channel_id) if guild else None
            text_name = text_channel.name if text_channel else f"Channel {cal.text_channel_id}"

            description = f"Posts to #{text_name}"
            blacklist_len = len(cal.blacklist) if cal.blacklist else 0
            whitelist_len = len(cal.whitelist) if cal.whitelist else 0
            if blacklist_len > 0 or whitelist_len > 0:
                filter_count = blacklist_len + whitelist_len
                description += f" - {filter_count} filter terms"

            options.append(discord.SelectOption(
                label=cal.calendar_id,
                value=cal.calendar_id,
                description=description[:100]
            ))

        self.calendar_select = discord.ui.Select(
            placeholder="Select a calendar to configure...",
            options=options[:25]
        )
        self.calendar_select.callback = self.calendar_selected
        self.add_item(self.calendar_select)

    async def calendar_selected(self, interaction: discord.Interaction):
        """Handle calendar selection for configuration"""
        selected_calendar_id = self.calendar_select.values[0]
        calendar = self.calendars[selected_calendar_id]

        guild = self.cog.bot.get_guild(self.guild_id)
        text_channel = guild.get_channel(calendar.text_channel_id) if guild else None
        voice_channel = guild.get_channel(calendar.voice_channel_id) if guild else None

        embed = discord.Embed(
            title=f"Calendar Configuration: {selected_calendar_id}",
            color=0x5865F2
        )

        embed.add_field(name="Calendar ID", value=selected_calendar_id, inline=True)
        embed.add_field(name="Text Channel", value=text_channel.mention if text_channel else f"Channel {calendar.text_channel_id}", inline=True)
        embed.add_field(name="Voice Channel", value=voice_channel.mention if voice_channel else f"Channel {calendar.voice_channel_id}", inline=True)
        embed.add_field(name="iCal URL", value=calendar.ical_url, inline=False)

        if calendar.blacklist:
            embed.add_field(
                name="Blacklisted Terms",
                value=", ".join(f"`{term}`" for term in calendar.blacklist),
                inline=False
            )
        else:
            embed.add_field(name="Blacklisted Terms", value="None", inline=False)

        if calendar.whitelist:
            embed.add_field(
                name="Whitelisted Terms",
                value=", ".join(f"`{term}`" for term in calendar.whitelist),
                inline=False
            )
        else:
            embed.add_field(name="Whitelisted Terms", value="None", inline=False)

        if calendar.reminder_role_id:
            role = guild.get_role(calendar.reminder_role_id) if guild else None
            if role:
                embed.add_field(name="Reminder Role", value=role.mention, inline=True)
            else:
                embed.add_field(name="Reminder Role", value=f"Role {calendar.reminder_role_id} (not found)", inline=True)
        else:
            embed.add_field(name="Reminder Role", value="None (no role pings)", inline=True)

        if calendar.last_sync:
            embed.add_field(
                name="Last Sync",
                value=f"<t:{int(calendar.last_sync.timestamp())}:R>",
                inline=True
            )

        # Get event count from database
        if self.cog.bot.db:
            event_ids = await self.cog.bot.db.calendars.get_created_event_ids(calendar.id)
            embed.add_field(name="Discord Events Created", value=str(len(event_ids)), inline=True)

        view = discord.ui.View(timeout=300)
        edit_button = discord.ui.Button(
            label="Edit Filters",
            style=discord.ButtonStyle.primary,
            emoji="✏️"
        )

        async def edit_button_callback(button_interaction):
            modal = CalendarConfigModal(self.cog, self.guild_id, selected_calendar_id, calendar)
            await button_interaction.response.send_modal(modal)

        edit_button.callback = edit_button_callback
        view.add_item(edit_button)

        await interaction.response.edit_message(embed=embed, view=view)


class CalendarRemoveView(discord.ui.View):
    """View for removing calendars with dropdown selection"""

    def __init__(self, cog: 'CalendarCog', guild_id: int, calendars: List):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.calendars = {cal.calendar_id: cal for cal in calendars}

        options = []
        for cal in calendars:
            guild = cog.bot.get_guild(guild_id)
            text_channel = guild.get_channel(cal.text_channel_id) if guild else None
            text_name = text_channel.name if text_channel else f"Channel {cal.text_channel_id}"

            description = f"Posts to #{text_name}"
            blacklist_len = len(cal.blacklist) if cal.blacklist else 0
            if blacklist_len > 0:
                description += f" - {blacklist_len} blacklisted terms"

            options.append(discord.SelectOption(
                label=cal.calendar_id,
                value=cal.calendar_id,
                description=description[:100]
            ))

        self.calendar_select = discord.ui.Select(
            placeholder="Select a calendar to remove...",
            options=options[:25]
        )
        self.calendar_select.callback = self.calendar_selected
        self.add_item(self.calendar_select)

    async def calendar_selected(self, interaction: discord.Interaction):
        """Handle calendar selection for removal"""
        await interaction.response.defer()

        selected_calendar_id = self.calendar_select.values[0]

        success = await self.cog.remove_calendar(self.guild_id, selected_calendar_id)

        if success:
            embed = discord.Embed(
                title="Calendar Removed",
                description=f"Calendar `{selected_calendar_id}` has been successfully removed.",
                color=0x00ff00
            )
        else:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to remove calendar `{selected_calendar_id}`.",
                color=0xff0000
            )

        await interaction.edit_original_response(embed=embed, view=None)


class CalendarCog(commands.Cog):
    """Cog for managing iCal calendar integration with Discord events and summaries"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("calendar")

        # In-memory cache for calendars (backed by database)
        self._calendars_cache: Dict[int, Dict[str, any]] = {}  # guild_id -> {cal_id: calendar}

    async def cog_load(self):
        """Load calendars from database and start tasks"""
        await self._load_all_calendars()

        self.calendar_update_task.start()
        self.event_status_task.start()
        self.reminder_task.start()

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.calendar_update_task.cancel()
        self.event_status_task.cancel()
        self.reminder_task.cancel()

    async def _load_all_calendars(self):
        """Load all calendars from database into cache"""
        self._calendars_cache.clear()

        if not self.bot.db:
            self.log.warning("Database not available, skipping calendar load")
            return

        for guild in self.bot.guilds:
            calendars = await self.bot.db.calendars.get_guild_calendars(guild.id)
            if calendars:
                self._calendars_cache[guild.id] = {cal.calendar_id: cal for cal in calendars}

        total = sum(len(cals) for cals in self._calendars_cache.values())
        self.log.info(f"Loaded {total} calendars for {len(self._calendars_cache)} guilds from database")

    async def get_guild_calendars(self, guild_id: int) -> Dict[str, any]:
        """Get calendars for a guild from cache or database"""
        if guild_id in self._calendars_cache:
            return self._calendars_cache[guild_id]

        if self.bot.db:
            calendars = await self.bot.db.calendars.get_guild_calendars(guild_id)
            if calendars:
                self._calendars_cache[guild_id] = {cal.calendar_id: cal for cal in calendars}
                return self._calendars_cache[guild_id]

        return {}

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

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You need administrator permissions to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if not ical_url.startswith(('http://', 'https://')):
                await interaction.followup.send(
                    "Please provide a valid HTTP/HTTPS URL for the iCal file.",
                    ephemeral=True
                )
                return

            blacklist_terms = []
            if blacklist:
                blacklist_terms = [term.strip() for term in blacklist.split(',') if term.strip()]

            whitelist_terms = []
            if whitelist:
                whitelist_terms = [term.strip() for term in whitelist.split(',') if term.strip()]

            # Test the iCal URL
            try:
                session = await http_client.get_session()
                async with session.get(ical_url, timeout=10) as response:
                    if response.status != 200:
                        await interaction.followup.send(
                            f"Could not access iCal URL (HTTP {response.status})",
                            ephemeral=True
                        )
                        return

                    content = await response.text()
                    Calendar.from_ical(content)

            except Exception as e:
                await interaction.followup.send(
                    f"Error accessing or parsing iCal file: {str(e)}",
                    ephemeral=True
                )
                return

            guild_id = interaction.guild_id

            # Check if calendar ID already exists
            existing = await self.get_guild_calendars(guild_id)
            if calendar_id in existing:
                await interaction.followup.send(
                    f"A calendar with ID `{calendar_id}` already exists. Please choose a different ID.",
                    ephemeral=True
                )
                return

            # Create calendar in database
            if not self.bot.db:
                await interaction.followup.send("Database not available.", ephemeral=True)
                return

            calendar_data = {
                'calendar_id': calendar_id,
                'text_channel_id': text_channel.id,
                'voice_channel_id': voice_channel.id,
                'ical_url': ical_url,
                'blacklist': blacklist_terms,
                'whitelist': whitelist_terms,
                'reminder_role_id': reminder_role.id if reminder_role else None
            }

            calendar = await self.bot.db.calendars.create_calendar(guild_id, calendar_data)

            # Update cache
            if guild_id not in self._calendars_cache:
                self._calendars_cache[guild_id] = {}
            self._calendars_cache[guild_id][calendar_id] = calendar

            # Create success embed
            embed = discord.Embed(
                title="Calendar Added Successfully",
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
                embed.add_field(name="Reminder Role", value=reminder_role.mention, inline=True)
            else:
                embed.add_field(name="Reminder Role", value="None (no role pings)", inline=True)

            embed.set_footer(text="The calendar will be synced automatically every hour. Reminders are sent 1 hour before events.")

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Trigger immediate sync
            await self._sync_calendar(guild_id, calendar)

            self.log.info(f"Added calendar {calendar_id} for guild {guild_id}")

        except Exception as e:
            self.log.error(f"Error adding calendar: {e}")
            await interaction.followup.send(
                f"An error occurred while adding the calendar: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="cal_remove", description="Remove an existing iCal calendar")
    async def cal_remove(self, interaction: discord.Interaction):
        """Remove an existing iCal calendar"""

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You need administrator permissions to use this command.",
                ephemeral=True
            )
            return

        guild_id = interaction.guild_id
        calendars = await self.get_guild_calendars(guild_id)

        if not calendars:
            await interaction.response.send_message(
                "No calendars found for this server. Use `/cal_add` to add one first.",
                ephemeral=True
            )
            return

        view = CalendarRemoveView(self, guild_id, list(calendars.values()))

        embed = discord.Embed(
            title="Remove Calendar",
            description="Select a calendar to remove from the dropdown below:",
            color=0xff9900
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="cal_config", description="Configure existing calendar filters and settings")
    async def cal_config(self, interaction: discord.Interaction):
        """Configure an existing iCal calendar"""

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You need administrator permissions to use this command.",
                ephemeral=True
            )
            return

        guild_id = interaction.guild_id
        calendars = await self.get_guild_calendars(guild_id)

        if not calendars:
            await interaction.response.send_message(
                "No calendars found for this server. Use `/cal_add` to add one first.",
                ephemeral=True
            )
            return

        view = CalendarConfigView(self, guild_id, list(calendars.values()))

        embed = discord.Embed(
            title="Calendar Configuration",
            description="Select a calendar to view details and edit filters:",
            color=0x5865F2
        )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def remove_calendar(self, guild_id: int, calendar_id: str) -> bool:
        """Remove a calendar and clean up associated data"""
        try:
            calendars = await self.get_guild_calendars(guild_id)
            if calendar_id not in calendars:
                return False

            calendar = calendars[calendar_id]

            # Delete the last summary message if it exists
            if calendar.last_message_id:
                try:
                    guild = self.bot.get_guild(guild_id)
                    channel = guild.get_channel(calendar.text_channel_id) if guild else None
                    if channel:
                        message = await channel.fetch_message(calendar.last_message_id)
                        await message.delete()
                except Exception as e:
                    self.log.warning(f"Could not delete last message for calendar {calendar_id}: {e}")

            # Delete created Discord events
            if self.bot.db:
                event_ids = await self.bot.db.calendars.get_created_event_ids(calendar.id)
                guild = self.bot.get_guild(guild_id)
                if guild:
                    for event_id in event_ids:
                        try:
                            event = await guild.fetch_scheduled_event(event_id)
                            await event.delete()
                        except Exception as e:
                            self.log.warning(f"Could not delete Discord event {event_id}: {e}")

            # Delete from database
            if self.bot.db:
                await self.bot.db.calendars.delete_calendar(calendar.id)

            # Remove from cache
            if guild_id in self._calendars_cache and calendar_id in self._calendars_cache[guild_id]:
                del self._calendars_cache[guild_id][calendar_id]

            self.log.info(f"Removed calendar {calendar_id} from guild {guild_id}")
            return True

        except Exception as e:
            self.log.error(f"Error removing calendar {calendar_id}: {e}")
            return False

    @tasks.loop(hours=1)
    async def calendar_update_task(self):
        """Task that runs every hour to sync all calendars"""
        self.log.info("Starting calendar sync task")

        for guild_id, calendars in self._calendars_cache.items():
            for calendar_id, calendar in calendars.items():
                try:
                    await self._sync_calendar(guild_id, calendar)
                except Exception as e:
                    self.log.error(f"Error syncing calendar {calendar_id} in guild {guild_id}: {e}")

        self.log.info("Calendar sync task completed")

    @calendar_update_task.before_loop
    async def before_calendar_update(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def event_status_task(self):
        """Task that runs every 5 minutes to monitor and update Discord event statuses"""
        now = datetime.now(timezone.utc)
        events_started = 0
        events_ended = 0
        events_cleaned = 0

        if not self.bot.db:
            return

        for guild_id, calendars in self._calendars_cache.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            for calendar_id, calendar in calendars.items():
                event_ids = await self.bot.db.calendars.get_created_event_ids(calendar.id)

                for event_id in event_ids:
                    try:
                        discord_event = await guild.fetch_scheduled_event(event_id)

                        if (discord_event.status == discord.EventStatus.scheduled and
                            discord_event.start_time <= now):
                            await discord_event.start()
                            self.log.info(f"Auto-started Discord event: {discord_event.name} in {guild.name}")
                            events_started += 1

                        elif (discord_event.status == discord.EventStatus.active and
                              discord_event.end_time and discord_event.end_time <= now):
                            await discord_event.end()
                            self.log.info(f"Auto-ended Discord event: {discord_event.name} in {guild.name}")
                            events_ended += 1

                    except discord.NotFound:
                        await self.bot.db.calendars.remove_event_by_discord_id(calendar.id, event_id)
                        events_cleaned += 1
                    except discord.HTTPException as e:
                        if "Channel already has an active event" not in str(e):
                            self.log.warning(f"HTTP error managing event status for event {event_id}: {e}")
                    except Exception as e:
                        self.log.warning(f"Error managing event status for event {event_id}: {e}")

        if events_started > 0 or events_ended > 0 or events_cleaned > 0:
            self.log.info(f"Event status check completed: {events_started} started, {events_ended} ended, {events_cleaned} cleaned up")

    @event_status_task.before_loop
    async def before_event_status(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def reminder_task(self):
        """Task that runs every 15 minutes to send reminders for upcoming events"""
        now = datetime.now(timezone.utc)
        reminders_sent = 0

        if not self.bot.db:
            return

        for guild_id, calendars in self._calendars_cache.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            for calendar_id, calendar in calendars.items():
                try:
                    events = await self._fetch_calendar_events(calendar.ical_url)
                    if not events:
                        continue

                    filtered_events = self._filter_events(events, calendar.blacklist or [], calendar.whitelist or [])

                    for event in filtered_events:
                        event_start = event.get('start')
                        if not event_start:
                            continue

                        if not isinstance(event_start, datetime):
                            event_start = datetime.combine(event_start, datetime.min.time())

                        if event_start.tzinfo is None:
                            event_start = event_start.replace(tzinfo=timezone.utc)

                        time_until_event = event_start - now
                        if timedelta(minutes=45) <= time_until_event <= timedelta(minutes=75):
                            reminder_key = f"{calendar_id}_{event['title']}_{event_start.isoformat()}"

                            is_sent = await self.bot.db.calendars.is_reminder_sent(calendar.id, reminder_key)
                            if is_sent:
                                continue

                            success = await self._send_event_reminder(guild_id, calendar, event, event_start)
                            if success:
                                await self.bot.db.calendars.mark_reminder_sent(calendar.id, reminder_key)
                                reminders_sent += 1

                except Exception as e:
                    self.log.error(f"Error processing reminders for calendar {calendar_id} in guild {guild_id}: {e}")

        if reminders_sent > 0:
            self.log.info(f"Sent {reminders_sent} event reminders")

        await self._cleanup_old_reminders()

    @reminder_task.before_loop
    async def before_reminder_task(self):
        await self.bot.wait_until_ready()

    async def _sync_calendar(self, guild_id: int, calendar):
        """Sync a single calendar"""
        self.log.info(f"Syncing calendar {calendar.calendar_id} for guild {guild_id}")

        try:
            events = await self._fetch_calendar_events(calendar.ical_url)

            if events is None:
                self.log.warning(f"Failed to fetch calendar events for {calendar.calendar_id}")
                return

            filtered_events = self._filter_events(events, calendar.blacklist or [], calendar.whitelist or [])
            weekly_events, week_start = self._get_weekly_events(filtered_events)

            await self._post_weekly_summary(guild_id, calendar, weekly_events, week_start)
            await self._manage_discord_events(guild_id, calendar, weekly_events)

            if self.bot.db:
                await self.bot.db.calendars.update_last_sync(calendar.id)

            # Update cache
            calendar.last_sync = datetime.now(timezone.utc)

        except Exception as e:
            self.log.error(f"Error in _sync_calendar for {calendar.calendar_id}: {e}")

    async def _fetch_calendar_events(self, ical_url: str) -> Optional[List[dict]]:
        """Fetch and parse iCal calendar events"""
        try:
            async def fetch_ical():
                session = await http_client.get_session()
                timeout = config.http_timeout
                for pattern, custom_timeout in config.feed_specific_timeouts.items():
                    if pattern in ical_url.lower():
                        timeout = custom_timeout
                        break
                async with session.get(ical_url, timeout=timeout) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    return await response.text()

            content = await retry_handler.execute_with_retry(
                f"fetch_ical_{ical_url}",
                fetch_ical
            )

            cal = Calendar.from_ical(content)

            start_date = datetime.now(timezone.utc)
            end_date = start_date + timedelta(weeks=4)

            try:
                events = recurring_ical_events.of(cal).between(start_date, end_date)
            except Exception as e:
                self.log.warning(f"Error parsing recurring events, falling back to basic parsing: {e}")
                events = []
                for component in cal.walk():
                    if component.name == "VEVENT":
                        events.append(component)

            parsed_events = []
            for event in events:
                try:
                    if hasattr(event, 'get'):
                        title = str(event.get('SUMMARY', 'No Title'))
                        start = event.get('DTSTART').dt if event.get('DTSTART') else None
                        end = event.get('DTEND').dt if event.get('DTEND') else None
                        description = str(event.get('DESCRIPTION', ''))
                        location = str(event.get('LOCATION', ''))
                    else:
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
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "Unknown error"

            if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
                self.log.error(f"Timeout fetching calendar from {ical_url}: {error_type}: {error_msg}")
            else:
                self.log.error(f"Error fetching calendar from {ical_url}: {error_type}: {error_msg}")
            return None

    def _filter_events(self, events: List[dict], blacklist: List[str], whitelist: List[str] = None) -> List[dict]:
        """Filter events based on blacklist and whitelist terms"""
        if not blacklist and not whitelist:
            return events

        whitelist = whitelist or []

        filtered = []
        for event in events:
            title = event.get('title', '').lower()

            is_blacklisted = any(term.lower() in title for term in blacklist) if blacklist else False

            if is_blacklisted:
                continue

            if whitelist:
                is_whitelisted = any(term.lower() in title for term in whitelist)
                if is_whitelisted:
                    filtered.append(event)
            else:
                filtered.append(event)

        return filtered

    def _get_weekly_events(self, events: List[dict]) -> tuple[List[dict], datetime]:
        """Get events for the current week (Monday to Sunday)"""
        now = datetime.now(timezone.utc)

        days_since_monday = now.weekday()
        week_start = now - timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

        weekly_events = []
        for event in events:
            event_start = event.get('start')
            if event_start:
                if isinstance(event_start, datetime):
                    event_datetime = event_start
                    if event_datetime.tzinfo is None:
                        event_datetime = event_datetime.replace(tzinfo=timezone.utc)
                else:
                    event_datetime = datetime.combine(event_start, datetime.min.time())
                    event_datetime = event_datetime.replace(tzinfo=timezone.utc)

                if week_start <= event_datetime <= week_end:
                    weekly_events.append(event)

        def sort_key(event):
            start = event.get('start')
            if start is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            elif isinstance(start, datetime):
                return start if start.tzinfo else start.replace(tzinfo=timezone.utc)
            else:
                return datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)

        weekly_events.sort(key=sort_key)
        return weekly_events, week_start

    async def _post_weekly_summary(self, guild_id: int, calendar, events: List[dict], week_start: datetime):
        """Post or update the weekly summary message"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(calendar.text_channel_id)
        if not channel:
            return

        # Get event title to ID mapping from database
        event_id_map = {}
        if self.bot.db:
            event_id_map = await self.bot.db.calendars.get_event_id_map(calendar.id)

        embed = self._create_summary_embed(events, event_id_map, guild_id)

        is_new_week = (calendar.current_week_start is None or
                      calendar.current_week_start != week_start)

        if is_new_week or not calendar.last_message_id:
            if calendar.last_message_id:
                try:
                    old_message = await channel.fetch_message(calendar.last_message_id)
                    await old_message.delete()
                except Exception as e:
                    self.log.warning(f"Could not delete old summary message: {e}")

            try:
                message = await channel.send(embed=embed)
                if self.bot.db:
                    await self.bot.db.calendars.update_last_message(calendar.id, message.id, week_start)
                calendar.last_message_id = message.id
                calendar.current_week_start = week_start
                self.log.info(f"Posted new weekly summary to {channel.name} (message ID: {message.id})")
            except Exception as e:
                self.log.error(f"Error posting weekly summary: {e}")
        else:
            try:
                old_message = await channel.fetch_message(calendar.last_message_id)
                await old_message.edit(embed=embed)
                self.log.info(f"Updated weekly summary in {channel.name} (message ID: {calendar.last_message_id})")
            except Exception as e:
                self.log.warning(f"Could not update existing message, posting new one: {e}")
                try:
                    message = await channel.send(embed=embed)
                    if self.bot.db:
                        await self.bot.db.calendars.update_last_message(calendar.id, message.id, week_start)
                    calendar.last_message_id = message.id
                    calendar.current_week_start = week_start
                except Exception as e2:
                    self.log.error(f"Error posting fallback weekly summary: {e2}")

    def _create_summary_embed(self, events: List[dict], event_id_map: Dict[str, int], guild_id: int) -> discord.Embed:
        """Create an embed for the weekly summary"""
        from core.timezone_util import to_guild_timezone

        embed = discord.Embed(
            title="Weekly Calendar Summary",
            color=0x5865F2
        )

        if not events:
            embed.description = "No events scheduled for this week."
            return embed

        days = {}
        for event in events:
            event_start = event.get('start')
            if event_start:
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

        for day_str, day_events in days.items():
            event_text = ""
            for event in day_events:
                title = event.get('title', 'No Title')
                start = event.get('start')

                if start:
                    if isinstance(start, datetime):
                        guild_start = to_guild_timezone(start, guild_id)
                        time_str = guild_start.strftime("%H:%M")
                    elif hasattr(start, 'strftime'):
                        time_str = start.strftime("%H:%M")
                    else:
                        time_str = "All day"
                else:
                    time_str = "Time TBD"

                if title in event_id_map:
                    discord_event_id = event_id_map[title]
                    event_link = f"https://discord.com/events/{guild_id}/{discord_event_id}"
                    event_text += f"* **{time_str}** - [{title}]({event_link})\n"
                else:
                    event_text += f"* **{time_str}** - {title}\n"

            embed.add_field(
                name=day_str,
                value=event_text or "No events",
                inline=False
            )

        now_guild = to_guild_timezone(datetime.now(timezone.utc), guild_id)
        embed.set_footer(text=f"Last updated: {now_guild.strftime('%Y-%m-%d %H:%M')}")
        return embed

    async def _manage_discord_events(self, guild_id: int, calendar, events: List[dict]):
        """Create, update, or delete Discord events based on calendar events"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_channel = guild.get_channel(calendar.voice_channel_id)
        if not voice_channel:
            return

        if not self.bot.db:
            return

        # Get existing Discord events
        existing_events = {}
        event_ids = await self.bot.db.calendars.get_created_event_ids(calendar.id)

        for event_id in event_ids:
            try:
                discord_event = await guild.fetch_scheduled_event(event_id)
                existing_events[discord_event.name] = discord_event
            except Exception:
                await self.bot.db.calendars.remove_event_by_discord_id(calendar.id, event_id)

        events_to_keep = set()

        for event in events:
            event_title = event.get('title', 'No Title')
            event_start = event.get('start')
            event_end = event.get('end')
            event_desc = event.get('description', '')

            if not event_start:
                continue

            if not isinstance(event_start, datetime):
                event_start = datetime.combine(event_start, datetime.min.time())
            if event_end and not isinstance(event_end, datetime):
                event_end = datetime.combine(event_end, datetime.min.time())

            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=timezone.utc)
            if event_end and event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=timezone.utc)

            if not event_end:
                event_end = event_start + timedelta(hours=1)

            events_to_keep.add(event_title)

            if event_title in existing_events:
                discord_event = existing_events[event_title]
                try:
                    if (discord_event.start_time != event_start or
                        discord_event.end_time != event_end or
                        discord_event.description != event_desc):

                        await discord_event.edit(
                            start_time=event_start,
                            end_time=event_end,
                            description=event_desc[:1000]
                        )
                        self.log.info(f"Updated Discord event: {event_title}")
                except Exception as e:
                    self.log.warning(f"Could not update Discord event {event_title}: {e}")
            else:
                try:
                    discord_event = await guild.create_scheduled_event(
                        name=event_title,
                        start_time=event_start,
                        end_time=event_end,
                        description=event_desc[:1000],
                        entity_type=discord.EntityType.voice,
                        channel=voice_channel,
                        privacy_level=discord.PrivacyLevel.guild_only
                    )
                    await self.bot.db.calendars.add_event(calendar.id, event_title, discord_event.id)
                    self.log.info(f"Created Discord event: {event_title}")
                except Exception as e:
                    self.log.error(f"Could not create Discord event {event_title}: {e}")

        for event_title, discord_event in existing_events.items():
            if event_title not in events_to_keep:
                try:
                    await discord_event.delete()
                    await self.bot.db.calendars.remove_event(calendar.id, event_title)
                    self.log.info(f"Deleted Discord event: {event_title}")
                except Exception as e:
                    self.log.warning(f"Could not delete Discord event {event_title}: {e}")

    async def _send_event_reminder(self, guild_id: int, calendar, event: dict, event_start: datetime) -> bool:
        """Send a reminder message for an upcoming event"""
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False

            channel = guild.get_channel(calendar.text_channel_id)
            if not channel:
                return False

            from core.timezone_util import to_guild_timezone

            embed = discord.Embed(
                title="Event Reminder",
                color=0xffa500
            )

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
                description = event['description'][:500]
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
            if self.bot.db:
                event_id_map = await self.bot.db.calendars.get_event_id_map(calendar.id)
                event_title = event.get('title', 'No Title')
                if event_title in event_id_map:
                    discord_event_id = event_id_map[event_title]
                    event_link = f"https://discord.com/events/{guild_id}/{discord_event_id}"
                    embed.add_field(
                        name="Discord Event",
                        value=f"[View Event]({event_link})",
                        inline=True
                    )

            embed.set_footer(text="Event starts in approximately 1 hour")

            content = None
            if calendar.reminder_role_id:
                role = guild.get_role(calendar.reminder_role_id)
                if role:
                    content = f"{role.mention} Event starting soon!"

            await channel.send(content=content, embed=embed)

            self.log.info(f"Sent reminder for event '{event.get('title')}' in guild {guild_id}")
            return True

        except Exception as e:
            self.log.error(f"Error sending event reminder: {e}")
            return False

    async def _cleanup_old_reminders(self):
        """Clean up old sent reminders to prevent database growth"""
        try:
            if not self.bot.db:
                return

            cleaned_count = 0

            for guild_id, calendars in self._calendars_cache.items():
                for calendar_id, calendar in calendars.items():
                    count = await self.bot.db.calendars.cleanup_old_reminders(calendar.id, days=7)
                    cleaned_count += count

            if cleaned_count > 0:
                self.log.info(f"Cleaned up {cleaned_count} old reminder entries")

        except Exception as e:
            self.log.error(f"Error cleaning up old reminders: {e}")


async def setup(bot):
    await bot.add_cog(CalendarCog(bot))
