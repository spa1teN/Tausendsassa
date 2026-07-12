"""Components-V2 dashboard for map management (/map).

One simple admin dashboard for the whole map lifecycle: create it (pick channel
+ region), change its region or channel, regenerate it, delete it, or open the
colour/pin styling view via the "🎨 Edit Style" button (cog._cv2_admin_callback,
whose Back button returns here via cog._cv2_style_back_callback).
"""

import discord
from typing import List, Optional

BLURPLE = 0x5865F2
GREEN = 0x57F287
RED = 0xED4245

# Same set the old /map_create offered (≤ 25 → fits one select).
REGIONS = [
    ("🌍 World", "world"), ("🇪🇺 Europe", "europe"), ("🌏 Asia", "asia"),
    ("🌍 Africa", "africa"), ("🌎 North America", "northamerica"),
    ("🌎 South America", "southamerica"), ("🇦🇺 Australia", "australia"),
    ("🇺🇸 US-Mainland", "usmainland"), ("🇩🇪 Germany", "germany"),
    ("🇫🇷 France", "france"), ("🇪🇸 Spain", "spain"), ("🇮🇹 Italy", "italy"),
    ("🇵🇱 Poland", "poland"), ("🇳🇱 Netherlands", "netherlands"),
    ("🇧🇪 Belgium", "belgium"), ("🇨🇭 Switzerland", "switzerland"),
    ("🇸🇪 Sweden", "sweden"), ("🇷🇺 Russia", "russia"), ("🇺🇦 Ukraine", "ukraine"),
    ("🇹🇷 Turkey", "turkey"), ("🇯🇵 Japan", "japan"), ("🇰🇷 South Korea", "southkorea"),
    ("🇧🇷 Brazil", "brazil"), ("🇨🇦 Canada", "canada"), ("🇲🇽 Mexico", "mexico"),
]
_REGION_LABEL = {value: label for label, value in REGIONS}


def notice_view(text: str, color: int = GREEN) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour(color))
    container.add_item(discord.ui.TextDisplay(text))
    view.add_item(container)
    return view


def _channel_name(guild: Optional[discord.Guild], channel_id: int) -> str:
    ch = guild.get_channel(channel_id) if guild else None
    return ch.mention if ch else f"channel {channel_id}"


async def build_map_dashboard(cog, guild_id: int) -> discord.ui.LayoutView:
    guild = cog.bot.get_guild(guild_id)
    map_data = cog.maps.get(str(guild_id))
    if map_data:
        return MapManageLayout(cog, guild, map_data)
    return MapCreateLayout(cog)


# ── No map yet → create flow (channel + region on one screen) ───────

class MapCreateLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        self.channel_id: Optional[int] = None
        self.region: str = "world"
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            "## 🗺️ Map Dashboard\n-# No map yet. Pick a channel and region, then **Create**."))
        row_c = discord.ui.ActionRow()
        row_c.add_item(_CreateChannelSelect(self))
        container.add_item(row_c)
        row_r = discord.ui.ActionRow()
        row_r.add_item(_CreateRegionSelect(self))
        container.add_item(row_r)
        row_b = discord.ui.ActionRow()
        row_b.add_item(_CreateButton(self))
        container.add_item(row_b)
        self.add_item(container)


class _CreateChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, layout):
        super().__init__(placeholder="Channel to post the map into...", min_values=1, max_values=1,
                         channel_types=[discord.ChannelType.text])
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        self.layout.channel_id = self.values[0].id
        await interaction.response.defer()


class _CreateRegionSelect(discord.ui.Select):
    def __init__(self, layout):
        options = [discord.SelectOption(label=label, value=value, default=(value == layout.region))
                   for label, value in REGIONS]
        super().__init__(placeholder="Region (default: World)...", options=options, min_values=1, max_values=1)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        self.layout.region = self.values[0]
        await interaction.response.defer()


class _CreateButton(discord.ui.Button):
    def __init__(self, layout):
        super().__init__(label="✅ Create Map", style=discord.ButtonStyle.green)
        self.layout = layout

    async def callback(self, interaction: discord.Interaction):
        L = self.layout
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        if not L.channel_id:
            await interaction.response.send_message("❌ Pick a channel first.", ephemeral=True)
            return
        await interaction.response.defer()
        ok, error = await L.cog.dash_create_map(interaction.guild.id, L.channel_id, L.region, interaction.user.id)
        await interaction.edit_original_response(view=await build_map_dashboard(L.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"✅ **Map created** in {_channel_name(interaction.guild, L.channel_id)} "
                             f"({_REGION_LABEL.get(L.region, L.region)})" if ok else f"❌ {error}",
                             GREEN if ok else RED),
            ephemeral=True)


# ── Map exists → management ─────────────────────────────────────────

class MapManageLayout(discord.ui.LayoutView):
    def __init__(self, cog, guild: Optional[discord.Guild], map_data: dict):
        super().__init__(timeout=300)
        self.cog = cog
        pins = len(map_data.get('pins', {}))
        region = map_data.get('region', 'world')
        custom = "yes" if map_data.get('settings') else "no"
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            f"## 🗺️ Map Dashboard\n"
            f"-# Channel: {_channel_name(guild, map_data.get('channel_id'))} · "
            f"Region: {_REGION_LABEL.get(region, region)} · Pins: {pins} · Custom style: {custom}"))
        container.add_item(discord.ui.Separator())
        row1 = discord.ui.ActionRow()
        row1.add_item(_RegionButton(cog))
        row1.add_item(_ChannelButton(cog))
        row1.add_item(_RegenerateButton(cog))
        container.add_item(row1)
        row2 = discord.ui.ActionRow()
        row2.add_item(_StyleButton(cog))
        row2.add_item(_DeleteButton(cog))
        container.add_item(row2)
        self.add_item(container)


class _RegionButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="🌍 Change Region", style=discord.ButtonStyle.primary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=MapRegionSelectLayout(self.cog))


class _ChannelButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="📢 Change Channel", style=discord.ButtonStyle.primary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=MapChannelSelectLayout(self.cog))


class _RegenerateButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="♻️ Regenerate", style=discord.ButtonStyle.secondary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.dash_regenerate(interaction.guild.id)
        await interaction.edit_original_response(view=await build_map_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(view=notice_view("♻️ **Map regenerated**"), ephemeral=True)


class _StyleButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="🎨 Edit Style", style=discord.ButtonStyle.primary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        # Opens the colour/pin styling view (Edit Colors, Edit Pin, Render Preview);
        # its Back button returns here via _cv2_style_back_callback.
        await self.cog._cv2_admin_callback(interaction)


class _DeleteButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="🗑️ Delete Map", style=discord.ButtonStyle.danger)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=MapDeleteConfirmLayout(self.cog))


class MapRegionSelectLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay("## 🌍 Change Region\n-# Regenerates the map in the new region."))
        row = discord.ui.ActionRow()
        row.add_item(_RegionSelect(cog))
        container.add_item(row)
        row2 = discord.ui.ActionRow()
        row2.add_item(_BackButton(cog))
        container.add_item(row2)
        self.add_item(container)


class _RegionSelect(discord.ui.Select):
    def __init__(self, cog):
        options = [discord.SelectOption(label=label, value=value) for label, value in REGIONS]
        super().__init__(placeholder="Pick a new region...", options=options, min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        region = self.values[0]
        await interaction.response.defer()
        await self.cog.dash_set_region(interaction.guild.id, region)
        await interaction.edit_original_response(view=await build_map_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"🌍 **Region changed to {_REGION_LABEL.get(region, region)}**"), ephemeral=True)


class MapChannelSelectLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay("## 📢 Change Channel\n-# Moves the map: deletes the old message, posts in the new channel."))
        row = discord.ui.ActionRow()
        row.add_item(_MoveChannelSelect(cog))
        container.add_item(row)
        row2 = discord.ui.ActionRow()
        row2.add_item(_BackButton(cog))
        container.add_item(row2)
        self.add_item(container)


class _MoveChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        super().__init__(placeholder="Pick the new channel...", min_values=1, max_values=1,
                         channel_types=[discord.ChannelType.text])
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        channel_id = self.values[0].id
        await interaction.response.defer()
        await self.cog.dash_set_channel(interaction.guild.id, channel_id)
        await interaction.edit_original_response(view=await build_map_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"📢 **Map moved to {_channel_name(interaction.guild, channel_id)}**"), ephemeral=True)


class MapDeleteConfirmLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(RED))
        container.add_item(discord.ui.TextDisplay(
            "## ⚠️ Delete the map?\n-# Removes all pins, the map message and any custom style. Cannot be undone."))
        row = discord.ui.ActionRow()
        row.add_item(_ConfirmDeleteButton(cog))
        row.add_item(_BackButton(cog))
        container.add_item(row)
        self.add_item(container)


class _ConfirmDeleteButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="Yes, delete", style=discord.ButtonStyle.danger)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        await interaction.response.defer()
        pins = await self.cog.dash_delete_map(interaction.guild.id)
        await interaction.edit_original_response(view=await build_map_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"🗑️ **Map deleted** ({pins} pin(s) removed)", RED), ephemeral=True)


class _BackButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=await build_map_dashboard(self.cog, interaction.guild.id))
