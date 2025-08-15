import json
import asyncio
import aiohttp
import io
import hashlib
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import geopandas as gpd
from shapely.geometry import box, Point
import math

import discord
from discord import app_commands
from discord.ext import commands

IMAGE_WIDTH = 2200
BOT_OWNER_ID = 485051896655249419

class LocationModal(discord.ui.Modal, title='Pin Location'):
    def __init__(self, cog, map_region: str):
        super().__init__()
        self.cog = cog
        self.map_region = map_region

    location = discord.ui.TextInput(
        label='Location',
        placeholder='e.g. Berlin, Deutschland or Paris, France...',
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._handle_pin_location(interaction, self.location.value)

class StateSelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # German states
        states = [
            ("Baden-Württemberg", "Baden-Württemberg"),
            ("Bayern", "Bayern"), 
            ("Berlin", "Berlin"),
            ("Brandenburg", "Brandenburg"),
            ("Bremen", "Bremen"),
            ("Hamburg", "Hamburg"),
            ("Hessen", "Hessen"),
            ("Mecklenburg-Vorpommern", "Mecklenburg-Vorpommern"),
            ("Niedersachsen", "Niedersachsen"),
            ("Nordrhein-Westfalen", "Nordrhein-Westfalen"),
            ("Rheinland-Pfalz", "Rheinland-Pfalz"),
            ("Saarland", "Saarland"),
            ("Sachsen", "Sachsen"),
            ("Sachsen-Anhalt", "Sachsen-Anhalt"),
            ("Schleswig-Holstein", "Schleswig-Holstein"),
            ("Thüringen", "Thüringen")
        ]

        state_select = discord.ui.Select(
            placeholder="Choose a German state...",
            options=[discord.SelectOption(label=name, value=value) for name, value in states[:16]]  # Discord limit
        )
        state_select.callback = self.state_selected
        self.add_item(state_select)

    async def state_selected(self, interaction: discord.Interaction):
        selected_state = interaction.data['values'][0]
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Generate state close-up map
            state_image = await self.cog._generate_state_closeup(self.guild_id, selected_state)
            if state_image:
                filename = f"state_{selected_state}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                await interaction.followup.send(
                    f"📍 **Close-up view of {selected_state}**", 
                    file=discord.File(state_image, filename=filename),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Could not generate map for {selected_state}",
                    ephemeral=True
                )
        except Exception as e:
            self.cog.log.error(f"Error generating state map: {e}")
            await interaction.followup.send("❌ Error generating state map", ephemeral=True)

class ContinentSelectionView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Kontinente für Weltkarten-Close-ups
        continents = [
            ("North America", "northamerica"),
            ("South America", "southamerica"),
            ("Europe", "europe"),
            ("Africa", "africa"),
            ("Asia", "asia"),
            ("Australia", "australia")
        ]

        continent_select = discord.ui.Select(
            placeholder="Choose a continent for close-up...",
            options=[discord.SelectOption(label=name, value=value) for name, value in continents]
        )
        continent_select.callback = self.continent_selected
        self.add_item(continent_select)

    async def continent_selected(self, interaction: discord.Interaction):
        selected_continent = interaction.data['values'][0]
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Generiere Kontinent-Close-up mit existierenden Karten-Konfigurationen
            continent_image = await self.cog._generate_continent_closeup(self.guild_id, selected_continent)
            if continent_image:
                continent_names = {
                    "northamerica": "North America",
                    "southamerica": "South America", 
                    "europe": "Europe",
                    "africa": "Africa",
                    "asia": "Asia",
                    "australia": "Australia"
                }
                
                name = continent_names.get(selected_continent, selected_continent.title())
                filename = f"continent_{selected_continent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                await interaction.followup.send(
                    f"🌍 **Close-up view of {name}**", 
                    file=discord.File(continent_image, filename=filename),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Could not generate map for {selected_continent}",
                    ephemeral=True
                )
        except Exception as e:
            self.cog.log.error(f"Error generating continent map: {e}")
            await interaction.followup.send("❌ Error generating continent map", ephemeral=True)
                

class MapMenuView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', region: str, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.region = region
        self.guild_id = guild_id

    @discord.ui.button(
        label="Region Close-up",
        style=discord.ButtonStyle.secondary,
        emoji="🔍"
    )
    async def region_closeup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.region == "world":
            # Zeige Kontinent-Auswahl für Weltkarten
            view = ContinentSelectionView(self.cog, self.guild_id)
            await interaction.response.edit_message(content="**🌍 Select a continent for close-up view:**", view=view, embed=None)
        elif self.region == "germany":
            # Zeige Bundesland-Auswahl für Deutschland-Karten
            view = StateSelectionView(self.cog, self.guild_id)
            await interaction.response.edit_message(content="**🔍 Select a German state for close-up view:**", view=view, embed=None)
        else:
            # Kein Close-up für andere Regionen
            await interaction.response.send_message("❌ Region close-up is not available for this map type.", ephemeral=True)

        

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
            
            view = UserPinOptionsView(self.cog, self.region)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # User doesn't have a pin - show modal directly
            await interaction.response.send_modal(LocationModal(self.cog, self.region))

    @discord.ui.button(
        label="...",
        style=discord.ButtonStyle.secondary,
        custom_id="map_menu_button"
    )
    async def menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MapMenuView(self.cog, self.region, self.guild_id)
        await interaction.response.send_message(content="**Select an option:**", view=view, ephemeral=True)
            
class UserPinOptionsView(discord.ui.View):
    def __init__(self, cog: 'MapV2Cog', region: str):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.cog = cog
        self.region = region

    @discord.ui.button(
        label="📍 Change",
        style=discord.ButtonStyle.primary,
        emoji="🔄"
    )
    async def change_location(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LocationModal(self.cog, self.region))

    @discord.ui.button(
        label="🗑️ Remove ",
        style=discord.ButtonStyle.danger,
        emoji="❌"
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
        await self.cog._invalidate_map_cache(guild_id)
        
        channel_id = self.cog.maps[guild_id]['channel_id']
        await self.cog._update_map(int(guild_id), channel_id)
        await self.cog._update_global_overview()

        await interaction.followup.send(
            f"✅ Your pin has been removed from the map!\n"
            f"📍 **Removed location:** {old_location}\n"
            f"🗺️ The map has been updated in <#{channel_id}>.",
            ephemeral=True
        )


class MapV2Cog(commands.Cog):
    """Cog for managing maps with user pins displayed as images."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("map")
        
        # New data structure
        self.data_dir = Path(__file__).parent.parent / "config"
        self.data_dir.mkdir(exist_ok=True)
        
        self.cache_dir = Path(__file__).parent.parent / "data/map_cache"
        self.cache_dir.mkdir(exist_ok=True)
        
        # Global overview config file
        self.global_config_file = self.data_dir / "map_global_config.json"
        self.global_config = self._load_global_config()
        
        self.maps = self._load_all_data()
        
        # In-memory cache for base maps - now unlimited time
        self.base_map_cache = {}
        
        # Map region configurations
        self.base_image_width = IMAGE_WIDTH
        self.map_configs = {
            "world": {
                "center_lat": 0.0,
                "center_lng": 0.0,
                "bounds": [[-65.0, -180.0], [85.0, 180.0]]
            },
            "europe": {
                "center_lat": 57.5,
                "center_lng": 12.0,
                "bounds": [[34.5, -25.0], [73.0, 40.0]]
            },
            "germany": {
                "center_lat": 51.1657,
                "center_lng": 10.4515,
                "bounds": [[47.2701, 5.8663], [55.0583, 15.0419]]
            },
            "asia": {
                "bounds": [[-8.0, 24.0], [82.0, 180.0]] 
            },
            "northamerica": {
                "bounds": [[5.0, -180.0], [82.0, -50.0]]
            },
            "southamerica": {
                "bounds": [[-60.0, -85.0], [20.0, -33.0]]
            },
            "africa": {
                "bounds": [[-40.0, -20.0], [40.0, 60.0]]
            },
            "australia": {
                "bounds": [[-45.0, 110.0], [-10.0, 155.0]]
            },
            "usmainland": {
                "bounds": [[24.0, -126.0], [51.0, -66.0]]
            }
        }

    def _load_global_config(self) -> Dict:
        """Load global overview configuration."""
        try:
            if self.global_config_file.exists():
                with self.global_config_file.open('r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.log.error(f"Failed to load global config: {e}")
        return {}

    async def _save_global_config(self):
        """Save global overview configuration."""
        try:
            with self.global_config_file.open('w', encoding='utf-8') as f:
                json.dump(self.global_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log.error(f"Failed to save global config: {e}")

    async def cog_load(self):
        """Called when the cog is loaded. Re-register persistent views."""
        try:
            # Register all persistent views for existing maps
            for guild_id, map_data in self.maps.items():
                region = map_data.get('region', 'world')
                view = MapPinButtonView(self, region, int(guild_id))
                self.bot.add_view(view)
                self.log.info(f"Re-registered persistent view for guild {guild_id}")
        except Exception as e:
            self.log.error(f"Error re-registering views: {e}")

    def _get_cache_key(self, guild_id: int) -> str:
        """Generate a cache key based on guild pins."""
        map_data = self.maps.get(str(guild_id), {})
        pins = map_data.get('pins', {})
        region = map_data.get('region', 'world')
        
        # Create hash from pins and region
        pin_data = {}
        for user_id, pin in pins.items():
            pin_data[user_id] = (pin['lat'], pin['lng'])
        
        cache_string = f"{region}:{json.dumps(pin_data, sort_keys=True)}"
        return hashlib.md5(cache_string.encode()).hexdigest()

    def _calculate_image_dimensions(self, region: str) -> Tuple[int, int]:
        """Calculate image dimensions based on region bounds and fixed width."""
        config = self.map_configs[region]
        (lat0, lon0), (lat1, lon1) = config["bounds"]
        
        # Calculate aspect ratio from geographic bounds
        lat_range = lat1 - lat0
        lon_range = lon1 - lon0
        
        # Use Web Mercator projection for aspect ratio calculation
        # Convert latitude to Web Mercator Y coordinates for proper scaling
        import math
        
        def lat_to_mercator_y(lat):
            return math.log(math.tan((90 + lat) * math.pi / 360))
        
        y0 = lat_to_mercator_y(lat0)
        y1 = lat_to_mercator_y(lat1)
        mercator_y_range = y1 - y0
        
        # Calculate height based on mercator projection ratio
        aspect_ratio = mercator_y_range / (lon_range * math.pi / 180)
        height = int(self.base_image_width * aspect_ratio)
        
        return self.base_image_width, height

    def _get_base_map_cache_key(self, region: str) -> str:
        """Generate cache key for base map (without pins)."""
        width, height = self._calculate_image_dimensions(region)
        return f"base_{region}_{width}_{height}"

    async def _get_cached_base_map(self, region: str) -> Optional[Image.Image]:
        """Get cached base map if available."""
        cache_key = self._get_base_map_cache_key(region)
        
        # Check in-memory cache first
        if cache_key in self.base_map_cache:
            self.log.info(f"Using in-memory cached base map for {region}")
            return self.base_map_cache[cache_key].copy()
        
        # Check disk cache - unlimited time now
        cache_file = self.cache_dir / f"{cache_key}.png"
        if cache_file.exists():
            try:
                image = Image.open(cache_file)
                # Store in memory cache too
                self.base_map_cache[cache_key] = image.copy()
                self.log.info(f"Using disk cached base map for {region}")
                return image.copy()
            except Exception as e:
                self.log.warning(f"Error loading cached base map: {e}")
        
        return None

    async def _cache_base_map(self, region: str, image: Image.Image):
        """Cache base map both in memory and on disk."""
        cache_key = self._get_base_map_cache_key(region)
        
        # Store in memory
        self.base_map_cache[cache_key] = image.copy()
        
        # Store on disk
        try:
            cache_file = self.cache_dir / f"{cache_key}.png"
            image.save(cache_file, 'PNG', optimize=True)
            self.log.info(f"Cached base map for {region}")
        except Exception as e:
            self.log.warning(f"Error caching base map to disk: {e}")

    async def _get_cached_map(self, guild_id: int) -> Optional[discord.File]:
        """Get cached final map if available - unlimited time now."""
        cache_key = self._get_cache_key(guild_id)
        cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
        
        if cache_file.exists():
            try:
                filename = f"map_{cache_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                self.log.info(f"Using cached final map for guild {guild_id}")
                return discord.File(cache_file, filename=filename)
            except Exception as e:
                self.log.warning(f"Error loading cached map: {e}")
        
        return None

    async def _cache_map(self, guild_id: int, image_buffer: BytesIO):
        """Cache the final map image."""
        try:
            cache_key = self._get_cache_key(guild_id)
            cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
            
            image_buffer.seek(0)
            with open(cache_file, 'wb') as f:
                f.write(image_buffer.read())
            
            self.log.info(f"Cached final map for guild {guild_id}")
        except Exception as e:
            self.log.warning(f"Error caching final map: {e}")

    async def _invalidate_map_cache(self, guild_id: int):
        """Invalidate cached maps for a guild."""
        try:
            # Remove all cached maps for this guild
            cache_pattern = f"map_{guild_id}_*.png"
            for cache_file in self.cache_dir.glob(cache_pattern):
                cache_file.unlink()
            self.log.info(f"Invalidated cache for guild {guild_id}")
        except Exception as e:
            self.log.warning(f"Error invalidating cache: {e}")

    def _load_all_data(self) -> Dict:
        """Load all guild map data from individual files."""
        maps = {}
        try:
            for guild_dir in self.data_dir.iterdir():
                if guild_dir.is_dir() and guild_dir.name.isdigit():
                    guild_id = guild_dir.name
                    map_file = guild_dir / "map.json"
                    if map_file.exists():
                        try:
                            with map_file.open('r', encoding='utf-8') as f:
                                maps[guild_id] = json.load(f)
                        except Exception as e:
                            self.log.error(f"Failed to load map data for guild {guild_id}: {e}")
        except Exception as e:
            self.log.error(f"Failed to load map data: {e}")
        
        return maps

    async def _save_data(self, guild_id: str):
        """Save map data for specific guild."""
        try:
            guild_dir = self.data_dir / guild_id
            guild_dir.mkdir(exist_ok=True)
            
            map_file = guild_dir / "map.json"
            
            if guild_id in self.maps:
                # Create backup if exists
                if map_file.exists():
                    backup_file = guild_dir / "map.json.bak"
                    map_file.replace(backup_file)
                
                with map_file.open('w', encoding='utf-8') as f:
                    json.dump(self.maps[guild_id], f, indent=2, ensure_ascii=False)
            else:
                # Remove file if guild data was deleted
                if map_file.exists():
                    map_file.unlink()
                    
        except Exception as e:
            self.log.error(f"Failed to save map data for guild {guild_id}: {e}")

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
                'User-Agent': 'DiscordBot-MapPins/2.0'
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

    async def _render_geopandas_map(self, region: str, width: int, height: int) -> Tuple[Image.Image, callable]:
        """Render map using geopandas for all regions."""
        try:
            # Load shapefiles
            base = Path(__file__).parent.parent / "data"
            world = gpd.read_file(base / "ne_10m_admin_0_countries.shp")
            states = gpd.read_file(base / "ne_10m_admin_1_states_provinces.shp") 
            land = gpd.read_file(base / "ne_10m_land.shp")
            lakes = gpd.read_file(base / "ne_10m_lakes.shp")
            rivers = gpd.read_file(base / "ne_10m_rivers_lake_centerlines.shp")
            
            # Get bounds based on region
            config = self.map_configs[region]
            (lat0, lon0), (lat1, lon1) = config["bounds"]
            minx, miny, maxx, maxy = lon0, lat0, lon1, lat1
            
            # For germany regions, try to get better bounds from actual data
            if region in ["germany"]:
                try:
                    de = world[world["ADMIN"] == "Germany"].geometry.unary_union
                    if de is not None:
                        de_buf = de.buffer(0.1)  # Smaller buffer for better fit
                        bounds = de_buf.bounds
                        if all(math.isfinite(v) for v in bounds) and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                            minx, miny, maxx, maxy = bounds
                except Exception as e:
                    self.log.warning(f"Could not get Germany bounds from data: {e}")
            
            bbox = box(minx, miny, maxx, maxy)

            # Projection function
            def to_px(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))

            # Create base image
            img = Image.new("RGB", (width, height), (168, 213, 242))  # Ocean blue
            draw = ImageDraw.Draw(img)

            # Draw land
            for poly in land.geometry:
                if not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=(240, 240, 220), outline=None)
                    except:
                        continue

            # Draw lakes
            for poly in lakes.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=(168, 213, 242))
                    except:
                        continue

            # Determine line widths based on region and image size
            if region == "world":
                river_width = max(1, int(width / 3000))  # Very thin for world map
                country_width = max(1, int(width / 1500))
                #state_width = max(1, int(width / 3000))
                state_width = 0
            elif region == "europe":
                river_width = max(1, int(width / 2000))
                country_width = max(1, int(width / 1000))
                #state_width = max(1, int(width / 2000))
                state_width = 0
            else:  # germany
                river_width = max(2, int(width / 1200))
                country_width = max(2, int(width / 600))
                state_width = max(1, int(width / 1200))

            # Draw rivers with appropriate width
            if region != "world":
                for line in rivers.geometry:
                    if line is None or not line.intersects(bbox):
                        continue
                    for seg in getattr(line, "geoms", [line]):
                        try:
                            pts = [to_px(y, x) for x, y in seg.coords]
                            if len(pts) >= 2:
                                draw.line(pts, fill=(60, 60, 200), width=river_width)
                        except:
                            continue
                    
            # Draw boundaries with appropriate widths
            if region != "world":
                for layer, color, width_multiplier in [
                        (world.geometry, (0, 0, 0), country_width),
                        (states.geometry, (100, 100, 100), state_width),
                ]:
                    for poly in layer:
                        if poly is None or not poly.intersects(bbox):
                            continue
                        for ring in getattr(poly, "geoms", [poly]):
                            try:
                                pts = [to_px(y, x) for x, y in ring.exterior.coords]
                                if len(pts) >= 2:
                                    if width_multiplier != 0:
                                        draw.line(pts, fill=color, width=width_multiplier)
                            except:
                                continue
                            
            return img, to_px
            
        except Exception as e:
            self.log.error(f"Failed to render geopandas map for {region}: {e}")
            # Fallback
            img = Image.new("RGB", (width, height), (168, 213, 242))
            
            def fallback_projection(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))
            
            return img, fallback_projection

    async def _generate_continent_closeup(self, guild_id: int, continent: str) -> Optional[BytesIO]:
        """Generate a close-up map of a continent using existing map configs."""
        try:
            if continent not in self.map_configs:
                self.log.warning(f"Continent {continent} not in map configurations")
                return None
        
            # Verwende existierende Karten-Generierung
            width, height = self._calculate_image_dimensions(continent)
            base_map, projection_func = await self._render_geopandas_map(continent, width, height)
        
            if not base_map or not projection_func:
                return None
        
            # Zeichne Pins für diese Guild
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            base_pin_size = int(height * 16 / 2400)
            pin_groups = self._group_overlapping_pins(pins, projection_func, base_pin_size)
        
            draw = ImageDraw.Draw(base_map)
            
            for group in pin_groups:
                x, y = group['position']
                count = group['count']
            
                if x < base_pin_size or x >= width - base_pin_size or y < base_pin_size or y >= height - base_pin_size:
                    continue
            
                pin_size = base_pin_size + (count - 1) * 3
                pin_color = '#FF4444'
            
                # Pin Shadow
                shadow_offset = 2
                draw.ellipse([
                    x - pin_size + shadow_offset,
                    y - pin_size + shadow_offset,
                    x + pin_size + shadow_offset,
                    y + pin_size + shadow_offset
                ], fill='#00000080')
            
                # Pin
                draw.ellipse([x - pin_size, y - pin_size, x + pin_size, y + pin_size],
                             fill=pin_color, outline='white', width=2)
            
                # Anzahl
                if count > 1:
                    try:
                        font = ImageFont.load_default()
                        text = str(count)
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        text_x = x - text_width // 2
                        text_y = y - text_height // 2
                        draw.text((text_x, text_y), text, fill='white', font=font)
                    except:
                        draw.text((x-5, y-5), str(count), fill='white')

            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return img_buffer
        
        except Exception as e:
            self.log.error(f"Failed to generate continent closeup for {continent}: {e}")
            return None
        
    async def _generate_state_closeup(self, guild_id: int, state_name: str) -> Optional[BytesIO]:
        """Generate a close-up map of a German state."""
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
                self.log.warning(f"State {state_name} not found. Available states: {list(german_states['name'].values)}")
                return None
            
            # Get state geometry and bounds
            state_geom = state_row.geometry.iloc[0]
            bounds = state_geom.bounds
            minx, miny, maxx, maxy = bounds
            
            # Add padding based on state size (proportional padding)
            width_range = maxx - minx
            height_range = maxy - miny
            padding_x = width_range * 0.05  # 5% padding
            padding_y = height_range * 0.05
            
            minx -= padding_x
            maxx += padding_x
            miny -= padding_y
            maxy += padding_y
            
            bbox = box(minx, miny, maxx, maxy)
            
            # Calculate image dimensions maintaining aspect ratio
            geo_width = maxx - minx
            geo_height = maxy - miny

            import math

            def lat_to_mercator_y(lat):
                return math.log(math.tan((90 + lat) * math.pi / 360))

            y0 = lat_to_mercator_y(miny)
            y1 = lat_to_mercator_y(maxy)
            mercator_y_range = y1 - y0

            lon_range_radians = geo_width * math.pi / 180
            aspect_ratio = mercator_y_range / lon_range_radians

            width = 1400
            height = int(width * aspect_ratio)
            
            # Projection function
            def to_px(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))

            # Load additional data
            world = gpd.read_file(base / "ne_10m_admin_0_countries.shp")
            land = gpd.read_file(base / "ne_10m_land.shp")
            lakes = gpd.read_file(base / "ne_10m_lakes.shp")
            rivers = gpd.read_file(base / "ne_10m_rivers_lake_centerlines.shp")
            
            # Create image
            img = Image.new("RGB", (width, height), (168, 213, 242))
            draw = ImageDraw.Draw(img)

            # Draw land - use standard land color
            for poly in land.geometry:
                if not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=(240, 240, 220), outline=None)
                    except:
                        continue

            # Draw lakes
            for poly in lakes.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=(168, 213, 242))
                    except:
                        continue

            # Calculate appropriate line widths for state view
            river_width = max(1, int(width / 800))
            country_width = max(2, int(width / 400))
            state_width = max(1, int(width / 800))

            # Draw rivers
            for line in rivers.geometry:
                if line is None or not line.intersects(bbox):
                    continue
                for seg in getattr(line, "geoms", [line]):
                    try:
                        pts = [to_px(y, x) for x, y in seg.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=(60, 60, 200), width=river_width)
                    except:
                        continue

            # Draw boundaries
            for layer, color, w in [
                (world.geometry, (0, 0, 0), country_width),
                (states.geometry, (100, 100, 100), state_width),
            ]:
                for poly in layer:
                    if poly is None or not poly.intersects(bbox):
                        continue
                    for ring in getattr(poly, "geoms", [poly]):
                        try:
                            pts = [to_px(y, x) for x, y in ring.exterior.coords]
                            if len(pts) >= 2:
                                draw.line(pts, fill=color, width=w)
                        except:
                            continue

            # Highlight the selected state with a subtle color and border
            try:
                if hasattr(state_geom, 'exterior'):
                    # Single polygon
                    coords_list = [state_geom.exterior.coords]
                else:
                    # MultiPolygon
                    coords_list = [ring.exterior.coords for ring in state_geom.geoms]
                
                for coords in coords_list:
                    pts = [to_px(y, x) for x, y in coords]
                    #if len(pts) >= 3:
                        # Subtle highlight - slightly different land color
                        #draw.polygon(pts, fill=(250, 250, 200), outline=(200, 0, 0), width=3)
            except Exception as e:
                self.log.warning(f"Could not highlight state {state_name}: {e}")

            # Draw pins for this guild in the state area
            map_data = self.maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            
            # Calculate pin size based on image height
            base_pin_size = int(height * 16 / 2400)  # Scale based on image height
            
            # Group overlapping pins
            pin_groups = self._group_overlapping_pins(pins, to_px, base_pin_size)
            
            for group in pin_groups:
                x, y = group['position']
                count = group['count']
                
                # Skip if outside image bounds
                if x < base_pin_size or x >= width - base_pin_size or y < base_pin_size or y >= height - base_pin_size:
                    continue
                
                # Calculate pin size based on count
                pin_size = base_pin_size + (count - 1) * 3
                pin_color = '#FF4444'
                
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
                
                # Draw count if multiple pins
                if count > 1:
                    try:
                        # Try to load a font, fallback to default
                        try:
                            font = ImageFont.truetype("arial.ttf", pin_size)
                        except:
                            font = ImageFont.load_default()
                        
                        text = str(count)
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        text_x = x - text_width // 2
                        text_y = y - text_height // 2
                        draw.text((text_x, text_y), text, fill='white', font=font)
                    except:
                        # Fallback without font
                        draw.text((x-5, y-5), str(count), fill='white')

            # Convert to BytesIO
            img_buffer = BytesIO()
            img.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return img_buffer
            
        except Exception as e:
            self.log.error(f"Failed to generate state closeup for {state_name}: {e}")
            return None
        
    def _group_overlapping_pins(self, pins: Dict, projection_func: callable, base_pin_size: int) -> List[Dict]:
        """Group overlapping pins together."""
        if not pins:
            return []
        
        # Convert pins to pixel coordinates
        pin_positions = []
        for user_id, pin_data in pins.items():
            lat, lng = pin_data['lat'], pin_data['lng']
            x, y = projection_func(lat, lng)
            pin_positions.append({
                'user_id': user_id,
                'position': (x, y),
                'data': pin_data
            })
        
        # Group pins that are close together
        groups = []
        used_pins = set()
        overlap_threshold = base_pin_size * 2  # Pins closer than this will be grouped
        
        for i, pin in enumerate(pin_positions):
            if i in used_pins:
                continue
                
            group = {
                'position': pin['position'],
                'count': 1,
                'pins': [pin]
            }
            used_pins.add(i)
            
            # Find nearby pins
            for j, other_pin in enumerate(pin_positions):
                if j in used_pins or j == i:
                    continue
                
                # Calculate distance
                dx = pin['position'][0] - other_pin['position'][0]
                dy = pin['position'][1] - other_pin['position'][1]
                distance = math.sqrt(dx*dx + dy*dy)
                
                if distance < overlap_threshold:
                    group['pins'].append(other_pin)
                    group['count'] += 1
                    used_pins.add(j)
            
            # Calculate center position for grouped pins
            if group['count'] > 1:
                center_x = sum(p['position'][0] for p in group['pins']) // group['count']
                center_y = sum(p['position'][1] for p in group['pins']) // group['count']
                group['position'] = (center_x, center_y)
            
            groups.append(group)
        
        return groups

    async def _generate_map_image(self, guild_id: int) -> Optional[discord.File]:
        """Generate a map image with pins for the guild."""
        try:
            # Check for cached final map first
            cached_map = await self._get_cached_map(guild_id)
            if cached_map:
                return cached_map

            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            
            # Calculate dimensions based on region
            width, height = self._calculate_image_dimensions(region)
            if region != "germany" and region != "usmainland":
                height = int(height * 0.8)
            
            # Try to get cached base map first
            base_map = await self._get_cached_base_map(region)
            projection_func = None
            
            if not base_map:
                # Generate new base map using geopandas for all regions
                base_map, projection_func = await self._render_geopandas_map(region, width, height)
                
                if base_map:
                    # Cache the new base map
                    await self._cache_base_map(region, base_map)
                else:
                    # Fallback to simple background
                    base_map = Image.new('RGB', (width, height), color=(168, 213, 242))
            else:
                # For cached maps, recreate the projection function
                config = self.map_configs[region]
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
                            if all(math.isfinite(v) for v in bounds) and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                                minx, miny, maxx, maxy = bounds
                    except Exception as e:
                        self.log.warning(f"Could not recreate Germany bounds: {e}")
                
                def to_px(lat, lon):
                    x = (lon - minx) / (maxx - minx) * width
                    y = (maxy - lat) / (maxy - miny) * height
                    return (int(x), int(y))
                
                projection_func = to_px
            
            # Calculate pin size based on image height
            base_pin_size = int(height * 16 / 2400)  # Scale based on original germany map ratio
            
            # Group overlapping pins
            pin_groups = self._group_overlapping_pins(pins, projection_func, base_pin_size)
            
            # Draw pins on the map
            draw = ImageDraw.Draw(base_map)
            
            for group in pin_groups:
                x, y = group['position']
                count = group['count']
                
                # Skip if pin is outside the image
                if x < base_pin_size or x >= width - base_pin_size or y < base_pin_size or y >= height - base_pin_size:
                    continue
                
                # Calculate pin size based on count
                pin_size = base_pin_size + (count - 1) * 3
                pin_color = '#FF4444'
                
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
                
                # Draw count if multiple pins
                if count > 1:
                    try:
                        # Try to load a font, fallback to default
                        try:
                            font = ImageFont.truetype("arial.ttf", pin_size)
                        except:
                            font = ImageFont.load_default()
                        
                        text = str(count)
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        text_x = x - text_width // 2
                        text_y = y - text_height // 2
                        draw.text((text_x, text_y), text, fill='white', font=font)
                    except:
                        # Fallback without font
                        draw.text((x-5, y-5), str(count), fill='white')
            
            # Convert PIL image to Discord file
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            
            # Cache the final image
            await self._cache_map(guild_id, img_buffer)
            
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
            await self._save_global_config()
            
        except Exception as e:
            self.log.error(f"Failed to update global overview: {e}")

    @app_commands.command(name="map_create", description="Create a map for the server")
    @app_commands.describe(
        channel="Channel where the map will be posted",
        region="Map region (world by default)"
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
        region: str = "world"
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

    async def _handle_pin_location(self, interaction: discord.Interaction, location: str):
        """Handle the actual pin location logic."""

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
        # Check if user is bot owner
        #app_info = await self.bot.application_info()
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ This command is only available to the bot owner.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        self.global_config['enabled'] = True
        self.global_config['channel_id'] = channel.id
        await self._save_global_config()
        
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
            # Clear in-memory cache
            self.base_map_cache.clear()
            
            # Clear disk cache
            cache_files = list(self.cache_dir.glob("*.png"))
            for cache_file in cache_files:
                cache_file.unlink()
            
            await interaction.followup.send(
                f"✅ Cache cleared successfully!\n"
                f"🗑️ Removed {len(cache_files)} cached images.",
                ephemeral=True
            )
            
        except Exception as e:
            self.log.error(f"Error clearing cache: {e}")
            await interaction.followup.send("❌ Error clearing cache.", ephemeral=True)

    @app_commands.command(name="owner_refresh_map_overview", description="Manually refresh global overview (Bot Owner only)")
    async def refresh_global_overview(self, interaction: discord.Interaction):
        # Check if user is bot owner
        #app_info = await self.bot.application_info()
        if interaction.user.id != 485051896655249419:
            await interaction.response.send_message("❌ This command is only available to the bot owner.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            await self._update_global_overview()
            await interaction.followup.send("✅ Global overview has been refreshed!", ephemeral=True)
        except Exception as e:
            self.log.error(f"Error refreshing global overview: {e}")
            await interaction.followup.send("❌ Error refreshing global overview.", ephemeral=True)

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        # Save all guild data
        for guild_id in self.maps.keys():
            asyncio.create_task(self._save_data(guild_id))
        
async def setup(bot: commands.Bot):
    await bot.add_cog(MapV2Cog(bot))
