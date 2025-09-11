"""User Views for Discord Map Bot."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional
from io import BytesIO

if TYPE_CHECKING:
    from cogs.map import MapV2Cog

# Import admin views and proximity modal
from .map_views_admin import AdminToolsView
from .map_improved_modals import ProximityModal


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
    
    @discord.ui.button(label="🌎 N. American Countries", style=discord.ButtonStyle.primary, row=3)
    async def north_american_countries(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = NorthAmericanCountrySelectionView(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.edit_message(
            content="**🌎 Select a North American country for close-up view:**", 
            view=view
        )
    
    @discord.ui.button(label="🌎 S. American Countries", style=discord.ButtonStyle.primary, row=4)
    async def south_american_countries(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SouthAmericanCountrySelectionView(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.edit_message(
            content="**🌎 Select a South American country for close-up view:**", 
            view=view
        )

    @discord.ui.button(label="Europe", style=discord.ButtonStyle.secondary, row=0)
    async def europe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "europe", "Europe")
    
    @discord.ui.button(label="🇪🇺 EU Countries", style=discord.ButtonStyle.primary, row=2)
    async def european_countries(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EuropeanCountrySelectionView(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.edit_message(
            content="**🇪🇺 Select a European country for close-up view:**", 
            view=view
        )

    @discord.ui.button(label="Africa", style=discord.ButtonStyle.secondary, row=1)
    async def africa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "africa", "Africa")

    @discord.ui.button(label="Asia", style=discord.ButtonStyle.secondary, row=1)
    async def asia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "asia", "Asia")
    
    @discord.ui.button(label="🌏 Asian Countries", style=discord.ButtonStyle.primary, row=2)
    async def asian_countries(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AsianCountrySelectionView(self.cog, self.guild_id, self.original_interaction)
        await interaction.response.edit_message(
            content="**🌏 Select an Asian country for close-up view:**", 
            view=view
        )

    @discord.ui.button(label="Australia", style=discord.ButtonStyle.secondary, row=1)
    async def australia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._generate_continent(interaction, "australia", "Australia")

    async def _generate_continent(self, interaction: discord.Interaction, continent: str, display_name: str):
        # Show loading message immediately and clear previous content
        loading_embed = discord.Embed(
            title="🌍 Generating Close-up",
            description="Just a moment, I'm generating the continent close-up view...",
            color=0x7289da
        )
        # Replace both content and embed, clear view
        await interaction.response.edit_message(
            content=None,  # Clear the selection text
            embed=loading_embed,
            view=None
        )
        
        try:
            # Use centralized progress handler
            from core.map_progress_handler import create_closeup_progress_callback
            progress_callback = await create_closeup_progress_callback(interaction, display_name, self.cog.log)
            
            continent_image = await self.cog._generate_continent_closeup(self.guild_id, continent, progress_callback)
            if continent_image:
                filename = f"continent_{continent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                # Replace loading message with the actual image
                await self.original_interaction.edit_original_response(
                    content=f"🌍 **Close-up view of {display_name}**",
                    embed=None,  # Clear the loading embed
                    attachments=[discord.File(continent_image, filename=filename)],
                    view=None
                )
            else:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description=f"Could not generate map for {display_name}",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,  # Clear any content
                    embed=error_embed,
                    view=None
                )
        except Exception as e:
            self.cog.log.error(f"Error generating continent map: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the continent close-up view.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(
                content=None,  # Clear any content
                embed=error_embed,
                view=None
            )


class EuropeanCountrySelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # European countries ordered by population (25 most populous)
        # Using only flag emojis as labels, removing country names
        countries = [
            ("🇷🇺", "Russia", "russia"),  # 144M
            ("🇩🇪", "Germany", "germany"),  # 84M  
            ("🇬🇧", "United Kingdom", "unitedkingdom"),  # 67M
            ("🇫🇷", "France", "france"),  # 68M
            ("🇮🇹", "Italy", "italy"),  # 60M
            ("🇪🇸", "Spain", "spain"),  # 47M
            ("🇺🇦", "Ukraine", "ukraine"),  # 44M
            ("🇵🇱", "Poland", "poland"),  # 38M
            ("🇷🇴", "Romania", "romania"),  # 19M
            ("🇳🇱", "Netherlands", "netherlands"),  # 17M
            ("🇧🇪", "Belgium", "belgium"),  # 11M
            ("🇬🇷", "Greece", "greece"),  # 11M
            ("🇨🇿", "Czech Republic", "czech"),  # 11M
            ("🇵🇹", "Portugal", "portugal"),  # 10M
            ("🇸🇪", "Sweden", "sweden"),  # 10M
            ("🇭🇺", "Hungary", "hungary"),  # 10M
            ("🇦🇹", "Austria", "austria"),  # 9M
            ("🇧🇬", "Bulgaria", "bulgaria"),  # 7M
            ("🇨🇭", "Switzerland", "switzerland"),  # 9M
            ("🇸🇰", "Slovakia", "slovakia"),  # 5M
            ("🇳🇴", "Norway", "norway"),  # 5M
            ("🇫🇮", "Finland", "finland"),  # 5M
            ("🇮🇪", "Ireland", "ireland"),  # 5M
            ("🇭🇷", "Croatia", "croatia"),  # 4M
            ("🇸🇮", "Slovenia", "slovenia"),  # 2M
        ]
        
        # Add buttons (max 25 components per view) - only using flag emojis, no text labels
        for i, (flag, name, value) in enumerate(countries):
            if i >= 25:  # Discord limit
                break
            row = i // 5  # 5 buttons per row
            
            button = discord.ui.Button(
                label="",  # Empty label, only flag emoji
                style=discord.ButtonStyle.secondary,
                emoji=flag,
                row=row
            )
            button.callback = self._create_country_callback(value, name)
            self.add_item(button)

    def _create_country_callback(self, country_code: str, country_name: str):
        async def country_callback(interaction: discord.Interaction):
            await self._generate_country(interaction, country_code, country_name)
        return country_callback

    async def _generate_country(self, interaction: discord.Interaction, country: str, display_name: str):
        # Show loading message immediately and clear previous content
        loading_embed = discord.Embed(
            title="🗺️ Generating Country Map",
            description=f"Just a moment, I'm generating the {display_name} map...",
            color=0x7289da
        )
        await interaction.response.edit_message(
            content=None,
            embed=loading_embed,
            view=None
        )
        
        try:
            # Use centralized progress handler
            from core.map_progress_handler import create_closeup_progress_callback
            progress_callback = await create_closeup_progress_callback(interaction, display_name, self.cog.log)
            
            country_image = await self.cog._generate_continent_closeup(self.guild_id, country, progress_callback)
            if country_image:
                filename = f"country_{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                # Replace loading message with the actual image
                await self.original_interaction.edit_original_response(
                    content=f"🗺️ **{display_name} Map**",
                    embed=None,
                    attachments=[discord.File(country_image, filename=filename)],
                    view=None
                )
            else:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description=f"Could not generate map for {display_name}",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,
                    embed=error_embed,
                    view=None
                )
        except Exception as e:
            self.cog.log.error(f"Error generating country map: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the country map.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(
                content=None,
                embed=error_embed,
                view=None
            )


class AsianCountrySelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # Asian countries ordered by population (most populous in Asia/partial Asia)
        # Using only flag emojis as labels, removing country names  
        countries = [
            ("🇨🇳", "China", "china"),  # 1.4B - need to add
            ("🇮🇳", "India", "india"),  # 1.4B - need to add  
            ("🇮🇩", "Indonesia", "indonesia"),  # 275M - need to add
            ("🇵🇰", "Pakistan", "pakistan"),  # 240M - need to add
            ("🇧🇩", "Bangladesh", "bangladesh"),  # 170M - need to add
            ("🇯🇵", "Japan", "japan"),  # 125M
            ("🇵🇭", "Philippines", "philippines"),  # 115M - need to add
            ("🇻🇳", "Vietnam", "vietnam"),  # 98M - need to add  
            ("🇹🇷", "Turkey", "turkey"),  # 85M
            ("🇮🇷", "Iran", "iran"),  # 85M - need to add
            ("🇩🇪", "Germany", "germany"),  # 84M (partial coverage in Russia)
            ("🇹🇭", "Thailand", "thailand"),  # 70M - need to add
            ("🇰🇷", "South Korea", "southkorea"),  # 52M
            ("🇲🇾", "Malaysia", "malaysia"),  # 35M - need to add
            ("🇺🇿", "Uzbekistan", "uzbekistan"),  # 35M - need to add
            ("🇸🇦", "Saudi Arabia", "saudiarabia"),  # 35M - need to add
            ("🇮🇶", "Iraq", "iraq"),  # 45M - need to add
            ("🇦🇫", "Afghanistan", "afghanistan"),  # 40M - need to add
            ("🇰🇿", "Kazakhstan", "kazakhstan"),  # 20M - need to add
            ("🇲🇲", "Myanmar", "myanmar"),  # 55M - need to add
            ("🇱🇰", "Sri Lanka", "srilanka"),  # 22M - need to add
            ("🇰🇭", "Cambodia", "cambodia"),  # 17M - need to add
            ("🇯🇴", "Jordan", "jordan"),  # 11M - need to add
            ("🇦🇿", "Azerbaijan", "azerbaijan"),  # 10M - need to add
            ("🇹🇯", "Tajikistan", "tajikistan"),  # 10M - need to add
        ]
        
        # For now, only include countries we have configs for
        available_countries = [
            ("🇯🇵", "Japan", "japan"), 
            ("🇰🇷", "South Korea", "southkorea"),
            ("🇷🇺", "Russia", "russia"),
            ("🇹🇷", "Turkey", "turkey"),
        ]
        
        for i, (flag, name, value) in enumerate(available_countries):
            button = discord.ui.Button(
                label="",  # Empty label, only flag emoji
                style=discord.ButtonStyle.secondary,
                emoji=flag,
                row=0
            )
            button.callback = self._create_country_callback(value, name)
            self.add_item(button)

    def _create_country_callback(self, country_code: str, country_name: str):
        async def country_callback(interaction: discord.Interaction):
            await self._generate_country(interaction, country_code, country_name)
        return country_callback

    async def _generate_country(self, interaction: discord.Interaction, country: str, display_name: str):
        loading_embed = discord.Embed(
            title="🗺️ Generating Country Map",
            description=f"Just a moment, I'm generating the {display_name} map...",
            color=0x7289da
        )
        await interaction.response.edit_message(
            content=None,
            embed=loading_embed,
            view=None
        )
        
        try:
            from core.map_progress_handler import create_closeup_progress_callback
            progress_callback = await create_closeup_progress_callback(interaction, display_name, self.cog.log)
            
            country_image = await self.cog._generate_continent_closeup(self.guild_id, country, progress_callback)
            if country_image:
                filename = f"country_{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                await self.original_interaction.edit_original_response(
                    content=f"🗺️ **{display_name} Map**",
                    embed=None,
                    attachments=[discord.File(country_image, filename=filename)],
                    view=None
                )
            else:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description=f"Could not generate map for {display_name}",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,
                    embed=error_embed,
                    view=None
                )
        except Exception as e:
            self.cog.log.error(f"Error generating country map: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the country map.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(
                content=None,
                embed=error_embed,
                view=None
            )


class NorthAmericanCountrySelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # North American countries with their flags (by population)
        # Using only flag emojis as labels, removing country names
        countries = [
            ("🇺🇸", "United States", "usmainland"), 
            ("🇲🇽", "Mexico", "mexico"),
            ("🇨🇦", "Canada", "canada"),
        ]
        
        for i, (flag, name, value) in enumerate(countries):
            button = discord.ui.Button(
                label="",  # Empty label, only flag emoji
                style=discord.ButtonStyle.secondary,
                emoji=flag,
                row=0
            )
            button.callback = self._create_country_callback(value, name)
            self.add_item(button)

    def _create_country_callback(self, country_code: str, country_name: str):
        async def country_callback(interaction: discord.Interaction):
            await self._generate_country(interaction, country_code, country_name)
        return country_callback

    async def _generate_country(self, interaction: discord.Interaction, country: str, display_name: str):
        loading_embed = discord.Embed(
            title="🗺️ Generating Country Map",
            description=f"Just a moment, I'm generating the {display_name} map...",
            color=0x7289da
        )
        await interaction.response.edit_message(
            content=None,
            embed=loading_embed,
            view=None
        )
        
        try:
            from core.map_progress_handler import create_closeup_progress_callback
            progress_callback = await create_closeup_progress_callback(interaction, display_name, self.cog.log)
            
            country_image = await self.cog._generate_continent_closeup(self.guild_id, country, progress_callback)
            if country_image:
                filename = f"country_{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                await self.original_interaction.edit_original_response(
                    content=f"🗺️ **{display_name} Map**",
                    embed=None,
                    attachments=[discord.File(country_image, filename=filename)],
                    view=None
                )
            else:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description=f"Could not generate map for {display_name}",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,
                    embed=error_embed,
                    view=None
                )
        except Exception as e:
            self.cog.log.error(f"Error generating country map: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the country map.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(
                content=None,
                embed=error_embed,
                view=None
            )


class SouthAmericanCountrySelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # South American countries with their flags (by population)  
        # Using only flag emojis as labels, removing country names
        countries = [
            ("🇧🇷", "Brazil", "brazil"),
            # Add more South American countries here when we have configs for them
        ]
        
        for i, (flag, name, value) in enumerate(countries):
            button = discord.ui.Button(
                label="",  # Empty label, only flag emoji
                style=discord.ButtonStyle.secondary,
                emoji=flag,
                row=0
            )
            button.callback = self._create_country_callback(value, name)
            self.add_item(button)

    def _create_country_callback(self, country_code: str, country_name: str):
        async def country_callback(interaction: discord.Interaction):
            await self._generate_country(interaction, country_code, country_name)
        return country_callback

    async def _generate_country(self, interaction: discord.Interaction, country: str, display_name: str):
        loading_embed = discord.Embed(
            title="🗺️ Generating Country Map",
            description=f"Just a moment, I'm generating the {display_name} map...",
            color=0x7289da
        )
        await interaction.response.edit_message(
            content=None,
            embed=loading_embed,
            view=None
        )
        
        try:
            from core.map_progress_handler import create_closeup_progress_callback
            progress_callback = await create_closeup_progress_callback(interaction, display_name, self.cog.log)
            
            country_image = await self.cog._generate_continent_closeup(self.guild_id, country, progress_callback)
            if country_image:
                filename = f"country_{country}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                await self.original_interaction.edit_original_response(
                    content=f"🗺️ **{display_name} Map**",
                    embed=None,
                    attachments=[discord.File(country_image, filename=filename)],
                    view=None
                )
            else:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description=f"Could not generate map for {display_name}",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,
                    embed=error_embed,
                    view=None
                )
        except Exception as e:
            self.cog.log.error(f"Error generating country map: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the country map.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(
                content=None,
                embed=error_embed,
                view=None
            )


class StateSelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction
        
        # Get German states from config with actual emojis
        states_config = self.cog.map_generator.map_config.GERMAN_STATES
        
        # Add buttons dynamically (5 per row, max 5 rows)
        for i, (full_name, state_data) in enumerate(states_config.items()):
            row = i // 4
            if row >= 4:  # Discord limit
                break
            
            # Create button with actual emoji from config
            emoji_id = state_data.get('emoji_id')
            # Use the actual emoji format if available
            emoji = f"<:coat_{state_data['short'].lower()}:{emoji_id}>" if emoji_id else None
            
            button = discord.ui.Button(
                label=state_data['short'],
                style=discord.ButtonStyle.secondary,
                emoji=emoji,
                row=row
            )
            button.callback = self._create_state_callback(full_name)
            self.add_item(button)

    def _create_state_callback(self, state_name: str):
        async def state_callback(interaction: discord.Interaction):
            # Get emoji for the loading message
            states_config = self.cog.map_generator.map_config.GERMAN_STATES
            state_data = states_config.get(state_name, {})
            emoji_id = state_data.get('emoji_id')
            emoji_str = f"<:coat_{state_data.get('short', 'state').lower()}:{emoji_id}>" if emoji_id else "🏛️"
            
            # Show loading message with state emoji and clear previous content
            loading_embed = discord.Embed(
                title=f"{emoji_str} Generating Close-up",
                description=f"Just a moment, I'm generating the {state_name} close-up view...",
                color=0x7289da
            )
            # Replace both content and embed, clear view
            await interaction.response.edit_message(
                content=None,  # Clear the selection text
                embed=loading_embed, 
                view=None
            )
            
            try:
                # Use centralized progress handler
                from core.map_progress_handler import create_closeup_progress_callback
                update_progress = await create_closeup_progress_callback(interaction, state_name, self.cog.log)
                
                state_image = await self.cog._generate_state_closeup(self.guild_id, state_name, update_progress)
                if state_image:
                    filename = f"state_{state_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    
                    # Replace loading message with the actual image
                    await self.original_interaction.edit_original_response(
                        content=f"{emoji_str} **Close-up view of {state_name}**",
                        embed=None,  # Clear the loading embed
                        attachments=[discord.File(state_image, filename=filename)],
                        view=None
                    )
                else:
                    error_embed = discord.Embed(
                        title="⛔ Generation Error",
                        description=f"Could not generate map for {state_name}",
                        color=0xff4444
                    )
                    await self.original_interaction.edit_original_response(
                        content=None,  # Clear any content
                        embed=error_embed, 
                        view=None
                    )
            except Exception as e:
                self.cog.log.error(f"Error generating state map: {e}")
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description="An error occurred while generating the close-up view.",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(
                    content=None,  # Clear any content
                    embed=error_embed, 
                    view=None
                )
        
        return state_callback


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
        supported_regions = ["world", "germany", "europe", "asia", "northamerica", "southamerica", 
                           "france", "spain", "italy", "poland", "netherlands", "belgium", "austria", 
                           "czech", "hungary", "portugal", "greece", "sweden", "norway", "denmark",
                           "finland", "romania", "bulgaria", "croatia", "slovenia", "slovakia", 
                           "ireland", "lithuania", "latvia", "estonia", "luxembourg", "malta", 
                           "cyprus", "switzerland", "ukraine", "russia", "turkey", "japan", 
                           "southkorea", "brazil", "canada", "mexico"]
        if region in supported_regions:
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
            emoji="🔍"
        )
        proximity_button.callback = self.nearby_members
        self.add_item(proximity_button)

    def _add_closeup_button(self):
        closeup_button = discord.ui.Button(
            label="Close-up",
            style=discord.ButtonStyle.secondary,
            emoji="🔎"
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
        elif region == "europe":
            # Show European country selection buttons
            view = EuropeanCountrySelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🇪🇺 Select a European country for close-up view:**", 
                view=view
            )
        elif region in ["asia", "japan", "southkorea", "russia", "turkey"]:
            # Show Asian country selection buttons
            view = AsianCountrySelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🌏 Select an Asian country for close-up view:**", 
                view=view
            )
        elif region in ["northamerica", "canada", "mexico", "usmainland"]:
            # Show North American country selection buttons
            view = NorthAmericanCountrySelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🌎 Select a North American country for close-up view:**", 
                view=view
            )
        elif region in ["southamerica", "brazil"]:
            # Show South American country selection buttons
            view = SouthAmericanCountrySelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🌎 Select a South American country for close-up view:**", 
                view=view
            )
        elif region in ["france", "spain", "italy", "poland", "netherlands", "belgium", "austria", 
                        "czech", "hungary", "portugal", "greece", "sweden", "norway", "denmark",
                        "finland", "romania", "bulgaria", "croatia", "slovenia", "slovakia", 
                        "ireland", "lithuania", "latvia", "estonia", "luxembourg", "malta", 
                        "cyprus", "switzerland", "ukraine"]:
            # For individual European countries, show other European countries
            view = EuropeanCountrySelectionView(self.cog, self.guild_id, interaction)
            await interaction.response.edit_message(
                content="**🇪🇺 Select another European country for close-up view:**", 
                view=view
            )
        else:
            embed = discord.Embed(
                title="⛔ Not Available",
                description="Region close-up is not available for this map type.",
                color=0xff4444
            )
            await interaction.response.edit_message(embed=embed, view=None)

    async def nearby_members(self, interaction: discord.Interaction):
        # Get current map data dynamically
        map_data = self.cog.maps.get(str(self.guild_id), {})
        
        # Double-check if proximity is enabled (shouldn't be needed but safety first)
        if not map_data.get('allow_proximity', False):
            embed = discord.Embed(
                title="⛔ Not Available",
                description="Proximity search is disabled for this map.",
                color=0xff4444
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return
        
        # Check if user has a pin
        user_id = str(interaction.user.id)
        if user_id not in map_data.get('pins', {}):
            embed = discord.Embed(
                title="⛔ No Pin Found",
                description="You need to pin your location first to search for nearby members!",
                color=0xff4444
            )
            await interaction.response.edit_message(embed=embed, view=None)
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
        # Remove "Select an option:" prefix for cleaner UX
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

        # Show loading message
        loading_embed = discord.Embed(
            title="🗺️ Updating Map",
            description="Removing pin and rendering updated map...",
            color=0x7289da
        )
        await interaction.edit_original_response(embed=loading_embed, view=None)

        old_location = self.cog.maps[guild_id]['pins'][user_id].get('location', 'Unknown')  # Use original location
        del self.cog.maps[guild_id]['pins'][user_id]
        await self.cog._save_data(guild_id)
        
        # OPTIMIZATION: Only Final Map Cache invalidieren, Base Map beibehalten
        await self.cog.storage.invalidate_final_map_cache_only(int(guild_id))
        self.cog.log.info(f"Pin removal for guild {guild_id}: preserved base map cache for efficiency")
        
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

        await interaction.edit_original_response(embed=embed, view=None)

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
        
        # Show loading message immediately
        loading_embed = discord.Embed(
            title="🗺️ Updating Map",
            description="Updating pin location and rendering updated map...",
            color=0x7289da
        )
        await self.original_interaction.edit_original_response(embed=loading_embed, view=None)
        
        # Handle the location update
        await self.cog._handle_pin_location_update(
            interaction, 
            self.location.value, 
            self.original_interaction
        )