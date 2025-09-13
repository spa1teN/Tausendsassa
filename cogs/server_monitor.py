# cogs/server_monitor.py

import asyncio
import json
import yaml
from pathlib import Path
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
        
        # Create config directory
        self.config_base = Path(__file__).parents[1] / "config"
        self.config_base.mkdir(exist_ok=True)
        
        # Monitor message tracking
        self.monitor_file = self.config_base / "server_monitor.json"
        self.monitor_config = self._load_monitor_config()
        
        # Start background update task
        self.update_task.start()
        
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.update_task.cancel()
        self._save_monitor_config()
    
    def _load_monitor_config(self) -> Dict[str, Any]:
        """Load monitor configuration"""
        if self.monitor_file.exists():
            try:
                with open(self.monitor_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.log.error(f"Error loading monitor config: {e}")
        
        return {
            "monitor_messages": {},  # channel_id: message_id
            "last_update": 0
        }
    
    def _save_monitor_config(self):
        """Save monitor configuration"""
        try:
            with open(self.monitor_file, 'w', encoding='utf-8') as f:
                json.dump(self.monitor_config, f, indent=2)
        except Exception as e:
            self.log.error(f"Error saving monitor config: {e}")
    
    def _get_feeds_data(self) -> Dict[int, Dict[str, Any]]:
        """Get RSS feeds data for all guilds"""
        feeds_data = {}
        
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                
                # Check for feeds config
                feed_config_file = guild_dir / "feed_config.yaml"
                if feed_config_file.exists():
                    try:
                        with open(feed_config_file, 'r', encoding='utf-8') as f:
                            feed_config = yaml.safe_load(f) or {}
                            feeds = feed_config.get("feeds", [])
                            
                            if feeds:
                                feeds_data[guild_id] = {
                                    "count": len(feeds),
                                    "feeds": feeds
                                }
                    except Exception as e:
                        self.log.warning(f"Error loading feeds for guild {guild_id}: {e}")
        
        return feeds_data
    
    def _get_maps_data(self) -> Dict[int, Dict[str, Any]]:
        """Get map data for all guilds"""
        maps_data = {}
        
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                
                # Check for map data (stored in map.json)
                map_file = guild_dir / "map.json"
                if map_file.exists():
                    try:
                        with open(map_file, 'r', encoding='utf-8') as f:
                            map_data = json.load(f)
                            
                            # Get region from map data
                            region = map_data.get("region", "world")
                            
                            # Count pins
                            pins = map_data.get("pins", [])
                            pin_count = len(pins)
                            
                            maps_data[guild_id] = {
                                "region": region,
                                "pin_count": pin_count
                            }
                    except Exception as e:
                        self.log.warning(f"Error loading map data for guild {guild_id}: {e}")
        
        return maps_data
    
    def _get_calendars_data(self) -> Dict[int, Dict[str, Any]]:
        """Get calendar data for all guilds"""
        calendars_data = {}
        
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                
                # Check for calendars config
                calendars_file = guild_dir / "calendars.yaml"
                if calendars_file.exists():
                    try:
                        with open(calendars_file, 'r', encoding='utf-8') as f:
                            calendars_config = yaml.safe_load(f) or {}
                            
                            if calendars_config:
                                calendars_data[guild_id] = {
                                    "count": len(calendars_config),
                                    "calendars": list(calendars_config.keys())
                                }
                    except Exception as e:
                        self.log.warning(f"Error loading calendars for guild {guild_id}: {e}")
        
        return calendars_data
    
    def _create_server_overview_embed(self) -> discord.Embed:
        """Create server overview embed"""
        embed = discord.Embed(
            title="🌐 Server Overview",
            description="Overview of all servers using this bot",
            color=0x5865F2,
            timestamp=get_current_time()
        )
        
        # Get all data
        feeds_data = self._get_feeds_data()
        maps_data = self._get_maps_data()
        calendars_data = self._get_calendars_data()
        
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
            name="📊 Statistics",
            value=f"🏠 **{len(all_guild_ids)}** servers\n"
                  f"📡 **{total_feeds}** RSS feeds\n"
                  f"📍 **{total_pins}** map pins\n"
                  f"📅 **{total_calendars}** calendars",
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
            server_info.append(f"**{guild_name}** (`{guild_id}`)\n{' • '.join(info_parts)}")
        
        # Split server info into multiple fields if needed (Discord 1024 char limit per field)
        if server_info:
            current_field = []
            current_length = 0
            field_count = 1
            
            for server in server_info:
                if current_length + len(server) + 1 > 1000:  # Leave some buffer
                    # Add current field
                    embed.add_field(
                        name=f"🏠 Servers" + (f" (Part {field_count})" if field_count > 1 else ""),
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
                    name=f"🏠 Servers" + (f" (Part {field_count})" if field_count > 1 else ""),
                    value="\n\n".join(current_field),
                    inline=False
                )
        else:
            embed.add_field(
                name="🏠 Servers",
                value="No servers found.",
                inline=False
            )
        
        embed.set_footer(text="Auto-updates every 30 minutes")
        return embed
    
    @tasks.loop(minutes=30)
    async def update_task(self):
        """Update monitor messages every 30 minutes"""
        self.log.info("Updating server monitor messages")
        
        embed = self._create_server_overview_embed()
        
        # Update all stored monitor messages
        for channel_id, message_id in list(self.monitor_config["monitor_messages"].items()):
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    # Channel not found, remove from config
                    del self.monitor_config["monitor_messages"][channel_id]
                    continue
                
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.edit(embed=embed)
                except discord.NotFound:
                    # Message was deleted, remove from config
                    del self.monitor_config["monitor_messages"][channel_id]
                    self.log.info(f"Removed deleted monitor message from channel {channel_id}")
                except discord.Forbidden:
                    self.log.warning(f"No permission to update monitor message in channel {channel_id}")
                
            except Exception as e:
                self.log.error(f"Error updating monitor message in channel {channel_id}: {e}")
        
        # Save config after cleanup
        self._save_monitor_config()
        
        # Update last update time
        self.monitor_config["last_update"] = datetime.now(timezone.utc).timestamp()
        self._save_monitor_config()
    
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
                "❌ This command is only available to the bot owner.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            channel_id = str(interaction.channel_id)
            
            # Check if we already have a monitor message in this channel
            existing_message_id = self.monitor_config["monitor_messages"].get(channel_id)
            
            if existing_message_id:
                try:
                    # Try to fetch and update the existing message
                    existing_message = await interaction.channel.fetch_message(int(existing_message_id))
                    embed = self._create_server_overview_embed()
                    await existing_message.edit(embed=embed)
                    
                    # Send confirmation that we updated the existing message
                    await interaction.followup.send(
                        "✅ Updated existing server monitor message above!",
                        ephemeral=True
                    )
                    
                    self.log.info(f"Updated existing server monitor message {existing_message_id} in channel {channel_id}")
                    return
                    
                except discord.NotFound:
                    # Message was deleted, remove from config and create new one
                    del self.monitor_config["monitor_messages"][channel_id]
                    self._save_monitor_config()
                    self.log.info(f"Existing server monitor message {existing_message_id} was deleted, creating new one")
                
                except Exception as e:
                    self.log.error(f"Error updating existing server monitor message: {e}")
                    # Continue to create a new message
            
            # Create new monitor message
            embed = self._create_server_overview_embed()
            message = await interaction.followup.send(embed=embed)
            
            # Store the new message ID
            self.monitor_config["monitor_messages"][channel_id] = message.id
            self._save_monitor_config()
            
            self.log.info(f"Created new server monitor message {message.id} in channel {channel_id}")
            
        except Exception as e:
            self.log.error(f"Error in server monitor command: {e}")
            error_embed = discord.Embed(
                title="❌ Server Monitor Error",
                description=f"An error occurred while gathering server data:\n```\n{str(e)}\n```",
                color=0xff0000
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function called when loading the cog"""
    await bot.add_cog(ServerMonitor(bot))