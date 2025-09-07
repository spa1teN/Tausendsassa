"""Improved Discord UI Views with dynamic buttons and update logic."""

import discord
from datetime import datetime
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


class AdminSettingsModal(discord.ui.Modal, title='Map Admin Settings'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        
        # Load current settings
        map_data = self.cog.maps.get(str(guild_id), {})
        settings = map_data.get('settings', {})
        
        # Pre-fill with current values
        self.proximity_enabled.default = "true" if map_data.get('allow_proximity', True) else "false"
        
        colors = settings.get('colors', {})
        land_color = colors.get('land', self.cog.map_generator.map_config.DEFAULT_LAND_COLOR)
        water_color = colors.get('water', self.cog.map_generator.map_config.DEFAULT_WATER_COLOR)
        
        self.land_color.default = f"{land_color[0]},{land_color[1]},{land_color[2]}"
        self.water_color.default = f"{water_color[0]},{water_color[1]},{water_color[2]}"
        
        pins = settings.get('pins', {})
        self.pin_color.default = pins.get('color', self.cog.map_generator.map_config.DEFAULT_PIN_COLOR)
        self.pin_size.default = str(pins.get('size', self.cog.map_generator.map_config.DEFAULT_PIN_SIZE))

    proximity_enabled = discord.ui.TextInput(
        label='Proximity Search Enabled',
        placeholder='true or false',
        required=True,
        max_length=5
    )
    
    land_color = discord.ui.TextInput(
        label='Land Color (R,G,B)',
        placeholder='240,240,220',
        required=False,
        max_length=20
    )
    
    water_color = discord.ui.TextInput(
        label='Water Color (R,G,B)', 
        placeholder='168,213,242',
        required=False,
        max_length=20
    )
    
    pin_color = discord.ui.TextInput(
        label='Pin Color (Hex)',
        placeholder='#FF4444',
        required=False,
        max_length=7
    )
    
    pin_size = discord.ui.TextInput(
        label='Pin Size',
        placeholder='16',
        required=False,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild_id = str(self.guild_id)
            
            # Validate and parse proximity setting
            prox_input = self.proximity_enabled.value.lower().strip()
            if prox_input not in ['true', 'false']:
                await interaction.followup.send("❌ Proximity setting must be 'true' or 'false'", ephemeral=True)
                return
            
            proximity_enabled = prox_input == 'true'
            
            # Parse and validate colors
            def parse_rgb(color_str: str, default: tuple) -> tuple:
                if not color_str.strip():
                    return default
                try:
                    parts = [int(x.strip()) for x in color_str.split(',')]
                    if len(parts) != 3 or not all(0 <= x <= 255 for x in parts):
                        return default
                    return tuple(parts)
                except:
                    return default
            
            land_color = parse_rgb(self.land_color.value, self.cog.map_generator.map_config.DEFAULT_LAND_COLOR)
            water_color = parse_rgb(self.water_color.value, self.cog.map_generator.map_config.DEFAULT_WATER_COLOR)
            
            # Validate pin color
            pin_color = self.pin_color.value.strip()
            if not pin_color:
                pin_color = self.cog.map_generator.map_config.DEFAULT_PIN_COLOR
            elif not pin_color.startswith('#') or len(pin_color) != 7:
                pin_color = self.cog.map_generator.map_config.DEFAULT_PIN_COLOR
            
            # Validate pin size
            try:
                pin_size = int(self.pin_size.value.strip()) if self.pin_size.value.strip() else self.cog.map_generator.map_config.DEFAULT_PIN_SIZE
                if pin_size < 5 or pin_size > 50:
                    pin_size = self.cog.map_generator.map_config.DEFAULT_PIN_SIZE
            except:
                pin_size = self.cog.map_generator.map_config.DEFAULT_PIN_SIZE
            
            # Update map data
            if guild_id not in self.cog.maps:
                await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
                return
            
            # Update settings
            self.cog.maps[guild_id]['allow_proximity'] = proximity_enabled
            
            if 'settings' not in self.cog.maps[guild_id]:
                self.cog.maps[guild_id]['settings'] = {}
            
            self.cog.maps[guild_id]['settings']['colors'] = {
                'land': land_color,
                'water': water_color
            }
            
            self.cog.maps[guild_id]['settings']['pins'] = {
                'color': pin_color,
                'size': pin_size
            }
            
            # Save changes
            await self.cog._save_data(guild_id)
            
            # Invalidate cache and update map
            await self.cog._invalidate_map_cache(int(guild_id))
            channel_id = self.cog.maps[guild_id]['channel_id']
            await self.cog._update_map(int(guild_id), channel_id)
            
            # Create success embed
            embed = discord.Embed(
                title="⚙️ Map Settings Updated",
                description="Map configuration has been successfully updated!",
                color=0x00ff44
            )
            
            embed.add_field(
                name="Proximity Search", 
                value="✅ Enabled" if proximity_enabled else "❌ Disabled", 
                inline=True
            )
            embed.add_field(
                name="Land Color", 
                value=f"RGB({land_color[0]}, {land_color[1]}, {land_color[2]})", 
                inline=True
            )
            embed.add_field(
                name="Water Color", 
                value=f"RGB({water_color[0]}, {water_color[1]}, {water_color[2]})", 
                inline=True
            )
            embed.add_field(
                name="Pin Color", 
                value=pin_color, 
                inline=True
            )
            embed.add_field(
                name="Pin Size", 
                value=str(pin_size), 
                inline=True
            )
            embed.add_field(
                name="Map Updated", 
                value=f"<#{channel_id}>", 
                inline=True
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.cog.log.error(f"Error updating admin settings: {e}")
            await interaction.followup.send("❌ Error updating settings", ephemeral=True)


class MapRemovalConfirmView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Yes, Delete Map", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(self.guild_id)
        
        if guild_id not in self.cog.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
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

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Deletion Cancelled",
            description="The map was not deleted.",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=embed, view=None)


class ContinentSelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

    @discord.ui.button(label="N. America", style=discord.ButtonStyle.secondary, row=0)
    async def north_america(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "northamerica", "North America")

    @discord.ui.button(label="S. America", style=discord.ButtonStyle.secondary, row=0)
    async def south_america(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "southamerica", "South America")

    @discord.ui.button(label="Europe", style=discord.ButtonStyle.secondary, row=0)
    async def europe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "europe", "Europe")

    @discord.ui.button(label="Africa", style=discord.ButtonStyle.secondary, row=1)
    async def africa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "africa", "Africa")

    @discord.ui.button(label="Asia", style=discord.ButtonStyle.secondary, row=1)
    async def asia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "asia", "Asia")

    @discord.ui.button(label="Australia", style=discord.ButtonStyle.secondary, row=1)
    async def australia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "australia", "Australia")

    async def _generate_continent(self, interaction: discord.Interaction, continent: str, display_name: str):
        await interaction.response.defer()
        
        try:
            continent_image = await self.cog._generate_continent_closeup(self.guild_id, continent)
            if continent_image:
                filename = f"continent_{continent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                # Edit the original message instead of creating new one
                await self.original_interaction.edit_original_response(
                    content=f"🌍 **Close-up view of {display_name}**",
                    attachments=[discord.File(continent_image, filename=filename)],
                    view=None
                )
            else:
                await interaction.followup.send(
                    f"❌ Could not generate map for {display_name}",
                    ephemeral=True
                )
        except Exception as e:
            self.cog.log.error(f"Error generating continent map: {e}")
            await interaction.followup.send("❌ Error generating continent map", ephemeral=True)


class StateSelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # German states as buttons (max 25 buttons per view)
        states = [
            ("Baden-Württemberg", "Baden-Württemberg"),
            ("Bayern", "Bayern"),
            ("Berlin", "Berlin"),
            ("Brandenburg", "Brandenburg"),
            ("Bremen", "Bremen"),
            ("Hamburg", "Hamburg"),
            ("Hessen", "Hessen"),
            ("Mecklenburg-Vorpommern", "M-V"),
            ("Niedersachsen", "Niedersachsen"),
            ("Nordrhein-Westfalen", "NRW"),
            ("Rheinland-Pfalz", "R-Pfalz"),
            ("Saarland", "Saarland"),
            ("Sachsen", "Sachsen"),
            ("Sachsen-Anhalt", "S-Anhalt"),
            ("Schleswig-Holstein", "S-Holstein"),
            ("Thüringen", "Thüringen")
        ]
        
        # Add buttons dynamically (5 per row, max 5 rows)
        for i, (full_name, short_name) in enumerate(states):
            row = i // 5
            if row >= 5:  # Discord limit
                break
            
            button = discord.ui.Button(
                label=short_name,
                style=discord.ButtonStyle.secondary,
                row=row
            )
            button.callback = self._create_state_callback(full_name)
            self.add_item(button)

    def _create_state_callback(self, state_name: str):
        async def state_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            
            try:
                state_image = await self.cog._generate_state_closeup(self.guild_id, state_name)
                if state_image:
                    filename = f"state_{state_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    
                    # Edit the original message instead of creating new one
                    await self.original_interaction.edit_original_response(
                        content=f"🏛️ **Close-up view of {state_name}**",
                        attachments=[discord.File(state_image, filename=filename)],
                        view=None
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Could not generate map for {state_name}",
                        ephemeral=True
                    )
            except Exception as e:
                self.cog.log.error(f"Error generating state map: {e}")
                await interaction.followup.send("❌ Error generating state map", ephemeral=True)
        
        return state_callback


class AdminToolsView(discord.ui.View):
    """Admin Tools interface for map management."""
    
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Customize Map", style=discord.ButtonStyle.primary, emoji="🎨")
    async def customize_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AdminSettingsModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Map", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠️ Confirm Map Deletion",
            description="**This action cannot be undone!**\n\nDeleting the map will:\n• Remove all user pins\n• Delete the map message\n• Clear all custom settings\n\nAre you sure you want to proceed?",
            color=0xff4444
        )
        
        view = MapRemovalConfirmView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


class MapMenuView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, user: discord.Member):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.user = user
        
        # Get current map data to determine button visibility
        map_data = self.cog.maps.get(str(guild_id), {})
        region = map_data.get('region', 'world')
        allow_proximity = map_data.get('allow_proximity', False)
        
        # Only add proximity button if enabled
        if allow_proximity:
            self._add_proximity_button()
        
        # Only add close-up button for supported regions
        if region in ["world", "germany"]:
            self._add_closeup_button()
            
        # Always add info button
        self._add_info_button()
        
        # Add admin tools button if user has admin permissions
        if user.guild_permissions.administrator:
            self._add_admin_tools_button()

    def _add_proximity_button(self):
        proximity_button = discord.ui.Button(
            label="Nearby",
            style=discord.ButtonStyle.secondary,
            emoji="📍"
        )
        proximity_button.callback = self.nearby_members
        self.add_item(proximity_button)

    def _add_closeup_button(self):
        closeup_button = discord.ui.Button(
            label="Close-up",
            style=discord.ButtonStyle.secondary,
            emoji="🔍"
        )
        closeup_button.callback = self.region_closeup
        self.add_item(closeup_button)
        
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
        await interaction.response.defer(ephemeral=True)

        guild_id = str(self.guild_id)
        
        if guild_id not in self.cog.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
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

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def region_closeup(self, interaction: discord.Interaction):
        # Get current map data dynamically
        map_data = self.cog.maps.get(str(self.guild_id), {})
        region = map_data.get('region', 'world')
        
        if region == "world":
            # Show continent selection buttons
            view = ContinentSelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🌍 Select a continent for close-up view:**", 
                view=view
            )
        elif region == "germany":
            # Show state selection buttons
            view = StateSelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🏛️ Select a German state for close-up view:**", 
                view=view
            )
        else:
            await interaction.response.send_message(
                "❌ Region close-up is not available for this map type.", 
                ephemeral=True
            )

    async def nearby_members(self, interaction: discord.Interaction):
        # Get current map data dynamically
        map_data = self.cog.maps.get(str(self.guild_id), {})
        
        # Double-check if proximity is enabled (shouldn't be needed but safety first)
        if not map_data.get('allow_proximity', False):
            await interaction.response.send_message(
                "Proximity search is disabled for this map.", 
                ephemeral=True
            )
            return
        
        # Check if user has a pin
        user_id = str(interaction.user.id)
        if user_id not in map_data.get('pins', {}):
            await interaction.response.send_message(
                "You need to pin your location first to search for nearby members!",
                ephemeral=True
            )
            return
        
        # Show proximity modal
        modal = ProximityModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        """Disable all buttons when the view times out."""
        for item in self.children:
            item.disabled = True


class MapPinButtonView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', region: str, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.region = region
        self.guild_id = guild_id

    @discord.ui.button(
        label="📍 My Pin",
        style=discord.ButtonStyle.primary,
        custom_id="map_pin_button"
    )
    async def pin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user already has a pin
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        if guild_id in self.cog.maps and user_id in self.cog.maps[guild_id].get('pins', {}):
            # User has a pin - show current location and options
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
            # User doesn't have a pin - show modal directly
            await interaction.response.send_modal(LocationModal(self.cog, int(guild_id)))

    @discord.ui.button(
        label="...",
        style=discord.ButtonStyle.secondary,
        custom_id="map_menu_button"
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create view with user parameter for admin check
        view = MapMenuView(self.cog, int(interaction.guild.id), interaction.user)
        await interaction.response.send_message(content="**Select an option:**", view=view, ephemeral=True)


class UserPinOptionsView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self._original_response = None  # Store original response for updating

    @discord.ui.button(
        label="Change",
        style=discord.ButtonStyle.primary,
        emoji="🔄"
    )
    async def change_location(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Store the original response for updating later
        self._original_response = interaction.response
        
        modal = UpdateLocationModal(self.cog, self.guild_id, interaction)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Remove ",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def remove_location(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        if guild_id not in self.cog.maps:
            await interaction.followup.send("❌ No map for this server.", ephemeral=True)
            return

        if user_id not in self.cog.maps[guild_id]['pins']:
            await interaction.followup.send("❌ You don't have a pin on the map.", ephemeral=True)
            return

        old_location = self.cog.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')
        del self.cog.maps[guild_id]['pins'][user_id]
        await self.cog._save_data(guild_id)
        
        # Invalidate cache since pins changed
        await self.cog._invalidate_map_cache(int(guild_id))
        
        channel_id = self.cog.maps[guild_id]['channel_id']
        await self.cog._update_map(int(guild_id), channel_id)
        await self.cog._update_global_overview()

        # Create embed for removal confirmation
        embed = discord.Embed(
            title="🗑️ Pin Removed",
            description=f"Your pin has been successfully removed from the map.",
            color=0xff4444
        )
        embed.add_field(name="Removed Location", value=old_location, inline=False)
        embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def on_timeout(self):
        """Disable all buttons when the view times out."""
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
        
        # Handle the location update
        result = await self.cog._handle_pin_location_update(
            interaction, 
            self.location.value, 
            self.original_interaction
        )


# Import the new modals
from .improved_modals import ProximityModal