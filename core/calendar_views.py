"""Components-V2 dashboard for calendar management.

Consolidates the former /cal_add, /cal_remove and /cal_config commands into a
single /calendar dashboard: one section per calendar (with a Manage button that
opens an edit/remove detail view) plus an Add button. The add screen gathers all
inputs on one CV2 message — a modal button for the text fields (id/url/filters)
and three selects for text-channel/voice-channel/reminder-role — because a modal
cannot host channel or role pickers.

All state that the dashboard message can be edited into must itself be a CV2
LayoutView (a CV2 message can never be edited back to content/embeds).
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


async def build_calendar_dashboard(cog, guild_id: int) -> "CalendarDashboardLayout":
    calendars = await cog.get_guild_calendars(guild_id)
    guild = cog.bot.get_guild(guild_id)
    return CalendarDashboardLayout(cog, guild, list(calendars.values()))


def _channel_name(guild: Optional[discord.Guild], channel_id: int) -> str:
    ch = guild.get_channel(channel_id) if guild else None
    return f"#{ch.name}" if ch else f"channel {channel_id}"


# ── Dashboard ───────────────────────────────────────────────────────

class CalendarDashboardLayout(discord.ui.LayoutView):
    def __init__(self, cog, guild: Optional[discord.Guild], calendars: List):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(f"## 📅 Calendar Dashboard\n-# {len(calendars)} calendar(s) configured"))
        container.add_item(discord.ui.Separator())

        if not calendars:
            container.add_item(discord.ui.TextDisplay("-# No calendars configured yet. Use **Add Calendar** below."))
        else:
            # A select scales to many calendars with a constant component count; a
            # Section per calendar would blow the 40-component CV2 message limit.
            lines = []
            for cal in calendars[:25]:
                n_filters = len(cal.blacklist or []) + len(cal.whitelist or [])
                lines.append(f"• **{cal.calendar_id}** → {_channel_name(guild, cal.text_channel_id)} · "
                             f"{n_filters} filter term{'s' if n_filters != 1 else ''}")
            summary = "\n".join(lines)[:3800]
            if len(calendars) > 25:
                summary += f"\n-# …and {len(calendars) - 25} more"
            container.add_item(discord.ui.TextDisplay(summary))
            row_sel = discord.ui.ActionRow()
            row_sel.add_item(_ManageSelect(cog, calendars))
            container.add_item(row_sel)

        row = discord.ui.ActionRow()
        row.add_item(_AddButton(cog))
        container.add_item(row)
        self.add_item(container)


class _ManageSelect(discord.ui.Select):
    def __init__(self, cog, calendars: List):
        options = []
        for cal in calendars[:25]:
            sync = "synced" if getattr(cal, "last_sync", None) else "never synced"
            options.append(discord.SelectOption(label=cal.calendar_id[:100], value=cal.calendar_id[:100], description=sync[:100]))
        super().__init__(placeholder="Manage a calendar…", options=options, min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        calendars = await self.cog.get_guild_calendars(interaction.guild.id)
        cal = calendars.get(self.values[0])
        if not cal:
            await interaction.response.edit_message(view=await build_calendar_dashboard(self.cog, interaction.guild.id))
            return
        await interaction.response.edit_message(view=CalendarDetailLayout(self.cog, interaction.guild, cal))


class _AddButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="➕ Add Calendar", style=discord.ButtonStyle.green)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        await interaction.response.edit_message(view=CalendarAddLayout(self.cog))


# ── Per-calendar detail (edit filters / remove) ─────────────────────

class CalendarDetailLayout(discord.ui.LayoutView):
    def __init__(self, cog, guild: Optional[discord.Guild], cal):
        super().__init__(timeout=300)
        self.cog = cog
        self.cal = cal
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        bl = ", ".join(f"`{t}`" for t in (cal.blacklist or [])) or "None"
        wl = ", ".join(f"`{t}`" for t in (cal.whitelist or [])) or "None"
        role = guild.get_role(cal.reminder_role_id) if (guild and cal.reminder_role_id) else None
        lines = [
            f"## 📅 {cal.calendar_id}",
            f"-# Text: {_channel_name(guild, cal.text_channel_id)} · Voice: {_channel_name(guild, cal.voice_channel_id)}",
            f"-# iCal: {cal.ical_url}",
            f"**Blacklist:** {bl}",
            f"**Whitelist:** {wl}",
            f"**Reminder role:** {role.mention if role else 'none'}",
        ]
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))
        row = discord.ui.ActionRow()
        row.add_item(_EditFiltersButton(cog, cal))
        row.add_item(_RemoveButton(cog, cal.calendar_id))
        row.add_item(_BackButton(cog))
        container.add_item(row)
        self.add_item(container)


class _EditFiltersModal(discord.ui.Modal):
    def __init__(self, cog, cal):
        super().__init__(title=f"Edit filters: {cal.calendar_id}"[:45])
        self.cog = cog
        self.cal = cal
        self.blacklist_field = discord.ui.TextInput(
            label="Blacklist (comma separated)", required=False, max_length=1000,
            style=discord.TextStyle.paragraph, default=", ".join(cal.blacklist or []))
        self.whitelist_field = discord.ui.TextInput(
            label="Whitelist (comma separated)", required=False, max_length=1000,
            style=discord.TextStyle.paragraph, default=", ".join(cal.whitelist or []))
        self.add_item(self.blacklist_field)
        self.add_item(self.whitelist_field)

    async def on_submit(self, interaction: discord.Interaction):
        new_bl = [t.strip() for t in self.blacklist_field.value.split(",") if t.strip()]
        new_wl = [t.strip() for t in self.whitelist_field.value.split(",") if t.strip()]
        if self.cog.bot.db:
            await self.cog.bot.db.calendars.update_filters(self.cal.id, blacklist=new_bl, whitelist=new_wl)
        self.cal.blacklist = new_bl
        self.cal.whitelist = new_wl
        # Refresh the detail view in place so the new filters show immediately.
        await interaction.response.edit_message(view=CalendarDetailLayout(self.cog, interaction.guild, self.cal))
        await interaction.followup.send(
            view=notice_view("✅ **Filters updated**\n-# Changes take effect at the next hourly sync."),
            ephemeral=True)


class _EditFiltersButton(discord.ui.Button):
    def __init__(self, cog, cal):
        super().__init__(label="✏️ Edit Filters", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.cal = cal

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_EditFiltersModal(self.cog, self.cal))


class _RemoveButton(discord.ui.Button):
    def __init__(self, cog, calendar_id: str):
        super().__init__(label="🗑️ Remove", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.calendar_id = calendar_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=CalendarRemoveConfirmLayout(self.cog, self.calendar_id))


class _BackButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=await build_calendar_dashboard(self.cog, interaction.guild.id))


class CalendarRemoveConfirmLayout(discord.ui.LayoutView):
    def __init__(self, cog, calendar_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.calendar_id = calendar_id
        container = discord.ui.Container(accent_colour=discord.Colour(RED))
        container.add_item(discord.ui.TextDisplay(
            f"## ⚠️ Remove `{calendar_id}`?\n-# This deletes the calendar, its Discord events and the last summary message."))
        row = discord.ui.ActionRow()
        row.add_item(_ConfirmRemoveButton(cog, calendar_id))
        row.add_item(_BackButton(cog))
        container.add_item(row)
        self.add_item(container)


class _ConfirmRemoveButton(discord.ui.Button):
    def __init__(self, cog, calendar_id: str):
        super().__init__(label="Confirm remove", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.calendar_id = calendar_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        ok = await self.cog.remove_calendar(interaction.guild.id, self.calendar_id)
        await interaction.response.edit_message(view=await build_calendar_dashboard(self.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(
                f"🗑️ **Removed `{self.calendar_id}`**" if ok else f"❌ **Failed to remove `{self.calendar_id}`**",
                RED),
            ephemeral=True)


# ── Add flow (single screen: modal for text + 3 selects) ────────────

class CalendarAddLayout(discord.ui.LayoutView):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        self.calendar_id: Optional[str] = None
        self.ical_url: Optional[str] = None
        self.blacklist: List[str] = []
        self.whitelist: List[str] = []
        self.text_channel_id: Optional[int] = None
        self.voice_channel_id: Optional[int] = None
        self.reminder_role_id: Optional[int] = None

        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay(
            "## 📅 Add Calendar\n-# 1) **Set ID & URL** (button)  2) pick text + voice channel  "
            "3) optional reminder role  4) **Create**"))
        row_t = discord.ui.ActionRow()
        row_t.add_item(_AddChannelSelect(self, "text"))
        container.add_item(row_t)
        row_v = discord.ui.ActionRow()
        row_v.add_item(_AddChannelSelect(self, "voice"))
        container.add_item(row_v)
        row_r = discord.ui.ActionRow()
        row_r.add_item(_AddRoleSelect(self))
        container.add_item(row_r)
        row_b = discord.ui.ActionRow()
        row_b.add_item(_AddDetailsButton(self))
        row_b.add_item(_AddCreateButton(self))
        row_b.add_item(_BackButton(cog))
        container.add_item(row_b)
        self.add_item(container)


class _AddDetailsModal(discord.ui.Modal):
    def __init__(self, parent: "CalendarAddLayout"):
        super().__init__(title="Calendar ID, URL & filters")
        self.layout = parent
        self.id_field = discord.ui.TextInput(label="Calendar ID (unique)", required=True, max_length=80,
                                             default=parent.calendar_id or "")
        self.url_field = discord.ui.TextInput(label="iCal URL (http/https)", required=True, max_length=500,
                                              default=parent.ical_url or "")
        self.bl_field = discord.ui.TextInput(label="Blacklist (comma separated)", required=False, max_length=1000,
                                             style=discord.TextStyle.paragraph, default=", ".join(parent.blacklist))
        self.wl_field = discord.ui.TextInput(label="Whitelist (comma separated)", required=False, max_length=1000,
                                             style=discord.TextStyle.paragraph, default=", ".join(parent.whitelist))
        for f in (self.id_field, self.url_field, self.bl_field, self.wl_field):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        self.layout.calendar_id = self.id_field.value.strip()
        self.layout.ical_url = self.url_field.value.strip()
        self.layout.blacklist = [t.strip() for t in self.bl_field.value.split(",") if t.strip()]
        self.layout.whitelist = [t.strip() for t in self.wl_field.value.split(",") if t.strip()]
        await interaction.response.defer()  # silent ack; selections stay visible


class _AddDetailsButton(discord.ui.Button):
    def __init__(self, parent: "CalendarAddLayout"):
        super().__init__(label="📝 Set ID & URL", style=discord.ButtonStyle.primary)
        self.layout = parent

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_AddDetailsModal(self.layout))


class _AddChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, parent: "CalendarAddLayout", kind: str):
        types = [discord.ChannelType.text] if kind == "text" else [discord.ChannelType.voice]
        super().__init__(
            placeholder=f"Select {'text channel for summaries' if kind == 'text' else 'voice channel for events'}...",
            min_values=1, max_values=1, channel_types=types)
        self.layout = parent
        self.kind = kind

    async def callback(self, interaction: discord.Interaction):
        if self.kind == "text":
            self.layout.text_channel_id = self.values[0].id
        else:
            self.layout.voice_channel_id = self.values[0].id
        await interaction.response.defer()


class _AddRoleSelect(discord.ui.RoleSelect):
    def __init__(self, parent: "CalendarAddLayout"):
        super().__init__(placeholder="Optional: reminder role to ping...", min_values=0, max_values=1)
        self.layout = parent

    async def callback(self, interaction: discord.Interaction):
        self.layout.reminder_role_id = self.values[0].id if self.values else None
        await interaction.response.defer()


class _AddCreateButton(discord.ui.Button):
    def __init__(self, parent: "CalendarAddLayout"):
        super().__init__(label="✅ Create", style=discord.ButtonStyle.green)
        self.layout = parent

    async def callback(self, interaction: discord.Interaction):
        p = self.layout
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions.", ephemeral=True)
            return
        missing = []
        if not p.calendar_id or not p.ical_url:
            missing.append("ID & URL (use **Set ID & URL**)")
        if not p.text_channel_id:
            missing.append("text channel")
        if not p.voice_channel_id:
            missing.append("voice channel")
        if missing:
            await interaction.response.send_message("❌ Still missing: " + ", ".join(missing), ephemeral=True)
            return

        await interaction.response.defer()
        calendar, error = await p.cog.create_calendar_validated(
            interaction.guild.id, p.calendar_id, p.text_channel_id, p.voice_channel_id,
            p.ical_url, p.blacklist, p.whitelist, p.reminder_role_id)
        if error:
            await interaction.followup.send(view=notice_view(f"❌ {error}", RED), ephemeral=True)
            return
        await interaction.edit_original_response(view=await build_calendar_dashboard(p.cog, interaction.guild.id))
        await interaction.followup.send(
            view=notice_view(f"✅ **Calendar `{p.calendar_id}` added**\n-# First sync running now; then hourly."),
            ephemeral=True)
