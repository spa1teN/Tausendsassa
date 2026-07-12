"""Components-V2 views for the moderation dashboard.

The dashboard message is a CV2 LayoutView from the start; because a CV2 message
can never be edited back to content/embeds, every state it can be edited into
(channel picker, role picker, refreshed dashboard) must be a LayoutView too.

Ported from the previous embed + ui.View dashboard (see git history); same two
features — member logging via a per-guild webhook and an auto join role — and
the same toggle semantics. The member-log *messages* themselves stay embeds
(see cogs/moderation.py); only this management UI is CV2.
"""

import discord
from typing import Optional
import aiohttp

BLURPLE = 0x5865F2


def notice_view(text: str, color: int = 0x57F287) -> discord.ui.LayoutView:
    """Small single-line CV2 container used for success/error notices."""
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour(color))
    container.add_item(discord.ui.TextDisplay(text))
    view.add_item(container)
    return view


async def build_dashboard_view(moderation_cog, guild_id: int) -> "ModerationDashboardLayout":
    config = await moderation_cog.get_guild_config(guild_id)
    guild = moderation_cog.bot.get_guild(guild_id)
    return ModerationDashboardLayout(moderation_cog, guild, config)


def _role_mention(guild: Optional[discord.Guild], role_id: int) -> str:
    if guild:
        role = guild.get_role(role_id)
        return role.mention if role else f"Role not found (ID: {role_id})"
    return f"Role ID: {role_id}"


class _ToggleButton(discord.ui.Button):
    """Per-feature accessory button: sets up the feature when unconfigured,
    disables it when configured (same toggle semantics as the old dashboard)."""

    def __init__(self, moderation_cog, kind: str, configured: bool):
        super().__init__(
            label="Disable" if configured else "Setup",
            style=discord.ButtonStyle.red if configured else discord.ButtonStyle.green,
        )
        self.moderation_cog = moderation_cog
        self.kind = kind
        self.configured = configured

    async def callback(self, interaction: discord.Interaction):
        cog = self.moderation_cog

        if self.kind == "member_log":
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You need `Manage Server` permission to use this feature.", ephemeral=True)
                return
            if self.configured:
                config = await cog.get_guild_config(interaction.guild.id)
                webhook_url = config.get('member_log_webhook')
                if webhook_url:
                    try:
                        async with aiohttp.ClientSession() as session:
                            webhook = discord.Webhook.from_url(webhook_url, session=session)
                            await webhook.delete(reason="Member logging disabled")
                    except (discord.HTTPException, aiohttp.ClientError):
                        pass  # Webhook might already be deleted
                await cog.clear_guild_config_key(interaction.guild.id, 'member_log_webhook')
                await self._back_to_dashboard(interaction)
                await interaction.followup.send(
                    view=notice_view("🗑️ **Member Logging Disabled**\n-# Member logging has been disabled and the webhook deleted.", 0xED4245),
                    ephemeral=True)
            else:
                await interaction.response.edit_message(view=ChannelSelectLayout(cog))
            return

        if self.kind == "join_role":
            if not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message(
                    "❌ You need `Manage Roles` permission to use this feature.", ephemeral=True)
                return
            if self.configured:
                await cog.clear_guild_config_key(interaction.guild.id, 'join_role')
                await self._back_to_dashboard(interaction)
                await interaction.followup.send(
                    view=notice_view("🗑️ **Auto Join Role Disabled**\n-# Auto role assignment for new members has been disabled.", 0xED4245),
                    ephemeral=True)
            else:
                await interaction.response.edit_message(view=RoleSelectLayout(cog))

    async def _back_to_dashboard(self, interaction: discord.Interaction):
        view = await build_dashboard_view(self.moderation_cog, interaction.guild.id)
        await interaction.response.edit_message(view=view)


class ModerationDashboardLayout(discord.ui.LayoutView):
    """Dashboard main panel: one section per feature with its status line and
    the setup/disable button as accessory."""

    def __init__(self, moderation_cog, guild: Optional[discord.Guild], config: dict):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay("## 🛡️ Moderation Dashboard"))
        container.add_item(discord.ui.Separator())

        webhook_url = config.get('member_log_webhook')
        member_log_status = ("✅ Enabled — logging joins, leaves, bans, kicks, and timeouts"
                             if webhook_url else "❌ Disabled")
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"**📋 Member Logging**\n-# {member_log_status}"),
            accessory=_ToggleButton(moderation_cog, "member_log", bool(webhook_url)),
        ))

        join_role_id = config.get('join_role')
        join_role_status = (f"✅ Enabled — assigning {_role_mention(guild, join_role_id)}"
                            if join_role_id else "❌ Disabled")
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"**👤 Auto Join Role**\n-# {join_role_status}"),
            accessory=_ToggleButton(moderation_cog, "join_role", bool(join_role_id)),
        ))

        self.add_item(container)


class _MemberLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, moderation_cog):
        super().__init__(
            placeholder="Select a channel for member logging...",
            min_values=1, max_values=1,
            channel_types=[discord.ChannelType.text],
        )
        self.moderation_cog = moderation_cog

    async def callback(self, interaction: discord.Interaction):
        cog = self.moderation_cog
        selected_channel = self.values[0]
        channel = interaction.guild.get_channel(selected_channel.id)

        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return

        bot_permissions = channel.permissions_for(interaction.guild.me)
        if not bot_permissions.manage_webhooks:
            await interaction.response.send_message(
                "❌ I don't have permission to create webhooks in that channel.", ephemeral=True)
            return

        try:
            webhook = await channel.create_webhook(
                name="Member Logger",
                avatar=await cog.bot.user.display_avatar.read(),
                reason="Moderation logging setup",
            )
            await cog.set_guild_config(interaction.guild.id, 'member_log_webhook', webhook.url)

            view = await build_dashboard_view(cog, interaction.guild.id)
            await interaction.response.edit_message(view=view)
            await interaction.followup.send(
                view=notice_view(f"✅ **Member Logging Enabled**\n-# Successfully configured member logging for {channel.mention}!"),
                ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to create webhook: {str(e)}", ephemeral=True)


class ChannelSelectLayout(discord.ui.LayoutView):
    def __init__(self, moderation_cog):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay("**📋 Member Logging**\n-# Select a channel for member logging:"))
        row = discord.ui.ActionRow()
        row.add_item(_MemberLogChannelSelect(moderation_cog))
        container.add_item(row)
        self.add_item(container)


class _JoinRoleSelect(discord.ui.RoleSelect):
    def __init__(self, moderation_cog):
        super().__init__(placeholder="Select a role to assign to new members...", min_values=1, max_values=1)
        self.moderation_cog = moderation_cog

    async def callback(self, interaction: discord.Interaction):
        cog = self.moderation_cog
        role = self.values[0]

        # Bot must sit above the role to be able to assign it.
        bot_member = interaction.guild.get_member(cog.bot.user.id)
        if role >= bot_member.top_role:
            await interaction.response.send_message(
                "❌ I cannot assign this role as it's higher than or equal to my highest role.",
                ephemeral=True)
            return

        await cog.set_guild_config(interaction.guild.id, 'join_role', role.id)

        view = await build_dashboard_view(cog, interaction.guild.id)
        await interaction.response.edit_message(view=view)
        await interaction.followup.send(
            view=notice_view(f"✅ **Auto Join Role Enabled**\n-# New members will automatically receive the {role.mention} role when they join."),
            ephemeral=True)


class RoleSelectLayout(discord.ui.LayoutView):
    def __init__(self, moderation_cog):
        super().__init__(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(BLURPLE))
        container.add_item(discord.ui.TextDisplay("**👤 Auto Join Role**\n-# Select a role to assign to new members:"))
        row = discord.ui.ActionRow()
        row.add_item(_JoinRoleSelect(moderation_cog))
        container.add_item(row)
        self.add_item(container)
