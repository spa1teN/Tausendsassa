"""Simplified Map Cog for Discord Bot with modular structure."""

import asyncio
import geopandas as gpd
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime
from PIL import Image
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands

# Import our modular components
from core.mapgen import MapGenerator
from core.mapstorage import MapStorage
from core.proximity import ProximityCalculator
from core.views import MapPinButtonView, LocationModal

# Constants
IMAGE_WIDTH = 2200
BOT_OWNER_ID = 485051896655249419


class MapV2Cog(commands.Cog):
    """Cog for managing maps with user pins displayed as images."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("map")
        
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

    async def cog_load(self):
        """Called when the cog is loaded. Re-register persistent views."""
        try:
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
                            await message.edit(view=view)
                            self.log.info(f"Updated view for guild {guild_id} with region {region}")
                    except Exception as e:
                        self.log.warning(f"Could not update view for guild {guild_id}: {e}")

                self.log.info(f"Re-registered persistent view for guild {guild_id}")
        except Exception as e:
            self.log.error(f"Error re-registering views: {e}")

    async def _update_map(self, guild_id: int, channel_id: int):
        """Update the map in the specified channel."""
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.log.error(f"Channel {channel_id} not found")
                return

            # Generate map image (uses caching internally)
            map_file = await self._generate_map_image(guild_id)
            if not map_file:
                self.log.error("Failed to generate map image")
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

        except Exception as e:
            self.log.error(f"Failed to update map: {e}")
        

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

    async def _generate_map_image(self, guild_id: int) -> Optional[discord.File]:
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
            base_map = await self.storage.get_cached_base_map(region, width, height)
            projection_func = None
            
            if not base_map:
                # Generate new base map using geopandas for all regions
                base_map, projection_func = await self.map_generator.render_geopandas_map(region, width, height)
                
                if base_map:
                    # Cache the new base map
                    await self.storage.cache_base_map(region, width, height, base_map)
                else:
                    # Fallback to simple background
                    base_map = Image.new('RGB', (width, height), color=(168, 213, 242))
            else:
                # For cached maps, recreate the projection function
                projection_func = self._create_projection_function(region, width, height)
            
            # Calculate pin size based on image height
            base_pin_size = int(height * 16 / 2400)  # Scale based on original germany map ratio
            
            # Group overlapping pins
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            # Draw pins on the map
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size)
            
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

    async def _generate_proximity_map(self, user_id: int, guild_id: int, distance_km: int) -> Optional[Tuple[BytesIO, List[Dict]]]:
        """Generate proximity map showing nearby users."""
        return await self.proximity_calc.generate_proximity_map(user_id, guild_id, distance_km, self.maps)

    async def _generate_continent_closeup(self, guild_id: int, continent: str) -> Optional[BytesIO]:
        """Generate a close-up map of a continent using existing map configs."""
        try:
            if continent not in self.map_generator.map_configs:
                self.log.warning(f"Continent {continent} not in map configurations")
                return None
        
            # Use existing map generation
            width, height = self.map_generator.calculate_image_dimensions(continent)
            base_map, projection_func = await self.map_generator.render_geopandas_map(continent, width, height)
        
            if not base_map or not projection_func:
                return None
        
            # Draw pins for this guild
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            base_pin_size = int(height * 16 / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
        
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size)

            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return img_buffer
        
        except Exception as e:
            self.log.error(f"Failed to generate continent closeup for {continent}: {e}")
            return None

    async def _generate_state_closeup(self, guild_id: int, state_name: str) -> Optional[BytesIO]:
        """Generate a close-up map of a German state with correct dimensions."""
        try:
            # Load German states shapefile
            base = Path(__file__).parent.parent / "data"
            states = gpd.read_file(base / "ne_10m_admin_1_states_provinces.shp")
            
            # Find the state - try different approaches for better matching
            german_states = states[states["admin"] == "Germany"]
            
            # Try exact match first
            state_row = german_states[german_states["name"] == state_name]
            
            # If no exact match, try case-insensitive contains
            if state_row.empty:
                state_row = german_states[german_states["name"].str.contains(state_name, case=False, na=False)]
            
            # Try alternative name matching
            if state_row.empty:
                # Some common alternatives
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
            
            # Get state geometry and bounds
            state_geom = state_row.geometry.iloc[0]
            bounds = state_geom.bounds
            minx, miny, maxx, maxy = bounds
            
            # Add padding based on state size
            width_range = maxx - minx
            height_range = maxy - miny
            padding_x = width_range * 0.05  # 5% padding
            padding_y = height_range * 0.05
            
            minx -= padding_x
            maxx += padding_x
            miny -= padding_y
            maxy += padding_y
            
            # Calculate dimensions using Web Mercator projection like other maps
            import math
            
            def lat_to_mercator_y(lat):
                return math.log(math.tan((90 + lat) * math.pi / 360))
            
            y0 = lat_to_mercator_y(miny)
            y1 = lat_to_mercator_y(maxy)
            mercator_y_range = y1 - y0
            
            lon_range_radians = (maxx - minx) * math.pi / 180
            aspect_ratio = mercator_y_range / lon_range_radians
            
            # Use consistent width with other map types
            width = 1400
            height = int(width * aspect_ratio)
            
            # Ensure reasonable height bounds
            height = max(600, min(height, 2000))
            
            # Generate base map with custom bounds
            base_map, projection_func = await self.map_generator.render_geopandas_map_bounds(minx, miny, maxx, maxy, width, height)
            
            if not base_map or not projection_func:
                return None
            
            # Draw pins for this guild
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            base_pin_size = int(height * 16 / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size)

            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return img_buffer
            
        except Exception as e:
            self.log.error(f"Failed to generate state closeup for {state_name}: {e}")
            return None

    async def _update_map(self, guild_id: int, channel_id: int):
        """Update the map in the specified channel."""
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.log.error(f"Channel {channel_id} not found")
                return

            # Generate map image (uses caching internally)
            map_file = await self._generate_map_image(guild_id)
            if not map_file:
                self.log.error("Failed to generate map image")
                return

            # Get map data for view
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
        
            # Button with persistent view - no embed, just image
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

        except Exception as e:
            self.log.error(f"Failed to update map: {e}")

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
                timestamp=datetime.now()
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
                            name=f"🏴 {guild_name}",
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
        """Handle the actual pin location logic."""
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server. Ask an admin to create one with `/create_map`.", ephemeral=True)
            return

        # Geocode the location
        geocode_result = await self.map_generator.geocode_location(location)
        if not geocode_result:
            await interaction.followup.send(
                f"❌ Could not find coordinates for '{location}'. Please try a more specific location "
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
                f"❌ The location '{location}' is outside the {region} map region. "
                f"Please choose a location within {region}.",
                ephemeral=True
            )
            return

        # Add or update pin
        user_id = str(interaction.user.id)
        self.maps[guild_id]['pins'][user_id] = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        await self._save_data(guild_id)
        
        # Invalidate cache since pins changed
        await self._invalidate_map_cache(int(guild_id))
        
        # Update the map and global overview
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()

        await interaction.followup.send(
            f"✅ Your location has been pinned on the map!\n"
            f"📍 **Location:** {display_name}\n"
            f"🗺️ The map has been updated in <#{channel_id}>.",
            ephemeral=True
        )

    async def _handle_pin_location_update(self, interaction: discord.Interaction, location: str, original_interaction: discord.Interaction):
        """Handle pin location update with response replacement."""
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return

        # Geocode the location
        geocode_result = await self.map_generator.geocode_location(location)
        if not geocode_result:
            await interaction.followup.send(
                f"❌ Could not find coordinates for '{location}'. Please try a more specific location "
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
                f"❌ The location '{location}' is outside the {region} map region. "
                f"Please choose a location within {region}.",
                ephemeral=True
            )
            return

        # Get old location for comparison
        user_id = str(interaction.user.id)
        old_location = None
        if user_id in self.maps[guild_id]['pins']:
            old_location = self.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')

        # Update or add pin
        self.maps[guild_id]['pins'][user_id] = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        await self._save_data(guild_id)
        
        # Invalidate cache since pins changed
        await self._invalidate_map_cache(int(guild_id))
        
        # Update the map and global overview
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()

        # Create embed for update confirmation
        embed = discord.Embed(
            title="📍 Pin Updated Successfully",
            description="Your location has been updated on the map!",
            color=0x00ff44
        )
        
        if old_location:
            embed.add_field(name="Previous Location", value=old_location, inline=False)
        
        embed.add_field(name="New Location", value=display_name, inline=False)
        embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
        embed.set_footer(text=f"Updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Try to edit the original message, fallback to new message
        try:
            await original_interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            # If editing fails, send new message
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_pin_location(self, interaction: discord.Interaction, location: str):
        """Handle the actual pin location logic for new pins."""
        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server. Ask an admin to create one with `/create_map`.", ephemeral=True)
            return

        # Geocode the location
        geocode_result = await self.map_generator.geocode_location(location)
        if not geocode_result:
            await interaction.followup.send(
                f"❌ Could not find coordinates for '{location}'. Please try a more specific location "
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
                f"❌ The location '{location}' is outside the {region} map region. "
                f"Please choose a location within {region}.",
                ephemeral=True
            )
            return

        # Check if this is an update or new pin
        user_id = str(interaction.user.id)
        is_update = user_id in self.maps[guild_id]['pins']
        old_location = None
        if is_update:
            old_location = self.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')

        # Add or update pin
        self.maps[guild_id]['pins'][user_id] = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        await self._save_data(guild_id)
        
        # Invalidate cache since pins changed
        await self._invalidate_map_cache(int(guild_id))
        
        # Update the map and global overview
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()

        # Create embed response
        if is_update:
            embed = discord.Embed(
                title="📍 Pin Updated Successfully",
                description="Your location has been updated on the map!",
                color=0x00ff44
            )
            embed.add_field(name="Previous Location", value=old_location, inline=False)
            embed.add_field(name="New Location", value=display_name, inline=False)
        else:
            embed = discord.Embed(
                title="📍 Pin Added Successfully", 
                description="Your location has been pinned on the map!",
                color=0x7289da
            )
            embed.add_field(name="Location", value=display_name, inline=False)
        
        embed.add_field(name="Map Updated", value=f"<#{channel_id}>", inline=False)
        embed.set_footer(text=f"Updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        await interaction.followup.send(embed=embed, ephemeral=True)
        
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
            await interaction.followup.send("❌ A map already exists for this server. Use `/map_remove` first to create a new one.", ephemeral=True)
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
        await self._update_map(interaction.guild.id, channel.id)
        await self._update_global_overview()

        await interaction.followup.send(
            f"✅ Map created successfully in {channel.mention}!\n"
            f"🗺️ Region: **{region.title()}**\n"
            f"📍 Users can now add their location.",
            ephemeral=True
        )

    @app_commands.command(name="map_remove", description="Remove the server map")
    @app_commands.default_permissions(administrator=True)
    async def remove_map(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return

        map_data = self.maps[guild_id]
        pin_count = len(map_data.get('pins', {}))
        
        # Try to delete the map message
        channel_id = map_data.get('channel_id')
        message_id = map_data.get('message_id')
        
        if channel_id and message_id:
            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    self.log.info(f"Deleted map message {message_id} in channel {channel_id}")
            except discord.NotFound:
                self.log.info(f"Map message {message_id} already deleted")
            except Exception as e:
                self.log.warning(f"Could not delete map message: {e}")
        
        # Invalidate cache when removing map
        await self._invalidate_map_cache(int(guild_id))
        
        del self.maps[guild_id]
        await self._save_data(guild_id)  # This will remove the file since guild_id not in maps
        await self._update_global_overview()

        await interaction.followup.send(
            f"✅ Map removed successfully!\n"
            f"📍 {pin_count} user pin(s) were also removed.\n"
            f"🗑️ Map message has been deleted.",
            ephemeral=True
        )

    @app_commands.command(name="map_pin", description="Pin your location on the server map")
    async def pin_on_map_v2(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        if guild_id not in self.maps:
            await interaction.response.send_message("❌ No map exists for this server. Ask an admin to create one with `/create_map`.", ephemeral=True)
            return

        region = self.maps[guild_id]['region']
        modal = LocationModal(self, region)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="map_unpin", description="Remove your pin from the server map")
    async def unpin_on_map(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return

        if user_id not in self.maps[guild_id]['pins']:
            await interaction.followup.send("❌ You don't have a pin on the map.", ephemeral=True)
            return

        old_location = self.maps[guild_id]['pins'][user_id].get('display_name', 'Unknown')
        del self.maps[guild_id]['pins'][user_id]
        await self._save_data(guild_id)
        
        # Invalidate cache since pins changed
        await self._invalidate_map_cache(int(guild_id))
        
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)
        await self._update_global_overview()

        await interaction.followup.send(
            f"✅ Your pin has been removed from the map!\n"
            f"📍 **Removed location:** {old_location}\n"
            f"🗺️ The map has been updated in <#{channel_id}>.",
            ephemeral=True
        )

    @app_commands.command(name="map_info", description="Show information about the server map")
    async def map_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return

        map_data = self.maps[guild_id]
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
                value="You haven't pinned a location yet.\nUse `/pin_on_map` to add one!", 
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="owner_setup_map_overview", description="Setup global map overview (Bot Owner only)")
    @app_commands.describe(channel="Channel for global overview")
    async def setup_global_overview(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ This command is only available to the bot owner.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        self.global_config['enabled'] = True
        self.global_config['channel_id'] = channel.id
        await self.storage.save_global_config(self.global_config)
        
        # Create initial overview
        await self._update_global_overview()
        
        await interaction.followup.send(
            f"✅ Global map overview has been set up in {channel.mention}!\n"
            f"📊 The overview will be automatically updated when maps change.",
            ephemeral=True
        )

    @app_commands.command(name="map_clear_cache", description="Clear cached map images (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def clear_cache(self, interaction: discord.Interaction):
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
            await interaction.followup.send("❌ Error clearing cache.", ephemeral=True)

    @app_commands.command(name="owner_refresh_map_overview", description="Manually refresh global overview (Bot Owner only)")
    async def refresh_global_overview(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ This command is only available to the bot owner.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            await self._update_global_overview()
            await interaction.followup.send("✅ Global overview has been refreshed!", ephemeral=True)
        except Exception as e:
            self.log.error(f"Error refreshing global overview: {e}")
            await interaction.followup.send("❌ Error refreshing global overview.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MapV2Cog(bot))
