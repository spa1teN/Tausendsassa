"""Admin Views for Discord Map Bot."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional
from io import BytesIO

if TYPE_CHECKING:
    from cogs.map import MapV2Cog


class AdminSettingsModal(discord.ui.Modal, title='Map Admin Settings'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction, preview_settings: Dict = None):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # Load current map data to get existing settings
        map_data = self.cog.maps.get(str(guild_id), {})
        existing_settings = map_data.get('settings', {})
        
        # Determine which settings to display
        if preview_settings:
            # Preview mode: show preview values
            settings_to_show = preview_settings
            self.cog.log.debug(f"Modal showing preview settings for guild {guild_id}")
        elif existing_settings:
            # Existing custom settings: show saved values
            settings_to_show = existing_settings
            self.cog.log.debug(f"Modal showing existing custom settings for guild {guild_id}")
        else:
            # No custom settings: show empty fields with defaults
            settings_to_show = {}
            self.cog.log.debug(f"Modal showing empty fields for guild {guild_id}")
        
        # Extract values from settings
        colors = settings_to_show.get('colors', {})
        borders = settings_to_show.get('borders', {})
        pins = settings_to_show.get('pins', {})
        
        # Set field defaults
        self.land_color.default = self._format_color_for_display(colors.get('land')) if colors.get('land') is not None else ""
        self.water_color.default = self._format_color_for_display(colors.get('water')) if colors.get('water') is not None else ""
        self.border_color.default = self._format_color_for_display(borders.get('country')) if borders.get('country') is not None else ""
        self.pin_color.default = self._format_color_for_display(pins.get('color')) if pins.get('color') is not None else ""
        self.pin_size.default = str(pins.get('size', "")) if pins.get('size') is not None else ""

    def _format_color_for_display(self, color_value):
        """Convert color value to display format for text input."""
        if color_value is None:
            return ""
        elif isinstance(color_value, tuple) and len(color_value) == 3:
            return f"{color_value[0]},{color_value[1]},{color_value[2]}"
        elif isinstance(color_value, str):
            return color_value
        else:
            return ""

    land_color = discord.ui.TextInput(
        label='Land Color (name/RGB/hex)',
        placeholder='beige or 240,240,220 or #F0F0DC',
        required=False,
        max_length=20
    )
    
    water_color = discord.ui.TextInput(
        label='Water Color (name/RGB/hex)', 
        placeholder='lightblue or 168,213,242 or #A8D5F2',
        required=False,
        max_length=20
    )
    
    border_color = discord.ui.TextInput(
        label='International Border Color (name/RGB/hex)',
        placeholder='black or 0,0,0 or #000000',
        required=False,
        max_length=20
    )
    
    pin_color = discord.ui.TextInput(
        label='Pin Color (name/hex)',
        placeholder='red or #FF4444',
        required=False,
        max_length=20
    )
    
    pin_size = discord.ui.TextInput(
        label='Pin Size (8-32)',
        placeholder='16',
        required=False,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Show loading message immediately
        loading_embed = discord.Embed(
            title="ðŸŽ¨ Generating Preview",
            description="Just a moment, I'm rendering the preview...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=loading_embed, attachments=[], view=None)
        
        try:
            guild_id = str(self.guild_id)
            
            # Parse colors using the color parser
            config = self.cog.map_generator.map_config
            
            # Safe color parsing with proper defaults
            land_color = config.parse_color(self.land_color.value, config.DEFAULT_LAND_COLOR) if self.land_color.value else config.DEFAULT_LAND_COLOR
            water_color = config.parse_color(self.water_color.value, config.DEFAULT_WATER_COLOR) if self.water_color.value else config.DEFAULT_WATER_COLOR
            country_color = config.parse_color(self.border_color.value, config.DEFAULT_COUNTRY_BORDER_COLOR) if self.border_color.value else config.DEFAULT_COUNTRY_BORDER_COLOR
            pin_color = config.parse_color(self.pin_color.value, config.DEFAULT_PIN_COLOR) if self.pin_color.value else config.DEFAULT_PIN_COLOR
            
            # Parse pin size with validation
            try:
                pin_size = int(self.pin_size.value) if self.pin_size.value else config.DEFAULT_PIN_SIZE
                pin_size = max(8, min(32, pin_size))  # Clamp between 8-32
            except (ValueError, TypeError):
                pin_size = config.DEFAULT_PIN_SIZE
            
            # Store preview settings temporarily
            preview_settings = {
                'colors': {
                    'land': land_color,
                    'water': water_color
                },
                'borders': {
                    'country': country_color,
                    'state': config.DEFAULT_STATE_BORDER_COLOR,
                    'river': water_color  # Use water color for rivers
                },
                'pins': {
                    'color': pin_color,
                    'size': pin_size
                }
            }
            
            # Generate preview
            preview_image = await self.cog._generate_preview_map(int(self.guild_id), preview_settings)
            
            if not preview_image:
                error_embed = discord.Embed(
                    title="âŒ Preview Error",
                    description="Failed to generate preview. Please try again.",
                    color=0xff4444
                )
                await interaction.edit_original_response(embed=error_embed, view=None)
                return
            
            # Create preview embed
            embed = discord.Embed(
                title="ðŸŽ¨ Map Settings Preview",
                description="Here's how your map will look with the new settings:",
                color=0x7289da
            )
            
            # Show color names if used
            def format_color_display(color_value, input_value):
                if input_value and input_value.lower() in config.COLOR_DICTIONARY:
                    return f"{input_value.title()}"
                elif isinstance(color_value, tuple):
                    return f"RGB({color_value[0]}, {color_value[1]}, {color_value[2]})"
                else:
                    return str(color_value)
            
            embed.add_field(
                name="Land Color", 
                value=format_color_display(land_color, self.land_color.value),
                inline=True
            )
            embed.add_field(
                name="Water Color", 
                value=format_color_display(water_color, self.water_color.value),
                inline=True
            )
            embed.add_field(
                name="International Borders", 
                value=format_color_display(country_color, self.border_color.value),
                inline=True
            )
            embed.add_field(
                name="Pin Color", 
                value=format_color_display(pin_color, self.pin_color.value),
                inline=True
            )
            embed.add_field(
                name="Pin Size", 
                value=str(pin_size),
                inline=True
            )
            
            # Send preview with confirmation buttons, replacing the loading message
            view = MapSettingsPreviewView(self.cog, self.guild_id, preview_settings, self.original_interaction)
            
            filename = f"map_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await interaction.edit_original_response(
                embed=embed,
                attachments=[discord.File(preview_image, filename=filename)],
                view=view
            )
            
        except Exception as e:
            self.cog.log.error(f"Error generating preview: {e}")
            error_embed = discord.Embed(
                title="âŒ Preview Error",
                description="An error occurred while generating the preview.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

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

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.secondary, emoji="❌")
    async def disable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_proximity(interaction, False)

    async def _set_proximity(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer()
        
        guild_id = str(self.guild_id)
        if guild_id not in self.cog.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return
        
        # Update setting
        self.cog.maps[guild_id]['allow_proximity'] = enabled
        await self.cog._save_data(guild_id)
        
        # Update button styles
        self.enable_button.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary
        self.disable_button.style = discord.ButtonStyle.danger if not enabled else discord.ButtonStyle.secondary
        
        # Update the view
        embed = discord.Embed(
            title="📍 Proximity Search Settings",
            description=f"Proximity search is now **{'enabled' if enabled else 'disabled'}** for this server.",
            color=0x00ff44 if enabled else 0xff4444
        )
        
        await interaction.edit_original_response(embed=embed, view=self)


class MapSettingsPreviewView(discord.ui.View):
    """View for confirming or adjusting map settings after preview."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int, preview_settings: Dict, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.preview_settings = preview_settings
        self.original_interaction = original_interaction

    @discord.ui.button(label="Apply Settings", style=discord.ButtonStyle.success, emoji="✅")
    async def apply_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show saving configuration loading message
        saving_embed = discord.Embed(
            title="💾 Saving Configuration",
            description="Saving the configuration and rendering base map...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=saving_embed, attachments=[], view=None)
    
        try:
            guild_id = str(self.guild_id)
        
            if guild_id not in self.cog.maps:
                await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
                return
            
            # Apply the preview settings
            if 'settings' not in self.cog.maps[guild_id]:
                self.cog.maps[guild_id]['settings'] = {}
        
            self.cog.maps[guild_id]['settings']['colors'] = self.preview_settings['colors']
            self.cog.maps[guild_id]['settings']['borders'] = self.preview_settings['borders']
            self.cog.maps[guild_id]['settings']['pins'] = self.preview_settings['pins']
        
            # Save changes
            await self.cog._save_data(guild_id)
        
            # Invalidate caches
            await self.cog.storage.invalidate_base_map_cache_only(int(guild_id))
            await self.cog.storage.invalidate_final_map_cache_only(int(guild_id))
        
            # Generate new base map with custom settings
            map_data = self.cog.maps[guild_id]
            region = map_data.get('region', 'world')
            width, height = self.cog.map_generator.calculate_image_dimensions(region)
            if region != "germany" and region != "usmainland":
                height = int(height * 0.8)
        
            self.cog.log.info(f"Pre-generating base map with custom settings for guild {guild_id}")
            base_map, _ = await self.cog.map_generator.render_geopandas_map(
                region, width, height, guild_id, self.cog.maps
            )
        
            if base_map:
                await self.cog.storage.cache_base_map(region, width, height, base_map, guild_id, self.cog.maps)
                self.cog.log.info(f"Pre-cached base map with custom settings for guild {guild_id}")
        
            channel_id = self.cog.maps[guild_id]['channel_id']
        
            # Try to use preview image for immediate update
            try:
                message = await self.original_interaction.original_response()
                if message.attachments:
                    preview_attachment = message.attachments[0]
                    preview_data = await preview_attachment.read()
                
                    channel = self.cog.bot.get_channel(channel_id)
                    if channel:
                        existing_message_id = self.cog.maps[guild_id].get('message_id')
                        if existing_message_id:
                            try:
                                map_message = await channel.fetch_message(existing_message_id)
                                
                                from core.map_views import MapPinButtonView
                                region = self.cog.maps[guild_id].get('region', 'world')
                                map_view = MapPinButtonView(self.cog, region, int(guild_id))
                                
                                filename = f"map_{region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                                await map_message.edit(
                                    attachments=[discord.File(BytesIO(preview_data), filename=filename)],
                                    view=map_view
                                )
                            
                                self.cog.log.info(f"Updated main map using preview image for guild {guild_id}")
                            except Exception as e:
                                self.cog.log.warning(f"Could not update main map with preview: {e}")
                                await self.cog._update_map(int(guild_id), channel_id)
                        else:
                            await self.cog._update_map(int(guild_id), channel_id)
                    else:
                        await self.cog._update_map(int(guild_id), channel_id)
                else:
                    await self.cog._update_map(int(guild_id), channel_id)
            except Exception as e:
                self.cog.log.warning(f"Error using preview for main map update: {e}")
                await self.cog._update_map(int(guild_id), channel_id)
        
            await self.cog._update_global_overview()
        
            # Show success message
            success_embed = discord.Embed(
                title="✅ Configuration Saved Successfully",
                description="Your map has been updated with the new settings!\nBase map pre-cached for faster future updates.",
                color=0x00ff44
            )
            success_embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
        
            await interaction.edit_original_response(embed=success_embed, attachments=[], view=None)
        
        except Exception as e:
            self.cog.log.error(f"Error applying settings: {e}")
            error_embed = discord.Embed(
                title="❌ Configuration Error",
                description="An error occurred while saving the configuration.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

    @discord.ui.button(label="Adjust Settings", style=discord.ButtonStyle.secondary, emoji="🔧")
    async def adjust_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show the settings modal again with current preview settings
        modal = AdminSettingsModal(self.cog, self.guild_id, self.original_interaction, self.preview_settings)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Settings Cancelled",
            description="No changes were made to the map.",
            color=0xff4444
        )
        await interaction.response.edit_message(embed=embed, attachments=[], view=None)


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
                title="❌ Error",
                description="No map exists for this server.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=embed, view=None)
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

        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Deletion Cancelled",
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
            row=1
        )
        clear_cache_button.callback = self.clear_cache
        self.add_item(clear_cache_button)

    @discord.ui.button(label="Customize Map", style=discord.ButtonStyle.primary, emoji="🎨")
    async def customize_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Load current settings from map data (not preview settings)
        modal = AdminSettingsModal(self.cog, self.guild_id, interaction, preview_settings=None)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Proximity Settings", style=discord.ButtonStyle.secondary, emoji="📍")
    async def proximity_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📍 Proximity Search Settings",
            description="Enable or disable proximity search for this server.",
            color=0x7289da
        )
        
        view = ProximitySettingsView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Delete Map", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠️ Confirm Map Deletion",
            description="**This action cannot be undone!**\n\nDeleting the map will:\n• Remove all user pins\n• Delete the map message\n• Clear all custom settings\n\nAre you sure you want to proceed?",
            color=0xff4444
        )
        
        view = MapRemovalConfirmView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def clear_cache(self, interaction: discord.Interaction):
        """Clear guild-specific cached maps."""
        await interaction.response.defer()
        
        try:
            # Clear cache for this specific guild
            await self.cog._invalidate_map_cache(self.guild_id)
            
            embed = discord.Embed(
                title="✅ Cache Cleared",
                description="Cached maps for this server have been cleared. The map will be regenerated with current settings.",
                color=0x00ff44
            )
            
            await interaction.edit_original_response(embed=embed, view=None)
            
        except Exception as e:
            self.cog.log.error(f"Error clearing guild cache: {e}")
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to clear cache.",
                color=0xff4444
            )
            await interaction.edit_original_response(embed=embed, view=None)
