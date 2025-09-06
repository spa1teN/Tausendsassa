# cogs/feeds.py

import os
import yaml
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import rss

# Configuration constants
POLL_INTERVAL_MINUTES = 1.0
MAX_POST_AGE_SECONDS = 120
RATE_LIMIT_SECONDS = 30
FAILURE_THRESHOLD = 3
AUTHORIZED_USERS = [485051896655249419, 506551160354766848, 703896034820096000]
GLOBAL_MONITOR_CHANNEL_ID = 1403336394801414234

# Predefined color choices for easier selection
COLOR_CHOICES = [
    app_commands.Choice(name="Blue", value="3498DB"),
    app_commands.Choice(name="Green", value="2ECC71"),
    app_commands.Choice(name="Red", value="E74C3C"),
    app_commands.Choice(name="Orange", value="F39C12"),
    app_commands.Choice(name="Purple", value="9B59B6"),
    app_commands.Choice(name="Cyan", value="1ABC9C"),
    app_commands.Choice(name="Yellow", value="F1C40F"),
    app_commands.Choice(name="Pink", value="E91E63"),
    app_commands.Choice(name="Dark Blue", value="2C3E50"),
    app_commands.Choice(name="Gray", value="95A5A6")
]

def _is_bluesky_feed_url(url: str) -> bool:
    """Check if the given URL is a Bluesky profile feed"""
    return "bsky.app/profile/" in url

def _create_bluesky_embed_template(name: str, default_color: int) -> dict:
    """Create a specialized embed template for Bluesky feeds"""
    return {
        "title": f"{name} just posted on Bluesky",  # Static title for all Bluesky posts
        "description": "{summary}",  # Show post content in description
        "url": "{link}",
        "color": default_color,
        "timestamp": "{published_custom}",
        "footer": {"text": name},
        "image": {"url": "{thumbnail}"}
    }

class FeedRemoveView(discord.ui.View):
    """View for feed removal with dropdown selection"""
    def __init__(self, feeds: List[dict], cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for feed in feeds[:25]:  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"URL: {feed['feed_url'][:50]}..." if len(feed['feed_url']) > 50 else feed['feed_url'],
                value=feed["name"]
            ))
        
        if options:
            select = FeedRemoveSelect(options, cog, guild_id)
            self.add_item(select)

class FeedRemoveSelect(discord.ui.Select):
    """Select dropdown for feed removal"""
    def __init__(self, options: List[discord.SelectOption], cog, guild_id: int):
        super().__init__(
            placeholder="Choose a feed to remove...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        feed_name = self.values[0]
        
        # Remove the feed
        config = self.cog._load_guild_config(self.guild_id)
        old_feeds = config.get("feeds", [])
        new_feeds = [f for f in old_feeds if f.get("name") != feed_name]
        
        config["feeds"] = new_feeds
        self.cog._save_guild_config(self.guild_id, config)
        
        # Update runtime config and stats
        self.cog.guild_configs[self.guild_id] = config
        if self.guild_id in self.cog.stats:
            self.cog.stats[self.guild_id].pop(feed_name, None)
        
        self.cog.poll_loop.restart()
        
        await interaction.response.edit_message(
            content=f"✅ Feed **{feed_name}** removed from this server.",
            view=None
        )

class FeedConfigureView(discord.ui.View):
    """View for feed configuration with dropdown selection"""
    def __init__(self, feeds: List[dict], cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for feed in feeds[:25]:  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"Channel: #{feed.get('channel_name', 'unknown')}",
                value=feed["name"]
            ))
        
        if options:
            select = FeedConfigureSelect(options, cog, guild_id)
            self.add_item(select)

class FeedConfigureSelect(discord.ui.Select):
    """Select dropdown for feed configuration"""
    def __init__(self, options: List[discord.SelectOption], cog, guild_id: int):
        super().__init__(
            placeholder="Choose a feed to configure...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        feed_name = self.values[0]
        
        # Find the feed config
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        feed_config = next((f for f in feeds if f.get("name") == feed_name), None)
        
        if not feed_config:
            await interaction.response.edit_message(
                content="❌ Feed not found.",
                view=None
            )
            return
        
        # Create configuration modal
        modal = FeedConfigModal(feed_config, self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

class FeedConfigModal(discord.ui.Modal):
    """Modal for configuring feed settings"""
    def __init__(self, feed_config: dict, cog, guild_id: int):
        self.feed_config = feed_config
        self.cog = cog
        self.guild_id = guild_id
        
        super().__init__(title=f"Configure Feed: {feed_config['name']}")
        
        # Add input fields
        self.name_input = discord.ui.TextInput(
            label="Feed Name",
            default=feed_config.get("name", ""),
            max_length=100
        )
        
        self.avatar_input = discord.ui.TextInput(
            label="Avatar URL (optional)",
            default=feed_config.get("avatar_url", ""),
            required=False,
            max_length=500
        )
        
        current_color = feed_config.get("embed_template", {}).get("color", 0x3498DB)
        self.color_input = discord.ui.TextInput(
            label="Color (hex without #, e.g. 3498DB)",
            default=f"{current_color:06X}",
            max_length=6
        )
        
        self.add_item(self.name_input)
        self.add_item(self.avatar_input)
        self.add_item(self.color_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Validate color
        try:
            color_hex = int(self.color_input.value.lstrip("#"), 16)
        except ValueError:
            await interaction.response.send_message(
                f"❌ Invalid color: {self.color_input.value}", ephemeral=True
            )
            return
        
        # Update feed config
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        
        for feed in feeds:
            if feed.get("name") == self.feed_config["name"]:
                old_name = feed["name"]
                feed["name"] = self.name_input.value
                feed["avatar_url"] = self.avatar_input.value or None
                feed["embed_template"]["color"] = color_hex
                feed["embed_template"]["footer"]["text"] = self.name_input.value
                
                # Update title for Bluesky feeds if name changed
                if _is_bluesky_feed_url(feed["feed_url"]):
                    feed["embed_template"]["title"] = f"{self.name_input.value} just posted on Bluesky"
                    feed["embed_template"]["author"]["name"] = self.name_input.value
                
                # Update stats if name changed
                if old_name != self.name_input.value and self.guild_id in self.cog.stats:
                    if old_name in self.cog.stats[self.guild_id]:
                        self.cog.stats[self.guild_id][self.name_input.value] = self.cog.stats[self.guild_id].pop(old_name)
                break
        
        self.cog._save_guild_config(self.guild_id, config)
        self.cog.guild_configs[self.guild_id] = config
        
        await interaction.response.send_message(
            f"✅ Feed **{self.name_input.value}** updated successfully!", ephemeral=True
        )

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
                # Check if guild still exists
                if not self.bot.get_guild(guild_id):
                    self.log.info(f"Guild {guild_id} no longer accessible, skipping config load")
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

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Handle bot being removed from a guild"""
        guild_id = guild.id
        self.log.info(f"Bot removed from guild {guild.name} (ID: {guild_id})")
        
        # Remove guild config and state
        self._remove_guild_config(guild_id)
        
        # Remove from runtime configs
        self.guild_configs.pop(guild_id, None)
        self.stats.pop(guild_id, None)
        
        # Remove webhooks for this guild's channels
        guild_channels = [channel.id for channel in guild.channels if hasattr(channel, 'id')]
        for channel_id in guild_channels:
            self.webhook_cache.pop(channel_id, None)
        self._save_webhook_cache()
        
        self.log.info(f"Cleaned up all data for removed guild {guild_id}")

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES, reconnect=True)
    async def poll_loop(self):
        """Main polling loop for all guild feeds with message update support"""
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

                # Process embeds (new posts and updates)
                for e in embeds:
                    try:
                        embed = discord.Embed.from_dict(e)
                        is_update = e.get("is_update", False)
                        message_info = e.get("message_info")
                        guid = e.get("guid")
                        
                        if is_update and message_info:
                            # Try to update existing message
                            message_id, old_channel_id = message_info
                            if old_channel_id == channel.id:
                                try:
                                    old_message = await channel.fetch_message(message_id)
                                    await old_message.edit(embed=embed)
                                    self.log.info("✅ Updated existing message for %s", name)
                                    # Update timestamp in state
                                    rss.mark_entry_posted(guild_id, guid, message_id, channel.id)
                                    continue
                                except discord.NotFound:
                                    self.log.info("Original message not found, posting new one for %s", name)
                                except Exception as ex:
                                    self.log.warning("Failed to update message for %s: %s", name, ex)
                        
                        # Post new message (either new entry or failed update)
                        webhook = await self._get_or_create_webhook(channel, name)
                        if webhook:
                            msg = await webhook.send(
                                embed=embed,
                                username=name,  # Use feed name as username
                                avatar_url=feed_cfg.get("avatar_url"),
                                wait=True
                            )
                            self.log.info("✅ Posted embed via webhook to channel <#%s>", channel.id)
                        else:
                            # Fallback to bot posting
                            msg = await self._post_via_bot_single(channel, embed, feed_cfg, name)
                        
                        if msg:
                            # Mark as posted with message info
                            rss.mark_entry_posted(guild_id, guid, msg.id, channel.id)
                            
                            # Handle crosspost
                            if feed_cfg.get("crosspost"):
                                try:
                                    await msg.publish()
                                    self.log.info("🚀 Published message")
                                except discord.HTTPException as exc:
                                    self.log.warning("Publish failed: %s", exc)
                                    
                    except Exception:
                        self.log.exception("❌ Failed to process embed for %s", name)

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
            self.log.info("✅ Posted embed via bot to channel <#%s>", channel.id)
            return msg
        except Exception:
            self.log.exception("❌ Failed to post embed for %s", name)
            return None

    @tasks.loop(hours=168)  # Weekly cleanup
    async def cleanup_loop(self):
        """Weekly cleanup of old posted entries"""
        self.log.info("🧹 Running weekly cleanup of posted entries")
        for guild_id in self.guild_configs.keys():
            try:
                rss.cleanup_old_entries(guild_id)
            except Exception:
                self.log.exception(f"Error during cleanup for guild {guild_id}")

    @tasks.loop(minutes=30)  # Update monitor every 30 minutes
    async def monitor_update_loop(self):
        """Update the global feed monitor"""
        await self._update_global_monitor()

    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        self.log.info("✓ poll_loop is ready")

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        self.log.info("✓ cleanup_loop is ready")

    @monitor_update_loop.before_loop
    async def before_monitor_update(self):
        await self.bot.wait_until_ready()
        self.log.info("✓ monitor_update_loop is ready")

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
        name="feeds_add",
        description="Add a new RSS feed to this server"
    )
    @app_commands.describe(
        name="Name of the RSS feed",
        feed_url="URL of the RSS feed",
        channel="Channel where posts will be sent",
        crosspost="Whether to crosspost (for announcement channels)",
        color="Color for the embed",
        avatar_url="Avatar URL for the webhook"
    )
    @app_commands.choices(color=COLOR_CHOICES)
    @app_commands.default_permissions(administrator=True)
    async def slash_feeds_add(
        self,
        interaction: discord.Interaction,
        name: str,
        feed_url: str,
        channel: discord.TextChannel,
        crosspost: bool = False,
        color: app_commands.Choice[str] = None,
        avatar_url: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        # Parse color
        default_hex = 0x3498DB
        if color:
            try:
                default_hex = int(color.value, 16)
            except ValueError:
                default_hex = 0x3498DB
        
        # Check if this is a Bluesky feed and use appropriate template
        if _is_bluesky_feed_url(feed_url):
            embed_template = _create_bluesky_embed_template(name, default_hex)
        else:
            # Standard template for normal RSS feeds
            embed_template = {
                "title": "{title}",
                "description": "{description}",
                "url": "{link}",
                "color": default_hex,
                "timestamp": "{published_custom}",
                "footer": {"text": name},
                "image": {"url": "{thumbnail}"}
            }
        
        new_feed = {
            "name": name,
            "feed_url": feed_url,
            "channel_id": channel.id,
            "max_items": 3,  # Fixed to 3
            "crosspost": crosspost,
            "avatar_url": avatar_url,
            "embed_template": embed_template
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
        
        # Special confirmation message for Bluesky feeds
        if _is_bluesky_feed_url(feed_url):
            await interaction.followup.send(
                f"✅ Bluesky feed **{name}** added to this server with custom title format.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"✅ Feed **{name}** added to this server.", ephemeral=True
            )

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
        
        view = FeedRemoveView(feeds, self, guild_id)
        await interaction.response.send_message(
            "Select a feed to remove:", view=view, ephemeral=True
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
            feed_type = "🦋 Bluesky" if _is_bluesky_feed_url(f["feed_url"]) else "📰 RSS"
            lines.append(
                f"• **{f['name']}** {feed_type} — <{f['feed_url']}> in <#{f['channel_id']}>"
                f" — Color: `#{col:06X}`"
            )
        embed = discord.Embed(
            title="📋 Current RSS Feeds",
            description="\n".join(lines),
            color=0x00ADEF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        
        view = FeedConfigureView(feeds, self, guild_id)
        await interaction.response.send_message(
            "Select a feed to configure:", view=view, ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
