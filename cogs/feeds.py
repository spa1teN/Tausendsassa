# cogs/feeds.py

import asyncio
from datetime import datetime
from typing import Dict, Optional, List
import json

import discord
import aiohttp
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
from core.timezone_util import get_current_time, get_current_timestamp


class FeedCog(commands.Cog):
    """Cog for polling RSS feeds, posting embeds, buttons, health monitoring
    and dynamic feed management with database-backed configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("feeds")

        # In-memory caches (backed by database)
        self._feeds_cache: Dict[int, List[dict]] = {}  # guild_id -> feeds list
        self._webhook_cache: Dict[int, discord.Webhook] = {}  # channel_id -> webhook

        # Health stats per feed
        self.stats: Dict[int, Dict[str, dict]] = {}  # guild_id -> feed_name -> stats

        # HTTP session for feed fetching
        self._session: Optional[aiohttp.ClientSession] = None

        # Start retry handler
        retry_handler.start_cleanup_task()

    async def cog_load(self):
        """Load configuration from database and start tasks"""
        await self._load_all_configs()
        await self._load_webhook_cache()

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        if self.poll_loop.is_running():
            self.poll_loop.cancel()
        if self.cleanup_loop.is_running():
            self.cleanup_loop.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ==========================================
    # Database Configuration Methods
    # ==========================================

    async def _load_all_configs(self):
        """Load all feed configurations from database"""
        self._feeds_cache.clear()
        self.stats.clear()

        if not self.bot.db:
            self.log.warning("Database not available, skipping config load")
            return

        # Get all guilds the bot is in
        for guild in self.bot.guilds:
            feeds = await self.bot.db.feeds.get_guild_feeds(guild.id)
            if feeds:
                self._feeds_cache[guild.id] = [self._feed_to_dict(f) for f in feeds]
                # Initialize stats
                self.stats[guild.id] = {
                    f.name: {"last_run": None, "last_success": None, "failures": 0}
                    for f in feeds
                }

        total_feeds = sum(len(feeds) for feeds in self._feeds_cache.values())
        self.log.info(f"Loaded {total_feeds} feeds for {len(self._feeds_cache)} guilds from database")

    def _feed_to_dict(self, feed) -> dict:
        """Convert Feed model to dict for compatibility"""
        embed_template = feed.embed_template
        if embed_template and isinstance(embed_template, str):
            try:
                embed_template = json.loads(embed_template)
            except json.JSONDecodeError:
                embed_template = {}

        return {
            "id": feed.id,
            "name": feed.name,
            "feed_url": feed.feed_url,
            "channel_id": feed.channel_id,
            "webhook_url": feed.webhook_url,
            "username": feed.username,
            "avatar_url": feed.avatar_url,
            "color": feed.color,
            "max_items": feed.max_items,
            "crosspost": feed.crosspost,
            "embed_template": embed_template or {},
            "enabled": feed.enabled,
        }

    async def get_guild_feeds(self, guild_id: int) -> List[dict]:
        """Get feeds for a guild from cache or database"""
        if guild_id in self._feeds_cache:
            return self._feeds_cache[guild_id]

        if self.bot.db:
            feeds = await self.bot.db.feeds.get_guild_feeds(guild_id)
            if feeds:
                self._feeds_cache[guild_id] = [self._feed_to_dict(f) for f in feeds]
                return self._feeds_cache[guild_id]

        return []

    async def add_feed(self, guild_id: int, feed_data: dict) -> bool:
        """Add a new feed to the database"""
        if not self.bot.db:
            return False

        try:
            feed = await self.bot.db.feeds.create_feed(guild_id, feed_data)
            # Update cache
            if guild_id not in self._feeds_cache:
                self._feeds_cache[guild_id] = []
            self._feeds_cache[guild_id].append(self._feed_to_dict(feed))

            # Initialize stats
            if guild_id not in self.stats:
                self.stats[guild_id] = {}
            self.stats[guild_id][feed.name] = {"last_run": None, "last_success": None, "failures": 0}

            self.log.info(f"Added feed '{feed.name}' for guild {guild_id}")
            return True
        except Exception as e:
            self.log.error(f"Error adding feed: {e}")
            return False

    async def remove_feed(self, guild_id: int, feed_name: str) -> bool:
        """Remove a feed from the database"""
        if not self.bot.db:
            return False

        try:
            result = await self.bot.db.feeds.delete_feed_by_name(guild_id, feed_name)
            if result:
                # Update cache
                if guild_id in self._feeds_cache:
                    self._feeds_cache[guild_id] = [
                        f for f in self._feeds_cache[guild_id] if f["name"] != feed_name
                    ]
                # Remove stats
                if guild_id in self.stats:
                    self.stats[guild_id].pop(feed_name, None)

                self.log.info(f"Removed feed '{feed_name}' from guild {guild_id}")
            return result
        except Exception as e:
            self.log.error(f"Error removing feed: {e}")
            return False

    async def update_feed(self, guild_id: int, feed_name: str, updates: dict) -> bool:
        """Update a feed in the database"""
        if not self.bot.db:
            return False

        try:
            feed = await self.bot.db.feeds.get_feed_by_name(guild_id, feed_name)
            if not feed:
                return False

            updated = await self.bot.db.feeds.update_feed(feed.id, **updates)
            if updated:
                # Refresh cache
                feeds = await self.bot.db.feeds.get_guild_feeds(guild_id)
                self._feeds_cache[guild_id] = [self._feed_to_dict(f) for f in feeds]
                self.log.info(f"Updated feed '{feed_name}' for guild {guild_id}")
                return True
            return False
        except Exception as e:
            self.log.error(f"Error updating feed: {e}")
            return False

    # ==========================================
    # Webhook Cache
    # ==========================================

    async def _load_webhook_cache(self):
        """Load webhook cache from database"""
        if not self.bot.db:
            return

        try:
            webhooks = await self.bot.db.cache.get_all_webhooks()
            for channel_id_str, data in webhooks.items():
                try:
                    channel_id = int(channel_id_str)
                    webhook = discord.Webhook.partial(
                        id=data["id"],
                        token=data["token"],
                        session=await self._get_session()
                    )
                    self._webhook_cache[channel_id] = webhook
                except (ValueError, KeyError) as e:
                    self.log.warning(f"Error loading webhook for channel {channel_id_str}: {e}")

            self.log.info(f"Loaded {len(self._webhook_cache)} webhooks from database")
        except Exception as e:
            self.log.warning(f"Error loading webhook cache: {e}")

    async def _save_webhook(self, channel_id: int, webhook: discord.Webhook):
        """Save webhook to database cache"""
        if not self.bot.db or not webhook.token:
            return

        try:
            await self.bot.db.cache.set_webhook(
                channel_id,
                webhook.id,
                webhook.token,
                webhook.name
            )
        except Exception as e:
            self.log.warning(f"Error saving webhook: {e}")

    async def _delete_webhook_cache(self, channel_id: int):
        """Delete webhook from database cache"""
        if self.bot.db:
            await self.bot.db.cache.delete_webhook(channel_id)

    async def _get_or_create_webhook(self, channel: discord.TextChannel,
                                      feed_name: str) -> Optional[discord.Webhook]:
        """Get webhook for channel from cache or create new one"""
        if channel.id in self._webhook_cache:
            webhook = self._webhook_cache[channel.id]
            try:
                await webhook.fetch()
                return webhook
            except discord.NotFound:
                del self._webhook_cache[channel.id]
                await self._delete_webhook_cache(channel.id)
            except Exception:
                pass

        # Create new webhook
        try:
            webhook = await channel.create_webhook(
                name=f"RSS Bot - {feed_name}",
                reason="Auto-created webhook for RSS feed"
            )
            self._webhook_cache[channel.id] = webhook
            await self._save_webhook(channel.id, webhook)
            self.log.info(f"Created new webhook for channel #{channel.name}")
            return webhook
        except discord.Forbidden:
            self.log.error(f"No permission to create webhook in #{channel.name}")
            return None
        except Exception:
            self.log.exception(f"Error creating webhook in #{channel.name}")
            return None

    # ==========================================
    # Event Handlers
    # ==========================================

    @commands.Cog.listener()
    async def on_ready(self):
        # Reload configs now that bot.guilds is populated
        await self._load_all_configs()
        
        try:
            await self.bot.tree.sync()
            self.log.info("Slash commands synced globally")
        except Exception:
            self.log.exception("Failed to sync slash commands")

        if not self.poll_loop.is_running():
            self.log.info("Starting poll_loop...")
            self.poll_loop.start()

        if not self.cleanup_loop.is_running():
            self.log.info("Starting cleanup_loop...")
            self.cleanup_loop.start()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Handle bot being removed from a guild"""
        guild_id = guild.id
        self.log.info(f"Bot removed from guild {guild.name} (ID: {guild_id})")

        # Clean up database
        if self.bot.db:
            feeds = await self.bot.db.feeds.get_guild_feeds(guild_id, enabled_only=False)
            for feed in feeds:
                await self.bot.db.feeds.delete_feed(feed.id)

        # Clean up caches
        self._feeds_cache.pop(guild_id, None)
        self.stats.pop(guild_id, None)

        # Remove webhooks for this guild's channels
        for channel in guild.channels:
            if hasattr(channel, 'id'):
                self._webhook_cache.pop(channel.id, None)
                if self.bot.db:
                    await self._delete_webhook_cache(channel.id)

        self.log.info(f"Cleaned up all data for removed guild {guild_id}")

    # ==========================================
    # Polling Logic
    # ==========================================

    async def _poll_single_feed(self, guild_id: int, feed_cfg: dict, guild_stats: dict) -> List[dict]:
        """Poll a single feed and return list of embeds to post"""
        name = feed_cfg.get("name")
        operation_id = f"feed_poll_{guild_id}_{name}"

        if name not in guild_stats:
            guild_stats[name] = {"last_run": None, "last_success": None, "failures": 0}

        st = guild_stats[name]
        st["last_run"] = datetime.utcnow()

        async def poll_operation():
            session = await self._get_session()
            return await rss.poll(feed_cfg, guild_id, self.bot.db, session)

        try:
            embeds = await retry_handler.execute_with_retry(
                operation_id,
                poll_operation
            )

            st["failures"] = 0
            st["last_success"] = datetime.utcnow()
            retry_handler.record_success(operation_id)
            return embeds or []

        except Exception as e:
            st["failures"] += 1
            retry_handler.record_failure(operation_id, e)

            consecutive_failures = retry_handler.get_failure_count(operation_id)

            self.log.error(
                f"Error polling feed {name} in guild {guild_id} (attempt {consecutive_failures}): {e}",
                exc_info=True if consecutive_failures >= FAILURE_THRESHOLD else False
            )
            return []

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES, reconnect=True)
    async def poll_loop(self):
        """Main polling loop with async processing"""
        if not self.bot.db:
            return

        all_tasks = []
        feed_info = []

        for guild_id, feeds in self._feeds_cache.items():
            guild_stats = self.stats.get(guild_id, {})

            for feed_cfg in feeds:
                if not feed_cfg.get("enabled", True):
                    continue

                task = self._poll_single_feed(guild_id, feed_cfg, guild_stats)
                all_tasks.append(task)

                channel = self.bot.get_channel(feed_cfg["channel_id"])
                feed_info.append((guild_id, feed_cfg, channel))

        if not all_tasks:
            return

        try:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
        except Exception as e:
            self.log.error(f"Error in parallel feed polling: {e}")
            return

        posts_made = 0
        updates_made = 0

        for embeds, (guild_id, feed_cfg, channel) in zip(results, feed_info):
            if isinstance(embeds, Exception):
                self.log.error(f"Feed polling error: {embeds}")
                continue

            if not embeds or not channel:
                continue

            name = feed_cfg.get("name")

            for e in embeds:
                try:
                    embed = discord.Embed.from_dict(e)
                    is_update = e.get("is_update", False)
                    message_info = e.get("message_info")
                    guid = e.get("guid")

                    if is_update and message_info:
                        message_id, old_channel_id = message_info
                        if old_channel_id == channel.id:
                            try:
                                webhook = await self._get_or_create_webhook(channel, name)
                                if webhook:
                                    await webhook.edit_message(message_id, embed=embed)
                                    self.log.info("Updated existing embed for %s", name)
                                    await rss.mark_entry_posted(guild_id, guid, message_id, channel.id, self.bot.db, feed_id=feed_cfg.get("id"))
                                    updates_made += 1
                                    continue
                            except Exception as ex:
                                self.log.warning("Failed to update message for %s: %s", name, ex)

                    # Post new message
                    webhook = await self._get_or_create_webhook(channel, name)
                    if webhook:
                        msg = await webhook.send(
                            embed=embed,
                            username=name,
                            avatar_url=feed_cfg.get("avatar_url"),
                            wait=True
                        )
                        self.log.info("Posted embed for %s", name)
                    else:
                        msg = await self._post_via_bot_single(channel, embed, feed_cfg, name)

                    if msg:
                        await rss.mark_entry_posted(guild_id, guid, msg.id, channel.id, self.bot.db, feed_id=feed_cfg.get("id"))
                        posts_made += 1

                        if feed_cfg.get("crosspost"):
                            try:
                                await msg.publish()
                            except discord.HTTPException as exc:
                                self.log.warning("Publish failed for %s: %s", name, exc)

                except Exception as ex:
                    self.log.exception("Failed to process embed for %s: %s", name, ex)

        if posts_made > 0 or updates_made > 0:
            self.log.info(f"Completed: {posts_made} new posts, {updates_made} updates")

    async def _post_via_bot_single(self, channel, embed, feed_cfg, name) -> Optional[discord.Message]:
        """Post single embed via bot with thread button"""
        try:
            author_name = name
            author_icon = feed_cfg.get("avatar_url")
            if author_name or author_icon:
                embed.set_author(
                    name=author_name or discord.Embed.Empty,
                    icon_url=author_icon or discord.Embed.Empty
                )

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Start Thread",
                style=discord.ButtonStyle.primary,
                custom_id=f"thread_{name}_{hash(embed.url or embed.title or 'unknown')}"
            ))

            msg = await channel.send(embed=embed, view=view)
            return msg
        except Exception:
            self.log.exception(f"Failed to post embed for {name}")
            return None

    # ==========================================
    # Background Tasks
    # ==========================================

    @tasks.loop(hours=168)  # Weekly cleanup
    async def cleanup_loop(self):
        """Weekly cleanup of old posted entries"""
        if not self.bot.db:
            return

        self.log.info("Running weekly cleanup of posted entries")
        for guild_id in self._feeds_cache.keys():
            try:
                await rss.cleanup_old_entries(guild_id, self.bot.db)
            except Exception:
                self.log.exception(f"Error during cleanup for guild {guild_id}")

    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self.log.info("poll_loop is ready")

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        self.log.info("cleanup_loop is ready")

    # ==========================================
    # Interaction Handlers
    # ==========================================

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
            f"Thread '{thread.name}' created!", ephemeral=True
        )

    # ==========================================
    # Slash Commands
    # ==========================================

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
                "You are not authorized to use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self.poll_loop()
        await interaction.followup.send("Poll executed.", ephemeral=True)

    @app_commands.command(
        name="feeds_add",
        description="Add a new RSS feed to this server"
    )
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_add(self, interaction: discord.Interaction):
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
        feeds = await self.get_guild_feeds(guild_id)

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
        feeds = await self.get_guild_feeds(guild_id)

        if not feeds:
            await interaction.response.send_message(
                "No feeds configured for this server.", ephemeral=True
            )
            return

        lines = []
        for f in feeds:
            feed_type = "Bluesky" if is_bluesky_feed_url(f["feed_url"]) else "RSS"
            status = "" if f.get("enabled", True) else " (disabled)"
            lines.append(
                f"* **{f['name']}** {feed_type}{status} - [Feed URL]({f['feed_url']}) in <#{f['channel_id']}>"
            )

        embed = discord.Embed(
            title="Current RSS Feeds",
            description="\n".join(lines),
            color=0x00ADEF
        )

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
        feeds = await self.get_guild_feeds(guild_id)

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
