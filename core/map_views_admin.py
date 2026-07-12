"""Admin Views for Discord Map Bot with separate modals."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional
from io import BytesIO

if TYPE_CHECKING:
    from cogs.map import MapV2Cog


class ColorSettingsModal(discord.ui.Modal, title='Map Color Settings'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # Load current settings to display in fields
        map_data = self.cog.maps.get(str(guild_id), {})
        existing_settings = map_data.get('settings', {})
        colors = existing_settings.get('colors', {})
        borders = existing_settings.get('borders', {})
        
        # Set current values as defaults
        self.land_color.default = self._format_color_for_display(colors.get('land', ''))
        self.water_color.default = self._format_color_for_display(colors.get('water', ''))
        self.border_color.default = self._format_color_for_display(borders.get('country', ''))

    def _format_color_for_display(self, color_value):
        """Convert color value to display format for text input."""
        if not color_value:
            return ""
        elif isinstance(color_value, tuple) and len(color_value) == 3:
            return f"{color_value[0]},{color_value[1]},{color_value[2]}"
        elif isinstance(color_value, str):
            return color_value
        else:
            return ""

    land_color = discord.ui.TextInput(
        label='Land Color (name/RGB/hex)',
        placeholder='beige or 240,240,220 or #F0F0DC (empty for default)',
        required=False,
        max_length=20
    )
    
    water_color = discord.ui.TextInput(
        label='Water Color (name/RGB/hex)', 
        placeholder='lightblue or 168,213,242 or #A8D5F2 (empty for default)',
        required=False,
        max_length=20
    )
    
    border_color = discord.ui.TextInput(
        label='Border Color (countries/states)',
        placeholder='black or 0,0,0 or #000000 (empty for default)',
        required=False,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = self.cog.map_generator.map_config

        guild_id = str(self.guild_id)
        map_data = self.cog.maps.get(guild_id, {})
        current_settings = map_data.get('settings', {})

        land_color = config.parse_color(self.land_color.value, config.DEFAULT_LAND_COLOR) if self.land_color.value else config.DEFAULT_LAND_COLOR
        water_color = config.parse_color(self.water_color.value, config.DEFAULT_WATER_COLOR) if self.water_color.value else config.DEFAULT_WATER_COLOR
        border_color = config.parse_color(self.border_color.value, config.DEFAULT_COUNTRY_BORDER_COLOR) if self.border_color.value else config.DEFAULT_COUNTRY_BORDER_COLOR

        updated_settings = current_settings.copy()
        updated_settings['colors'] = {'land': land_color, 'water': water_color}
        updated_settings['borders'] = {'country': border_color, 'state': border_color, 'river': water_color}

        map_data['settings'] = updated_settings
        self.cog.maps[guild_id] = map_data
        # Save to DB but do NOT update the map card — user must preview+apply first
        await self.cog._save_data(guild_id)

        view = self.cog._build_admin_view(self.guild_id, show_preview_btn=True)
        try:
            await self.original_interaction.followup.delete_message(
                self.original_interaction.message.id)
        except Exception:
            pass
        await interaction.followup.send(
            view=view, files=getattr(view, '_swatch_attachments', []),
            ephemeral=True)

class PinSettingsModal(discord.ui.Modal, title='Pin Settings'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # Load current settings to display in fields
        map_data = self.cog.maps.get(str(guild_id), {})
        existing_settings = map_data.get('settings', {})
        pins = existing_settings.get('pins', {})
        
        # Set current values as defaults
        self.pin_color.default = self._format_color_for_display(pins.get('color', ''))
        self.pin_size.default = str(pins.get('size', '')) if pins.get('size') else ''

    def _format_color_for_display(self, color_value):
        """Convert color value to display format for text input."""
        if not color_value:
            return ""
        elif isinstance(color_value, tuple) and len(color_value) == 3:
            return f"{color_value[0]},{color_value[1]},{color_value[2]}"
        elif isinstance(color_value, str):
            return color_value
        else:
            return ""

    pin_color = discord.ui.TextInput(
        label='Pin Color (name/hex)',
        placeholder='red or #FF4444 (leave empty for default)',
        required=False,
        max_length=20
    )
    
    pin_size = discord.ui.TextInput(
        label='Pin Size (8-32)',
        placeholder='16 (leave empty for default)',
        required=False,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = self.cog.map_generator.map_config
        guild_id = str(self.guild_id)
        map_data = self.cog.maps.get(guild_id, {})
        current_settings = map_data.get('settings', {})
        pin_color = config.parse_color(self.pin_color.value, config.DEFAULT_PIN_COLOR) if self.pin_color.value else config.DEFAULT_PIN_COLOR
        try:
            pin_size = int(self.pin_size.value) if self.pin_size.value else config.DEFAULT_PIN_SIZE
            pin_size = max(8, min(32, pin_size))
        except (ValueError, TypeError):
            pin_size = config.DEFAULT_PIN_SIZE
        updated_settings = current_settings.copy()
        if 'pins' not in updated_settings:
            updated_settings['pins'] = {}
        updated_settings['pins'].update({'color': pin_color, 'size': pin_size})
        view = self.cog._build_admin_view(self.guild_id, show_preview_btn=True)
        try:
            await self.original_interaction.followup.delete_message(
                self.original_interaction.message.id)
        except Exception:
            pass
        await interaction.followup.send(
            view=view, files=getattr(view, '_swatch_attachments', []),
            ephemeral=True)
