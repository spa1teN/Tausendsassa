"""Simplified Map Cog for Discord Bot with modular structure and improved caching."""

import asyncio
import geopandas as gpd
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
import math
from shapely.geometry import box

# Import our modular components
from core.map_gen import MapGenerator
from core.map_storage import MapStorage
from core.map_proximity import ProximityCalculator
from core.map_views import MapPinButtonView, LocationModal, UserPinOptionsView
from core.map_views_admin import AdminToolsView
from core.map_config import MapConfig

# Import German timezone utilities
from core.timezone_util import get_german_time, format_german_time

# Constants
IMAGE_WIDTH = 1500
# BOT_OWNER_ID and PIN_COOLDOWN_MINUTES will be loaded from config in __init__


class MapV2Cog(commands.Cog):
    """Cog for managing maps with user pins displayed as images."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("map")
        
        # Import config here to avoid circular imports
        from core.config import config
        self.config = config
        
        # Setup directories
        self.data_dir = Path(__file__).parent.parent / "config"
        self.cache_dir = Path(__file__).parent.parent / "data/map_cache"
        
        # Initialize modular components
        self.storage = MapStorage(self.data_dir, self.cache_dir, self.log)
        self.map_generator = MapGenerator(self.data_dir, self.cache_dir, self.log)
        self.proximity_calc = ProximityCalculator(self.map_generator, self.log)
        
        # Load data and configs
        self.global_config = self.storage.load_global_config()
        self.maps = self.storage.load_all_data()
        
        # Cooldown tracking for pin updates
        self.pin_cooldowns = {}  # user_id -> last_update_timestamp
    
    def _is_user_on_cooldown(self, user_id: str) -> Tuple[bool, Optional[datetime]]:
        """Check if user is on cooldown for pin updates."""
        if user_id not in self.pin_cooldowns:
            return False, None
        
        last_update = self.pin_cooldowns[user_id]
        cooldown_expires = last_update + timedelta(minutes=self.config.pin_cooldown_minutes)
        
        if datetime.now() < cooldown_expires:
            return True, cooldown_expires
        else:
            # Cooldown expired, remove from tracking
            del self.pin_cooldowns[user_id]
            return False, None
    
    def _set_user_cooldown(self, user_id: str):
        """Set cooldown for user after pin update."""
        self.pin_cooldowns[user_id] = datetime.now()

    async def cog_load(self):
        """Called when the cog is loaded. Re-register persistent views."""
        try:
            # Clear base map cache on restart for fresh start
            self.storage.cache.memory_cache.clear()
            self.log.info("Cleared all base map cache on restart")
        
            # Register all persistent views for existing maps
            for guild_id, map_data in self.maps.items():
                # Get current region from map data
                region = map_data.get('region', 'world')
                view = MapPinButtonView(self, region, int(guild_id))
                self.bot.add_view(view)

                # Update existing map messages with correct view
                channel_id = map_data.get('channel_id')
                message_id = map_data.get('message_id')
                if channel_id and message_id:
                    try:
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                    
                            # Check if map has custom settings
                            has_custom_settings = bool(map_data.get('settings'))
                            if has_custom_settings:
                                # Force complete regeneration for custom maps
                                self.log.info(f"Force-regenerating map with custom settings for guild {guild_id}")
                            
                                # Invalidate ALL cache for this guild
                                await self._invalidate_map_cache(int(guild_id))
                            
                                # Force regeneration (will use custom settings)
                                await self._update_map(int(guild_id), channel_id)
                                self.log.info(f"Completed regeneration for guild {guild_id} with custom settings")
                            else:
                                # Just update the view for default maps
                                await message.edit(view=view)
                                self.log.info(f"Updated view for guild {guild_id} with region {region}")
                    except Exception as e:
                        self.log.warning(f"Could not update view for guild {guild_id}: {e}")

                self.log.info(f"Re-registered persistent view for guild {guild_id}")
        except Exception as e:
            self.log.error(f"Error re-registering views: {e}")

    async def _update_map(self, guild_id: int, channel_id: int, interaction=None):
        """Update the map in the specified channel."""
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.log.error(f"Channel {channel_id} not found")
                return

            # Send progress message if we have an interaction (from /map_create)
            progress_message = None
            if interaction:
                progress_embed = discord.Embed(
                    title="🗺️ Generating Map",
                    description="Creating your server map...",
                    color=0x7289da
                )
                progress_message = await interaction.followup.send(embed=progress_embed, ephemeral=True)

            # Use centralized progress handler
            from core.map_progress_handler import create_server_map_progress_callback
            progress_callback = await create_server_map_progress_callback(interaction, self.log, progress_message) if progress_message else None

            # Generate map image (uses caching internally and respects custom settings)
            map_file = await self._generate_map_image(guild_id, progress_callback)
            if not map_file:
                self.log.error("Failed to generate map image")
                if progress_message:
                    error_embed = discord.Embed(
                        title="⛔ Error",
                        description="Failed to generate map image.",
                        color=0xff4444
                    )
                    await progress_message.edit(embed=error_embed)
                return

            # Get map data for view - get current region
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
        
            # Button with persistent view
            view = MapPinButtonView(self, region, guild_id)

            # Check if there's an existing map message to edit
            existing_message_id = map_data.get('message_id')
            if existing_message_id:
                try:
                    message = await channel.fetch_message(existing_message_id)
                    await message.edit(content=None, attachments=[map_file], view=view)
                    return
                except discord.NotFound:
                    self.log.info(f"Previous map message {existing_message_id} not found, creating new one")
                except Exception as e:
                    self.log.warning(f"Failed to edit existing map message: {e}")

            # Send new message - just image with buttons
            message = await channel.send(file=map_file, view=view)
            
            # Update message ID in data
            if str(guild_id) not in self.maps:
                self.maps[str(guild_id)] = {}
            self.maps[str(guild_id)]['message_id'] = message.id
            await self._save_data(str(guild_id))

            # Complete progress message
            if progress_message:
                success_embed = discord.Embed(
                    title="✅ Map Created Successfully",
                    description="Your server map has been posted to the channel!",
                    color=0x00ff00
                )
                await progress_message.edit(embed=success_embed)

        except Exception as e:
            self.log.error(f"Failed to update map: {e}")
            if interaction and progress_message:
                error_embed = discord.Embed(
                    title="⛔ Error",
                    description="Failed to create map. Please try again.",
                    color=0xff4444
                )
                await progress_message.edit(embed=error_embed)

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        # Save all guild data
        for guild_id in self.maps.keys():
            asyncio.create_task(self._save_data(guild_id))

    async def _save_data(self, guild_id: str):
        """Save map data for specific guild."""
        await self.storage.save_data(guild_id, self.maps)

    async def _invalidate_map_cache(self, guild_id: int):
        """Invalidate cached maps for a guild."""
        await self.storage.invalidate_map_cache(guild_id)

    async def _generate_map_image(self, guild_id: int, progress_callback=None) -> Optional[discord.File]:
        """Generate a map image with pins for the guild."""
        try:
            # Check for cached final map first
            cached_map = await self.storage.get_cached_map(guild_id, self.maps)
            if cached_map:
                return cached_map

            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            
            # Calculate dimensions based on region
            width, height = self.map_generator.calculate_image_dimensions(region)
            if region != "germany" and region != "usmainland":
                height = int(height * 0.8)
            
            # Try to get cached base map first
            base_map = await self.storage.get_cached_base_map(region, width, height, str(guild_id), self.maps)
            projection_func = None
            
            if not base_map:
                # Generate new base map using improved renderer
                self.log.info(f"No base map in cache for {region}, rendering new one (will take some time)")
                
                # Define progress callback for rendering updates
                async def internal_progress_callback(message, percentage, image_buffer=None):
                    self.log.info(f"Map rendering progress: {message} ({percentage}%)")
                    if progress_callback:
                        await progress_callback(message, percentage, image_buffer)
                
                base_map, projection_func = await self.map_generator.render_geopandas_map(region, width, height, str(guild_id), self.maps, internal_progress_callback)
                
                if base_map:
                    # Cache the new base map
                    await self.storage.cache_base_map(region, width, height, base_map, str(guild_id), self.maps)
                else:
                    # Fallback to simple background
                    land_color, water_color = self.map_generator.get_map_colors(str(guild_id), self.maps)
                    base_map = Image.new('RGB', (width, height), color=water_color)
            else:
                # For cached maps, recreate the projection function
                projection_func = self._create_projection_function(region, width, height)
            
            # Calculate pin size based on image height and custom settings
            pin_color, custom_pin_size = self.map_generator.get_pin_settings(str(guild_id), self.maps)
            base_pin_size = int(height * custom_pin_size / 2400)  # Scale based on custom size
            
            # Group overlapping pins
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            # Draw pins on the map with custom settings
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size, str(guild_id), self.maps)
            
            # Convert PIL image to Discord file
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            
            # Cache the final image
            await self.storage.cache_map(guild_id, self.maps, img_buffer)
            
            img_buffer.seek(0)
            filename = f"map_{region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            return discord.File(img_buffer, filename=filename)
            
        except Exception as e:
            self.log.error(f"Failed to generate map image: {e}")
            return None

    def _create_projection_function(self, region: str, width: int, height: int):
        """Create projection function for cached maps."""
        config = self.map_generator.map_configs[region]
        (lat0, lon0), (lat1, lon1) = config["bounds"]
        minx, miny, maxx, maxy = lon0, lat0, lon1, lat1
        
        # For germany regions, try to get better bounds
        if region in ["germany"]:
            try:
                base_path = Path(__file__).parent.parent / "data"
                world = gpd.read_file(base_path / "ne_10m_admin_0_countries.shp")
                de = world[world["ADMIN"] == "Germany"].geometry.unary_union
                if de is not None:
                    de_buf = de.buffer(0.1)  # Smaller buffer
                    bounds = de_buf.bounds
                    if all(map(lambda v: v is not None and v == v, bounds)) and bounds[2] > bounds[0] and bounds[3] > bounds[1]:  # Check for finite values
                        minx, miny, maxx, maxy = bounds
            except Exception as e:
                self.log.warning(f"Could not recreate Germany bounds: {e}")
        
        def to_px(lat, lon):
            x = (lon - minx) / (maxx - minx) * width
            y = (maxy - lat) / (maxy - miny) * height
            return (int(x), int(y))
        
        return to_px

    async def _generate_proximity_map(self, user_id: int, guild_id: int, distance_km: int, progress_callback=None) -> Optional[Tuple[BytesIO, List[Dict]]]:
        """Generate proximity map showing nearby users."""
        return await self.proximity_calc.generate_proximity_map(user_id, guild_id, distance_km, self.maps, progress_callback)

    async def _generate_continent_closeup(self, guild_id: int, continent: str, progress_callback=None) -> Optional[BytesIO]:
        """Generate a close-up map of a continent using existing map configs."""
        try:
            if continent not in self.map_generator.map_configs:
                self.log.warning(f"Continent {continent} not in map configurations")
                return None
        
            # Check for cached closeup map first
            cached_closeup = await self.storage.get_cached_closeup(guild_id, self.maps, "continent", continent)
            if cached_closeup:
                return cached_closeup
        
            # Calculate dimensions
            width, height = self.map_generator.calculate_image_dimensions(continent)
            
            # Try to get cached base map first
            base_map = await self.storage.get_cached_closeup_base_map(guild_id, self.maps, "continent", continent, width, height)
            projection_func = None
            
            if not base_map:
                # Generate new base map
                self.log.info(f"No base map in cache for {continent} closeup, rendering new one (will take some time)")
                
                # Define progress callback for rendering updates
                async def internal_progress_callback(message, percentage, image_buffer=None):
                    self.log.info(f"Continent closeup rendering progress: {message} ({percentage}%)")
                    if progress_callback:
                        await progress_callback(message, percentage, image_buffer)
                
                base_map, projection_func = await self.map_generator.render_geopandas_map(continent, width, height, str(guild_id), self.maps, internal_progress_callback)
                
                if base_map:
                    # Cache the new base map
                    await self.storage.cache_closeup_base_map(guild_id, self.maps, "continent", continent, width, height, base_map)
                else:
                    return None
            else:
                # For cached maps, recreate the projection function
                projection_func = self._create_projection_function(continent, width, height)
            
            # Draw pins for this guild
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            pin_color, custom_pin_size = self.map_generator.get_pin_settings(str(guild_id), self.maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
        
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size, str(guild_id), self.maps)

            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            
            # Cache the closeup map
            await self.storage.cache_closeup(guild_id, self.maps, "continent", continent, img_buffer)
            
            img_buffer.seek(0)
            return img_buffer
        
        except Exception as e:
            self.log.error(f"Failed to generate continent closeup for {continent}: {e}")
            return None

    async def _generate_state_closeup(self, guild_id: int, state_name: str, progress_callback=None) -> Optional[BytesIO]:
        """Generate a close-up map of a German state using unified renderer."""
        try:
            # Check for cached closeup map first
            cached_closeup = await self.storage.get_cached_closeup(guild_id, self.maps, "state", state_name)
            if cached_closeup:
                return cached_closeup
            
            # Load shapefiles to find state bounds
            base = Path(__file__).parent.parent / "data"
            states = gpd.read_file(base / "ne_10m_admin_1_states_provinces.shp")
            
            # Find the state
            german_states = states[states["admin"] == "Germany"]
            state_row = german_states[german_states["name"] == state_name]
            
            if state_row.empty:
                state_row = german_states[german_states["name"].str.contains(state_name, case=False, na=False)]
            
            if state_row.empty:
                name_alternatives = {
                    "Bayern": "Bavaria",
                    "Nordrhein-Westfalen": "North Rhine-Westphalia",
                    "Baden-Württemberg": "Baden-Wurttemberg",
                    "Thüringen": "Thuringia"
                }
                alt_name = name_alternatives.get(state_name, state_name)
                state_row = german_states[german_states["name"].str.contains(alt_name, case=False, na=False)]
            
            if state_row.empty:
                self.log.warning(f"State {state_name} not found")
                return None
            
            # Get bounds and add padding
            state_geom = state_row.geometry.iloc[0]
            bounds = state_geom.bounds
            minx, miny, maxx, maxy = bounds
            
            width_range = maxx - minx
            height_range = maxy - miny
            padding_x = width_range * 0.05
            padding_y = height_range * 0.05
            
            minx -= padding_x
            maxx += padding_x
            miny -= padding_y
            maxy += padding_y
            
            # Calculate dimensions using Web Mercator
            def lat_to_mercator_y(lat):
                return math.log(math.tan((90 + lat) * math.pi / 360))
            
            y0 = lat_to_mercator_y(miny)
            y1 = lat_to_mercator_y(maxy)
            mercator_y_range = y1 - y0
            
            lon_range_radians = (maxx - minx) * math.pi / 180
            aspect_ratio = mercator_y_range / lon_range_radians
            
            width = 1400
            height = int(width * aspect_ratio)
            height = max(600, min(height, 2000))
            
            # Try to get cached base map first
            base_map = await self.storage.get_cached_closeup_base_map(guild_id, self.maps, "state", state_name, width, height)
            projection_func = None
            
            if not base_map:
                # Generate new base map
                self.log.info(f"No base map in cache for {state_name} state closeup, rendering new one (will take some time)")
                
                # Notify user about base map rendering if callback provided
                if progress_callback:
                    await progress_callback(f"No base map in cache, rendering new one (will take some time)", 5)
                
                # Define progress callback for rendering updates
                async def render_progress_callback(message, percentage, image_buffer=None):
                    self.log.info(f"State closeup rendering progress: {message} ({percentage}%)")
                    # Also update the user via the existing progress callback if provided
                    if progress_callback:
                        await progress_callback(f"Rendering base map: {message}", percentage, image_buffer)
                
                base_map, projection_func = await self.map_generator.render_base_map(
                    minx, miny, maxx, maxy, width, height, 
                    map_type="state_closeup", 
                    guild_id=str(guild_id), 
                    maps=self.maps,
                    zoom_level="state_closeup",
                    progress_callback=render_progress_callback
                )
                
                if base_map:
                    # Cache the new base map
                    await self.storage.cache_closeup_base_map(guild_id, self.maps, "state", state_name, width, height, base_map)
                else:
                    return None
            else:
                # For cached maps, recreate the projection function
                projection_func = self.map_generator.create_projection_function(minx, miny, maxx, maxy, width, height)
            
            # Highlight the selected state with a subtle border
            draw = ImageDraw.Draw(base_map)
            try:
                if hasattr(state_geom, 'exterior'):
                    coords_list = [state_geom.exterior.coords]
                else:
                    coords_list = [ring.exterior.coords for ring in state_geom.geoms]
                
                for coords in coords_list:
                    pts = [projection_func(y, x) for x, y in coords]
                    if len(pts) >= 2:
                        # Thicker red border for selected state
                        draw.line(pts, fill=(200, 0, 0), width=max(2, 3))
            except Exception as e:
                self.log.warning(f"Could not highlight state {state_name}: {e}")

            # Draw pins for this guild with custom settings
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            pin_color, custom_pin_size = self.map_generator.get_pin_settings(str(guild_id), self.maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size, str(guild_id), self.maps)

            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            
            # Cache the closeup map
            await self.storage.cache_closeup(guild_id, self.maps, "state", state_name, img_buffer)
            
            img_buffer.seek(0)
            return img_buffer
            
        except Exception as e:
            self.log.error(f"Failed to generate state closeup for {state_name}: {e}")
            return None

    async def _update_global_overview(self):
        """Update global overview of all maps."""
        try:
            if not self.global_config.get('enabled', False):
                return
                
            overview_channel_id = self.global_config.get('channel_id')
            if not overview_channel_id:
                return
            
            channel = self.bot.get_channel(overview_channel_id)
            if not channel:
                self.log.error(f"Global overview channel {overview_channel_id} not found")
                return
            
            # Create overview embed
            embed = discord.Embed(
                title="🗺️ Global Map Overview",
                description="Overview of all server maps across Discord",
                color=0x7289da,
                timestamp=get_german_time()
            )
            
            total_pins = 0
            active_maps = 0
            
            # Group by region
            region_stats = {}
            
            for guild_id, map_data in self.maps.items():
                try:
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                        
                    pins = map_data.get('pins', {})
                    region = map_data.get('region', 'world')
                    pin_count = len(pins)
                    
                    if pin_count > 0:
                        active_maps += 1
                        total_pins += pin_count
                        
                        if region not in region_stats:
                            region_stats[region] = {'servers': 0, 'pins': 0}
                        
                        region_stats[region]['servers'] += 1
                        region_stats[region]['pins'] += pin_count
                        
                        # Add server info
                        guild_name = guild.name
                        if len(guild_name) > 25:
                            guild_name = guild_name[:22] + "..."
                            
                        embed.add_field(
                            name=f"🔴 {guild_name}",
                            value=f"📍 {pin_count} pins • 🌍 {region.title()}",
                            inline=True
                        )
                except Exception as e:
                    self.log.warning(f"Error processing guild {guild_id} for overview: {e}")
            
            # Add summary
            embed.insert_field_at(
                0,
                name="📊 Summary",
                value=f"🗺️ **{active_maps}** active maps\n📍 **{total_pins}** total pins",
                inline=False
            )
            
            # Add region breakdown
            if region_stats:
                region_text = []
                for region, stats in sorted(region_stats.items()):
                    region_text.append(f"🌍 **{region.title()}**: {stats['servers']} servers, {stats['pins']} pins")
                
                embed.add_field(
                    name="🌍 By Region",
                    value="\n".join(region_text),
                    inline=False
                )
            
            embed.set_footer(text="Updated automatically")
            
            # Update existing message or create new one
            existing_message_id = self.global_config.get('message_id')
            if existing_message_id:
                try:
                    message = await channel.fetch_message(existing_message_id)
                    await message.edit(embed=embed)
                    return
                except discord.NotFound:
                    self.log.info("Previous global overview message not found, creating new one")
                except Exception as e:
                    self.log.warning(f"Failed to edit global overview message: {e}")
            
            # Send new message
            message = await channel.send(embed=embed)
            self.global_config['message_id'] = message.id
            await self.storage.save_global_config(self.global_config)
            
        except Exception as e:
            self.log.error(f"Failed to update global overview: {e}")

    async def _handle_pin_location(self, interaction: discord.Interaction, location: str):
        """Handle the actual pin location logic with cooldown check."""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
    
        if guild_id not in self.maps:
            await interaction.followup.send("⛔ No map exists for this server. Ask an admin to create one with `/map_create`.", ephemeral=True)
            return

        # Check if user is updating an existing pin and if they're on cooldown
        is_update = user_id in self.maps[guild_id]['pins']
        if is_update:
            on_cooldown, cooldown_expires = self._is_user_on_cooldown(user_id)
            if on_cooldown:
                # Calculate remaining time
                remaining = cooldown_expires - datetime.now()
                remaining_minutes = int(remaining.total_seconds() / 60)
                await interaction.followup.send(
                    f"⛔ You can update your pin again in **{remaining_minutes} minutes**. "
                    f"There's a {self.config.pin_cooldown_minutes}-minute cooldown after updating your location.",
                    ephemeral=True
                )
                return

        # Geocode the location
        geocode_result = await self.map_generator.geocode_location(location)
        if not geocode_result:
            await interaction.followup.send(
                f"⛔ Could not find coordinates for '{location}'. Please try a more specific location "
                f"(e.g., 'Berlin, Germany' instead of just 'Berlin').",
                ephemeral=True
            )
            return

        lat, lng, display_name = geocode_result
    
        # Check if coordinates are within the map region bounds
        region = self.maps[guild_id]['region']
        bounds = self.map_generator.map_configs[region]['bounds']
        if not (bounds[0][0] <= lat <= bounds[1][0] and bounds[0][1] <= lng <= bounds[1][1]):
            await interaction.followup.send(
                f"⛔ The location '{location}' is outside the {region} map region. "
                f"Please choose a location within {region}.",
                ephemeral=True
            )
            return

        # Get old location for comparison
        old_location = None
        if is_update:
            old_location = self.maps[guild_id]['pins'][user_id].get('location', 'Unknown')  # Use original location

        # Add or update pin - store only the original location
        self.maps[guild_id]['pins'][user_id] = {
            'username': interaction.user.display_name,
            'location': location,  # Original user input
            'display_name': display_name,  # Geocoded display name for internal use
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Set cooldown for pin updates
        if is_update:
            self._set_user_cooldown(user_id)

        await self._save_data(guild_id)
    
        # Show rendering loading message
        rendering_embed = discord.Embed(
            title="🗺️ Rendering Map",
            description="Updating the map with your new pin location...",
            color=0x7289da
        )
        loading_msg = await interaction.followup.send(embed=rendering_embed, ephemeral=True)
    
        # Invalidate only final map cache
        await self.storage.invalidate_final_map_cache_only(int(guild_id))
        self.log.info(f"Pin update for guild {guild_id}: preserved base map cache for efficiency")
    
        # Update the map and global overview
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()

        # Create success embed
        if is_update:
            success_embed = discord.Embed(
                title="📌 Pin Updated Successfully",
                description="Your location has been updated on the map!",
                color=0x00ff44
            )
            success_embed.add_field(name="Previous Location", value=old_location, inline=False)
            success_embed.add_field(name="New Location", value=location, inline=False)  # Show user input
            success_embed.add_field(name="Cooldown", value=f"Next update allowed in {self.config.pin_cooldown_minutes} minutes", inline=False)
        else:
            success_embed = discord.Embed(
                title="📌 Pin Added Successfully", 
                description="Your location has been pinned on the map!",
                color=0x7289da
            )
            success_embed.add_field(name="Location", value=location, inline=False)  # Show user input
    
        success_embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
        success_embed.set_footer(text=f"Updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Replace loading message with success message
        await loading_msg.edit(embed=success_embed)

    async def _handle_pin_location_update(self, interaction: discord.Interaction, location: str, original_interaction: discord.Interaction):
        """Handle pin location update with response replacement and cooldown check."""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
    
        if guild_id not in self.maps:
            await interaction.followup.send("⛔ No map exists for this server.", ephemeral=True)
            return

        # Check cooldown for updates
        on_cooldown, cooldown_expires = self._is_user_on_cooldown(user_id)
        if on_cooldown:
            remaining = cooldown_expires - datetime.now()
            remaining_minutes = int(remaining.total_seconds() / 60)
            await interaction.followup.send(
                f"⛔ You can update your pin again in **{remaining_minutes} minutes**. "
                f"There's a {self.config.pin_cooldown_minutes}-minute cooldown after updating your location.",
                ephemeral=True
            )
            return

        # Geocode the location
        geocode_result = await self.map_generator.geocode_location(location)
        if not geocode_result:
            await interaction.followup.send(
                f"⛔ Could not find coordinates for '{location}'. Please try a more specific location "
                f"(e.g., 'Berlin, Germany' instead of just 'Berlin').",
                ephemeral=True
            )
            return

        lat, lng, display_name = geocode_result
    
        # Check if coordinates are within the map region bounds
        region = self.maps[guild_id]['region']
        bounds = self.map_generator.map_configs[region]['bounds']
        if not (bounds[0][0] <= lat <= bounds[1][0] and bounds[0][1] <= lng <= bounds[1][1]):
            await interaction.followup.send(
                f"⛔ The location '{location}' is outside the {region} map region. "
                f"Please choose a location within {region}.",
                ephemeral=True
            )
            return

        # Get old location for comparison
        old_location = None
        if user_id in self.maps[guild_id]['pins']:
            old_location = self.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')

        # Update pin
        self.maps[guild_id]['pins'][user_id] = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Set cooldown for updates
        self._set_user_cooldown(user_id)

        await self._save_data(guild_id)
    
        # Invalidate only final map cache, preserve base maps
        await self.storage.invalidate_final_map_cache_only(int(guild_id))
        self.log.info(f"Pin update for guild {guild_id}: preserved base map cache for efficiency")
        
        # Update the map and global overview
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()
        
        # Create embed for update confirmation
        embed = discord.Embed(
            title="📌 Pin Updated Successfully",
            description="Your location has been updated on the map!",
            color=0x00ff44
        )
    
        if old_location:
            embed.add_field(name="Previous Location", value=old_location, inline=False)
    
        embed.add_field(name="New Location", value=display_name, inline=False)
        embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
        embed.add_field(name="Cooldown", value=f"Next update allowed in {self.config.pin_cooldown_minutes} minutes", inline=False)
        embed.set_footer(text=f"Updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Try to edit the original message, fallback to new message
        try:
            await original_interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            # If editing fails, send new message
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _generate_preview_map(self, guild_id: int, preview_settings: Dict, progress_callback=None) -> Optional[Tuple[BytesIO, Image.Image]]:
        """Generate a preview map with temporary settings - OPTIMIZED with intelligent caching.
        Returns tuple of (final_preview_image, base_map_for_caching)."""
        try:
            guild_id_str = str(guild_id)
            map_data = self.maps.get(guild_id_str, {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            
            # Calculate dimensions based on region
            width, height = self.map_generator.calculate_image_dimensions(region)
            if region != "germany" and region != "usmainland":
                height = int(height * 0.8)
            
            # OPTIMIZATION: Check if we can reuse existing base map
            current_settings = map_data.get('settings', {})
            current_colors = current_settings.get('colors', {})
            preview_colors = preview_settings.get('colors', {})
            
            # If only pin settings changed (not colors/borders), reuse base map
            colors_changed = (
                current_colors.get('land') != preview_colors.get('land') or
                current_colors.get('water') != preview_colors.get('water')
            )
            
            current_borders = current_settings.get('borders', {})
            preview_borders = preview_settings.get('borders', {})
            borders_changed = (
                current_borders.get('country') != preview_borders.get('country') or
                current_borders.get('road') != preview_borders.get('road')
            )
            
            base_map = None
            projection_func = None
            
            if not colors_changed and not borders_changed:
                # REUSE: Only pin settings changed, use cached base map
                self.log.info(f"Preview optimization: Reusing base map for guild {guild_id} (only pins changed)")
                base_map = await self.storage.get_cached_base_map(region, width, height, guild_id_str, self.maps)
                if base_map:
                    projection_func = self._create_projection_function(region, width, height)
            
            if not base_map:
                # GENERATE: Colors/borders changed, need new base map
                self.log.info(f"Preview generation: Creating new base map for guild {guild_id} (colors/borders changed)")
                temp_maps = {guild_id_str: map_data.copy()}
                temp_maps[guild_id_str]['settings'] = preview_settings
                
                # Define progress callback for preview rendering
                async def preview_progress_callback(message, percentage, image_buffer=None):
                    self.log.info(f"Preview rendering progress: {message} ({percentage}%)")
                    if progress_callback:
                        await progress_callback(message, percentage, image_buffer)
                
                base_map, projection_func = await self.map_generator.render_geopandas_map(
                    region, width, height, guild_id_str, temp_maps, preview_progress_callback
                )
            
            if not base_map or not projection_func:
                # Fallback to simple background
                temp_maps = {guild_id_str: map_data.copy()}
                temp_maps[guild_id_str]['settings'] = preview_settings
                land_color, water_color = self.map_generator.get_map_colors(guild_id_str, temp_maps)
                base_map = Image.new('RGB', (width, height), color=water_color)
                projection_func = self._create_projection_function(region, width, height)
            
            # Create temporary maps for pin rendering
            temp_maps = {guild_id_str: map_data.copy()}
            temp_maps[guild_id_str]['settings'] = preview_settings
            
            # Store a copy of the base map before adding pins (for caching when approved)
            base_map_for_caching = base_map.copy()
            
            # Calculate pin size based on preview settings
            pin_color, custom_pin_size = self.map_generator.get_pin_settings(guild_id_str, temp_maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            
            # Group overlapping pins
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            # Draw pins on the map with preview settings
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size, guild_id_str, temp_maps)
            
            # Convert PIL image to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            
            return img_buffer, base_map_for_caching
        
        except Exception as e:
            self.log.error(f"Failed to generate preview map: {e}")
            return None, None

    async def _apply_cached_preview_as_map(self, guild_id: int, cached_preview: BytesIO) -> bool:
        """Apply a cached preview image as the final map without regenerating."""
        try:
            # Cache the preview image as the final map
            cached_preview.seek(0)
            await self.storage.cache_map(guild_id, self.maps, cached_preview)
            
            # Get map data for view - get current region
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            channel_id = map_data.get('channel_id')
            
            if not channel_id:
                return False
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                return False

            # Create the discord file from cached preview
            cached_preview.seek(0)
            filename = f"map_{region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            map_file = discord.File(cached_preview, filename=filename)
            
            # Button with persistent view
            view = MapPinButtonView(self, region, guild_id)

            # Check if there's an existing map message to edit
            existing_message_id = map_data.get('message_id')
            if existing_message_id:
                try:
                    message = await channel.fetch_message(existing_message_id)
                    await message.edit(content=None, attachments=[map_file], view=view)
                    return True
                except discord.NotFound:
                    self.log.info(f"Previous map message {existing_message_id} not found, creating new one")
                except Exception as e:
                    self.log.warning(f"Failed to edit existing map message: {e}")

            # Send new message - just image with buttons
            message = await channel.send(file=map_file, view=view)
            
            # Update message ID in data
            if str(guild_id) not in self.maps:
                self.maps[str(guild_id)] = {}
            self.maps[str(guild_id)]['message_id'] = message.id
            await self._save_data(str(guild_id))
            
            return True
            
        except Exception as e:
            self.log.error(f"Failed to apply cached preview as map: {e}")
            return False

    async def _generate_fast_pin_preview(self, guild_id: int, preview_settings: Dict) -> Optional[BytesIO]:
        """Generate fast pin preview by reusing cached base map - ALWAYS use cache for pin-only changes."""
        try:
            guild_id_str = str(guild_id)
            map_data = self.maps.get(guild_id_str, {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            
            # Calculate dimensions based on region
            width, height = self.map_generator.calculate_image_dimensions(region)
            if region != "germany" and region != "usmainland":
                height = int(height * 0.8)
            
            # ALWAYS TRY CACHE FIRST for pin previews
            base_map = await self.storage.get_cached_base_map(region, width, height, guild_id_str, self.maps)
            projection_func = None
            
            if base_map:
                # CACHE HIT: Use cached base map
                self.log.info(f"Fast pin preview: Using cached base map for guild {guild_id}")
                projection_func = self._create_projection_function(region, width, height)
            else:
                # CACHE MISS: Generate base map and cache it
                self.log.info(f"Fast pin preview: Generating and caching base map for guild {guild_id}")
                base_map, projection_func = await self.map_generator.render_geopandas_map(
                    region, width, height, guild_id_str, self.maps
                )
                if base_map:
                    await self.storage.cache_base_map(region, width, height, base_map, guild_id_str, self.maps)
            
            if not base_map or not projection_func:
                # Fallback: Generate simple background
                land_color, water_color = self.map_generator.get_map_colors(guild_id_str, self.maps)
                base_map = Image.new('RGB', (width, height), color=water_color)
                projection_func = self._create_projection_function(region, width, height)
            
            # Create temporary maps with preview pin settings
            temp_maps = {guild_id_str: map_data.copy()}
            temp_maps[guild_id_str]['settings'] = preview_settings
            
            # Calculate pin size with preview settings
            pin_color, custom_pin_size = self.map_generator.get_pin_settings(guild_id_str, temp_maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            
            # Group overlapping pins
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            # Draw pins on the map with preview settings
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size, guild_id_str, temp_maps)
            
            # Convert PIL image to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            
            return img_buffer
        
        except Exception as e:
            self.log.error(f"Failed to generate fast pin preview: {e}")
            return None
            
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Remove user's pin when they leave the server"""
        try:
            guild_id = str(member.guild.id)
            user_id = str(member.id)

            if guild_id in self.maps and user_id in self.maps[guild_id].get('pins', {}):
                # Remove the pin
                old_location = self.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')
                del self.maps[guild_id]['pins'][user_id]
                
                # Also remove from cooldown tracking
                if user_id in self.pin_cooldowns:
                    del self.pin_cooldowns[user_id]
                
                await self._save_data(guild_id)

                # Invalidate Cache and update map
                await self._invalidate_map_cache(int(guild_id))
                channel_id = self.maps[guild_id]['channel_id']
                await self._update_map(int(guild_id), channel_id)
                await self._update_global_overview()

                self.log.info(f"Removed pin for user {member.display_name} ({user_id}) who left guild {guild_id}")

        except Exception as e:
            self.log.info(f"Error removing pin for leaving member: {e}")

    # Slash Commands
    @app_commands.command(name="map_create", description="Create a map for the server")
    @app_commands.describe(
        channel="Channel where the map will be posted",
        region="Map region (world by default)",
        allow_proximity="Allow users to see nearby members"
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="World", value="world"),
        app_commands.Choice(name="Europe", value="europe"),
        app_commands.Choice(name="Germany", value="germany"),
        app_commands.Choice(name="Asia", value="asia"),
        app_commands.Choice(name="Africa", value="africa"),
        app_commands.Choice(name="North America", value="northamerica"),
        app_commands.Choice(name="South America", value="southamerica"),
        app_commands.Choice(name="Australia", value="australia"),
        app_commands.Choice(name="US-Mainland", value="usmainland"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def create_map(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        region: str = "world",
        allow_proximity: bool = True
    ):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id in self.maps:
            await interaction.followup.send("⛔ A map already exists for this server. Use the Admin Tools to remove it first.", ephemeral=True)
            return

        self.maps[guild_id] = {
            'channel_id': channel.id,
            'region': region,
            'pins': {},
            'allow_proximity': allow_proximity,
            'created_at': datetime.now().isoformat(),
            'created_by': interaction.user.id
        }

        await self._save_data(guild_id)
        await self._update_map(interaction.guild.id, channel.id, interaction)
        await self._update_global_overview()

    @app_commands.command(name="map_pin", description="Manage your location on the server map")
    async def pin_on_map_v2(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        if guild_id not in self.maps:
            await interaction.response.send_message("⛔ No map exists for this server. Ask an admin to create one with `/map_create`.", ephemeral=True)
            return

        # Same functionality as the "My Pin" button
        user_id = str(interaction.user.id)
        
        if user_id in self.maps[guild_id].get('pins', {}):
            # User has a pin - show current location and options
            user_pin = self.maps[guild_id]['pins'][user_id]
            current_location = user_pin.get('display_name', 'Unknown')
            
            embed = discord.Embed(
                title="📍 Your Current Location",
                description=f"**Location:** {current_location}\n"
                           f"**Added:** {user_pin.get('timestamp', 'Unknown')}",
                color=0x7289da
            )
            
            # Check cooldown status
            on_cooldown, cooldown_expires = self._is_user_on_cooldown(user_id)
            if on_cooldown:
                remaining = cooldown_expires - datetime.now()
                remaining_minutes = int(remaining.total_seconds() / 60)
                embed.add_field(
                    name="Cooldown Status",
                    value=f"Next update allowed in {remaining_minutes} minutes",
                    inline=False
                )
            
            from core.map_views import UserPinOptionsView
            view = UserPinOptionsView(self, int(guild_id))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # User doesn't have a pin - show modal directly
            modal = LocationModal(self, int(guild_id))
            await interaction.response.send_modal(modal)

    @app_commands.command(name="owner_clear_map_cache", description="Clear cached map images (bot owner only)")
    @app_commands.default_permissions(administrator=True)
    async def clear_cache(self, interaction: discord.Interaction):
        if interaction.user.id != self.config.owner_id:
            await interaction.response.send_message("⛔ This command is only available to the bot owner.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            deleted_count = await self.storage.clear_all_cache()
            
            await interaction.followup.send(
                f"✅ Cache cleared successfully!\n"
                f"🗑️ Removed {deleted_count} cached images.",
                ephemeral=True
            )
            
        except Exception as e:
            self.log.error(f"Error clearing cache: {e}")
            await interaction.followup.send("⛔ Error clearing cache.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MapV2Cog(bot))