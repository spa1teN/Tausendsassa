"""Feed creation UI v2 — type selector, auto-fill, preview webhook.

Flow: /feeds → Add Feed → pick type → simplified modal → preview → confirm.

Types:
  RSS         — full URL required (unchanged from v1)
  Reddit Forum — subreddit name → r/{name}.rss, name = "r/{name} - Reddit"
  Reddit User  — username → user/{name}.rss, name = "u/{name} - Reddit"
  Bluesky      — handle → bsky.app/profile/{handle}/rss, name = "@{handle} - Bluesky"
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
import discord
import feedparser

from core.feeds_config import is_bluesky_feed_url, create_bluesky_embed_template, create_standard_embed_template

log = logging.getLogger("tausendsassa.feeds")
BLURPLE = 0x5865F2
GREEN = 0x57F287
RED = 0xED4245

# ── Type selector ──────────────────────────────────────────────────────

class FeedTypeSelect(discord.ui.LayoutView):
    """First screen: pick the feed type."""

    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            "## 📰 Add Feed\n-# What kind of feed do you want to add?"))

        row1 = discord.ui.ActionRow()
        row1.add_item(_TypeButton(cog, "📡 RSS / Atom", "rss"))
        row1.add_item(_TypeButton(cog, "📰 Reddit Forum", "reddit_forum"))
        container.add_item(row1)

        row2 = discord.ui.ActionRow()
        row2.add_item(_TypeButton(cog, "👤 Reddit User", "reddit_user"))
        row2.add_item(_TypeButton(cog, "🦋 Bluesky", "bluesky"))
        container.add_item(row2)

        from core.feeds_dashboard import _BackButton
        row3 = discord.ui.ActionRow()
        row3.add_item(_BackButton(cog))
        container.add_item(row3)
        self.add_item(container)


class _TypeButton(discord.ui.Button):
    def __init__(self, cog, label: str, feed_type: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.cog = cog
        self.feed_type = feed_type

    async def callback(self, interaction: discord.Interaction):
        if self.feed_type == "rss":
            # Use the existing full-URL flow
            from core.feeds_dashboard import FeedAddLayout
            await interaction.response.edit_message(view=FeedAddLayout(self.cog))
        else:
            await interaction.response.send_modal(_SimplifiedModal(self.cog, self.feed_type))


# ── Simplified modal for Reddit/Bluesky ───────────────────────────────

class _SimplifiedModal(discord.ui.Modal):
    """Modal for Reddit Forum, Reddit User, and Bluesky — nickname + optional avatar/color."""

    def __init__(self, cog, feed_type: str):
        labels = {
            "reddit_forum": ("Subreddit name", "r/", "e.g. anime"),
            "reddit_user": ("Reddit username", "u/", "e.g. spa1teN"),
            "bluesky": ("Bluesky handle", "@", "e.g. spa1ten.bsky.social"),
        }
        label, prefix, placeholder = labels[feed_type]
        super().__init__(title=f"Add {label}")
        self.cog = cog
        self.feed_type = feed_type
        self.name_field = discord.ui.TextInput(
            label=label, placeholder=placeholder, required=True, max_length=100)
        self.add_item(self.name_field)
        if feed_type in ("reddit_forum", "reddit_user"):
            self.avatar_field = discord.ui.TextInput(
                label="Avatar URL (optional)", required=False, max_length=500, default="")
            self.color_field = discord.ui.TextInput(
                label="Color (name/RGB/hex)", required=True, max_length=50, default="3498DB")
            self.add_item(self.avatar_field)
            self.add_item(self.color_field)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.name_field.value.strip().lstrip("@").lstrip("r/").lstrip("u/").strip()

        if self.feed_type == "reddit_forum":
            feed_url = f"https://www.reddit.com/r/{raw}/new.rss"
            feed_name = f"r/{raw}"
        elif self.feed_type == "reddit_user":
            feed_url = f"https://www.reddit.com/user/{raw}/new.rss"
            feed_name = f"u/{raw}"
        else:  # bluesky
            feed_url = f"https://bsky.app/profile/{raw}/rss"
            feed_name = f"@{raw}"
        if self.feed_type in ("reddit_forum", "reddit_user"):
            avatar_url = self.avatar_field.value.strip() or None
        else:
            avatar_url = await _fetch_avatar(self.feed_type, raw)

        await interaction.response.edit_message(
            view=_PreviewLayout(self.cog, self.feed_type, feed_name, feed_url, avatar_url, raw))



async def _fetch_avatar(feed_type: str, name: str) -> Optional[str]:
    """Fetch avatar URL — Bluesky only (Reddit JSON blocked)."""
    if feed_type != "bluesky":
        return None
    try:
        async with aiohttp.ClientSession() as session:
            resolve_url = "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle"
            async with session.get(resolve_url, params={"handle": name},
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    did = (await r.json()).get("did")
                    if did:
                        profile_url = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
                        async with session.get(profile_url, params={"actor": did},
                                               timeout=aiohttp.ClientTimeout(total=10)) as r2:
                            if r2.status == 200:
                                avatar = (await r2.json()).get("avatar", "")
                                if avatar:
                                    return avatar
    except Exception:
        pass
    return None

class _PreviewLayout(discord.ui.LayoutView):
    """Show auto-filled settings, send a preview webhook, let user confirm or edit."""

    def __init__(self, cog, feed_type: str, feed_name: str, feed_url: str,
                 avatar_url: Optional[str], raw_name: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.feed_type = feed_type
        self.feed_name = feed_name
        self.feed_url = feed_url
        self.avatar_url = avatar_url
        self.raw_name = raw_name
        self.channel_id: Optional[int] = None
        self.preview_msg: Optional[discord.Message] = None

        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        lines = [
            f"## 🔍 Preview: {feed_name}",
            f"-# URL: `{feed_url}`",
        ]
        if avatar_url:
            lines.append(f"-# Avatar: [link]({avatar_url})")
        else:
            lines.append("-# Avatar: *(not found — you can set one later)*")
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))

        row1 = discord.ui.ActionRow()
        row1.add_item(_PreviewChannelSelect(self))
        container.add_item(row1)

        row2 = discord.ui.ActionRow()
        row2.add_item(_PreviewSendButton(self))
        row2.add_item(_PreviewConfirmButton(self))
        from core.feeds_dashboard import _BackButton
        row2.add_item(_BackButton(cog))
        container.add_item(row2)
        self.add_item(container)

    async def create_preview(self, interaction: discord.Interaction):
        """Send a preview webhook message and show confirmation."""
        if not self.channel_id:
            await interaction.response.send_message("❌ Select a channel first.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Fetch the latest entry
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.feed_url, timeout=aiohttp.ClientTimeout(total=15),
                                       headers={"User-Agent": "Tausendsassa-Bot/1.0"}) as r:
                    if r.status != 200:
                        await interaction.followup.send(
                            f"❌ Could not fetch feed (HTTP {r.status}). Check the name.", ephemeral=True)
                        return
                    parsed = feedparser.parse(await r.text())
        except Exception as e:
            await interaction.followup.send(f"❌ Error fetching feed: {e}", ephemeral=True)
            return

        if not parsed.entries:
            await interaction.followup.send("❌ Feed has no entries. Try again later.", ephemeral=True)
            return

        entry = parsed.entries[0]
        title = entry.get("title", self.feed_name)
        link = entry.get("link", "")
        from core.feeds_rss import _strip_html
        title = _strip_html(title).strip() or self.feed_name

        # Build CV2 preview
        from core import feeds_cv2
        embed_data = {
            "title": title,
            "description": entry.get("summary", "") or entry.get("description", ""),
            "url": link,
            "timestamp": "",
            "image": {},
        }
        view = feeds_cv2.build_entry_view(embed_data, self.feed_name, 0x3498DB)

        try:
            wh_name = f"Preview-{self.feed_name}"[:80]
            webhooks = await channel.webhooks()
            wh = next((w for w in webhooks if w.name == wh_name), None)
            if not wh:
                wh = await channel.create_webhook(name=wh_name)
            msg = await wh.send(
                username=self.feed_name,
                avatar_url=self.avatar_url,
                view=view,
                wait=True,
            )
            self.preview_msg = msg
            await interaction.followup.send(
                "✅ Preview sent! Check the channel, then click **Confirm** to save the feed.\n"
                "-# You can adjust the avatar URL in feed settings later.",
                ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed to send preview: {e}", ephemeral=True)


class _PreviewChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, layout: _PreviewLayout):
        super().__init__(placeholder="Select channel for preview + posting...",
                         min_values=1, max_values=1,
                         channel_types=[discord.ChannelType.text, discord.ChannelType.news])
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        self.layout.channel_id = self.values[0].id
        await interaction.response.defer()


class _PreviewSendButton(discord.ui.Button):
    def __init__(self, layout: _PreviewLayout):
        super().__init__(label="🔍 Preview", style=discord.ButtonStyle.primary)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        await self.layout.create_preview(interaction)


class _PreviewConfirmButton(discord.ui.Button):
    def __init__(self, layout: _PreviewLayout):
        super().__init__(label="✅ Confirm", style=discord.ButtonStyle.green)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        L = self.layout
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permissions required.", ephemeral=True)
            return
        if not L.channel_id:
            await interaction.response.send_message("❌ Select a channel first.", ephemeral=True)
            return

        await interaction.response.defer()

        from core.feeds_config import is_bluesky_feed_url, create_bluesky_embed_template, create_standard_embed_template
        tpl = (create_bluesky_embed_template(L.feed_name, 0x3498DB)
               if is_bluesky_feed_url(L.feed_url)
               else create_standard_embed_template(L.feed_name, 0x3498DB))
        tpl["cv2"] = True

        new_feed = {
            "name": L.feed_name,
            "feed_url": L.feed_url,
            "channel_id": L.channel_id,
            "max_items": 3,
            "crosspost": False,
            "avatar_url": L.avatar_url,
            "embed_template": tpl,
        }
        ok = await L.cog.add_feed(interaction.guild.id, new_feed)

        from core.feeds_dashboard import build_feeds_dashboard
        await interaction.edit_original_response(view=await build_feeds_dashboard(L.cog, interaction.guild.id))

        # Clean up preview webhook
        if L.preview_msg:
            try:
                await L.preview_msg.delete()
            except Exception:
                pass

        kind = {"reddit_forum": "Reddit feed", "reddit_user": "Reddit user feed", "bluesky": "Bluesky feed"}.get(L.feed_type, "Feed")
        from core.feeds_dashboard import notice_view
        await interaction.followup.send(
            view=notice_view(f"✅ **{kind} `{L.feed_name}` added**" if ok else f"❌ Failed"),
            ephemeral=True)
