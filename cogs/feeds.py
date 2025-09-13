# cogs/feeds.py

import asyncio
import shutil
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import feeds_rss as rss
from core.feeds_config import (
    POLL_INTERVAL_MINUTES, RATE_LIMIT_SECONDS, FAILURE_THRESHOLD, 
    AUTHORIZED_USERS, COLOR_CHOICES,
    is_bluesky_feed_url, create_bluesky_embed_template, create_standard_embed_template
)
from core.feeds_views import FeedRemoveView, FeedConfigureView
from core.retry_handler import retry_handler
from core.config import config
from core.validation import ConfigValidator

# Import timezone utilities
from core.timezone_util import get_current_time, get_current_timestamp

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
        
        
        # Start retry handler
        retry_handler.start_cleanup_task()

    # Config Management
    def _get_guild_config_path(self, guild_id: int) -> Path:
        """Get the config file path for a specific guild"""
        guild_dir = self.config_base / str(guild_id)
        guild_dir.mkdir(exist_ok=True)
        return guild_dir / "feed_config.yaml"

    def _load_guild_config(self, guild_id: int) -> dict:
        """Load configuration for a specific guild"""
        config_path = self._get_guild_config_path(guild_id)
        if not config_path.exists():
            return {"feeds": []}
        
        try:
            import yaml
            with config_path.open(encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                return config
        except Exception as e:
            self.log.error(f"Failed to load config for guild {guild_id}: {e}")
            return {"feeds": []}

    def _save_guild_config(self, guild_id: int, config: dict):
        """Save configuration for a specific guild"""
        config_path = self._get_guild_config_path(guild_id)
        try:
            import yaml
            with config_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            self.log.error(f"Failed to save config for guild {guild_id}: {e}")

    def _remove_guild_config(self, guild_id: int):
        """Remove all configuration for a guild"""
        guild_dir = self.config_base / str(guild_id)
        if guild_dir.exists():
            try:
                shutil.rmtree(guild_dir)
                self.log.info(f"Removed config directory for guild {guild_id}")
            except Exception as e:
                self.log.error(f"Failed to remove config for guild {guild_id}: {e}")

    def _load_all_guild_configs(self):
        """Load all guild configurations"""
        self.guild_configs.clear()
        self.stats.clear()
        
        for guild_dir in self.config_base.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_id = int(guild_dir.name)
                if not self.bot.get_guild(guild_id):
                    self._safe_log("info", "Guild %s no longer accessible, skipping config load", guild_id)
                    continue
                    
                config = self._load_guild_config(guild_id)
                self.guild_configs[guild_id] = config
                
                # Initialize stats for this guild's feeds
                self.stats[guild_id] = {
                    feed["name"]: {"last_run": None, "last_success": None, "failures": 0}
                    for feed in config.get("feeds", [])
                }
        
        total_feeds = sum(len(config.get("feeds", [])) for config in self.guild_configs.values())
        self.log.info(f"Loaded configs for {len(self.guild_configs)} guilds with {total_feeds} total feeds")

    # Webhook Management
    def _load_webhook_cache(self):
        """Load webhook cache from JSON file"""
        if not self.webhook_cache_file.exists():
            return
        
        try:
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



    async def _get_or_create_webhook(self, channel: discord.TextChannel, 
                                   feed_name: str) -> Optional[discord.Webhook]:
        """Get webhook for channel from cache or create new one"""
        if channel.id in self.webhook_cache:
            webhook = self.webhook_cache[channel.id]
            try:
                await webhook.fetch()
                return webhook
            except discord.NotFound:
                del self.webhook_cache[channel.id]
            except Exception:
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

    # Event Handlers
    @commands.Cog.listener()
    async def on_ready(self):
        self._load_all_guild_configs()
        
        try:
            await self.bot.tree.sync()
            self.log.info("✅ Slash commands synced globally")
        except Exception:
            self.log.exception("Failed to sync slash commands")

        if not self.poll_loop.is_running():
            self.log.info("▶ Starting poll_loop...")
            self.poll_loop.start()
        
        if not self.cleanup_loop.is_running():
            self.log.info("▶ Starting cleanup_loop...")
            self.cleanup_loop.start()


    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Handle bot being removed from a guild"""
        guild_id = guild.id
        self.log.info(f"Bot removed from guild {guild.name} (ID: {guild_id})")
        
        self._remove_guild_config(guild_id)
        self.guild_configs.pop(guild_id, None)
        self.stats.pop(guild_id, None)
        
        # Remove webhooks for this guild's channels
        guild_channels = [channel.id for channel in guild.channels if hasattr(channel, 'id')]
        for channel_id in guild_channels:
            self.webhook_cache.pop(channel_id, None)
        self._save_webhook_cache()
        
        self.log.info(f"Cleaned up all data for removed guild {guild_id}")

    # Polling Logic
    async def _poll_single_feed(self, guild_id: int, feed_cfg: dict, guild_stats: dict) -> List[dict]:
        """Poll a single feed and return list of embeds to post"""
        name = feed_cfg.get("name")
        feed_url = feed_cfg.get("feed_url", "")
        operation_id = f"feed_poll_{guild_id}_{name}"
        
        if name not in guild_stats:
            guild_stats[name] = {"last_run": None, "last_success": None, "failures": 0}
        
        st = guild_stats[name]
        st["last_run"] = datetime.utcnow()

        async def poll_operation():
            """Wrapped polling operation for retry handler"""
            return await asyncio.wait_for(
                asyncio.to_thread(rss.poll, feed_cfg, guild_id),
                timeout=config.http_timeout
            )

        try:
            # Use retry handler for robust polling
            embeds = await retry_handler.execute_with_retry(
                operation_id,
                poll_operation
            )
            
            # Success - update stats
            st["failures"] = 0
            st["last_success"] = datetime.utcnow()
            retry_handler.record_success(operation_id)
            return embeds or []
            
        except Exception as e:
            # Update local stats for monitoring
            st["failures"] += 1
            retry_handler.record_failure(operation_id, e)
            
            # Get failure count from retry handler for more accurate tracking
            consecutive_failures = retry_handler.get_failure_count(operation_id)
            
            
            self.log.error(
                f"❌ Error polling feed {name} in guild {guild_id} (attempt {consecutive_failures}): {e}",
                exc_info=True if consecutive_failures >= FAILURE_THRESHOLD else False
            )
            return []

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES, reconnect=True)
    async def poll_loop(self):
        """Main polling loop with async processing"""
        now = datetime.utcnow()
        total_feeds = sum(len(config.get("feeds", [])) for config in self.guild_configs.values())
        #self.log.info(f"🔄 Running async poll_loop for {total_feeds} feeds across {len(self.guild_configs)} guilds")
        
        # Collect all feed polling tasks
        all_tasks = []
        feed_info = []  # Store (guild_id, feed_cfg, channel) for each task
        
        for guild_id, config in self.guild_configs.items():
            guild_stats = self.stats.get(guild_id, {})
            
            for feed_cfg in config.get("feeds", []):
                task = self._poll_single_feed(guild_id, feed_cfg, guild_stats)
                all_tasks.append(task)
                
                channel = self.bot.get_channel(feed_cfg["channel_id"])
                feed_info.append((guild_id, feed_cfg, channel))
        
        if not all_tasks:
            return
            
        # Execute all feed polling tasks in parallel
        #self.log.info(f"📡 Fetching {len(all_tasks)} feeds in parallel...")
        start_time = datetime.utcnow()
        
        try:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
        except Exception as e:
            self.log.error(f"Error in parallel feed polling: {e}")
            return
        
        fetch_time = (datetime.utcnow() - start_time).total_seconds()
        #self.log.info(f"⚡ Completed feed fetching for {total_feeds} feeds across {len(self.guild_configs)} guilds in {fetch_time:.1f}s")
        
        # Process results and post embeds
        posts_made = 0
        updates_made = 0
        
        for i, (embeds, (guild_id, feed_cfg, channel)) in enumerate(zip(results, feed_info)):
            if isinstance(embeds, Exception):
                self.log.error(f"Feed polling error: {embeds}")
                continue
                
            if not embeds or not channel:
                continue
            
            name = feed_cfg.get("name")
            
            # Process each embed from this feed
            for e in embeds:
                try:
                    embed = discord.Embed.from_dict(e)
                    is_update = e.get("is_update", False)
                    message_info = e.get("message_info")
                    guid = e.get("guid")
                    
                    if is_update and message_info:
                        # Handle update
                        message_id, old_channel_id = message_info
                        if old_channel_id == channel.id:
                            try:
                                webhook = await self._get_or_create_webhook(channel, name)
                                if webhook:
                                    await webhook.edit_message(message_id, embed=embed)
                                    self.log.info("✅ Updated existing embed for %s", name)
                                    rss.mark_entry_posted(guild_id, guid, message_id, channel.id)
                                    updates_made += 1
                                    continue  # Important: Skip posting new message
                                else:
                                    self.log.info("No webhook available for update, posting new message")
                            except Exception as ex:
                                self.log.warning("Failed to update message for %s: %s", name, ex)
                    
                    # Post new message (either new entry or failed update)
                    webhook = await self._get_or_create_webhook(channel, name)
                    if webhook:
                        msg = await webhook.send(
                            embed=embed,
                            username=name,
                            avatar_url=feed_cfg.get("avatar_url"),
                            wait=True
                        )
                        self.log.info("✅ Posted embed for %s", name)
                    else:
                        # Fallback to bot posting
                        msg = await self._post_via_bot_single(channel, embed, feed_cfg, name)
                    
                    if msg:
                        rss.mark_entry_posted(guild_id, guid, msg.id, channel.id)
                        posts_made += 1
                        
                        # Handle crosspost
                        if feed_cfg.get("crosspost"):
                            try:
                                await msg.publish()
                                self.log.debug("Published message for %s", name)
                            except discord.HTTPException as exc:
                                self.log.warning("Publish failed for %s: %s", name, exc)
                                
                except Exception as ex:
                    self.log.exception("❌ Failed to process embed for %s: %s", name, ex)
        
        total_time = (datetime.utcnow() - start_time).total_seconds()
        if posts_made > 0 or updates_made > 0:
            self.log.info(f"📊 Completed in {total_time:.1f}s: {posts_made} new posts, {updates_made} updates")
        

    async def _post_via_bot_single(self, channel, embed, feed_cfg, name) -> Optional[discord.Message]:
        """Post single embed via bot with thread button"""
        try:
            # Add author icon and name
            author_name = name
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
                custom_id=f"thread_{name}_{hash(embed.url or embed.title or 'unknown')}"
            ))

            msg = await channel.send(embed=embed, view=view)
            self.log.debug("Posted embed via bot to channel #%s", channel.name)
            return msg
        except Exception:
            self.log.exception("❌ Failed to post embed for %s", name)
            return None

    # Background Tasks
    @tasks.loop(hours=168)  # Weekly cleanup
    async def cleanup_loop(self):
        """Weekly cleanup of old posted entries"""
        self.log.info("🧹 Running weekly cleanup of posted entries")
        for guild_id in self.guild_configs.keys():
            try:
                rss.cleanup_old_entries(guild_id)
            except Exception:
                self.log.exception(f"Error during cleanup for guild {guild_id}")


    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self.log.info("✓ poll_loop is ready")

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        self.log.info("✓ cleanup_loop is ready")


    # Helper Methods


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
        name="feeds_add",
        description="Add a new RSS feed to this server"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_add(self, interaction: discord.Interaction):
        # Create modal for adding new feed
        from core.feeds_views import FeedConfigModal
        modal = FeedConfigModal({}, self, interaction.guild.id, is_edit=False)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="feeds_remove",
        description="Remove an RSS feed from this server"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_remove(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = self._load_guild_config(guild_id)
        feeds = config.get("feeds", [])
        
        if not feeds:
            await interaction.response.send_message(
                "No feeds configured for this server.", ephemeral=True
            )
            return
        
        from core.feeds_views import FeedRemoveView
        view = FeedRemoveView(feeds, self, guild_id)
        await interaction.response.send_message(
            "Select a feed to remove:", view=view, ephemeral=True
        )

    @app_commands.command(
        name="feeds_list",
        description="List all RSS feeds configured for this server"
    )
    @app_commands.default_permissions(administrator=True)
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
            feed_type = "🦋 Bluesky" if is_bluesky_feed_url(f["feed_url"]) else "📰 RSS"
            lines.append(
                f"• **{f['name']}** {feed_type} — [Feed URL]({f['feed_url']}) in <#{f['channel_id']}>"
            )
        
        embed = discord.Embed(
            title="📋 Current RSS Feeds",
            description="\n".join(lines),
            color=0x00ADEF
        )
        
        # Add buttons for remove and configure
        from core.feeds_views import FeedListView
        view = FeedListView(self, guild_id)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(
        name="feeds_configure",
        description="Configure settings for an existing RSS feed"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_configure(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = self._load_guild_config(guild_id)
        feeds = config.get("feeds", [])
        
        if not feeds:
            await interaction.response.send_message(
                "No feeds configured for this server.", ephemeral=True
            )
            return
        
        # Add channel names to feeds for better display
        for feed in feeds:
            channel = self.bot.get_channel(feed.get("channel_id"))
            feed["channel_name"] = channel.name if channel else "unknown"
        
        from core.feeds_views import FeedConfigureView
        view = FeedConfigureView(feeds, self, guild_id)
        await interaction.response.send_message(
            "Select a feed to configure:", view=view, ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
