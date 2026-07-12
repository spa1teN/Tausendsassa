"""Components-V2 dashboard for RSS/Bluesky feed management.

Consolidates the former /feeds_add, /feeds_remove, /feeds_list and
/feeds_configure commands into a single /feeds dashboard: one section per feed
(Manage button → edit/toggle/remove detail view) plus an Add button whose screen
gathers the text fields (modal) and the target channel (select) on one CV2
message. Feed *posts* stay embeds (webhook + embed_template); only this
management UI is CV2.
"""

import discord
from typing import List, Optional

BLURPLE = 0x5865F2
GREEN = 0x57F287
RED = 0xED4245


def notice_view(text: str, color: int = GREEN) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour(color))
    container.add_item(discord.ui.TextDisplay(text))
    view.add_item(container)
    return view


def _is_bluesky(url: str) -> bool:
    from core.feeds_config import is_bluesky_feed_url
    return is_bluesky_feed_url(url)


def _normalize_feed_url(url: str) -> str:
    """Prepend https:// when a scheme is missing.

    A scheme-less URL (e.g. 'bsky.app/profile/…/rss') makes aiohttp raise
    InvalidUrlClientError, which the poller swallows — the feed then silently
    never posts. Normalizing on input prevents that.
    """
    url = (url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


async def build_feeds_dashboard(cog, guild_id: int) -> "FeedsDashboardLayout":
    feeds = await cog.get_guild_feeds(guild_id)
    guild = cog.bot.get_guild(guild_id)
    return FeedsDashboardLayout(cog, guild, feeds)


def _channel_name(guild: Optional[discord.Guild], channel_id: int) -> str:
    # Return a channel mention (<#id>) — Discord renders it as a clickable
    # #channel link in CV2 TextDisplays. Fall back to the raw id if it's gone.
    if not channel_id:
        return "—"
    ch = guild.get_channel(channel_id) if guild else None
    return ch.mention if ch else f"<#{channel_id}>"


# ── Dashboard ───────────────────────────────────────────────────────

# One feed per Section costs ~3 of the 40 components a CV2 message allows, so the
# list is paginated: 8 rows/page keeps a comfortable margin under the limit.
FEEDS_PER_PAGE = 8


class FeedsDashboardLayout(discord.ui.LayoutView):
    def __init__(self, cog, guild: Optional[discord.Guild], feeds: List[dict], page: int = 0):
        super().__init__(timeout=300)
        total = len(feeds)
        pages = max(1, (total + FEEDS_PER_PAGE - 1) // FEEDS_PER_PAGE)
        page = max(0, min(page, pages - 1))
        start = page * FEEDS_PER_PAGE
        shown = feeds[start:start + FEEDS_PER_PAGE]

        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        header = f"## 📰 Feeds Dashboard\n-# {total} feed(s) configured"
        if pages > 1:
            header += f" · page {page + 1}/{pages}"
        container.add_item(discord.ui.TextDisplay(header))
        container.add_item(discord.ui.Separator())

        if not feeds:
            container.add_item(discord.ui.TextDisplay("-# No feeds configured yet. Use **Add Feed** below."))
        else:
            for feed in shown:
                kind = "Bluesky" if _is_bluesky(feed["feed_url"]) else "RSS"
                state = "" if feed.get("enabled", True) else " · ⏸ disabled"
                text = (f"**{feed['name']}** · {kind}{state}\n"
                        f"-# → {_channel_name(guild, feed.get('channel_id'))}")
                container.add_item(discord.ui.Section(
                    discord.ui.TextDisplay(text),
                    accessory=_EditRowButton(cog, feed["name"]),
                ))

        row = discord.ui.ActionRow()
        if pages > 1:
            row.add_item(_PageButton(cog, page - 1, "◀", page == 0))
            row.add_item(_PageButton(cog, page + 1, "▶", page >= pages - 1))
        row.add_item(_AddButton(cog))
        container.add_item(row)
        self.add_item(container)


class _EditRowButton(discord.ui.Button):
    def __init__(self, cog, feed_name: str):
        super().__init__(label="Edit", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.feed_name = feed_name

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        feed = next((f for f in feeds if f["name"] == self.feed_name), None)
        if not feed:
            await interaction.response.edit_message(view=await build_feeds_dashboard(self.cog, interaction.guild.id))
            return
        await interaction.response.edit_message(view=FeedDetailLayout(self.cog, interaction.guild, feed))


class _PageButton(discord.ui.Button):
    def __init__(self, cog, page: int, label: str, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.cog = cog
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        await interaction.response.edit_message(
            view=FeedsDashboardLayout(self.cog, interaction.guild, feeds, self.page))


class _AddButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="➕ Add Feed", style=discord.ButtonStyle.green)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        from core.feeds_add import FeedTypeSelect
        await interaction.response.edit_message(view=FeedTypeSelect(self.cog))


# ── Per-feed detail (edit / toggle / remove) ────────────────────────

class FeedDetailLayout(discord.ui.LayoutView):
    def __init__(self, cog, guild: Optional[discord.Guild], feed: dict):
        super().__init__(timeout=300)
        kind = "Bluesky" if _is_bluesky(feed["feed_url"]) else "RSS"
        enabled = feed.get("enabled", True)
        color = (feed.get("embed_template") or {}).get("color", 0x3498DB)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        lines = [
            f"## 📰 {feed['name']}",
            f"-# {kind} · {_channel_name(guild, feed.get('channel_id'))} · {'✅ enabled' if enabled else '⏸ disabled'}",
            f"-# URL: {feed['feed_url']}",
            f"-# Color: #{color:06X} · Crosspost: {'on' if feed.get('crosspost') else 'off'}",
        ]
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))
        row = discord.ui.ActionRow()
        row.add_item(_EditButton(cog, feed))
        row.add_item(_ChannelButton(cog, feed))
        row.add_item(_ToggleButton(cog, feed))
        row.add_item(_RemoveButton(cog, feed["name"]))
        row.add_item(_BackButton(cog))
        container.add_item(row)
        self.add_item(container)


class _ToggleButton(discord.ui.Button):
    def __init__(self, cog, feed: dict):
        enabled = feed.get("enabled", True)
        super().__init__(label="Disable" if enabled else "Enable",
                         style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.feed = feed

    async def callback(self, interaction: discord.Interaction):
        new_enabled = not self.feed.get("enabled", True)
        await self.cog.update_feed(interaction.guild.id, self.feed["name"], {"enabled": new_enabled})
        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        feed = next((f for f in feeds if f["name"] == self.feed["name"]), self.feed)
        await interaction.response.edit_message(view=FeedDetailLayout(self.cog, interaction.guild, feed))


class _ChannelButton(discord.ui.Button):
    def __init__(self, cog, feed: dict):
        super().__init__(label="📢 Channel", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.feed = feed

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=FeedChannelSelectLayout(self.cog, self.feed))


class FeedChannelSelectLayout(discord.ui.LayoutView):
    def __init__(self, cog, feed: dict):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            f"## 📢 Post channel for `{feed['name']}`\n-# Pick where new items are posted. Already-posted messages stay put."))
        row = discord.ui.ActionRow()
        row.add_item(_FeedChannelSelect(cog, feed))
        container.add_item(row)
        row2 = discord.ui.ActionRow()
        row2.add_item(_DetailBackButton(cog, feed["name"]))
        container.add_item(row2)
        self.add_item(container)


class _FeedChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog, feed: dict):
        super().__init__(placeholder="Pick the channel to post into...", min_values=1, max_values=1,
                         channel_types=[discord.ChannelType.text, discord.ChannelType.news])
        self.cog = cog
        self.feed = feed

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        new_channel_id = self.values[0].id
        await self.cog.update_feed(interaction.guild.id, self.feed["name"], {"channel_id": new_channel_id})
        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        feed = next((f for f in feeds if f["name"] == self.feed["name"]), self.feed)
        await interaction.response.edit_message(view=FeedDetailLayout(self.cog, interaction.guild, feed))
        await interaction.followup.send(
            view=notice_view(f"📢 **`{feed['name']}` now posts to {_channel_name(interaction.guild, new_channel_id)}**"),
            ephemeral=True)


class _DetailBackButton(discord.ui.Button):
    def __init__(self, cog, feed_name: str):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.feed_name = feed_name

    async def callback(self, interaction: discord.Interaction):
        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        feed = next((f for f in feeds if f["name"] == self.feed_name), None)
        if not feed:
            await interaction.response.edit_message(view=await build_feeds_dashboard(self.cog, interaction.guild.id))
            return
        await interaction.response.edit_message(view=FeedDetailLayout(self.cog, interaction.guild, feed))


class _RemoveButton(discord.ui.Button):
    def __init__(self, cog, feed_name: str):
        super().__init__(label="🗑️ Remove", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.feed_name = feed_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=FeedRemoveConfirmLayout(self.cog, self.feed_name))


class _BackButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=await build_feeds_dashboard(self.cog, interaction.guild.id))


class FeedRemoveConfirmLayout(discord.ui.LayoutView):
    def __init__(self, cog, feed_name: str):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(RED))
        container.add_item(discord.ui.TextDisplay(
            f"## ⚠️ Remove feed `{feed_name}`?\n-# The feed stops posting; already-posted messages stay."))
        row = discord.ui.ActionRow()
        row.add_item(_ConfirmRemoveButton(cog, feed_name))
        row.add_item(_BackButton(cog))
        container.add_item(row)
        self.add_item(container)


class _ConfirmRemoveButton(discord.ui.Button):
    def __init__(self, cog, feed_name: str):
        super().__init__(label="Confirm remove", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.feed_name = feed_name

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        ok = await self.cog.remove_feed(interaction.guild.id, self.feed_name)
        await interaction.response.edit_message(view=await build_feeds_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"🗑️ **Removed `{self.feed_name}`**" if ok else f"❌ **Failed to remove `{self.feed_name}`**", RED),
            ephemeral=True)


def _build_embed_template(name: str, url: str, color_hex: int) -> dict:
    from core.feeds_config import (is_bluesky_feed_url, create_bluesky_embed_template,
                                   create_standard_embed_template)
    if is_bluesky_feed_url(url):
        return create_bluesky_embed_template(name, color_hex)
    return create_standard_embed_template(name, color_hex)


# ── Edit existing feed ──────────────────────────────────────────────

class _EditModal(discord.ui.Modal):
    def __init__(self, cog, feed: dict):
        super().__init__(title=f"Edit feed: {feed['name']}"[:45])
        self.cog = cog
        self.feed = feed
        current_color = (feed.get("embed_template") or {}).get("color", 0x3498DB)
        self.name_field = discord.ui.TextInput(label="Feed Name", default=feed.get("name", ""), max_length=100, required=True)
        self.url_field = discord.ui.TextInput(label="Feed URL", default=feed.get("feed_url", ""), max_length=500,
                                             required=True, style=discord.TextStyle.paragraph)
        self.avatar_field = discord.ui.TextInput(label="Avatar URL (optional)", default=feed.get("avatar_url") or "",
                                                required=False, max_length=500)
        self.color_field = discord.ui.TextInput(label="Color (name/RGB/hex)", default=f"{current_color:06X}",
                                               max_length=50, required=True)
        self.crosspost_field = discord.ui.TextInput(label="Crosspost (true/false)",
                                                   default=str(feed.get("crosspost", False)).lower(), max_length=5, required=True)
        for f in (self.name_field, self.url_field, self.avatar_field, self.color_field, self.crosspost_field):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        from core.colors import get_discord_embed_color
        color_hex = get_discord_embed_color(self.color_field.value)
        if color_hex is None:
            await interaction.response.send_message(f"❌ Invalid color: `{self.color_field.value}`", ephemeral=True)
            return
        cp = self.crosspost_field.value.lower().strip()
        if cp not in ("true", "false", "1", "0", "yes", "no"):
            await interaction.response.send_message(f"❌ Invalid crosspost value: `{self.crosspost_field.value}` (use true/false)", ephemeral=True)
            return
        crosspost = cp in ("true", "1", "yes")

        updates = {
            "name": self.name_field.value,
            "feed_url": _normalize_feed_url(self.url_field.value),
            "avatar_url": self.avatar_field.value or None,
            "crosspost": crosspost,
            "embed_template": _build_embed_template(self.name_field.value, _normalize_feed_url(self.url_field.value), color_hex),
        }
        old_name = self.feed.get("name")
        ok = await self.cog.update_feed(interaction.guild.id, old_name, updates)
        if ok and old_name != self.name_field.value and interaction.guild.id in getattr(self.cog, "stats", {}):
            if old_name in self.cog.stats[interaction.guild.id]:
                self.cog.stats[interaction.guild.id][self.name_field.value] = self.cog.stats[interaction.guild.id].pop(old_name)

        feeds = await self.cog.get_guild_feeds(interaction.guild.id)
        feed = next((f for f in feeds if f["name"] == self.name_field.value), self.feed)
        await interaction.response.edit_message(view=FeedDetailLayout(self.cog, interaction.guild, feed))
        await interaction.followup.send(
            view=notice_view(f"✅ **Feed `{self.name_field.value}` updated**" if ok else "❌ **Update failed**",
                             GREEN if ok else RED),
            ephemeral=True)


class _EditButton(discord.ui.Button):
    def __init__(self, cog, feed: dict):
        super().__init__(label="✏️ Edit", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.feed = feed

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_EditModal(self.cog, self.feed))


# ── Add flow (single screen: modal for text + channel select) ───────

class FeedAddLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        self.name: Optional[str] = None
        self.feed_url: Optional[str] = None
        self.avatar_url: Optional[str] = None
        self.color_hex: int = 0x3498DB
        self.channel_id: Optional[int] = None

        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            "## 📰 Add Feed\n-# 1) **Set details** (button)  2) pick a channel  3) **Create**"))
        row_c = discord.ui.ActionRow()
        row_c.add_item(_AddChannelSelect(self))
        container.add_item(row_c)
        row_b = discord.ui.ActionRow()
        row_b.add_item(_AddDetailsButton(self))
        row_b.add_item(_AddCreateButton(self))
        row_b.add_item(_BackButton(cog))
        container.add_item(row_b)
        self.add_item(container)


class _AddDetailsModal(discord.ui.Modal):
    def __init__(self, layout: "FeedAddLayout"):
        super().__init__(title="Feed name, URL, avatar & color")
        self.layout = layout
        self.name_field = discord.ui.TextInput(label="Feed Name", required=True, max_length=100, default=layout.name or "")
        self.url_field = discord.ui.TextInput(label="Feed URL (RSS/Atom/Bluesky)", required=True, max_length=500,
                                             style=discord.TextStyle.paragraph, default=layout.feed_url or "")
        self.avatar_field = discord.ui.TextInput(label="Avatar URL (optional)", required=False, max_length=500,
                                                default=layout.avatar_url or "")
        self.color_field = discord.ui.TextInput(label="Color (name/RGB/hex)", required=True, max_length=50,
                                               default=f"{layout.color_hex:06X}")
        for f in (self.name_field, self.url_field, self.avatar_field, self.color_field):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        from core.colors import get_discord_embed_color
        color_hex = get_discord_embed_color(self.color_field.value)
        if color_hex is None:
            await interaction.response.send_message(f"❌ Invalid color: `{self.color_field.value}`", ephemeral=True)
            return
        self.layout.name = self.name_field.value.strip()
        self.layout.feed_url = _normalize_feed_url(self.url_field.value)
        self.layout.avatar_url = self.avatar_field.value.strip() or None
        self.layout.color_hex = color_hex
        await interaction.response.defer()  # silent ack; channel selection stays visible


class _AddDetailsButton(discord.ui.Button):
    def __init__(self, layout: "FeedAddLayout"):
        super().__init__(label="📝 Set details", style=discord.ButtonStyle.primary)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_AddDetailsModal(self.layout))


class _AddChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, layout: "FeedAddLayout"):
        super().__init__(placeholder="Select the channel to post into...", min_values=1, max_values=1,
                         channel_types=[discord.ChannelType.text, discord.ChannelType.news])
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        self.layout.channel_id = self.values[0].id
        await interaction.response.defer()


class _AddCreateButton(discord.ui.Button):
    def __init__(self, layout: "FeedAddLayout"):
        super().__init__(label="✅ Create", style=discord.ButtonStyle.green)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        L = self.layout
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        missing = []
        if not L.name or not L.feed_url:
            missing.append("name & URL (use **Set details**)")
        if not L.channel_id:
            missing.append("channel")
        if missing:
            await interaction.response.send_message("❌ Still missing: " + ", ".join(missing), ephemeral=True)
            return

        new_feed = {
            "name": L.name,
            "feed_url": L.feed_url,
            "channel_id": L.channel_id,
            "max_items": 3,
            "crosspost": False,
            "avatar_url": L.avatar_url,
            "embed_template": _build_embed_template(L.name, L.feed_url, L.color_hex),
        }
        await interaction.response.defer()
        ok = await L.cog.add_feed(interaction.guild.id, new_feed)
        await interaction.edit_original_response(view=await build_feeds_dashboard(L.cog, interaction.guild.id))
        kind = "Bluesky feed" if _is_bluesky(L.feed_url) else "RSS feed"
        await interaction.followup.send(
            view=notice_view(f"✅ **{kind} `{L.name}` added**" if ok else f"❌ **Failed to add `{L.name}`**",
                             GREEN if ok else RED),
            ephemeral=True)
