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
        # Parse and store color settings
        config = self.cog.map_generator.map_config
        
        # Use existing settings as base
        guild_id = str(self.guild_id)
        map_data = self.cog.maps.get(guild_id, {})
        current_settings = map_data.get('settings', {})
        
        # Parse colors with defaults
        land_color = config.parse_color(self.land_color.value, config.DEFAULT_LAND_COLOR) if self.land_color.value else config.DEFAULT_LAND_COLOR
        water_color = config.parse_color(self.water_color.value, config.DEFAULT_WATER_COLOR) if self.water_color.value else config.DEFAULT_WATER_COLOR
        border_color = config.parse_color(self.border_color.value, config.DEFAULT_COUNTRY_BORDER_COLOR) if self.border_color.value else config.DEFAULT_COUNTRY_BORDER_COLOR
        river_color = water_color
        
        # Prepare updated settings
        updated_settings = current_settings.copy()
        updated_settings['colors'] = {
            'land': land_color,
            'water': water_color
        }
        updated_settings['borders'] = {
            'country': border_color,
            'state': border_color,  # Same as country
            'river': river_color
        }
        
        # Generate preview
        await self._show_preview(interaction, updated_settings)

    async def _show_preview(self, interaction: discord.Interaction, settings: Dict):
        """Show preview of color settings."""
        # Show loading message
        loading_embed = discord.Embed(
            title="🎨 Generating Preview",
            description="Just a moment, I'm rendering the preview...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=loading_embed, attachments=[], view=None)
        
        try:
            # Use centralized progress handler
            from core.map_progress_handler import create_preview_progress_callback
            progress_callback = await create_preview_progress_callback(interaction, self.cog.log)
            
            # Generate preview
            result = await self.cog._generate_preview_map(int(self.guild_id), settings, progress_callback)
            
            if not result or result[0] is None:
                preview_image, base_map = None, None
            else:
                preview_image, base_map = result
            
            if not preview_image:
                error_embed = discord.Embed(
                    title="⛔ Preview Error",
                    description="Failed to generate preview. Please try again.",
                    color=0xff4444
                )
                await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)
                return
            
            # Create preview embed
            embed = discord.Embed(
                title="🎨 Color Settings Preview",
                description="Here's how your map will look with the new color settings:",
                color=0x7289da
            )
            
            # Show color values
            colors = settings['colors']
            borders = settings['borders']
            
            def format_color_display(color_value, input_value):
                config = self.cog.map_generator.map_config
                if input_value and input_value.lower() in config.COLOR_DICTIONARY:
                    return f"{input_value.title()}"
                elif isinstance(color_value, tuple):
                    return f"RGB({color_value[0]}, {color_value[1]}, {color_value[2]})"
                else:
                    return str(color_value)
            
            embed.add_field(
                name="Land Color", 
                value=format_color_display(colors['land'], self.land_color.value),
                inline=True
            )
            embed.add_field(
                name="Water Color", 
                value=format_color_display(colors['water'], self.water_color.value),
                inline=True
            )
            embed.add_field(
                name="Borders", 
                value=format_color_display(borders['country'], self.border_color.value),
                inline=True
            )
            
            # Send preview with confirmation buttons
            # Create a copy of the preview image for caching
            preview_image_copy = BytesIO(preview_image.getvalue())
            view = ColorSettingsPreviewView(self.cog, self.guild_id, settings, self.original_interaction, preview_image_copy, base_map)
            
            filename = f"color_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await interaction.edit_original_response(
                content=None,
                embed=embed,
                attachments=[discord.File(preview_image, filename=filename)],
                view=view
            )
            
        except Exception as e:
            self.cog.log.error(f"Error generating color preview: {e}")
            error_embed = discord.Embed(
                title="⛔ Preview Error",
                description="An error occurred while generating the preview.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)


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
        # Parse and store pin settings
        config = self.cog.map_generator.map_config
        
        # Use existing settings as base
        guild_id = str(self.guild_id)
        map_data = self.cog.maps.get(guild_id, {})
        current_settings = map_data.get('settings', {})
        
        # Parse pin settings
        pin_color = config.parse_color(self.pin_color.value, config.DEFAULT_PIN_COLOR) if self.pin_color.value else config.DEFAULT_PIN_COLOR
        
        try:
            pin_size = int(self.pin_size.value) if self.pin_size.value else config.DEFAULT_PIN_SIZE
            pin_size = max(8, min(32, pin_size))
        except (ValueError, TypeError):
            pin_size = config.DEFAULT_PIN_SIZE
        
        # Prepare updated settings
        updated_settings = current_settings.copy()
        if 'pins' not in updated_settings:
            updated_settings['pins'] = {}
        updated_settings['pins'].update({
            'color': pin_color,
            'size': pin_size
        })
        
        # Generate preview
        await self._show_preview(interaction, updated_settings)

    async def _show_preview(self, interaction: discord.Interaction, settings: Dict):
        """Show preview of pin settings with optimized performance."""
        # Show loading message
        loading_embed = discord.Embed(
            title="📍 Generating Preview",
            description="Just a moment, I'm rendering the preview...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=loading_embed, attachments=[], view=None)
        
        try:
            # Generate fast pin preview (reuses base map cache)
            preview_image = await self.cog._generate_fast_pin_preview(int(self.guild_id), settings)
            
            if not preview_image:
                error_embed = discord.Embed(
                    title="⛔ Preview Error",
                    description="Failed to generate preview. Please try again.",
                    color=0xff4444
                )
                await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)
                return
            
            # Create preview embed
            embed = discord.Embed(
                title="📍 Pin Settings Preview",
                description="Here's how your pins will look with the new settings:",
                color=0x7289da
            )
            
            # Show pin values
            pins = settings['pins']
            
            def format_color_display(color_value, input_value):
                config = self.cog.map_generator.map_config
                if input_value and input_value.lower() in config.COLOR_DICTIONARY:
                    return f"{input_value.title()}"
                elif isinstance(color_value, tuple):
                    return f"RGB({color_value[0]}, {color_value[1]}, {color_value[2]})"
                else:
                    return str(color_value)
            
            embed.add_field(
                name="Pin Color", 
                value=format_color_display(pins['color'], self.pin_color.value),
                inline=True
            )
            embed.add_field(
                name="Pin Size", 
                value=str(pins['size']),
                inline=True
            )
            
            # Send preview with confirmation buttons
            view = PinSettingsPreviewView(self.cog, self.guild_id, settings, self.original_interaction)
            
            filename = f"pin_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await interaction.edit_original_response(
                embed=embed,
                attachments=[discord.File(preview_image, filename=filename)],
                view=view
            )
            
        except Exception as e:
            self.cog.log.error(f"Error generating pin preview: {e}")
            error_embed = discord.Embed(
                title="⛔ Preview Error",
                description="An error occurred while generating the preview.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)


class ColorSettingsPreviewView(discord.ui.View):
    """View for confirming color settings after preview."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int, settings: Dict, original_interaction: discord.Interaction, preview_image: BytesIO = None, base_map: 'Image.Image' = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.settings = settings
        self.original_interaction = original_interaction
        self.preview_image = preview_image  # Cache the preview image to reuse
        self.base_map = base_map  # Cache the base map for saving when approved

    @discord.ui.button(label="Apply Colors", style=discord.ButtonStyle.success, emoji="✅")
    async def apply_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_settings(interaction)

    @discord.ui.button(label="Adjust Colors", style=discord.ButtonStyle.secondary, emoji="🔧")
    async def adjust_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ColorSettingsModal(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="⛔")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⛔ Color Settings Cancelled",
            description="No changes were made to the map colors.",
            color=0xff4444
        )
        await interaction.response.edit_message(embed=embed, attachments=[], view=None)

    async def _apply_settings(self, interaction: discord.Interaction):
        """Apply the color settings."""
        saving_embed = discord.Embed(
            title="💾 Saving Colors",
            description="Saving color configuration...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=saving_embed, attachments=[], view=None)
        
        try:
            guild_id = str(self.guild_id)
            
            if guild_id not in self.cog.maps:
                await interaction.edit_original_response(content=None, embed=discord.Embed(
                    title="⛔ Error", description="No map exists for this server.", color=0xff4444), attachments=[], view=None)
                return
            
            # Apply settings
            if 'settings' not in self.cog.maps[guild_id]:
                self.cog.maps[guild_id]['settings'] = {}
            
            self.cog.maps[guild_id]['settings'].update(self.settings)
            await self.cog._save_data(guild_id)
            
            # Radical cleanup: remove ALL PNG files when settings change
            await self.cog.storage.cache.invalidate_all_png_files_for_settings_change(guild_id)
            
            # Use cached preview image if available, otherwise regenerate
            if self.preview_image and self.base_map:
                # Use the cached preview image to avoid regeneration
                success = await self.cog._apply_cached_preview_as_map(int(guild_id), self.preview_image)
                
                if success:
                    # Save the new base map from the preview
                    map_data = self.cog.maps.get(guild_id, {})
                    region = map_data.get('region', 'world')
                    width, height = self.cog.map_generator.calculate_image_dimensions(region)
                    if region != "germany" and region != "usmainland":
                        height = int(height * 0.8)
                    
                    # Cache the new base map (this replaces the old one)
                    await self.cog.storage.cache_base_map(region, width, height, self.base_map, guild_id, self.cog.maps)
                    
                    # Now invalidate old closeup base maps and final maps since they use old colors
                    await self.cog.storage.cache.invalidate_cache(guild_id, ["closeup_base_map", "final_map", "closeup"])
                    
                    self.cog.log.info(f"Applied new base map for guild {guild_id} with updated colors")
                else:
                    # Fallback: regenerate if cached preview fails - clean up all old maps
                    await self.cog.storage.cache.invalidate_cache(guild_id, ["base_map", "final_map", "closeup", "closeup_base_map"])
                    channel_id = self.cog.maps[guild_id]['channel_id']
                    await self.cog._update_map(int(guild_id), channel_id)
            else:
                # No cached preview - do full regeneration with comprehensive cleanup
                await self.cog.storage.invalidate_cache(guild_id, ["base_map", "final_map", "closeup", "closeup_base_map"])
                channel_id = self.cog.maps[guild_id]['channel_id']
                await self.cog._update_map(int(guild_id), channel_id)
            
            await self.cog._update_global_overview()
            
            success_embed = discord.Embed(
                title="✅ Colors Applied Successfully",
                description="Your map colors have been updated!",
                color=0x00ff44
            )
            channel_id = self.cog.maps[guild_id]['channel_id']
            success_embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
            
            await interaction.edit_original_response(content=None, embed=success_embed, attachments=[], view=None)
            
        except Exception as e:
            self.cog.log.error(f"Error applying color settings: {e}")
            error_embed = discord.Embed(
                title="⛔ Error",
                description="An error occurred while saving the colors.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)


class PinSettingsPreviewView(discord.ui.View):
    """View for confirming pin settings after preview."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int, settings: Dict, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.settings = settings
        self.original_interaction = original_interaction

    @discord.ui.button(label="Apply Pins", style=discord.ButtonStyle.success, emoji="✅")
    async def apply_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_settings(interaction)

    @discord.ui.button(label="Adjust Pins", style=discord.ButtonStyle.secondary, emoji="🔧")
    async def adjust_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PinSettingsModal(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="⛔")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⛔ Pin Settings Cancelled",
            description="No changes were made to the pin settings.",
            color=0xff4444
        )
        await interaction.response.edit_message(embed=embed, attachments=[], view=None)

    async def _apply_settings(self, interaction: discord.Interaction):
        """Apply the pin settings."""
        saving_embed = discord.Embed(
            title="💾 Saving Pins",
            description="Saving pin configuration...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=saving_embed, attachments=[], view=None)
        
        try:
            guild_id = str(self.guild_id)
            
            if guild_id not in self.cog.maps:
                await interaction.edit_original_response(content=None, embed=discord.Embed(
                    title="⛔ Error", description="No map exists for this server.", color=0xff4444), attachments=[], view=None)
                return
            
            # Apply settings
            if 'settings' not in self.cog.maps[guild_id]:
                self.cog.maps[guild_id]['settings'] = {}
            
            self.cog.maps[guild_id]['settings'].update(self.settings)
            await self.cog._save_data(guild_id)
            
            # Radical cleanup: remove ALL PNG files when settings change
            await self.cog.storage.cache.invalidate_all_png_files_for_settings_change(guild_id)
            
            # Only invalidate final map cache for pin changes (base map unchanged)
            await self.cog.storage.invalidate_final_map_cache_only(int(guild_id))
            
            # Update main map
            channel_id = self.cog.maps[guild_id]['channel_id']
            await self.cog._update_map(int(guild_id), channel_id)
            await self.cog._update_global_overview()
            
            success_embed = discord.Embed(
                title="✅ Pins Applied Successfully",
                description="Your pin settings have been updated!",
                color=0x00ff44
            )
            success_embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
            
            await interaction.edit_original_response(content=None, embed=success_embed, attachments=[], view=None)
            
        except Exception as e:
            self.cog.log.error(f"Error applying pin settings: {e}")
            error_embed = discord.Embed(
                title="⛔ Error",
                description="An error occurred while saving the pin settings.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=error_embed, attachments=[], view=None)


class ProximitySettingsView(discord.ui.View):
    """View for setting proximity search on/off."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Get current setting
        map_data = self.cog.maps.get(str(guild_id), {})
        current_setting = map_data.get('allow_proximity', True)
        
        # Set initial button styles
        self.enable_button.style = discord.ButtonStyle.success if current_setting else discord.ButtonStyle.secondary
        self.disable_button.style = discord.ButtonStyle.danger if not current_setting else discord.ButtonStyle.secondary

    @discord.ui.button(label="Enable", style=discord.ButtonStyle.secondary, emoji="✅")
    async def enable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_proximity(interaction, True)

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.secondary, emoji="⛔")
    async def disable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_proximity(interaction, False)

    async def _set_proximity(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer()
        
        guild_id = str(self.guild_id)
        if guild_id not in self.cog.maps:
            await interaction.followup.send("⛔ No map exists for this server.", ephemeral=True)
            return
        
        # Update setting
        self.cog.maps[guild_id]['allow_proximity'] = enabled
        await self.cog._save_data(guild_id)
        
        # Update button styles
        self.enable_button.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary
        self.disable_button.style = discord.ButtonStyle.danger if not enabled else discord.ButtonStyle.secondary
        
        # Update the view
        embed = discord.Embed(
            title="🔍 Proximity Search Settings",
            description=f"Proximity search is now **{'enabled' if enabled else 'disabled'}** for this server.",
            color=0x00ff44 if enabled else 0xff4444
        )
        
        await interaction.edit_original_response(content=None, embed=embed, attachments=[], view=self)


class MapRemovalConfirmView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Yes, Delete Map", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        guild_id = str(self.guild_id)
        
        if guild_id not in self.cog.maps:
            embed = discord.Embed(
                title="⛔ Error",
                description="No map exists for this server.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=embed, attachments=[], view=None)
            return

        map_data = self.cog.maps[guild_id]
        pin_count = len(map_data.get('pins', {}))
        
        # Try to delete the map message
        channel_id = map_data.get('channel_id')
        message_id = map_data.get('message_id')
        
        if channel_id and message_id:
            try:
                channel = self.cog.bot.get_channel(channel_id)
                if channel:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    self.cog.log.info(f"Deleted map message {message_id} in channel {channel_id}")
            except discord.NotFound:
                self.cog.log.info(f"Map message {message_id} already deleted")
            except Exception as e:
                self.cog.log.warning(f"Could not delete map message: {e}")
        
        # Invalidate cache when removing map
        await self.cog._invalidate_map_cache(int(guild_id))
        
        del self.cog.maps[guild_id]
        await self.cog._save_data(guild_id)
        await self.cog._update_global_overview()

        embed = discord.Embed(
            title="🗑️ Map Deleted",
            description="The server map has been permanently removed.",
            color=0xff4444
        )
        embed.add_field(name="Pins Removed", value=str(pin_count), inline=True)
        embed.add_field(name="Map Message", value="Deleted", inline=True)

        await interaction.edit_original_response(content=None, embed=embed, attachments=[], view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="⛔")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⛔ Deletion Cancelled",
            description="The map was not deleted.",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=embed, view=None)


class AdminToolsView(discord.ui.View):
    """Admin Tools interface for map management."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Check if map has custom settings to show clear cache button
        map_data = self.cog.maps.get(str(guild_id), {})
        has_custom_settings = bool(map_data.get('settings'))
        
        if has_custom_settings:
            self._add_clear_cache_button()

    def _add_clear_cache_button(self):
        clear_cache_button = discord.ui.Button(
            label="Clear Cache",
            style=discord.ButtonStyle.secondary,
            emoji="🗑️",
            row=2
        )
        clear_cache_button.callback = self.clear_cache
        self.add_item(clear_cache_button)

    @discord.ui.button(label="Customize Colors", style=discord.ButtonStyle.primary, emoji="🎨", row=0)
    async def customize_colors(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ColorSettingsModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Customize Pins", style=discord.ButtonStyle.primary, emoji="📍", row=0)
    async def customize_pins(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PinSettingsModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Proximity Settings", style=discord.ButtonStyle.secondary, emoji="🔍", row=1)
    async def proximity_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔍 Proximity Search Settings",
            description="Enable or disable proximity search for this server.",
            color=0x7289da
        )
        
        view = ProximitySettingsView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Delete Map", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠️ Confirm Map Deletion",
            description="**This action cannot be undone!**\n\nDeleting the map will:\n• Remove all user pins\n• Delete the map message\n• Clear all custom settings\n\nAre you sure you want to proceed?",
            color=0xff4444
        )
        
        view = MapRemovalConfirmView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def clear_cache(self, interaction: discord.Interaction):
        """Clear guild-specific cached maps - preserves default base maps."""
        await interaction.response.defer()
        
        try:
            # Use new admin clear cache method that preserves default base maps
            deleted_count = await self.cog.storage.admin_clear_cache(self.guild_id)
            
            embed = discord.Embed(
                title="✅ Cache Cleared",
                description=f"Cleared {deleted_count} cached files for this server.\n\n"
                           f"**Removed:** Custom base maps, final maps, closeups\n"
                           f"**Preserved:** Default base maps for faster loading",
                color=0x00ff44
            )
            
            await interaction.edit_original_response(content=None, embed=embed, attachments=[], view=None)
            
        except Exception as e:
            self.cog.log.error(f"Error clearing guild cache: {e}")
            embed = discord.Embed(
                title="⛔ Error",
                description="Failed to clear cache.",
                color=0xff4444
            )
            await interaction.edit_original_response(content=None, embed=embed, attachments=[], view=None)