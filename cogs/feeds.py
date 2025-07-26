# cogs/feeds.py
import logging
import yaml
from pathlib import Path
import asyncio

import discord
import os
# Guild-specific slash command registration for immediate availability
GUILD_ID = 1398477775828029645
GUILD = discord.Object(id=GUILD_ID) if GUILD_ID else None

from discord import app_commands
from discord.ext import commands, tasks

from core import rss
log = logging.getLogger("rssbot")

class FeedCog(commands.Cog):
    """Cog for polling RSS feeds and exposing control commands."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Load configuration
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.feeds = self.cfg.get("feeds", [])
        log.info(f"Loaded {len(self.feeds)} feeds from config.yaml")

    @commands.Cog.listener()
    async def on_ready(self):
        # Sync slash commands once
        try:
            await self.bot.tree.sync()
            log.info("✅ Slash commands synced")
        except Exception:
            log.exception("Failed to sync slash commands")
        # Start polling loop
        if not self.poll_loop.is_running():
            log.info("▶ Starting poll_loop…")
            self.poll_loop.start()

    @tasks.loop(minutes=5.0, reconnect=True)
    async def poll_loop(self):
        log.info(f"🔄 Running poll_loop for {len(self.feeds)} feeds")
        for feed_cfg in self.feeds:
            name = feed_cfg.get("name") or feed_cfg.get("feed_url")
            url = feed_cfg.get("feed_url")
            log.info(f"🔍 Polling {name}: {url}")

            # Run blocking poll in thread with timeout
            try:
                embeds = await asyncio.wait_for(
                    asyncio.to_thread(rss.poll, feed_cfg),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                log.error("❌ Timeout while polling %s", name)
                continue
            except Exception:
                log.exception("❌ Error polling feed %s", name)
                continue

            log.info(f"📥 Found {len(embeds)} new embeds for {name}")
            if not embeds:
                continue

            # Send all embeds, then publish first message if configured
            msgs = []
            for e in embeds:
                try:
                    embed = discord.Embed.from_dict(e)
                    # set author from config
                    author_name = feed_cfg.get("username")
                    author_icon = feed_cfg.get("avatar_url")
                    if author_name or author_icon:
                        embed.set_author(
                            name=author_name or discord.Embed.Empty,
                            icon_url=author_icon or discord.Embed.Empty
                        )
                    channel = self.bot.get_channel(feed_cfg["channel_id"])
                    if channel is None:
                        log.warning("⚠️ Channel %s not found for %s", feed_cfg["channel_id"], name)
                        continue
                    msg = await channel.send(embed=embed)
                    log.info("✅ Posted embed to channel %s", channel.id)
                    msgs.append(msg)
                except Exception:
                    log.exception("❌ Failed to post embed for %s", name)

            # Crosspost batch
            if feed_cfg.get("crosspost") and msgs:
                try:
                    await msgs[0].publish()
                    log.info("🚀 Published batch of %d messages", len(msgs))
                except discord.HTTPException as e:
                    log.warning("Publish failed: %s", e)

    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        log.info("✔ poll_loop is now ready")

    # -------- Slash Commands --------
    @app_commands.command(
        name="ping",
        description="Test if the bot is responsive"
    )
    async def slash_ping(self, interaction: discord.Interaction):
        """Replies with Pong and latency."""
        await interaction.response.send_message(f"Pong! {self.bot.latency*1000:.0f} ms", ephemeral=True)

    @app_commands.command(
        name="poll_now",
        description="Run the RSS poll immediately"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def slash_poll_now(self, interaction: discord.Interaction):
        """Triggers the poll loop manually"""
        await interaction.response.defer(ephemeral=True)
        await self.poll_loop()
        await interaction.followup.send("✅ Poll executed.", ephemeral=True)

    @app_commands.command(
        name="feeds_reload",
        description="Reload feed configuration and restart polling"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def slash_feeds_reload(self, interaction: discord.Interaction):
        """Reloads config.yaml and restarts the poll loop"""
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.feeds = self.cfg.get("feeds", [])
        self.poll_loop.restart()
        await interaction.response.send_message("✅ Feeds reloaded.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
