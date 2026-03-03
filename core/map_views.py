"""User Views for Discord Map Bot."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING
from io import BytesIO

if TYPE_CHECKING:
    from cogs.map import MapV2Cog

from .map_views_admin import AdminToolsView


class LocationModal(discord.ui.Modal, title='Pin Location'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    location = discord.ui.TextInput(
        label='Location',
        placeholder='e.g. Berlin, Deutschland or Paris, France...',
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._handle_pin_location(interaction, self.location.value)


class MapMenuView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, user: discord.Member):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.user = user

        self._add_info_button()

        if user.guild_permissions.administrator:
            self._add_admin_tools_button()

    def _add_info_button(self):
        info_button = discord.ui.Button(
            label="Info",
            style=discord.ButtonStyle.secondary,
            emoji="ℹ️"
        )
        info_button.callback = self.map_info
        self.add_item(info_button)

    def _add_admin_tools_button(self):
        admin_tools_button = discord.ui.Button(
            label="Admin Tools",
            style=discord.ButtonStyle.danger,
            emoji="⚙️"
        )
        admin_tools_button.callback = self.admin_tools
        self.add_item(admin_tools_button)

    async def admin_tools(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ Admin Tools",
            description="Administrative tools for managing this server's map.",
            color=0x7289da
        )
        view = AdminToolsView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def map_info(self, interaction: discord.Interaction):
        """Show map information (same functionality as /map_info command)."""
        await interaction.response.defer()

        guild_id = str(self.guild_id)

        if guild_id not in self.cog.maps:
            embed = discord.Embed(
                title="⛔ Error",
                description="No map exists for this server.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        map_data = self.cog.maps[guild_id]
        pins = map_data.get('pins', {})
        region = map_data['region']
        channel_id = map_data['channel_id']
        created_at = map_data.get('created_at', 'Unknown')

        embed = discord.Embed(
            title="🗺️ Server Map Information",
            color=0x7289da,
            timestamp=datetime.now()
        )

        embed.add_field(name="📊 Statistics", value=f"📍 **{len(pins)}** pinned locations", inline=True)
        embed.add_field(name="🌍 Region", value=region.title(), inline=True)
        embed.add_field(name="📺 Channel", value=f"<#{channel_id}>", inline=True)

        if created_at != 'Unknown':
            try:
                created_date = datetime.fromisoformat(created_at).strftime('%Y-%m-%d')
                embed.add_field(name="📅 Created", value=created_date, inline=True)
            except:
                pass

        user_id = str(interaction.user.id)
        if user_id in pins:
            user_pin = pins[user_id]
            embed.add_field(
                name="📍 Your Pin",
                value=f"**Location:** {user_pin.get('display_name', 'Unknown')}\n"
                      f"**Added:** {user_pin.get('timestamp', 'Unknown')}",
                inline=False
            )
        else:
            embed.add_field(
                name="📍 Your Pin",
                value="You haven't pinned a location yet.\nUse the 'My Pin' button to add one!",
                inline=False
            )

        await interaction.edit_original_response(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class MapPinButtonView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', region: str, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.region = region
        self.guild_id = guild_id

        # Add Explore button between My Pin and ... (row 0)
        webapp_url = cog.config.webapp_url
        if webapp_url:
            self.add_item(discord.ui.Button(
                label="🌍 Explore",
                style=discord.ButtonStyle.link,
                url=f"{webapp_url}/map/{guild_id}",
                row=0,
            ))

        # Add ... button after Explore (row 0)
        menu_btn = discord.ui.Button(
            label="...",
            style=discord.ButtonStyle.secondary,
            custom_id="map_menu_button",
            row=0,
        )
        menu_btn.callback = self._menu_callback
        self.add_item(menu_btn)

    @discord.ui.button(
        label="📍 My Pin",
        style=discord.ButtonStyle.primary,
        custom_id="map_pin_button",
        row=0,
    )
    async def pin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

        if guild_id in self.cog.maps and user_id in self.cog.maps[guild_id].get('pins', {}):
            user_pin = self.cog.maps[guild_id]['pins'][user_id]
            current_location = user_pin.get('display_name', 'Unknown')

            embed = discord.Embed(
                title="📍 Your Current Location",
                description=f"**Location:** {current_location}\n"
                           f"**Added:** {user_pin.get('timestamp', 'Unknown')}",
                color=0x7289da
            )

            view = UserPinOptionsView(self.cog, int(guild_id))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(LocationModal(self.cog, int(guild_id)))

    async def _menu_callback(self, interaction: discord.Interaction):
        view = MapMenuView(self.cog, int(interaction.guild.id), interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)


class UserPinOptionsView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(
        label="Change",
        style=discord.ButtonStyle.primary,
        emoji="🔄"
    )
    async def change_location(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = UpdateLocationModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Remove ",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def remove_location(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

        if guild_id not in self.cog.maps:
            embed = discord.Embed(
                title="⛔ Error",
                description="No map for this server.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        if user_id not in self.cog.maps[guild_id]['pins']:
            embed = discord.Embed(
                title="⛔ Error",
                description="You don't have a pin on the map.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=embed, view=None)
            return

        loading_embed = discord.Embed(
            title="🗺️ Updating Map",
            description="Removing pin and rendering updated map...",
            color=0x7289da
        )
        await interaction.edit_original_response(embed=loading_embed, view=None)

        old_location = self.cog.maps[guild_id]['pins'][user_id].get('location', 'Unknown')
        del self.cog.maps[guild_id]['pins'][user_id]
        await self.cog._delete_pin(int(guild_id), int(user_id))

        await self.cog.storage.invalidate_final_map_cache_only(int(guild_id))
        self.cog.log.info(f"Pin removal for guild {guild_id}: preserved base map cache for efficiency")

        channel_id = self.cog.maps[guild_id]['channel_id']
        await self.cog._update_map(int(guild_id), channel_id)
        await self.cog._update_global_overview()

        embed = discord.Embed(
            title="🗑️ Pin Removed",
            description=f"Your pin has been successfully removed from the map.",
            color=0xff4444
        )
        embed.add_field(name="Removed Location", value=old_location, inline=False)
        embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)

        await interaction.edit_original_response(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class UpdateLocationModal(discord.ui.Modal, title='Update Pin Location'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

    location = discord.ui.TextInput(
        label='New Location',
        placeholder='e.g. Munich, Germany or Tokyo, Japan...',
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        loading_embed = discord.Embed(
            title="🗺️ Updating Map",
            description="Updating pin location and rendering updated map...",
            color=0x7289da
        )
        await self.original_interaction.edit_original_response(embed=loading_embed, view=None)

        await self.cog._handle_pin_location_update(
            interaction,
            self.location.value,
            self.original_interaction
        )
