# cogs/feeds.py

import os
import yaml
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import rss

# Configuration constants
POLL_INTERVAL_MINUTES = 1.0
MAX_POST_AGE_SECONDS = 1800
RATE_LIMIT_SECONDS = 30
FAILURE_THRESHOLD = 3
AUTHORIZED_USERS = [485051896655249419, 506551160354766848, 703896034820096000]
GLOBAL_MONITOR_CHANNEL_ID = 1403336394801414234

class FeedCog(commands.Cog):
    """Cog for polling RSS feeds, posting embeds, buttons, health monitoring
    and dynamic feed management with per-guild configuration."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("feeds")
        
        # Create base config directory
        self.config_base = Path(__file__).parents[1] / "config"
        self.config_base.mkdir(exist_ok=True)
        
        self.guild_configs: Dict[int, dict] = {}
        self.webhook_cache: Dict[int, discord.Webhook] = {}
        self.webhook_cache_file = self.config_base / "webhook_cache.json"
        self._load_webhook_cache()
        
        # Health stats per guild
        self.stats: Dict[int, Dict[str, dict]] = {}
        
        # Global monitor message tracking
        self.monitor_message_file = self.config_base / "monitor_message.json"
        self.monitor_message_id: Optional[int] = None
        self._load_monitor_message_id()

    def _get_guild_config_path(self, guild_id: int) -> Path:
        """Get the config file path for a specific guild"""
        guild_dir = self.config_base / str(guild_id)
        guild_dir.mkdir(exist_ok=True)
        return guild_dir / "feed_config.yaml"

    def _load_guild_config(self, guild_id: int) -> dict:
        """Load configuration for a specific guild"""
        config_path = self._get_guild_config_path(guild_id)
        if not config_path.exists():
            return {"feeds": [], "monitor_channel_id": None}
        
        try:
            with config_path.open(encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                return config
        except Exception as e:
            self.log.error(f"Failed to load config for guild {guild_id}: {e}")
            return {"feeds": [], "monitor_channel_id": None}

    def _save_guild_config(self, guild_id: int, config: dict):
        """Save configuration for a specific guild"""
        config_path = self._get_guild_config_path(guild_id)
        try:
            with config_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            self.log.error(f"Failed to save config for guild {guild_id}: {e}")

    def _load_all_guild_configs(self):
        """Load all guild configurations"""
        self.guild_configs.clear()
        self.stats.clear()
        
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                config = self._load_guild_config(guild_id)
                self.guild_configs[guild_id] = config
                
                # Initialize stats for this guild's feeds
                self.stats[guild_id] = {
                    feed["name"]: {"last_run": None, "last_success": None, "failures": 0}
                    for feed in config.get("feeds", [])
                }
        
        total_feeds = sum(len(config.get("feeds", [])) for config in self.guild_configs.values())
        self.log.info(f"Loaded configs for {len(self.guild_configs)} guilds with {total_feeds} total feeds")

    def _load_webhook_cache(self):
        """Load webhook cache from JSON file"""
        if not self.webhook_cache_file.exists():
            return
        
        try:
            import json
            with self.webhook_cache_file.open(encoding="utf-8") as f:
                cache_data = json.load(f)
            
            # Reconstruct webhook objects from saved data
            for channel_id_str, webhook_data in cache_data.items():
                try:
                    channel_id = int(channel_id_str)
                    webhook = discord.Webhook.partial(
                        id=webhook_data["id"],
                        token=webhook_data["token"],
                        session=self.bot.http._HTTPClient__session
                    )
                    self.webhook_cache[channel_id] = webhook
                except (ValueError, KeyError) as e:
                    self.log.warning(f"Error loading webhook for channel {channel_id_str}: {e}")
            
            self.log.info(f"Loaded webhook cache: {len(self.webhook_cache)} webhooks")
        except Exception as e:
            self.log.warning(f"Error loading webhook cache: {e}")
            self.webhook_cache_file.unlink(missing_ok=True)

    def _save_webhook_cache(self):
        """Save webhook cache to JSON file"""
        try:
            import json
            cache_data = {}
            for channel_id, webhook in self.webhook_cache.items():
                if webhook.token:  # Only save complete webhooks
                    cache_data[str(channel_id)] = {
                        "id": webhook.id,
                        "token": webhook.token,
                        "name": webhook.name
                    }
            
            with self.webhook_cache_file.open("w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            self.log.warning(f"Error saving webhook cache: {e}")

    def _load_monitor_message_id(self):
        """Load the global monitor message ID"""
        if not self.monitor_message_file.exists():
            return
        
        try:
            import json
            with self.monitor_message_file.open(encoding="utf-8") as f:
                data = json.load(f)
                self.monitor_message_id = data.get("message_id")
        except Exception as e:
            self.log.warning(f"Error loading monitor message ID: {e}")

    def _save_monitor_message_id(self, message_id: int):
        """Save the global monitor message ID"""
        try:
            import json
            with self.monitor_message_file.open("w", encoding="utf-8") as f:
                json.dump({"message_id": message_id}, f)
            self.monitor_message_id = message_id
        except Exception as e:
            self.log.error(f"Error saving monitor message ID: {e}")

    async def _get_or_create_webhook(self, channel: discord.TextChannel, 
                                   feed_name: str) -> Optional[discord.Webhook]:
        """Get webhook for channel from cache or create new one"""
        if channel.id in self.webhook_cache:
            webhook = self.webhook_cache[channel.id]
            try:
                # Test if webhook still exists
                await webhook.fetch()
                return webhook
            except discord.NotFound:
                # Webhook was deleted, remove from cache
                del self.webhook_cache[channel.id]
            except Exception:
                # Other error, webhook might still exist
                pass

        # Create new webhook
        try:
            webhook = await channel.create_webhook(
                name=f"RSS Bot - {feed_name}",
                reason="Auto-created webhook for RSS feed"
            )
            self.webhook_cache[channel.id] = webhook
            self._save_webhook_cache()
            self.log.info(f"✅ Created new webhook for channel #{channel.name}")
            return webhook
        except discord.Forbidden:
            self.log.error(f"❌ No permission to create webhook in #{channel.name}")
            return None
        except Exception:
            self.log.exception(f"❌ Error creating webhook in #{channel.name}")
            return None

    @commands.Cog.listener()
    async def on_ready(self):
        # Load all guild configurations
        self._load_all_guild_configs()
        
        # Sync slash commands
        try:
            await self.bot.tree.sync()
            self.log.info("✅ Slash commands synced globally")
        except Exception:
            self.log.exception("Failed to sync slash commands")

        # Start polling and cleanup tasks
        if not self.poll_loop.is_running():
            self.log.info("▶ Starting poll_loop...")
            self.poll_loop.start()
        
        if not self.cleanup_loop.is_running():
            self.log.info("▶ Starting cleanup_loop...")
            self.cleanup_loop.start()

        if not self.monitor_update_loop.is_running():
            self.log.info("▶ Starting monitor_update_loop...")
            self.monitor_update_loop.start()

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES, reconnect=True)
    async def poll_loop(self):
        """Main polling loop for all guild feeds"""
        now = datetime.utcnow()
        total_feeds = sum(len(config.get("feeds", [])) for config in self.guild_configs.values())
        self.log.info(f"🔄 Running poll_loop for {total_feeds} feeds across {len(self.guild_configs)} guilds")
        
        for guild_id, config in self.guild_configs.items():
            guild_stats = self.stats.get(guild_id, {})
            monitor_channel_id = config.get("monitor_channel_id")
            
            for feed_cfg in config.get("feeds", []):
                name = feed_cfg.get("name")
                if name not in guild_stats:
                    guild_stats[name] = {"last_run": None, "last_success": None, "failures": 0}
                
                st = guild_stats[name]
                st["last_run"] = now

                # Fetch feed in thread with timeout
                try:
                    embeds = await asyncio.wait_for(
                        asyncio.to_thread(rss.poll, feed_cfg, guild_id),
                        timeout=RATE_LIMIT_SECONDS
                    )
                except Exception:
                    st["failures"] += 1
                    await self._maybe_alert(guild_id, name, st["failures"], monitor_channel_id)
                    self.log.exception("❌ Error polling feed %s in guild %s", name, guild_id)
                    continue

                # Success
                st["failures"] = 0
                st["last_success"] = datetime.utcnow()
                
                if not embeds:
                    continue

                channel = self.bot.get_channel(feed_cfg["channel_id"])
                if not channel:
                    self.log.warning("⚠️ Channel %s not found for %s in guild %s",
                                feed_cfg["channel_id"], name, guild_id)
                    continue

                # Get or create webhook
                webhook = await self._get_or_create_webhook(channel, name)
                if not webhook:
                    self.log.warning("⚠️ No webhook available for %s, using bot posting", name)
                    await self._post_via_bot(channel, embeds, feed_cfg, name)
                    continue
                
                # Post via webhook
                msgs = []
                for e in embeds:
                    try:
                        embed = discord.Embed.from_dict(e)
                        
                        msg = await webhook.send(
                            embed=embed,
                            username=feed_cfg.get("username", name),
                            avatar_url=feed_cfg.get("avatar_url"),
                            wait=True
                        )
                        self.log.info("✅ Posted embed via webhook to channel <#%s>", channel.id)
                        msgs.append(msg)
                    except Exception:
                        self.log.exception("❌ Failed to post embed for %s", name)

                # Crosspost batch if enabled
                if feed_cfg.get("crosspost") and msgs:
                    try:
                        #await msgs[0].publish()
                        self.log.info("🚀 Published batch of %d messages", len(msgs))
                    except discord.HTTPException as exc:
                        self.log.warning("Publish failed: %s", exc)

    @tasks.loop(hours=168)  # Weekly cleanup
    async def cleanup_loop(self):
        """Weekly cleanup of old posted entries"""
        self.log.info("🧹 Running weekly cleanup of posted entries")
        # The actual cleanup is handled in the rss module per guild
        for guild_id in self.guild_configs.keys():
            try:
                rss.cleanup_old_entries(guild_id)
            except Exception:
                self.log.exception(f"Error during cleanup for guild {guild_id}")

    @tasks.loop(minutes=30)  # Update monitor every 30 minutes
    async def monitor_update_loop(self):
        """Update the global feed monitor"""
        await self._update_global_monitor()

    async def _post_via_bot(self, channel, embeds, feed_cfg, name):
        """Fallback method for normal bot posting when webhook unavailable"""
        msgs = []
        for e in embeds:
            try:
                embed = discord.Embed.from_dict(e)
                # Add author icon and name
                author_name = feed_cfg.get("username")
                author_icon = feed_cfg.get("avatar_url")
                if author_name or author_icon:
                    embed.set_author(
                        name=author_name or discord.Embed.Empty,
                        icon_url=author_icon or discord.Embed.Empty
                    )
                
                # Add thread creation button
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="Start Thread",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"thread_{name}_{e.get('guid', 'unknown')}"
                ))

                msg = await channel.send(embed=embed, view=view)
                self.log.info("✅ Posted embed via bot to channel <#%s>", channel.id)
                msgs.append(msg)
            except Exception:
                self.log.exception("❌ Failed to post embed for %s", name)

        # Crosspost batch if enabled
        if feed_cfg.get("crosspost") and msgs:
            try:
                await msgs[0].publish()
                self.log.info("🚀 Published batch of %d messages", len(msgs))
            except discord.HTTPException as exc:
                self.log.warning("Publish failed: %s", exc)
                    
    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self.log.info("✔ poll_loop is ready")

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        self.log.info("✔ cleanup_loop is ready")

    @monitor_update_loop.before_loop
    async def before_monitor_update(self):
        await self.bot.wait_until_ready()
        self.log.info("✔ monitor_update_loop is ready")

    async def _maybe_alert(self, guild_id: int, feed_name: str, failures: int, monitor_channel_id: Optional[int]):
        """Send alert if failure threshold reached"""
        if failures == FAILURE_THRESHOLD and monitor_channel_id:
            channel = self.bot.get_channel(monitor_channel_id)
            if channel:
                await channel.send(
                    f"⚠️ Feed **{feed_name}** has {failures} consecutive failures."
                )

    async def _update_global_monitor(self):
        """Update the global monitor with all feed information"""
        if not GLOBAL_MONITOR_CHANNEL_ID:
            return
            
        monitor_channel = self.bot.get_channel(GLOBAL_MONITOR_CHANNEL_ID)
        if not monitor_channel:
            self.log.warning("Global monitor channel not found")
            return

        # Build embed with all feed information
        embed = discord.Embed(
            title="🌐 Global RSS Feed Monitor",
            color=0x00FF00,
            timestamp=datetime.utcnow()
        )
        
        total_feeds = 0
        for guild_id, config in self.guild_configs.items():
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else f"Unknown Guild ({guild_id})"
            
            feeds = config.get("feeds", [])
            if not feeds:
                continue
                
            feed_list = []
            for feed in feeds:
                feed_list.append(f"• {feed['name']}: `{feed['feed_url']}`")
            
            embed.add_field(
                name=f"{guild_name} (ID: {guild_id})",
                value="\n".join(feed_list) if feed_list else "No feeds",
                inline=False
            )
            total_feeds += len(feeds)
        
        embed.description = f"Monitoring {total_feeds} feeds across {len(self.guild_configs)} servers"
        
        try:
            if self.monitor_message_id:
                try:
                    message = await monitor_channel.fetch_message(self.monitor_message_id)
                    await message.edit(embed=embed)
                    return
                except discord.NotFound:
                    self.monitor_message_id = None
            
            # Create new monitor message
            message = await monitor_channel.send(embed=embed)
            self._save_monitor_message_id(message.id)
            
        except Exception as e:
            self.log.error(f"Failed to update global monitor: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle thread creation button interactions"""
        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("thread_"):
            return
        
        await interaction.response.defer(ephemeral=True)
        parts = custom_id.split("_", 2)
        if len(parts) != 3:
            return
            
        _, feed_name, guid = parts
        thread = await interaction.channel.create_thread(
            name=f"{feed_name} Discussion",
            message=interaction.message
        )
        await interaction.followup.send(
            f"🧵 Thread '{thread.name}' created!", ephemeral=True
        )

    # ---- Slash Commands ----
    
    @app_commands.command(
        name="ping",
        description="Test if the bot is responsive"
    )
    async def slash_ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Pong! {self.bot.latency*1000:.0f} ms", ephemeral=True
        )

    @app_commands.command(
        name="owner_poll_now",
        description="Run the RSS poll immediately (authorized users only)"
    )
    async def slash_poll_now(self, interaction: discord.Interaction):
        if interaction.user.id not in AUTHORIZED_USERS:
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.", ephemeral=True
            )
            return
            
        await interaction.response.defer(ephemeral=True)
        await self.poll_loop()
        await interaction.followup.send("✅ Poll executed.", ephemeral=True)

    @app_commands.command(
        name="feeds_reload",
        description="Reload feed configuration and restart polling"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_reload(self, interaction: discord.Interaction):
        self._load_all_guild_configs()
        self.poll_loop.restart()
        await interaction.response.send_message(
            "✅ Feeds reloaded.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_status",
        description="Show health status of RSS feeds for this server"
    )
    async def slash_status(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        guild_stats = self.stats.get(guild_id, {})
        
        if not guild_stats:
            await interaction.response.send_message(
                "No feeds configured for this server.", ephemeral=True
            )
            return
            
        embed = discord.Embed(
            title="📊 RSS Feed Health Status",
            color=0x00FF00,
            timestamp=datetime.utcnow()
        )
        
        for name, st in guild_stats.items():
            lr = st["last_run"].strftime("%Y-%m-%d %H:%M:%S") if st["last_run"] else "-"
            ls = st["last_success"].strftime("%Y-%m-%d %H:%M:%S") if st["last_success"] else "-"
            fv = st["failures"]
            embed.add_field(
                name=name,
                value=(f"Last Run: `{lr}`\n"
                       f"Last Success: `{ls}`\n"
                       f"Consecutive Failures: `{fv}`"),
                inline=False
            )
        await interaction.response.send_message(
            embed=embed, ephemeral=True
        )

    @app_commands.command(
        name="feeds_add",
        description="Add a new RSS feed to this server"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_add(
        self,
        interaction: discord.Interaction,
        name: str,
        feed_url: str,
        channel: discord.TextChannel,
        max_items: int = 3,
        crosspost: bool = False,
        color: str = None,
        user_name: str = None,
        avatar_url: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        # Parse color hex
        default_hex = 0x3498DB
        if color:
            c = color.lstrip("#")
            try:
                default_hex = int(c, 16)
            except ValueError:
                return await interaction.followup.send(
                    f"❌ `{color}` is not a valid hex color.", ephemeral=True
                )
        
        new_feed = {
            "name": name,
            "feed_url": feed_url,
            "channel_id": channel.id,
            "max_items": max_items,
            "crosspost": crosspost,
            "username": user_name,
            "avatar_url": avatar_url,
            "embed_template": {
                "title": "{title}",
                "description": "{description}",
                "url": "{link}",
                "color": default_hex,
                "timestamp": "{published_custom}",
                "footer": {"text": name},
                "image": {"url": "{thumbnail}"}
            }
        }
        
        # Load and update guild config
        config = self._load_guild_config(guild_id)
        config.setdefault("feeds", []).append(new_feed)
        self._save_guild_config(guild_id, config)
        
        # Update runtime config and stats
        self.guild_configs[guild_id] = config
        if guild_id not in self.stats:
            self.stats[guild_id] = {}
        self.stats[guild_id][name] = {"last_run": None, "last_success": None, "failures": 0}
        
        self.poll_loop.restart()
        await interaction.followup.send(
            f"✅ Feed **{name}** added to this server.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_remove",
        description="Remove an RSS feed from this server by name"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_remove(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        config = self._load_guild_config(guild_id)
        old_feeds = config.get("feeds", [])
        new_feeds = [f for f in old_feeds if f.get("name") != name]
        
        if len(new_feeds) == len(old_feeds):
            return await interaction.followup.send(
                f"❌ No feed named **{name}** found on this server.", ephemeral=True
            )
        
        config["feeds"] = new_feeds
        self._save_guild_config(guild_id, config)
        
        # Update runtime config and stats
        self.guild_configs[guild_id] = config
        if guild_id in self.stats:
            self.stats[guild_id].pop(name, None)
        
        self.poll_loop.restart()
        await interaction.followup.send(
            f"✅ Feed **{name}** removed from this server.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_list",
        description="List all RSS feeds configured for this server"
    )
    async def slash_feeds_list(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = self.guild_configs.get(guild_id, {})
        feeds = config.get("feeds", [])
        
        if not feeds:
            await interaction.response.send_message(
                "No feeds configured for this server.", ephemeral=True
            )
            return
            
        lines = []
        for f in feeds:
            col = f["embed_template"].get("color", 0)
            lines.append(
                f"• **{f['name']}** – <{f['feed_url']}> in <#{f['channel_id']}>"
                f" – Color: `#{col:06X}`"
            )
        embed = discord.Embed(
            title="📑 Current RSS Feeds",
            description="\n".join(lines),
            color=0x00ADEF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="feeds_webhook_status",
        description="Show webhook status for all channels"
    )
    async def slash_webhook_status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔗 Webhook Status",
            color=0x00ADEF,
            timestamp=datetime.utcnow()
        )
        
        # Show cached webhooks
        for channel_id, webhook in self.webhook_cache.items():
            channel = self.bot.get_channel(channel_id)
            channel_name = f"#{channel.name}" if channel else f"ID:{channel_id}"
            embed.add_field(
                name=channel_name,
                value=f"Webhook: `{webhook.name}`\nID: `{webhook.id}`",
                inline=True
            )

        if not self.webhook_cache:
            embed.description = "No webhook cache available."
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

        
async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
