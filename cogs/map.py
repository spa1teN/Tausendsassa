import json
import asyncio
import aiohttp
import io
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands


class MapCog(commands.Cog):
    """Cog for managing maps with user pins displayed as images."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("map")
        self.data_file = Path(__file__).parent.parent / "map_data.json"
        self.maps = self._load_data()
        
        # Map region configurations for static map API
        self.map_configs = {
            "world": {
                "center_lat": 20.0,
                "center_lng": 0.0,
                "zoom": 2,
                "bounds": [[-85, -180], [85, 180]],
                "width": 800,
                "height": 400
            },
            "europe": {
                "center_lat": 54.5,
                "center_lng": 15.0,
                "zoom": 4,
                "bounds": [[34.5, -25.0], [71.0, 40.0]],
                "width": 800,
                "height": 600
            },
            "germany": {
                "center_lat": 51.1657,
                "center_lng": 10.4515,
                "zoom": 6,
                "bounds": [[47.2701, 5.8663], [55.0583, 15.0419]],
                "width": 600,
                "height": 800
            }
        }
        
        # Pin colors for different users
        self.pin_colors = [
            "#FF4444", "#44FF44", "#4444FF", "#FFFF44", "#FF44FF",
            "#44FFFF", "#FF8844", "#88FF44", "#4488FF", "#FF4488"
        ]

    def _load_data(self) -> Dict:
        """Load map data from JSON file."""
        try:
            if self.data_file.exists():
                with self.data_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            self.log.info("No existing map data found, starting with empty maps")
        except Exception as e:
            self.log.error(f"Failed to load map data: {e}")
        
        return {}

    async def _save_data(self):
        """Save map data to JSON file."""
        try:
            if self.data_file.exists():
                backup_file = self.data_file.with_suffix('.json.bak')
                self.data_file.replace(backup_file)
            
            with self.data_file.open('w', encoding='utf-8') as f:
                json.dump(self.maps, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log.error(f"Failed to save map data: {e}")

    async def _geocode_location(self, location: str) -> Optional[Tuple[float, float, str]]:
        """Geocode a location string to lat/lng coordinates and return display name."""
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': location,
                'format': 'json',
                'limit': 1,
                'addressdetails': 1
            }
            headers = {
                'User-Agent': 'DiscordBot-MapPins/1.0'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data:
                            lat = float(data[0]['lat'])
                            lng = float(data[0]['lon'])
                            display_name = data[0].get('display_name', location)
                            return (lat, lng, display_name)
            
            self.log.warning(f"No results found for location: {location}")
            return None
            
        except Exception as e:
            self.log.error(f"Geocoding failed for '{location}': {e}")
            return None

    def _deg2num(self, lat_deg: float, lon_deg: float, zoom: int) -> Tuple[float, float]:
        """Convert lat/lng to tile coordinates."""
        import math
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = (lon_deg + 180.0) / 360.0 * n
        ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return (xtile, ytile)

    def _lat_lng_to_pixel(self, lat: float, lng: float, center_lat: float, center_lng: float, 
                         zoom: int, width: int, height: int) -> Tuple[int, int]:
        """Convert lat/lng coordinates to pixel coordinates on the map image."""
        import math
        
        # Convert both the point and center to Web Mercator coordinates
        def lat_lng_to_web_mercator(lat_deg, lng_deg):
            lat_rad = math.radians(lat_deg)
            x = lng_deg * 20037508.34 / 180
            y = math.log(math.tan((90 + lat_deg) * math.pi / 360)) / (math.pi / 180)
            y = y * 20037508.34 / 180
            return x, y
        
        # Get Web Mercator coordinates
        point_x, point_y = lat_lng_to_web_mercator(lat, lng)
        center_x, center_y = lat_lng_to_web_mercator(center_lat, center_lng)
        
        # Calculate the scale for this zoom level
        # At zoom level 0, the entire world (20037508.34 * 2 mercator units) fits in 256 pixels
        scale = 256 * (2 ** zoom) / (20037508.34 * 2)
        
        # Convert to pixel offset from center
        pixel_x = (point_x - center_x) * scale
        pixel_y = (center_y - point_y) * scale  # Note: Y is inverted
        
        # Add to center of image
        final_x = width // 2 + pixel_x
        final_y = height // 2 + pixel_y
        
        return (int(final_x), int(final_y))

    async def _download_map_tiles(self, center_lat: float, center_lng: float, zoom: int, 
                                width: int, height: int) -> Optional[Image.Image]:
        """Download and stitch map tiles from OpenStreetMap."""
        try:
            import math
            
            # Calculate which tiles we need
            center_x, center_y = self._deg2num(center_lat, center_lng, zoom)
            
            # Calculate tile bounds - we need enough tiles to cover the image
            tiles_x = math.ceil(width / 256) + 2
            tiles_y = math.ceil(height / 256) + 2
            
            start_x = int(center_x - tiles_x // 2)
            start_y = int(center_y - tiles_y // 2)
            
            # Create base image
            tile_width = tiles_x * 256
            tile_height = tiles_y * 256
            base_image = Image.new('RGB', (tile_width, tile_height))
            
            # Store the actual center position in pixels for later coordinate conversion
            actual_center_x = tiles_x // 2 * 256 + (center_x - int(center_x)) * 256
            actual_center_y = tiles_y // 2 * 256 + (center_y - int(center_y)) * 256
            
            # Download and place tiles
            async with aiohttp.ClientSession() as session:
                for x_offset in range(tiles_x):
                    for y_offset in range(tiles_y):
                        tile_x = start_x + x_offset
                        tile_y = start_y + y_offset
                        
                        # Skip invalid tile coordinates
                        if tile_x < 0 or tile_y < 0 or tile_x >= (2 ** zoom) or tile_y >= (2 ** zoom):
                            continue
                        
                        # OpenStreetMap tile URL
                        url = f"https://tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"
                        
                        try:
                            headers = {'User-Agent': 'DiscordBot-MapPins/1.0'}
                            async with session.get(url, headers=headers, timeout=10) as response:
                                if response.status == 200:
                                    tile_data = await response.read()
                                    tile_image = Image.open(BytesIO(tile_data))
                                    
                                    # Place tile in the base image
                                    x_pos = x_offset * 256
                                    y_pos = y_offset * 256
                                    base_image.paste(tile_image, (x_pos, y_pos))
                                else:
                                    self.log.warning(f"Failed to download tile {tile_x}/{tile_y}: {response.status}")
                        except Exception as e:
                            self.log.warning(f"Error downloading tile {tile_x}/{tile_y}: {e}")
                            # Fill with water color if tile fails
                            tile_image = Image.new('RGB', (256, 256), color='#a8d5f2')
                            x_pos = x_offset * 256
                            y_pos = y_offset * 256
                            base_image.paste(tile_image, (x_pos, y_pos))
            
            # Crop to desired size, centered on the actual center
            crop_x = int(actual_center_x - width // 2)
            crop_y = int(actual_center_y - height // 2)
            
            # Ensure crop coordinates are valid
            crop_x = max(0, min(crop_x, tile_width - width))
            crop_y = max(0, min(crop_y, tile_height - height))
            
            final_image = base_image.crop((crop_x, crop_y, crop_x + width, crop_y + height))
            
            return final_image
            
        except Exception as e:
            self.log.error(f"Failed to download map tiles: {e}")
            # Return a simple colored background as fallback
            return Image.new('RGB', (width, height), color='#a8d5f2')

    async def _generate_map_image(self, guild_id: int) -> Optional[discord.File]:
        """Generate a map image with pins for the guild."""
        try:
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            config = self.map_configs[region]
            
            width, height = config['width'], config['height']
            
            # Download real map tiles as base
            base_map = await self._download_map_tiles(
                config['center_lat'], config['center_lng'], 
                config['zoom'], width, height
            )
            
            if not base_map:
                # Fallback to simple background
                base_map = Image.new('RGB', (width, height), color='#a8d5f2')
            
            draw = ImageDraw.Draw(base_map)
            
            # Group pins by location to count duplicates
            location_groups = {}
            for user_id, pin_data in pins.items():
                # Round coordinates to group nearby pins (within ~1km)
                rounded_lat = round(pin_data['lat'], 3)  # ~111m precision
                rounded_lng = round(pin_data['lng'], 3)
                location_key = (rounded_lat, rounded_lng)
                
                if location_key not in location_groups:
                    location_groups[location_key] = {
                        'count': 0,
                        'display_name': pin_data.get('display_name', pin_data.get('location', 'Unknown')),
                        'lat': pin_data['lat'],
                        'lng': pin_data['lng']
                    }
                location_groups[location_key]['count'] += 1
            
            # Try to load fonts
            try:
                pin_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
                count_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
            except:
                try:
                    pin_font = ImageFont.truetype("arial.ttf", 14)
                    count_font = ImageFont.truetype("arial.ttf", 11)
                except:
                    pin_font = ImageFont.load_default()
                    count_font = ImageFont.load_default()
            
            # Draw pins for each unique location
            for location_key, location_data in location_groups.items():
                lat, lng = location_data['lat'], location_data['lng']
                count = location_data['count']
                
                # Convert coordinates to pixel position
                x, y = self._lat_lng_to_pixel(
                    lat, lng, 
                    config['center_lat'], config['center_lng'],
                    config['zoom'], width, height
                )
                
                # Skip if pin is outside the image
                if x < 10 or x >= width-10 or y < 10 or y >= height-10:
                    continue
                
                # Pin size varies by count (more people = bigger pin)
                base_pin_size = 8
                pin_size = min(base_pin_size + (count - 1) * 2, 20)  # Max size 20
                
                # Pin color - red for single, darker red for multiple
                pin_color = '#FF4444' if count == 1 else '#CC0000'
                
                # Draw pin shadow
                shadow_offset = 2
                draw.ellipse([
                    x - pin_size + shadow_offset, 
                    y - pin_size + shadow_offset, 
                    x + pin_size + shadow_offset, 
                    y + pin_size + shadow_offset
                ], fill='#00000080')
                
                # Draw pin
                draw.ellipse([x - pin_size, y - pin_size, x + pin_size, y + pin_size], 
                           fill=pin_color, outline='white', width=2)
                
                # Draw count if more than 1 person
                if count > 1:
                    count_text = str(count)
                    
                    # Get text dimensions
                    bbox = draw.textbbox((0, 0), count_text, font=count_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    # Position count label above the pin
                    text_x = x - text_width // 2
                    text_y = y - pin_size - text_height - 5
                    
                    # Ensure text stays within bounds
                    text_x = max(2, min(text_x, width - text_width - 2))
                    text_y = max(2, text_y)
                    
                    # Draw text background (rounded rectangle)
                    bg_padding = 3
                    bg_rect = [
                        text_x - bg_padding, 
                        text_y - bg_padding,
                        text_x + text_width + bg_padding, 
                        text_y + text_height + bg_padding
                    ]
                    draw.rounded_rectangle(bg_rect, radius=8, fill='white', outline='black', width=1)
                    
                    # Draw count text
                    draw.text((text_x, text_y), count_text, fill='black', font=count_font)
            
            # Convert PIL image to Discord file
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            
            filename = f"map_{region}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            return discord.File(img_buffer, filename=filename)
            
        except Exception as e:
            self.log.error(f"Failed to generate map image: {e}")
            return None

    async def _update_map(self, guild_id: int, channel_id: int):
        """Update the map in the specified channel."""
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.log.error(f"Channel {channel_id} not found")
                return

            # Generate map image
            map_file = await self._generate_map_image(guild_id)
            if not map_file:
                self.log.error("Failed to generate map image")
                return

            # Get map data for embed info
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            region = map_data.get('region', 'world')

            # Create embed with map info
            embed = discord.Embed(
                title=f"🗺️ Server Map - {region.title()}",
                description=f"Member location map\n\n"
                           f"📍 **{len(pins)} members** have pinned their location\n"
                           f"🌍 **Region:** {region.title()}",
                color=0x7289da,
                timestamp=datetime.now()
            )
            
            
            if pins:
                # Count unique locations for display
                location_groups = {}
                for user_id, pin_data in pins.items():
                    rounded_lat = round(pin_data['lat'], 3)
                    rounded_lng = round(pin_data['lng'], 3)
                    location_key = (rounded_lat, rounded_lng)
                    
                    if location_key not in location_groups:
                        location_groups[location_key] = {
                            'count': 0,
                            'display_name': pin_data.get('display_name', pin_data.get('location', 'Unknown location'))
                        }
                    location_groups[location_key]['count'] += 1
                
                # Show locations with multiple pins
                multi_locations = [(data['display_name'], data['count']) for data in location_groups.values() if data['count'] > 1]
                if multi_locations:
                    multi_locations.sort(key=lambda x: x[1], reverse=True)  # Sort by count
                    location_list = []
                    for location, count in multi_locations[:3]:  # Show top 3
                        if len(location) > 35:
                            location = location[:32] + "..."
                        location_list.append(f"📍 **{location}**: {count} members")
                    
                    embed.add_field(
                        name="Popular Locations",
                        value="\n".join(location_list) if location_list else "No shared locations",
                        inline=False
                    )

            embed.set_image(url=f"attachment://{map_file.filename}")
            embed.set_footer(text="Use /pin_on_map to add your location!")

            # Check if there's an existing map message to edit
            existing_message_id = map_data.get('message_id')
            if existing_message_id:
                try:
                    message = await channel.fetch_message(existing_message_id)
                    await message.edit(embed=embed, attachments=[map_file])
                    return
                except discord.NotFound:
                    self.log.info(f"Previous map message {existing_message_id} not found, creating new one")
                except Exception as e:
                    self.log.warning(f"Failed to edit existing map message: {e}")

            # Send new message
            message = await channel.send(embed=embed, file=map_file)
            
            # Update message ID in data
            if str(guild_id) not in self.maps:
                self.maps[str(guild_id)] = {}
            self.maps[str(guild_id)]['message_id'] = message.id
            await self._save_data()

        except Exception as e:
            self.log.error(f"Failed to update map: {e}")

    @app_commands.command(name="create_map", description="Create a map for the server")
    @app_commands.describe(
        channel="Channel where the map will be posted",
        region="Map region (world, europe, or germany)"
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="World", value="world"),
        app_commands.Choice(name="Europe", value="europe"),
        app_commands.Choice(name="Germany", value="germany"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def create_map(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        region: str = "world"
    ):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id in self.maps:
            await interaction.followup.send("❌ A map already exists for this server. Use `/remove_map` first to create a new one.", ephemeral=True)
            return

        self.maps[guild_id] = {
            'channel_id': channel.id,
            'region': region,
            'pins': {},
            'created_at': datetime.now().isoformat(),
            'created_by': interaction.user.id
        }

        await self._save_data()
        await self._update_map(interaction.guild.id, channel.id)

        await interaction.followup.send(
            f"✅ Map created successfully in {channel.mention}!\n"
            f"🗺️ Region: **{region.title()}**\n"
            f"📍 Users can now use `/pin_on_map` to add their location.",
            ephemeral=True
        )

    @app_commands.command(name="remove_map", description="Remove the server map")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_map(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server.", ephemeral=True)
            return

        pin_count = len(self.maps[guild_id].get('pins', {}))
        del self.maps[guild_id]
        await self._save_data()

        await interaction.followup.send(
            f"✅ Map removed successfully!\n"
            f"📍 {pin_count} user pin(s) were also removed.",
            ephemeral=True
        )

    @app_commands.command(name="pin_on_map", description="Pin your location on the server map")
    @app_commands.describe(location="Your location (e.g., 'Berlin, Germany' or 'New York, USA')")
    async def pin_on_map(self, interaction: discord.Interaction, location: str):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        
        if guild_id not in self.maps:
            await interaction.followup.send("❌ No map exists for this server. Ask an admin to create one with `/create_map`.", ephemeral=True)
            return

        # Geocode the location
        geocode_result = await self._geocode_location(location)
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
        bounds = self.map_configs[region]['bounds']
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

        await self._save_data()
        
        # Update the map
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)

        await interaction.followup.send(
            f"✅ Your location has been pinned on the map!\n"
            f"📍 **Location:** {display_name}\n"
            f"🗺️ The map has been updated in <#{channel_id}>.",
            ephemeral=True
        )

    @app_commands.command(name="unpin_on_map", description="Remove your pin from the server map")
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
        await self._save_data()
        
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(interaction.guild.id, channel_id)

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

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        asyncio.create_task(self._save_data())


async def setup(bot: commands.Bot):
    await bot.add_cog(MapCog(bot))