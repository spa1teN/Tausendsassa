# cogs/server_monitor.py

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.config import config
from core.timezone_util import get_current_time


class ServerMonitor(commands.Cog):
    """Server overview monitoring cog - provides centralized server statistics"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("server_monitor")

        # In-memory cache for monitor config
        self._monitor_messages: Dict[str, str] = {}  # channel_id -> message_id
        self._last_update: float = 0

    async def cog_load(self):
        """Load configuration and start background task"""
        await self._load_config()
        self.update_task.start()

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.update_task.cancel()

    async def _load_config(self):
        """Load monitor configuration from database"""
        if self.bot.db:
            cfg = await self.bot.db.monitor.get_monitor_config('server')
            self._monitor_messages = cfg.get('monitor_messages', {})
            self._last_update = cfg.get('last_update', 0)

    async def _save_config(self):
        """Save monitor configuration to database"""
        if self.bot.db:
            # Delete removed messages first
            existing = await self.bot.db.monitor.get_all_monitor_messages_dict('server')
            for channel_id in existing:
                if channel_id not in self._monitor_messages:
                    await self.bot.db.monitor.delete_message(int(channel_id), 'server')

            # Save current messages
            for channel_id, message_id in self._monitor_messages.items():
                await self.bot.db.monitor.set_message(
                    channel_id=int(channel_id),
                    message_id=int(message_id),
                    monitor_type='server',
                    auto_update_interval=1800  # 30 minutes
                )

    async def _get_feeds_data(self) -> Dict[int, Dict[str, Any]]:
        """Get RSS feeds data for all guilds from database"""
        feeds_data = {}

        if self.bot.db:
            # Get all feeds from database
            rows = await self.bot.db.feeds.fetch(
                "SELECT guild_id, COUNT(*) as count FROM feeds GROUP BY guild_id"
            )
            for row in rows:
                feeds_data[row['guild_id']] = {
                    "count": row['count'],
                }

        return feeds_data

    async def _get_maps_data(self) -> Dict[int, Dict[str, Any]]:
        """Get map data for all guilds from database"""
        maps_data = {}

        if self.bot.db:
            # Get map settings with pin counts
            rows = await self.bot.db.maps.fetch("""
                SELECT ms.guild_id, ms.region,
                       (SELECT COUNT(*) FROM map_pins mp WHERE mp.guild_id = ms.guild_id) as pin_count
                FROM map_settings ms
            """)
            for row in rows:
                maps_data[row['guild_id']] = {
                    "region": row['region'] or "world",
                    "pin_count": row['pin_count']
                }

        return maps_data

    async def _get_calendars_data(self) -> Dict[int, Dict[str, Any]]:
        """Get calendar data for all guilds from database"""
        calendars_data = {}

        if self.bot.db:
            # Get calendar counts per guild
            rows = await self.bot.db.calendars.fetch(
                "SELECT guild_id, COUNT(*) as count FROM calendars GROUP BY guild_id"
            )
            for row in rows:
                calendars_data[row['guild_id']] = {
                    "count": row['count'],
                }

        return calendars_data

    async def _create_server_overview_embed(self) -> discord.Embed:
        """Create server overview embed"""
        embed = discord.Embed(
            title="Server Overview",
            description="Overview of all servers using this bot",
            color=0x5865F2,
            timestamp=get_current_time()
        )

        # Get all data from database
        feeds_data = await self._get_feeds_data()
        maps_data = await self._get_maps_data()
        calendars_data = await self._get_calendars_data()

        # Collect all guilds
        all_guild_ids = set()
        all_guild_ids.update(feeds_data.keys())
        all_guild_ids.update(maps_data.keys())
        all_guild_ids.update(calendars_data.keys())

        # Add bot's guilds that might not have configs yet
        for guild in self.bot.guilds:
            all_guild_ids.add(guild.id)

        # Create overview fields
        total_feeds = sum(data["count"] for data in feeds_data.values())
        total_pins = sum(data["pin_count"] for data in maps_data.values())
        total_calendars = sum(data["count"] for data in calendars_data.values())

        embed.add_field(
            name="Statistics",
            value=f"**{len(all_guild_ids)}** servers\n"
                  f"**{total_feeds}** RSS feeds\n"
                  f"**{total_pins}** map pins\n"
                  f"**{total_calendars}** calendars",
            inline=True
        )

        # Sort guilds by name for consistent display
        sorted_guilds = []
        for guild_id in all_guild_ids:
            guild = self.bot.get_guild(guild_id)
            if guild:
                sorted_guilds.append((guild.name, guild_id, guild))
            else:
                sorted_guilds.append((f"Unknown Guild", guild_id, None))

        sorted_guilds.sort(key=lambda x: x[0].lower())

        # Create detailed server list (split into multiple fields if needed)
        server_info = []
        for guild_name, guild_id, guild in sorted_guilds:
            # Get data for this guild
            feeds_info = feeds_data.get(guild_id, {})
            maps_info = maps_data.get(guild_id, {})
            calendars_info = calendars_data.get(guild_id, {})

            # Build server info line
            info_parts = []

            if feeds_info:
                info_parts.append(f"{feeds_info['count']} feeds")

            if maps_info:
                region = maps_info["region"]
                pins = maps_info["pin_count"]
                info_parts.append(f"{region} map ({pins} pins)")

            if calendars_info:
                info_parts.append(f"{calendars_info['count']} calendars")

            if not info_parts:
                info_parts.append("no features configured")

            # Show server name with ID in brackets, then features
            server_info.append(f"**{guild_name}** (`{guild_id}`)\n{' | '.join(info_parts)}")

        # Split server info into multiple fields if needed (Discord 1024 char limit per field)
        if server_info:
            current_field = []
            current_length = 0
            field_count = 1

            for server in server_info:
                if current_length + len(server) + 1 > 1000:  # Leave some buffer
                    # Add current field
                    embed.add_field(
                        name=f"Servers" + (f" (Part {field_count})" if field_count > 1 else ""),
                        value="\n\n".join(current_field),
                        inline=False
                    )
                    # Start new field
                    current_field = [server]
                    current_length = len(server)
                    field_count += 1
                else:
                    current_field.append(server)
                    current_length += len(server) + 1

            # Add last field
            if current_field:
                embed.add_field(
                    name=f"Servers" + (f" (Part {field_count})" if field_count > 1 else ""),
                    value="\n\n".join(current_field),
                    inline=False
                )
        else:
            embed.add_field(
                name="Servers",
                value="No servers found.",
                inline=False
            )

        embed.set_footer(text="Auto-updates every 30 minutes")
        return embed

    @tasks.loop(minutes=30)
    async def update_task(self):
        """Update monitor messages every 30 minutes"""
        self.log.info("Updating server monitor messages")

        embed = await self._create_server_overview_embed()

        # Update all stored monitor messages
        for channel_id, message_id in list(self._monitor_messages.items()):
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    # Channel not found, remove from config
                    del self._monitor_messages[channel_id]
                    continue

                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.edit(embed=embed)
                except discord.NotFound:
                    # Message was deleted, remove from config
                    del self._monitor_messages[channel_id]
                    self.log.info(f"Removed deleted monitor message from channel {channel_id}")
                except discord.Forbidden:
                    self.log.warning(f"No permission to update monitor message in channel {channel_id}")

            except Exception as e:
                self.log.error(f"Error updating monitor message in channel {channel_id}: {e}")

        # Save config after cleanup
        await self._save_config()

        # Update last update time
        self._last_update = datetime.now(timezone.utc).timestamp()

    @update_task.before_loop
    async def before_update_task(self):
        """Wait for bot to be ready before starting updates"""
        await self.bot.wait_until_ready()
        self.log.info("Server monitor update task started")

    @app_commands.command(name="owner_server_monitor", description="Display server overview with RSS feeds, maps, and calendars")
    async def server_monitor_command(self, interaction: discord.Interaction):
        """Display server overview monitoring information"""

        # Permission check - only bot owner
        if interaction.user.id != config.owner_id:
            await interaction.response.send_message(
                "This command is only available to the bot owner.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            channel_id = str(interaction.channel_id)

            # Check if we already have a monitor message in this channel
            existing_message_id = self._monitor_messages.get(channel_id)

            if existing_message_id:
                try:
                    # Try to fetch and update the existing message
                    existing_message = await interaction.channel.fetch_message(int(existing_message_id))
                    embed = await self._create_server_overview_embed()
                    await existing_message.edit(embed=embed)

                    # Send confirmation that we updated the existing message
                    await interaction.followup.send(
                        "Updated existing server monitor message above!",
                        ephemeral=True
                    )

                    self.log.info(f"Updated existing server monitor message {existing_message_id} in channel {channel_id}")
                    return

                except discord.NotFound:
                    # Message was deleted, remove from config and create new one
                    del self._monitor_messages[channel_id]
                    await self._save_config()
                    self.log.info(f"Existing server monitor message {existing_message_id} was deleted, creating new one")

                except Exception as e:
                    self.log.error(f"Error updating existing server monitor message: {e}")
                    # Continue to create a new message

            # Create new monitor message
            embed = await self._create_server_overview_embed()
            message = await interaction.followup.send(embed=embed)

            # Store the new message ID
            self._monitor_messages[channel_id] = str(message.id)
            await self._save_config()

            self.log.info(f"Created new server monitor message {message.id} in channel {channel_id}")

        except Exception as e:
            self.log.error(f"Error in server monitor command: {e}")
            error_embed = discord.Embed(
                title="Server Monitor Error",
                description=f"An error occurred while gathering server data:\n```\n{str(e)}\n```",
                color=0xff0000
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function called when loading the cog"""
    await bot.add_cog(ServerMonitor(bot))
