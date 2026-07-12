# cogs/feeds.py

import asyncio
import os
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
)
from core.retry_handler import retry_handler
from core.config import config
from core.validation import ConfigValidator
from core.timezone_util import get_current_time, get_current_timestamp
from core import feeds_cv2


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

        # Cookie-authenticated media downloader (Reddit galleries, RedGifs)
        cookie_path = os.environ.get("COOKIES_PATH", "/app/data/cookies.txt")
        try:
            from core.media_downloader import get_downloader
            self.media_downloader = get_downloader(cookie_path)
        except Exception:
            self.media_downloader = None
            self.log.warning("media_downloader not available")

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

        tpl = embed_template or {}
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
            "embed_template": tpl,
            "enabled": feed.enabled,
            "cv2": tpl.get("cv2", False) if isinstance(tpl, dict) else False,
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
        # Reload configs now that bot.guilds is populated. Command sync happens
        # once in bot.py setup_hook — no per-cog tree.sync() here (avoids the
        # redundant global sync and its rate-limit risk).
        await self._load_all_configs()

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

    async def _poll_url(self, url: str, consumers: list, session) -> list:
        """Fetch one feed URL once and fan the parse out to every guild using it.

        `consumers` is a list of (guild_id, feed_cfg, guild_stats). Returns a list
        of (guild_id, feed_cfg, embeds) for the posting stage. Health bookkeeping
        mirrors the old per-feed behaviour: a completed fetch (even with no new
        items) resets the failure count; only a raised fetch error increments it.
        """
        now = datetime.utcnow()
        fetch_failed = False
        parsed = None
        try:
            parsed = await rss.fetch_parsed(url, session, self.bot.db)
        except Exception as e:
            fetch_failed = True
            self.log.error(f"Error fetching feed {url}: {e}", exc_info=True)

        out = []
        for guild_id, feed_cfg, guild_stats in consumers:
            name = feed_cfg.get("name")
            st = guild_stats.setdefault(name, {"last_run": None, "last_success": None, "failures": 0})
            st["last_run"] = now
            feed_id = feed_cfg.get("id")
            embeds = []

            if not fetch_failed:
                st["failures"] = 0
                st["last_success"] = now
                if feed_id and self.bot.db:
                    try:
                        await self.bot.db.feeds.reset_failure_count(feed_id)
                    except Exception:
                        self.log.warning(f"Failed to persist feed health for {name}", exc_info=True)
                if parsed is not None:
                    try:
                        embeds = await rss.extract_new_embeds(parsed, feed_cfg, guild_id, self.bot.db)
                    except Exception:
                        self.log.exception(f"Failed to extract embeds for {name} in guild {guild_id}")
            else:
                st["failures"] = st.get("failures", 0) + 1
                if feed_id and self.bot.db:
                    try:
                        await self.bot.db.feeds.increment_failure_count(feed_id)
                    except Exception:
                        self.log.warning(f"Failed to persist feed health for {name}", exc_info=True)

            out.append((guild_id, feed_cfg, embeds))
        return out

    async def _post_embeds(self, guild_id: int, feed_cfg: dict, channel, embeds: list) -> tuple:
        """Post/update a guild's embeds for one feed. Returns (posts, updates)."""
        posts_made = 0
        updates_made = 0
        name = feed_cfg.get("name")

        for e in embeds:
            try:
                embed = discord.Embed.from_dict(e)
                is_update = e.get("is_update", False)
                message_info = e.get("message_info")
                guid = e.get("guid")
                entry_link = e.get("entry_link")

                if is_update and message_info:
                    message_id, old_channel_id = message_info
                    if old_channel_id == channel.id:
                        try:
                            webhook = await self._get_or_create_webhook(channel, name)
                            if webhook:
                                await webhook.edit_message(message_id, embed=embed)
                                self.log.info("Updated existing embed for %s", name)
                                await rss.mark_entry_posted(guild_id, guid, message_id, channel.id, self.bot.db, feed_id=feed_cfg.get("id"), entry_link=entry_link)
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
                    await rss.mark_entry_posted(guild_id, guid, msg.id, channel.id, self.bot.db, feed_id=feed_cfg.get("id"), entry_link=entry_link)
                    posts_made += 1

                    if feed_cfg.get("crosspost"):
                        try:
                            await msg.publish()
                        except discord.HTTPException as exc:
                            self.log.warning("Publish failed for %s: %s", name, exc)

            except Exception as ex:
                self.log.exception("Failed to process embed for %s: %s", name, ex)

        return posts_made, updates_made


    async def _post_cv2(self, guild_id: int, feed_cfg: dict, channel, embeds: list) -> tuple:
        """Post/update feed entries as CV2 LayoutView messages via webhook.

        Unlike _post_embeds, this builds a discord.ui.LayoutView per entry
        and sends it with the webhook's `view=` parameter (supported in
        discord.py 2.7.1+). Per-feed username/avatar are preserved.

        Returns (posts_made, updates_made).
        """
        posts_made = 0
        updates_made = 0
        name = feed_cfg.get("name")
        color = feed_cfg.get("color") or 0x3498DB
        if isinstance(color, str):
            color = int(color.lstrip("#"), 16)

        for e in embeds:
            try:
                is_update = e.get("is_update", False)
                message_info = e.get("message_info")
                guid = e.get("guid")
                entry_link = e.get("entry_link")
                # Video/GIF hosts: detect and handle. RedGifs gets CV2 attachment,
                # other hosts (Imgur/Giphy/Tenor) post raw URL for Discord auto-embed.
                video_url = feeds_cv2.find_raw_video_url(e, entry_link)
                is_redgifs = video_url and "redgifs.com" in video_url
                if video_url and not is_redgifs:
                    await self._post_raw_video_url(channel, feed_cfg, e, guild_id, guid, video_url, is_update, message_info)
                    posts_made += 1
                    continue
                # Collect images: cookie-based gallery + RedGifs, fallback to Pi proxy
                gallery_images = None
                attach_files = None
                if entry_link:
                    if self.media_downloader and "reddit.com" in entry_link and int(guild_id) == 694270970558546051:
                        try:
                            gallery_images, attach_files = await self.media_downloader.resolve_entry_media(e, entry_link)
                        except Exception:
                            pass
                    if not gallery_images:
                        if "reddit.com" in entry_link:
                            gallery_images = await feeds_cv2.fetch_gallery_images(entry_link)
                        elif "bsky.app" in entry_link:
                            try:
                                from core.feeds_thumbnails import get_image_urls
                                gallery_images = get_image_urls(entry_link)
                            except Exception:
                                pass

                # Compute media resolution count for dashboard markers
                media_count = (len(gallery_images) if gallery_images else 0) + (len(attach_files) if attach_files else 0)

                view = feeds_cv2.build_entry_view(e, name, int(color), gallery_images=gallery_images)

                if is_update and message_info:
                    message_id, old_channel_id = message_info
                    if old_channel_id == channel.id:
                        webhook = None
                        try:
                            webhook = await self._get_or_create_webhook(channel, name)
                            if webhook:
                                await webhook.edit_message(message_id, view=view)
                                self.log.info("Updated CV2 message for %s", name)
                                await rss.mark_entry_posted(
                                    guild_id, guid, message_id, channel.id,
                                    self.bot.db, feed_id=feed_cfg.get("id"),
                                    entry_link=entry_link, media_count=media_count)
                                updates_made += 1
                                continue
                        except Exception as ex:
                            self.log.warning("Failed to update CV2 message for %s: %s", name, ex)
                            # Legacy embed posts can't be edited into a CV2 message
                            # ("embeds field cannot be used with IS_COMPONENTS_V2").
                            # Delete the stale message so the fresh CV2 post below
                            # replaces it instead of leaving a duplicate; subsequent
                            # updates then edit the new CV2 message cleanly.
                            try:
                                if webhook:
                                    await webhook.delete_message(message_id)
                            except Exception:
                                pass

                # Post new CV2 message via webhook
                webhook = await self._get_or_create_webhook(channel, name)
                # Convert attachment refs to discord.File objects
                files = []
                if attach_files:
                    for ref, data in attach_files:
                        fname = ref.split("://", 1)[-1]
                        files.append(discord.File(data, filename=fname))
                if webhook:
                    kwargs = dict(view=view, username=name,
                                  avatar_url=feed_cfg.get("avatar_url"), wait=True)
                    if files:
                        kwargs["files"] = files
                    msg = await webhook.send(**kwargs)
                    self.log.info("Posted CV2 message for %s", name)
                else:
                    kwargs = dict(view=view)
                    if files:
                        kwargs["files"] = files
                    msg = await channel.send(**kwargs)
                if msg:
                    await rss.mark_entry_posted(
                        guild_id, guid, msg.id, channel.id,
                        self.bot.db, feed_id=feed_cfg.get("id"),
                        entry_link=entry_link, media_count=media_count)
                    posts_made += 1

                    if feed_cfg.get("crosspost"):
                        try:
                            await msg.publish()
                        except discord.HTTPException as exc:
                            self.log.warning("Publish failed for %s: %s", name, exc)

            except Exception as ex:
                self.log.exception("Failed to process CV2 entry for %s: %s", name, ex)

        return posts_made, updates_made

    async def _post_raw_video_url(self, channel, feed_cfg: dict, entry: dict, guild_id: int,
                                   guid: str, video_url: str, is_update: bool, message_info):
        """Post just the raw video/GIF URL — no embed, no CV2.

        Discord auto-embeds RedGifs, Imgur GIFs, v.redd.it, Giphy, Tenor, etc.
        as inline players when given a bare URL.
        """
        name = feed_cfg.get("name")
        # If updating an old CV2 message, delete it — can't convert CV2 to raw URL
        if is_update and message_info:
            old_msg_id, old_channel_id = message_info
            if old_channel_id == channel.id:
                try:
                    webhook = await self._get_or_create_webhook(channel, name)
                    if webhook:
                        await webhook.delete_message(old_msg_id)
                    else:
                        old_msg = await channel.fetch_message(old_msg_id)
                        await old_msg.delete()
                except Exception:
                    pass
        webhook = await self._get_or_create_webhook(channel, name)
        if webhook:
            msg = await webhook.send(content=video_url, username=name,
                                     avatar_url=feed_cfg.get("avatar_url"), wait=True)
        else:
            msg = await channel.send(content=video_url)
        if msg:
            await rss.mark_entry_posted(guild_id, guid, msg.id, channel.id,
                                        self.bot.db, feed_id=feed_cfg.get("id"),
                                        entry_link=entry.get("entry_link"),
                                        media_count=1)

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES, reconnect=True)
    async def poll_loop(self):
        """Main polling loop: fetch each unique URL once, fan out to all guilds."""
        if not self.bot.db:
            return

        # Group enabled feeds by URL so a URL shared across guilds is fetched a
        # single time and every guild gets its own posting decision (per-guild
        # posted_entries dedup). Previously each guild fetched independently and
        # the global feed cache let an update reach only whichever guild won the
        # race; now the fetch and the per-guild decision are decoupled.
        url_to_consumers = {}  # url -> [(guild_id, feed_cfg, guild_stats), ...]
        for guild_id, feeds in self._feeds_cache.items():
            guild_stats = self.stats.get(guild_id, {})
            for feed_cfg in feeds:
                if not feed_cfg.get("enabled", True):
                    continue
                url = feed_cfg.get("feed_url")
                if not url:
                    continue
                url_to_consumers.setdefault(url, []).append((guild_id, feed_cfg, guild_stats))

        if not url_to_consumers:
            return

        session = await self._get_session()
        tasks_ = [self._poll_url(url, consumers, session) for url, consumers in url_to_consumers.items()]
        results = await asyncio.gather(*tasks_, return_exceptions=True)

        posts_made = 0
        updates_made = 0
        for res in results:
            if isinstance(res, Exception):
                self.log.error(f"Feed URL polling error: {res}")
                continue
            for guild_id, feed_cfg, embeds in res:
                if not embeds:
                    continue
                channel = self.bot.get_channel(feed_cfg["channel_id"])
                if not channel:
                    continue
                if feed_cfg.get("cv2"):
                    p, u = await self._post_cv2(guild_id, feed_cfg, channel, embeds)
                else:
                    p, u = await self._post_embeds(guild_id, feed_cfg, channel, embeds)
                posts_made += p
                updates_made += u

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
        name="feeds",
        description="Manage RSS/Bluesky feeds (add, edit, enable/disable, remove)"
    )
    @app_commands.default_permissions(administrator=True)
    async def feeds_dashboard(self, interaction: discord.Interaction):
        """Single Components-V2 dashboard replacing /feeds_add, _remove, _list, _configure."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You need administrator permissions to use this command.", ephemeral=True)
            return
        from core.feeds_dashboard import build_feeds_dashboard
        view = await build_feeds_dashboard(self, interaction.guild.id)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
