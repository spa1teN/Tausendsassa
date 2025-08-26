import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import aiohttp
from datetime import datetime, timezone
from typing import Optional

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.member_join_times = {}  # Store join times for leave duration calculation
        self.log = bot.get_cog_logger("mod")
        
    def get_config_path(self, guild_id: int) -> str:
        """Get configuration file path for specific guild"""
        config_dir = f"config/{guild_id}"
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "moderation_config.json")

    def load_config(self, guild_id: int) -> dict:
        """Load configuration from JSON file for specific guild"""
        config_path = self.get_config_path(guild_id)
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save_config(self, guild_id: int, config: dict):
        """Save configuration to JSON file for specific guild"""
        try:
            config_path = self.get_config_path(guild_id)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except IOError:
            pass  # Fail silently if unable to save

    def get_guild_config(self, guild_id: int) -> dict:
        """Get configuration for specific guild"""
        return self.load_config(guild_id)

    def set_guild_config(self, guild_id: int, key: str, value):
        """Set configuration value for specific guild"""
        config = self.load_config(guild_id)
        config[key] = value
        self.save_config(guild_id, config)

    def create_join_embed(self, member: discord.Member) -> discord.Embed:
        """Create embed for member join event"""
        embed = discord.Embed(
            description=f"<@{member.id}> joined the server",
            color=0x00ff00,  # Green for joins
            timestamp=datetime.now(timezone.utc)
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
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.set_footer(text=f"Member #{len(member.guild.members)}")
        
        return embed

    def create_leave_embed(self, member: discord.Member, duration: Optional[str] = None) -> discord.Embed:
        """Create embed for member leave event"""
        embed = discord.Embed(
            description=f"{member.display_name} left the server",
            color=0xff0000,  # Red for leaves
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        if duration:
            embed.add_field(name="Time on Server", value=duration, inline=True)
        
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.set_footer(text=f"Members remaining: {len(member.guild.members) - 1}")
        
        return embed

    def create_ban_embed(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.Embed:
        """Create embed for ban event"""
        embed = discord.Embed(
            description=f"{user.display_name} was banned",
            color=0x8b0000,  # Dark red for bans
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Banned by", value=moderator.display_name, inline=True)
        
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=True)
        embed.add_field(name="User ID", value=str(user.id), inline=True)
        
        return embed

    def create_kick_embed(self, user: discord.User, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.Embed:
        """Create embed for kick event"""
        embed = discord.Embed(
            description=f"{user.display_name} was kicked",
            color=0xff4500,  # Orange red for kicks
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Kicked by", value=moderator.display_name, inline=True)
        
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=True)
        embed.add_field(name="User ID", value=str(user.id), inline=True)
        
        return embed

    def create_timeout_embed(self, member: discord.Member, duration: str, moderator: Optional[discord.Member], reason: Optional[str]) -> discord.Embed:
        """Create embed for timeout event"""
        embed = discord.Embed(
            description=f"<@{member.id}> was timed out",
            color=0xffa500,  # Orange for timeouts
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Duration", value=duration, inline=True)
        if moderator:
            embed.add_field(name="Timed out by", value=moderator.display_name, inline=True)
        
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        
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
        """Send log message to configured channel"""
        config = self.get_guild_config(guild_id)
        webhook_url = config.get('member_log_webhook')
        username = "Member Logger"
        avatar_url = "https://cdn.discordapp.com/attachments/1398436953422037013/1409705617131835434/17800528-benutzer-einfache-flache-symbolvektorillustration-vektor.jpg?ex=68ae5a2a&is=68ad08aa&hm=e36a3fc3f8c38417ae251ed852deceec54f1aabe867119c64200d1393fa7870e&"
        
        if webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    webhook = discord.Webhook.from_url(webhook_url, session=session)
                    await webhook.send(username=username, avatar_url=avatar_url, embed=embed)
            except (discord.HTTPException, aiohttp.ClientError):
                self.log.error("Failed to send mod-log embed")
                pass  # Fail silently if webhook is invalid

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join events"""
        # Store join time for duration calculation
        self.member_join_times[member.id] = datetime.now(timezone.utc)
        
        # Send log message
        embed = self.create_join_embed(member)
        await self.send_log_message(member.guild.id, embed)
        
        # Auto-assign role if configured
        config = self.get_guild_config(member.guild.id)
        join_role_id = config.get('join_role')
        
        if join_role_id:
            role = member.guild.get_role(join_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-assigned join role")
                except discord.Forbidden:
                    self.log.error("Failed to assign role on join")
                    pass  # Bot doesn't have permission

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave events"""
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
        
        embed = self.create_ban_embed(user, moderator, reason)
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
        
        embed = discord.Embed(
            description=f"{user.display_name} was unbanned",
            color=0x90ee90,  # Light green for unbans
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name="Member Unbanned", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if moderator:
            embed.add_field(name="Unbanned by", value=moderator.display_name, inline=True)
        
        embed.add_field(name="User ID", value=str(user.id), inline=True)
        
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

    @app_commands.command(name="owner_give_role", description="Give role to user (owner only)")
    @app_commands.describe(
        user="User to give role to",
        role="Role to give"
    )
    async def give_role_command(
            self, 
            interaction: discord.Interaction, 
            user: discord.Member,
            role: discord.Role
    ):
        if interaction.user.id != 703896034820096000:
            await interaction.response.send_message("Owner only", ephemeral=True)
            return
    
        try:
            await user.add_roles(role)
            await interaction.response.send_message(
                f"✅ Added role **{role.name}** to {user.mention}", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot doesn't have permission to manage this role", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error: {str(e)}", 
                ephemeral=True
            )
                
    @app_commands.command(name="mod_dashboard", description="View current moderation configuration")
    @app_commands.default_permissions(administrator=True)
    async def mod_dashboard(self, interaction: discord.Interaction):
        """Display moderation dashboard"""
        config = self.get_guild_config(interaction.guild.id)
        
        embed = discord.Embed(
            title="🛡️ Moderation Dashboard",
            color=0x5865f2,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Member logging configuration
        webhook_url = config.get('member_log_webhook')
        if webhook_url:
            embed.add_field(
                name="📝 Member Logging",
                value="✅ **Enabled**\nLogging joins, leaves, bans, kicks, and timeouts",
                inline=False
            )
        else:
            embed.add_field(
                name="📝 Member Logging",
                value="❌ **Disabled**\nUse `/mod_memberlog_setup` to enable",
                inline=False
            )
        
        # Join role configuration
        join_role_id = config.get('join_role')
        if join_role_id:
            role = interaction.guild.get_role(join_role_id)
            role_mention = role.mention if role else f"Role not found (ID: {join_role_id})"
            embed.add_field(
                name="👤 Auto Join Role",
                value=f"✅ **Enabled**\nAssigning role: {role_mention}",
                inline=False
            )
        else:
            embed.add_field(
                name="👤 Auto Join Role",
                value="❌ **Disabled**\nUse `/mod_joinrole_setup` to enable",
                inline=False
            )
        
        embed.set_footer(text=f"Guild ID: {interaction.guild.id}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Delete a specified number of messages from the current channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.default_permissions(administrator=True)
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
                color=0x00ff00,
                timestamp=datetime.now(timezone.utc)
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

    @app_commands.command(name="mod_memberlog_setup", description="Setup member logging with webhook")
    @app_commands.describe(webhook_url="The webhook URL for the logging channel")
    @app_commands.default_permissions(administrator=True)
    async def setup_member_log(self, interaction: discord.Interaction, webhook_url: str):
        """Setup member logging"""
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need `Manage Server` permission to use this command.", ephemeral=True)
            return
        
        # Validate webhook URL
        if not webhook_url.startswith('https://discord.com/api/webhooks/'):
            await interaction.response.send_message("❌ Invalid webhook URL format.", ephemeral=True)
            return
        
        try:
            # Test webhook
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                await webhook.fetch()
        except (discord.HTTPException, aiohttp.ClientError):
            await interaction.response.send_message("❌ Invalid or inaccessible webhook URL.", ephemeral=True)
            return
        
        self.set_guild_config(interaction.guild.id, 'member_log_webhook', webhook_url)
        
        embed = discord.Embed(
            title="✅ Member Logging Enabled",
            description="Successfully configured member logging!\n\nThe bot will now log:\n• Member joins\n• Member leaves\n• Bans and unbans\n• Kicks\n• Timeouts",
            color=0x00ff00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mod_memberlog_disable", description="Disable member logging")
    @app_commands.default_permissions(administrator=True)
    async def disable_member_log(self, interaction: discord.Interaction):
        """Disable member logging"""
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need `Manage Server` permission to use this command.", ephemeral=True)
            return
        
        config = self.get_guild_config(interaction.guild.id)
        if 'member_log_webhook' not in config:
            await interaction.response.send_message("❌ Member logging is not enabled.", ephemeral=True)
            return
        
        # Remove webhook from config
        config = self.get_guild_config(interaction.guild.id)
        if 'member_log_webhook' in config:
            del config['member_log_webhook']
            self.save_config(interaction.guild.id, config)
        
        embed = discord.Embed(
            title="✅ Member Logging Disabled",
            description="Member logging has been disabled.",
            color=0xff0000
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mod_joinrole_setup", description="Setup auto role assignment for new members")
    @app_commands.describe(role="The role to assign to new members")
    @app_commands.default_permissions(administrator=True)
    async def setup_join_role(self, interaction: discord.Interaction, role: discord.Role):
        """Setup auto join role"""
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You need `Manage Roles` permission to use this command.", ephemeral=True)
            return
        
        # Check if bot can assign the role
        bot_member = interaction.guild.get_member(self.bot.user.id)
        if role >= bot_member.top_role:
            await interaction.response.send_message("❌ I cannot assign this role as it's higher than or equal to my highest role.", ephemeral=True)
            return
        
        self.set_guild_config(interaction.guild.id, 'join_role', role.id)
        
        embed = discord.Embed(
            title="✅ Auto Join Role Enabled",
            description=f"New members will automatically receive the {role.mention} role when they join.",
            color=0x00ff00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mod_joinrole_disable", description="Disable auto role assignment for new members")
    @app_commands.default_permissions(administrator=True)
    async def disable_join_role(self, interaction: discord.Interaction):
        """Disable auto join role"""
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You need `Manage Roles` permission to use this command.", ephemeral=True)
            return
        
        config = self.get_guild_config(interaction.guild.id)
        if 'join_role' not in config:
            await interaction.response.send_message("❌ Auto join role is not enabled.", ephemeral=True)
            return
        
        # Remove join role from config
        config = self.get_guild_config(interaction.guild.id)
        if 'join_role' in config:
            del config['join_role']
            self.save_config(interaction.guild.id, config)
        
        embed = discord.Embed(
            title="✅ Auto Join Role Disabled",
            description="Auto role assignment for new members has been disabled.",
            color=0xff0000
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
