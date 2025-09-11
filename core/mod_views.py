import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from typing import Optional
import aiohttp

class ChannelSelectView(discord.ui.View):
    def __init__(self, moderation_cog):
        super().__init__(timeout=300)
        self.moderation_cog = moderation_cog

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select a channel for member logging...",
        min_values=1,
        max_values=1,
        channel_types=[discord.ChannelType.text]
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        # Get the actual channel object from the guild using the ID
        selected_channel = select.values[0]
        channel = interaction.guild.get_channel(selected_channel.id)
        
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return

        # Check if bot has permission to create webhooks in the channel
        bot_permissions = channel.permissions_for(interaction.guild.me)
        if not bot_permissions.manage_webhooks:
            await interaction.response.send_message("❌ I don't have permission to create webhooks in that channel.", ephemeral=True)
            return

        try:
            # Create webhook
            webhook = await channel.create_webhook(
                name="Member Logger",
                avatar=await self.moderation_cog.bot.user.display_avatar.read(),
                reason="Moderation logging setup"
            )
            
            # Save webhook URL to config
            self.moderation_cog.set_guild_config(interaction.guild.id, 'member_log_webhook', webhook.url)

            # Replace channel selection with updated dashboard
            dashboard_embed = self.moderation_cog.create_dashboard_embed(interaction.guild.id)
            dashboard_view = ModerationDashboardView(self.moderation_cog)
            dashboard_view.update_buttons(interaction.guild.id)
            
            await interaction.response.edit_message(
                content=None,
                embed=dashboard_embed, 
                view=dashboard_view
            )
            
            # Send success message as followup
            success_embed = discord.Embed(
                title="✅ Member Logging Enabled",
                description=f"Successfully configured member logging for {channel.mention}!",
                color=0x00ff00
            )
            await interaction.followup.send(embed=success_embed, ephemeral=True)

        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to create webhook: {str(e)}", ephemeral=True)

    async def on_timeout(self):
        """Called when the view times out"""
        for item in self.children:
            item.disabled = True

class RoleSelectView(discord.ui.View):
    def __init__(self, moderation_cog):
        super().__init__(timeout=300)
        self.moderation_cog = moderation_cog

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select a role to assign to new members...",
        min_values=1,
        max_values=1
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]

        # Check if bot can assign the role
        bot_member = interaction.guild.get_member(self.moderation_cog.bot.user.id)
        if role >= bot_member.top_role:
            await interaction.response.send_message("❌ I cannot assign this role as it's higher than or equal to my highest role.", ephemeral=True)
            return

        self.moderation_cog.set_guild_config(interaction.guild.id, 'join_role', role.id)

        # Replace role selection with updated dashboard
        dashboard_embed = self.moderation_cog.create_dashboard_embed(interaction.guild.id)
        dashboard_view = ModerationDashboardView(self.moderation_cog)
        dashboard_view.update_buttons(interaction.guild.id)
        
        await interaction.response.edit_message(
            content=None,
            embed=dashboard_embed, 
            view=dashboard_view
        )
        
        # Send success message as followup
        success_embed = discord.Embed(
            title="✅ Auto Join Role Enabled",
            description=f"New members will automatically receive the {role.mention} role when they join.",
            color=0x00ff00
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

    async def on_timeout(self):
        """Called when the view times out"""
        for item in self.children:
            item.disabled = True

class ModerationDashboardView(discord.ui.View):
    def __init__(self, moderation_cog):
        super().__init__(timeout=300)
        self.moderation_cog = moderation_cog

    @discord.ui.button(label="Setup Member Log", style=discord.ButtonStyle.green, emoji="📋")
    async def setup_member_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need `Manage Server` permission to use this feature.", ephemeral=True)
            return

        config = self.moderation_cog.get_guild_config(interaction.guild.id)
        
        if config.get('member_log_webhook'):
            # Disable member logging - also delete the webhook
            await self._disable_member_logging(interaction, config)
        else:
            # Replace dashboard with channel selection
            view = ChannelSelectView(self.moderation_cog)
            await interaction.response.edit_message(
                content="Select a channel for member logging:",
                embed=None,
                view=view
            )

    @discord.ui.button(label="Setup Join Role", style=discord.ButtonStyle.blurple, emoji="👤")
    async def setup_join_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You need `Manage Roles` permission to use this feature.", ephemeral=True)
            return

        config = self.moderation_cog.get_guild_config(interaction.guild.id)
        
        if config.get('join_role'):
            # Disable join role
            await self._disable_join_role(interaction)
        else:
            # Replace dashboard with role selection
            view = RoleSelectView(self.moderation_cog)
            await interaction.response.edit_message(
                content="Select a role to assign to new members:",
                embed=None,
                view=view
            )

    async def _disable_member_logging(self, interaction: discord.Interaction, config: dict):
        """Helper method to disable member logging"""
        webhook_url = config.get('member_log_webhook')
        if webhook_url:
            try:
                # Create a new aiohttp session for webhook deletion
                async with aiohttp.ClientSession() as session:
                    webhook = discord.Webhook.from_url(webhook_url, session=session)
                    await webhook.delete(reason="Member logging disabled")
            except (discord.HTTPException, aiohttp.ClientError):
                pass  # Webhook might already be deleted
        
        # Remove webhook from config properly
        guild_str = str(interaction.guild.id)
        if guild_str in self.moderation_cog.config and 'member_log_webhook' in self.moderation_cog.config[guild_str]:
            del self.moderation_cog.config[guild_str]['member_log_webhook']
            self.moderation_cog.save_config()
        
        # Update the dashboard in place
        dashboard_embed = self.moderation_cog.create_dashboard_embed(interaction.guild.id)
        view = ModerationDashboardView(self.moderation_cog)
        view.update_buttons(interaction.guild.id)
        
        await interaction.response.edit_message(
            content=None,
            embed=dashboard_embed, 
            view=view
        )
        
        # Send success message as followup
        success_embed = discord.Embed(
            title="✅ Member Logging Disabled",
            description="Member logging has been disabled and webhook deleted.",
            color=0xff0000
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

    async def _disable_join_role(self, interaction: discord.Interaction):
        """Helper method to disable join role"""
        guild_str = str(interaction.guild.id)
        if guild_str in self.moderation_cog.config and 'join_role' in self.moderation_cog.config[guild_str]:
            del self.moderation_cog.config[guild_str]['join_role']
            self.moderation_cog.save_config()
        
        # Update the dashboard in place
        dashboard_embed = self.moderation_cog.create_dashboard_embed(interaction.guild.id)
        view = ModerationDashboardView(self.moderation_cog)
        view.update_buttons(interaction.guild.id)
        
        await interaction.response.edit_message(
            content=None,
            embed=dashboard_embed, 
            view=view
        )
        
        # Send success message as followup
        success_embed = discord.Embed(
            title="✅ Auto Join Role Disabled",
            description="Auto role assignment for new members has been disabled.",
            color=0xff0000
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

    async def on_timeout(self):
        """Called when the view times out"""
        for item in self.children:
            item.disabled = True

    def update_buttons(self, guild_id: int):
        """Update button states based on current configuration"""
        config = self.moderation_cog.get_guild_config(guild_id)
        
        # Update member log button
        if config.get('member_log_webhook'):
            self.children[0].label = "Disable Member Log"
            self.children[0].style = discord.ButtonStyle.red
            self.children[0].emoji = "🗑️"
        else:
            self.children[0].label = "Setup Member Log"
            self.children[0].style = discord.ButtonStyle.green
            self.children[0].emoji = "📋"
        
        # Update join role button
        if config.get('join_role'):
            self.children[1].label = "Disable Join Role"
            self.children[1].style = discord.ButtonStyle.red
            self.children[1].emoji = "🗑️"
        else:
            self.children[1].label = "Setup Join Role"
            self.children[1].style = discord.ButtonStyle.blurple
            self.children[1].emoji = "👤"