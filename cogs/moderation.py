import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timezone
from typing import Optional
import aiohttp
import asyncio

# Import timezone utilities
from core.timezone_util import get_current_time, get_current_timestamp, save_guild_timezone, get_guild_timezone

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "config/moderation_config.json"
        self.config = self.load_config()
        self.member_join_times = {}  # Store join times for leave duration calculation
        self.recently_banned_kicked = set()  # Track recently banned/kicked users

    def load_config(self) -> dict:
        """Load configuration from JSON file"""
        # Ensure config directory exists
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save_config(self):
        """Save configuration to JSON file"""
        try:
            # Ensure config directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except IOError:
            pass  # Fail silently if unable to save

    def get_guild_config(self, guild_id: int) -> dict:
        """Get configuration for specific guild"""
        return self.config.get(str(guild_id), {})

    def set_guild_config(self, guild_id: int, key: str, value):
        """Set configuration value for specific guild"""
        guild_str = str(guild_id)
        if guild_str not in self.config:
            self.config[guild_str] = {}
        self.config[guild_str][key] = value
        self.save_config()

    def create_dashboard_embed(self, guild_id: int) -> discord.Embed:
        """Create embed for moderation dashboard"""
        config = self.get_guild_config(guild_id)
        
        embed = discord.Embed(
            title="🛡️ Moderation Dashboard",
            color=0x5865f2
        )
        
        # Member logging configuration
        webhook_url = config.get('member_log_webhook')
        if webhook_url:
            embed.add_field(
                name="📋 Member Logging",
                value="✅ **Enabled**\nLogging joins, leaves, bans, kicks, and timeouts",
                inline=False
            )
        else:
            embed.add_field(
                name="📋 Member Logging",
                value="❌ **Disabled**\nClick 'Setup Member Log' to enable",
                inline=False
            )
        
        # Join role configuration
        join_role_id = config.get('join_role')
        if join_role_id:
            # We need the guild object to get the role
            guild = self.bot.get_guild(guild_id)
            if guild:
                role = guild.get_role(join_role_id)
                role_mention = role.mention if role else f"Role not found (ID: {join_role_id})"
            else:
                role_mention = f"Role ID: {join_role_id}"
            
            embed.add_field(
                name="👤 Auto Join Role",
                value=f"✅ **Enabled**\nAssigning role: {role_mention}",
                inline=False
            )
        else:
            embed.add_field(
                name="👤 Auto Join Role",
                value="❌ **Disabled**\nClick 'Setup Join Role' to enable",
                inline=False
            )
        
        embed.set_footer(text=f"Guild ID: {guild_id}")
        
        return embed

    def create_join_embed(self, member: discord.Member, role_assigned=None, role_name=None) -> discord.Embed:
        """Create embed for member join event"""
        embed = discord.Embed(
            title=f"{member.display_name} joined the server",
            color=0x00ff00  # Green for joins
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Calculate account age
        account_age = datetime.now(timezone.utc) - member.created_at
        days = account_age.days
        if days == 0:
            age_str = "Less than 1 day"
        elif days == 1:
            age_str = "1 day"
        else:
            age_str = f"{days} days"
        
        embed.add_field(name="Account Age", value=age_str, inline=True)
        
        # Add role assignment status if join role is configured
        if role_assigned is not None:
            if role_assigned:
                # Get role ID from the member's guild to use proper mention format
                config = self.get_guild_config(member.guild.id)
                role_id = config.get('join_role')
                if role_id:
                    embed.add_field(name="Auto Role", value=f"<@&{role_id}>", inline=True)
                else:
                    embed.add_field(name="Auto Role", value=f"Assigned: @{role_name}", inline=True)
            else:
                embed.add_field(name="Auto Role", value="❌ Failed to assign", inline=True)
        
        return embed

    def create_leave_embed(self, member: discord.Member, duration: Optional[str] = None) -> discord.Embed:
        """Create embed for member leave event"""
        embed = discord.Embed(
            title=f"{member.display_name} left the server",
            color=0xff0000  # Red for leaves
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        if duration:
            embed.add_field(name="Time on Server", value=duration, inline=True)
        
        
        return embed

    def create_ban_embed(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str], guild: discord.Guild) -> discord.Embed:
        """Create embed for ban event"""
        embed = discord.Embed(
            title=f"{user.display_name} was banned",
            color=0x8b0000  # Dark red for bans
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Banned by", value=f"<@{moderator.id}>", inline=True)
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=True)
        
        
        return embed

    def create_kick_embed(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str], guild: discord.Guild) -> discord.Embed:
        """Create embed for kick event"""
        embed = discord.Embed(
            title=f"{user.display_name} was kicked",
            color=0xff4500  # Orange red for kicks
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Kicked by", value=f"<@{moderator.id}>", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=True)
        
        
        
        return embed

    def create_timeout_embed(self, member: discord.Member, duration: str, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.Embed:
        """Create embed for timeout event"""
        embed = discord.Embed(
            title=f"{member.display_name} was timed out",
            color=0xffa500  # Orange for timeouts
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Duration", value=duration, inline=True)
        if moderator:
            embed.add_field(name="Timed out by", value=f"<@{moderator.id}>", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        
        return embed

    def create_unban_embed(self, user: discord.User, moderator: Optional[discord.Member], guild: discord.Guild) -> discord.Embed:
        """Create embed for unban event"""
        embed = discord.Embed(
            title=f"{user.display_name} was unbanned",
            color=0x90ee90  # Light green for unbans
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Unbanned by", value=f"<@{moderator.id}>", inline=True)
        
        
        
        return embed

    def calculate_duration(self, start_time: datetime) -> str:
        """Calculate duration between start time and now"""
        duration = datetime.now(timezone.utc) - start_time
        days = duration.days
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        if not parts:
            return "Less than 1 minute"
        
        return ", ".join(parts)

    async def send_log_message(self, guild_id: int, embed: discord.Embed):
        """Send log message to configured webhook"""
        config = self.get_guild_config(guild_id)
        webhook_url = config.get('member_log_webhook')
        
        if webhook_url:
            try:
                # Create a new aiohttp session for webhook requests
                async with aiohttp.ClientSession() as session:
                    webhook = discord.Webhook.from_url(webhook_url, session=session)
                    # Read pb.png file and send it with the webhook
                    with open('pb.png', 'rb') as f:
                        pb_file = discord.File(f, 'pb.png')
                        await webhook.send(embed=embed, file=pb_file, avatar_url="attachment://pb.png")
            except (discord.HTTPException, aiohttp.ClientError, FileNotFoundError):
                # Fallback to sending without profile picture if pb.png is not found
                try:
                    async with aiohttp.ClientSession() as session:
                        webhook = discord.Webhook.from_url(webhook_url, session=session)
                        await webhook.send(embed=embed)
                except (discord.HTTPException, aiohttp.ClientError):
                    pass  # Fail silently if webhook is invalid

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
                        
                        embed = self.create_kick_embed(entry.target, entry.user, entry.reason, guild)
                        await self.send_log_message(guild.id, embed)
                        return True
        except discord.Forbidden:
            pass
        return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join events"""
        # Store join time for duration calculation
        self.member_join_times[member.id] = datetime.now(timezone.utc)
        
        # Auto-assign role if configured
        config = self.get_guild_config(member.guild.id)
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
        
        # Send log message with role assignment status (removed role_id parameter)
        embed = self.create_join_embed(member, role_assigned=role_assigned, role_name=role_name)
        await self.send_log_message(member.guild.id, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave events"""
        # Check if this user was recently banned or kicked
        if member.id in self.recently_banned_kicked:
            self.recently_banned_kicked.discard(member.id)  # Remove from set
            return
        
        # Check for recent kick in audit logs
        if await self.check_for_kick(member.guild, member.id):
            return
        
        # Calculate duration on server
        duration = None
        if member.id in self.member_join_times:
            join_time = self.member_join_times[member.id]
            duration = self.calculate_duration(join_time)
            del self.member_join_times[member.id]
        
        # Send log message
        embed = self.create_leave_embed(member, duration)
        await self.send_log_message(member.guild.id, embed)

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
        
        embed = self.create_ban_embed(user, moderator, reason, guild)
        await self.send_log_message(guild.id, embed)

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
        
        embed = self.create_unban_embed(user, moderator, guild)
        await self.send_log_message(guild.id, embed)

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
                
                # Calculate timeout duration
                duration_delta = after.timed_out_until - datetime.now(timezone.utc)
                duration = self.calculate_duration(datetime.now(timezone.utc) - duration_delta)
                
                embed = self.create_timeout_embed(after, duration, moderator, reason)
                await self.send_log_message(after.guild.id, embed)

    @app_commands.command(name="mod_dashboard", description="Manage current moderation configuration")
    @app_commands.default_permissions(administrator=True)
    async def mod_dashboard(self, interaction: discord.Interaction):
        """Display moderation dashboard with interactive buttons"""
        # Import here to avoid circular imports
        from core.mod_views import ModerationDashboardView
        
        embed = self.create_dashboard_embed(interaction.guild.id)
        view = ModerationDashboardView(self)
        view.update_buttons(interaction.guild.id)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="clear", description="Delete a specified number of messages from the current channel")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def clear_messages(self, interaction: discord.Interaction, amount: int):
        """Clear specified number of messages from channel"""
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You need `Manage Messages` permission to use this command.", ephemeral=True)
            return
        
        if not interaction.guild.me.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ I don't have permission to delete messages in this channel.", ephemeral=True)
            return
        
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Amount must be between 1 and 100.", ephemeral=True)
            return
        
        # Defer the response since message deletion might take time
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get the channel where command was used
            channel = interaction.channel
            
            # Delete messages (Discord API limit is 100 messages at once)
            deleted = await channel.purge(limit=amount)
            deleted_count = len(deleted)
            
            # Create success embed
            embed = discord.Embed(
                title="🧹 Messages Cleared",
                description=f"Successfully deleted {deleted_count} message{'s' if deleted_count != 1 else ''} from {channel.mention}",
                color=0x00ff00
            )
            embed.set_footer(text=f"Cleared by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete messages in this channel.", ephemeral=True)
        except discord.HTTPException as e:
            if e.code == 50034:  # You can only bulk delete messages that are under 14 days old
                await interaction.followup.send("❌ Cannot delete messages older than 14 days. Try with a smaller number.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An error occurred while deleting messages.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
