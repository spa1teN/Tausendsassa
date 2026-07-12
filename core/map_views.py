"""User Views for Discord Map Bot."""

import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cogs.map import MapV2Cog


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
        # Pass the button interaction (original_interaction) so the stale
        # "Your Pin" message that launched this edit can be removed.
        await self.cog._handle_pin_location_update(
            interaction,
            self.location.value,
            interaction,
            self.original_interaction,
        )
