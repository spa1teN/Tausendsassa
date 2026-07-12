import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import aiohttp
import asyncio

# Import timezone utilities
from core.timezone_util import get_current_time, get_current_timestamp, save_guild_timezone, get_guild_timezone

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log = bot.get_cog_logger("moderation")
        self.member_join_times = {}  # Store join times for leave duration calculation
        self.recently_banned_kicked = set()  # Track recently banned/kicked users
        self._config_cache: Dict[int, Dict[str, Any]] = {}  # In-memory cache for config

    async def get_guild_config(self, guild_id: int) -> dict:
        """Get configuration for specific guild from database"""
        # Check cache first
        if guild_id in self._config_cache:
            return self._config_cache[guild_id]

        if self.bot.db:
            config = await self.bot.db.moderation.get_guild_config(guild_id)
            self._config_cache[guild_id] = config
            return config
        return {}

    async def set_guild_config(self, guild_id: int, key: str, value):
        """Set configuration value for specific guild in database"""
        if self.bot.db:
            await self.bot.db.moderation.save_guild_config(guild_id, key, value)
            # Update cache
            if guild_id not in self._config_cache:
                self._config_cache[guild_id] = {}
            self._config_cache[guild_id][key] = value

    async def clear_guild_config_key(self, guild_id: int, key: str):
        """Clear a specific config key for a guild"""
        if self.bot.db:
            if key == 'member_log_webhook':
                await self.bot.db.moderation.clear_webhook(guild_id)
            elif key == 'join_role':
                await self.bot.db.moderation.clear_join_role(guild_id)
            # Update cache
            if guild_id in self._config_cache and key in self._config_cache[guild_id]:
                del self._config_cache[guild_id][key]

    def invalidate_cache(self, guild_id: int):
        """Invalidate the cache for a guild"""
        if guild_id in self._config_cache:
            del self._config_cache[guild_id]

    def _build_log_view(self, color: int, body: str, avatar_url: str) -> discord.ui.LayoutView:
        """Compact CV2 member-log message: bold first line, -# detail lines,
        avatar as thumbnail."""
        container = discord.ui.Container(accent_colour=discord.Colour(color))
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(body),
            accessory=discord.ui.Thumbnail(media=avatar_url),
        ))
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    def build_join_view(self, member: discord.Member, role_assigned=None, role_name=None, role_id=None) -> discord.ui.LayoutView:
        """Log message for member join event"""
        user_link = f"[{member.display_name}](https://discord.com/users/{member.id})"
        created_unix = int(member.created_at.timestamp())
        body = f"**{user_link} joined the server**\n-# Account created: <t:{created_unix}:R>"

        # Add role assignment status if join role is configured
        if role_assigned is not None:
            if role_assigned:
                if role_id:
                    body += f"\n-# Auto Role: <@&{role_id}>"
                else:
                    body += f"\n-# Auto Role: Assigned: @{role_name}"
            else:
                body += "\n-# Auto Role: ❌ Failed to assign"

        return self._build_log_view(0x00FF00, body, member.display_avatar.url)

    def build_leave_view(self, member: discord.Member, join_time: Optional[datetime] = None) -> discord.ui.LayoutView:
        """Log message for member leave event"""
        user_link = f"[{member.display_name}](https://discord.com/users/{member.id})"
        body = f"**{user_link} left the server**"
        if join_time:
            join_unix = int(join_time.timestamp())
            body += f"\n-# Joined: <t:{join_unix}:R>"
        return self._build_log_view(0xFF0000, body, member.display_avatar.url)

    def build_ban_view(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.ui.LayoutView:
        """Log message for ban event"""
        user_link = f"[{user.display_name}](https://discord.com/users/{user.id})"
        body = f"**{user_link} was banned**"
        if moderator:
            mod_link = f"[{moderator.display_name}](https://discord.com/users/{moderator.id})"
            body += f"\n-# Banned by: {mod_link}"
        if reason:
            body += f"\n-# Reason: {reason}"
        return self._build_log_view(0x8B0000, body, user.display_avatar.url)

    def build_kick_view(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.ui.LayoutView:
        """Log message for kick event"""
        user_link = f"[{user.display_name}](https://discord.com/users/{user.id})"
        body = f"**{user_link} was kicked**"
        if moderator:
            mod_link = f"[{moderator.display_name}](https://discord.com/users/{moderator.id})"
            body += f"\n-# Kicked by: {mod_link}"
        if reason:
            body += f"\n-# Reason: {reason}"
        return self._build_log_view(0xFF4500, body, user.display_avatar.url)

    def build_timeout_view(self, member: discord.Member, timed_out_until: datetime, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.ui.LayoutView:
        """Log message for timeout event"""
        user_link = f"[{member.display_name}](https://discord.com/users/{member.id})"
        timeout_unix = int(timed_out_until.timestamp())
        body = f"**{user_link} was timed out**\n-# Ends: <t:{timeout_unix}:R>"
        if moderator:
            mod_link = f"[{moderator.display_name}](https://discord.com/users/{moderator.id})"
            body += f"\n-# Timed out by: {mod_link}"
        if reason:
            body += f"\n-# Reason: {reason}"
        return self._build_log_view(0xFFA500, body, member.display_avatar.url)

    def build_unban_view(self, user: discord.User, moderator: Optional[discord.Member]) -> discord.ui.LayoutView:
        """Log message for unban event"""
        user_link = f"[{user.display_name}](https://discord.com/users/{user.id})"
        body = f"**{user_link} was unbanned**"
        if moderator:
            mod_link = f"[{moderator.display_name}](https://discord.com/users/{moderator.id})"
            body += f"\n-# Unbanned by: {mod_link}"
        return self._build_log_view(0x90EE90, body, user.display_avatar.url)

    async def send_log_message(
        self,
        guild_id: int,
        view: discord.ui.LayoutView,
        action: str = None,
        target_id: int = None,
        moderator_id: int = None,
        reason: str = None,
    ):
        """Persist the action, then send the CV2 log message to the configured webhook.

        The view carries no interactive components (link-only), so plain channel
        webhooks accept it (discord.py enforces this via view.is_dispatchable())."""
        if action and self.bot.db:
            try:
                await self.bot.db.moderation.log_action(guild_id, action, target_id, moderator_id, reason)
            except Exception:
                self.log.warning(f"Failed to persist moderation action '{action}' for guild {guild_id}", exc_info=True)

        config = await self.get_guild_config(guild_id)
        webhook_url = config.get('member_log_webhook')

        if not webhook_url:
            return

        try:
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                await webhook.send(view=view)
        except (discord.HTTPException, aiohttp.ClientError) as e:
            self.log.warning(f"Member-log webhook failed for guild {guild_id}: {e}")

    async def check_for_kick(self, guild: discord.Guild, user_id: int):
        """Check audit logs for recent kick events"""
        try:
            await asyncio.sleep(0.5)  # Small delay to ensure audit log is updated
            async for entry in guild.audit_logs(action=discord.AuditLogAction.kick, limit=5):
                if entry.target and entry.target.id == user_id:
                    # Check if this kick happened recently (within last 10 seconds)
                    time_diff = datetime.now(timezone.utc) - entry.created_at
                    if time_diff.total_seconds() < 10:
                        # Add to banned/kicked set and send kick embed
                        self.recently_banned_kicked.add(user_id)

                        view = self.build_kick_view(entry.target, entry.user, entry.reason)
                        await self.send_log_message(
                            guild.id, view, action="kick",
                            target_id=entry.target.id,
                            moderator_id=entry.user.id if entry.user else None,
                            reason=entry.reason,
                        )
                        return True
        except (discord.Forbidden, discord.NotFound):
            pass
        return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join events"""
        # Store join time for duration calculation
        self.member_join_times[member.id] = datetime.now(timezone.utc)

        # Auto-assign role if configured
        config = await self.get_guild_config(member.guild.id)
        join_role_id = config.get('join_role')

        role_assigned = None
        role_name = None

        if join_role_id:
            role = member.guild.get_role(join_role_id)
            if role:
                role_name = role.name
                try:
                    await member.add_roles(role, reason="Auto-assigned join role")
                    role_assigned = True
                except discord.Forbidden:
                    role_assigned = False  # Bot doesn't have permission
            else:
                role_assigned = False  # Role not found

        # Send log message with role assignment status
        view = self.build_join_view(member, role_assigned=role_assigned, role_name=role_name, role_id=join_role_id)
        await self.send_log_message(member.guild.id, view, action="join", target_id=member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave events"""
        # Check if this user was recently banned or kicked
        if member.id in self.recently_banned_kicked:
            self.recently_banned_kicked.discard(member.id)  # Remove from set
            return

        # Check for recent kick in audit logs
        try:
            if await self.check_for_kick(member.guild, member.id):
                return
        except discord.NotFound:
            return  # Bot was removed from the guild

        # Look up when they joined (tracked in-memory) to show it in the log
        join_time = self.member_join_times.pop(member.id, None)

        # Send log message
        view = self.build_leave_view(member, join_time=join_time)
        try:
            await self.send_log_message(member.guild.id, view, action="leave", target_id=member.id)
        except discord.NotFound:
            pass  # Guild no longer accessible

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Handle member ban events"""
        # Add user to recently banned set to prevent leave message
        self.recently_banned_kicked.add(user.id)

        # Get ban information
        try:
            ban = await guild.fetch_ban(user)
            reason = ban.reason
        except discord.NotFound:
            reason = None

        # Try to get moderator from audit log
        moderator = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass

        view = self.build_ban_view(user, moderator, reason)
        await self.send_log_message(
            guild.id, view, action="ban",
            target_id=user.id,
            moderator_id=moderator.id if moderator else None,
            reason=reason,
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """Handle member unban events"""
        # Try to get moderator from audit log
        moderator = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    moderator = entry.user
                    break
        except discord.Forbidden:
            pass

        view = self.build_unban_view(user, moderator)
        await self.send_log_message(
            guild.id, view, action="unban",
            target_id=user.id,
            moderator_id=moderator.id if moderator else None,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member update events (for timeouts)"""
        # Check if timeout status changed
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:  # Member was timed out
                # Try to get moderator and reason from audit log
                moderator = None
                reason = None
                try:
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                        if entry.target.id == after.id and hasattr(entry.changes, 'after') and hasattr(entry.changes.after, 'timed_out_until'):
                            moderator = entry.user
                            reason = entry.reason
                            break
                except discord.Forbidden:
                    pass

                view = self.build_timeout_view(after, after.timed_out_until, moderator, reason)
                await self.send_log_message(
                    after.guild.id, view, action="timeout",
                    target_id=after.id,
                    moderator_id=moderator.id if moderator else None,
                    reason=reason,
                )

    @app_commands.command(name="mod_dashboard", description="Manage current moderation configuration")
    @app_commands.default_permissions(administrator=True)
    async def mod_dashboard(self, interaction: discord.Interaction):
        """Display moderation dashboard (Components V2)."""
        from core.mod_views import build_dashboard_view

        view = await build_dashboard_view(self, interaction.guild.id)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="clear", description="Delete a specified number of messages from the current channel")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def clear_messages(self, interaction: discord.Interaction, amount: int):
        """Clear specified number of messages from channel"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need `Manage Messages` permission to use this command.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message("I don't have permission to delete messages in this channel.", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await interaction.response.send_message("Amount must be between 1 and 100.", ephemeral=True)
            return

        # Defer the response since message deletion might take time
        await interaction.response.defer(ephemeral=True)

        try:
            # Get the channel where command was used
            channel = interaction.channel

            # Delete messages (Discord API limit is 100 messages at once)
            deleted = await channel.purge(limit=amount)
            deleted_count = len(deleted)

            from core.mod_views import notice_view
            plural = "s" if deleted_count != 1 else ""
            await interaction.followup.send(
                view=notice_view(f"🧹 **{deleted_count} message{plural} deleted** in {channel.mention}", 0xED4245),
                ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
        except discord.HTTPException as e:
            if e.code == 50034:  # You can only bulk delete messages that are under 14 days old
                await interaction.followup.send("Cannot delete messages older than 14 days. Try with a smaller number.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred while deleting messages.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
