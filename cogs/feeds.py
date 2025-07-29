# cogs/feeds.py

import os
import logging
import yaml
import asyncio
from pathlib import Path
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import rss

GUILD_ID = 1398409754967015647
GUILD    = discord.Object(id=GUILD_ID) if GUILD_ID else None

log = logging.getLogger("rssbot")


class FeedCog(commands.Cog):
    """Cog for polling RSS feeds, posting embeds, buttons, health monitoring
    and dynamic feed management."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # load config
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.feeds = self.cfg.get("feeds", [])
        log.info(f"Loaded {len(self.feeds)} feeds from config.yaml")

        # health stats
        self.stats = {
            feed["name"]: {"last_run": None, "last_success": None, "failures": 0}
            for feed in self.feeds
        }
        self.monitor_channel_id = self.cfg.get("monitor_channel_id")
        self.failure_threshold   = self.cfg.get("failure_threshold", 3)

    @commands.Cog.listener()
    async def on_ready(self):
        # sync slash commands (guild‐scoped if GUILD set)
        try:
            if GUILD:
                await self.bot.tree.sync(guild=GUILD)
            else:
                await self.bot.tree.sync()
            log.info("✅ Slash commands synced")
        except Exception:
            log.exception("Failed to sync slash commands")

        # start polling
        if not self.poll_loop.is_running():
            log.info("▶ Starting poll_loop…")
            self.poll_loop.start()

    @tasks.loop(minutes=5.0, reconnect=True)
    async def poll_loop(self):
        now = datetime.utcnow()
        log.info(f"🔄 Running poll_loop for {len(self.feeds)} feeds")
        for feed_cfg in self.feeds:
            name = feed_cfg.get("name")
            st   = self.stats[name]
            st["last_run"] = now

            # fetch in thread + timeout
            try:
                embeds = await asyncio.wait_for(
                    asyncio.to_thread(rss.poll, feed_cfg),
                    timeout=30.0
                )
            except Exception:
                st["failures"] += 1
                await self._maybe_alert(name, st["failures"])
                log.exception("❌ Error polling feed %s", name)
                continue

            # success
            st["failures"]     = 0
            st["last_success"] = datetime.utcnow()
            #log.info(f"📥 Found {len(embeds)} new embeds for {name}")
            if not embeds:
                continue

            channel = self.bot.get_channel(feed_cfg["channel_id"])
            if not channel:
                log.warning("⚠️ Channel %s not found for %s",
                            feed_cfg["channel_id"], name)
                continue

            msgs = []
            for e in embeds:
                try:
                    embed = discord.Embed.from_dict(e)
                    # author icon+name
                    author_name = feed_cfg.get("username")
                    author_icon = feed_cfg.get("avatar_url")
                    if author_name or author_icon:
                        embed.set_author(
                            name=author_name or discord.Embed.Empty,
                            icon_url=author_icon or discord.Embed.Empty
                        )
                    # buttons
                    article_url = e.get("url") or feed_cfg.get("feed_url")
                    view = discord.ui.View()
                    if article_url:
                        view.add_item(discord.ui.Button(
                            label="Quelle öffnen",
                            style=discord.ButtonStyle.link,
                            url=article_url
                        ))
                    view.add_item(discord.ui.Button(
                        label="Thread öffnen",
                        style=discord.ButtonStyle.primary,
                        custom_id=f"thread_{name}_{e.get('guid')}"
                    ))

                    msg = await channel.send(embed=embed, view=view)
                    log.info("✅ Posted embed to channel %s", channel.id)
                    msgs.append(msg)
                except Exception:
                    log.exception("❌ Failed to post embed for %s", name)

            # crosspost batch
            if feed_cfg.get("crosspost") and msgs:
                try:
                    await msgs[0].publish()
                    log.info("🚀 Published batch of %d messages", len(msgs))
                except discord.HTTPException as exc:
                    log.warning("Publish failed: %s", exc)

    @poll_loop.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        log.info("✔ poll_loop is now ready")

    async def _maybe_alert(self, feed_name: str, failures: int):
        if failures == self.failure_threshold and self.monitor_channel_id:
            chan = self.bot.get_channel(self.monitor_channel_id)
            if chan:
                await chan.send(
                    f"⚠️ Feed **{feed_name}** hat {failures} Fehler hintereinander."
                )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        cid = interaction.data.get("custom_id", "")
        if not cid.startswith("thread_"):
            return
        await interaction.response.defer(ephemeral=True)
        _, feed_name, guid = cid.split("_", 2)
        thread = await interaction.channel.create_thread(
            name=f"{feed_name} Discussion",
            message=interaction.message
        )
        await interaction.followup.send(
            f"🧵 Thread '{thread.name}' erstellt!", ephemeral=True
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
        name="poll_now",
        description="Run the RSS poll immediately"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def slash_poll_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.poll_loop()
        await interaction.followup.send("✅ Poll executed.", ephemeral=True)

    @app_commands.command(
        name="feeds_reload",
        description="Reload feed configuration and restart polling"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def slash_feeds_reload(self, interaction: discord.Interaction):
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open(encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.feeds = self.cfg.get("feeds", [])
        # rebuild stats for new feeds
        self.stats = {
            feed["name"]: {"last_run": None, "last_success": None, "failures": 0}
            for feed in self.feeds
        }
        self.poll_loop.restart()
        await interaction.response.send_message(
            "✅ Feeds reloaded.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_status",
        description="Show health status of all RSS feeds"
    )
    async def slash_status(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📊 RSS-Feed Health Status",
            color=0x00FF00,
            timestamp=datetime.utcnow()
        )
        for name, st in self.stats.items():
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
        description="Add a new RSS feed"
    )
    @app_commands.default_permissions(manage_guild=True)
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
        # parse color hex
        default_hex = 0x3498DB
        if color:
            c = color.lstrip("#")
            try:
                default_hex = int(c, 16)
            except ValueError:
                return await interaction.followup.send(
                    f"❌ `{color}` ist keine gültige Hex-Farbe.", ephemeral=True
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
                "image":  {"url": "{thumbnail}"}
            }
        }
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open("r+", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            cfg.setdefault("feeds", []).append(new_feed)
            f.seek(0)
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
            f.truncate()
        self.cfg   = cfg
        self.feeds = cfg["feeds"]
        self.stats[name] = {"last_run": None, "last_success": None, "failures": 0}
        self.poll_loop.restart()
        await interaction.followup.send(
            f"✅ Feed **{name}** hinzugefügt.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_remove",
        description="Remove an RSS feed by name"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def slash_feeds_remove(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        await interaction.response.defer(ephemeral=True)
        cfg_path = Path(__file__).parents[1] / "config.yaml"
        with cfg_path.open("r+", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            old = cfg.get("feeds", [])
            new = [f for f in old if f.get("name") != name]
            if len(new) == len(old):
                return await interaction.followup.send(
                    f"❌ Kein Feed mit Namen **{name}** gefunden.", ephemeral=True
                )
            cfg["feeds"] = new
            f.seek(0)
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
            f.truncate()
        self.cfg   = cfg
        self.feeds = cfg["feeds"]
        self.stats.pop(name, None)
        self.poll_loop.restart()
        await interaction.followup.send(
            f"✅ Feed **{name}** entfernt.", ephemeral=True
        )

    @app_commands.command(
        name="feeds_list",
        description="List all configured RSS feeds"
    )
    async def slash_feeds_list(self, interaction: discord.Interaction):
        lines = []
        for f in self.feeds:
            col = f["embed_template"].get("color", 0)
            lines.append(
                f"• **{f['name']}** – <{f['feed_url']}> in <#{f['channel_id']}>"
                f" – Farbe: `#{col:06X}`"
            )
        embed = discord.Embed(
            title="📑 Aktuelle RSS-Feeds",
            description="\n".join(lines) or "Keine Feeds konfiguriert.",
            color=0x00ADEF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FeedCog(bot))
