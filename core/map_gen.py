"""Map generation utilities for the Discord Map Bot."""

import math
import asyncio
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Callable, Union
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import geopandas as gpd
from shapely.geometry import box
import aiohttp

# Import configuration
from core.map_config import MapConfig


class MapGenerator:
    """Handles map generation and rendering."""
    
    def __init__(self, data_dir: Path, cache_dir: Path, logger):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.log = logger
        self.map_config = MapConfig()
        
        # Map region configurations from config
        self.base_image_width = 1500
        self.map_configs = self.map_config.MAP_REGIONS

    def _ensure_color_tuple(self, color_value, default_tuple: tuple) -> tuple:
        """Ensure color value is a valid RGB tuple."""
        # WICHTIG: Auch Listen akzeptieren, nicht nur Tupel
        if isinstance(color_value, (tuple, list)) and len(color_value) == 3:
            # Validate tuple/list values are integers in range 0-255
            try:
                r, g, b = color_value
                if all(isinstance(x, (int, float)) and 0 <= x <= 255 for x in [r, g, b]):
                    return (int(r), int(g), int(b))
            except (ValueError, TypeError):
                pass
        elif isinstance(color_value, str) and color_value.startswith('#') and len(color_value) == 7:
            # Convert hex to RGB tuple
            try:
                hex_val = color_value[1:]
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return (r, g, b)
            except ValueError:
                pass
    
        # Return default if conversion fails
        return default_tuple

    def _ensure_color_string(self, color_value, default_string: str) -> str:
        """Ensure color value is a valid hex string."""
        if isinstance(color_value, str) and color_value.startswith('#') and len(color_value) == 7:
            return color_value
        elif isinstance(color_value, tuple) and len(color_value) == 3:
            # Convert RGB tuple to hex
            try:
                r, g, b = color_value
                if all(isinstance(x, (int, float)) and 0 <= x <= 255 for x in [r, g, b]):
                    return f"#{int(r):02x}{int(g):02x}{int(b):02x}".upper()
            except (ValueError, TypeError):
                pass
        
        # Return default if conversion fails
        return default_string
    
    def get_map_colors(self, guild_id: str, maps: Dict) -> Tuple[tuple, tuple]:
        """Get custom colors for land and water from map settings."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        colors = settings.get('colors', {})
    
        land_color_raw = colors.get('land', self.map_config.DEFAULT_LAND_COLOR)
        water_color_raw = colors.get('water', self.map_config.DEFAULT_WATER_COLOR)
        
        # Ensure both colors are valid RGB tuples
        land_color = self._ensure_color_tuple(land_color_raw, self.map_config.DEFAULT_LAND_COLOR)
        water_color = self._ensure_color_tuple(water_color_raw, self.map_config.DEFAULT_WATER_COLOR)
        
        # Debug logging to track color usage
        if settings and colors:
            self.log.debug(f"Using custom colors for guild {guild_id}: land={land_color}, water={water_color}")
        else:
            self.log.debug(f"Using default colors for guild {guild_id}: land={land_color}, water={water_color}")
    
        return land_color, water_color

    def get_border_colors(self, guild_id: str, maps: Dict) -> Tuple[tuple, tuple, tuple]:
        """Get custom colors for borders from map settings."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        borders = settings.get('borders', {})
        
        country_color_raw = borders.get('country', self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
        state_color_raw = borders.get('state', self.map_config.DEFAULT_STATE_BORDER_COLOR)
        river_color_raw = borders.get('river', self.map_config.DEFAULT_RIVER_COLOR)
    
        # Ensure all colors are valid RGB tuples
        country_color = self._ensure_color_tuple(country_color_raw, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
        state_color = self._ensure_color_tuple(state_color_raw, self.map_config.DEFAULT_STATE_BORDER_COLOR)
        river_color = self._ensure_color_tuple(river_color_raw, self.map_config.DEFAULT_RIVER_COLOR)
        
        # Debug logging to track border color usage
        if settings and borders:
            self.log.debug(f"Using custom border colors for guild {guild_id}: country={country_color}, state={state_color}, river={river_color}")
        else:
            self.log.debug(f"Using default border colors for guild {guild_id}")
    
        return country_color, state_color, river_color

    def get_pin_settings(self, guild_id: str, maps: Dict) -> Tuple[str, int]:
        """Get custom pin color and size from map settings."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        pins = settings.get('pins', {})
        
        pin_color_raw = pins.get('color', self.map_config.DEFAULT_PIN_COLOR)
        pin_size_raw = pins.get('size', self.map_config.DEFAULT_PIN_SIZE)
        
        # Ensure pin color is valid hex string
        pin_color = self._ensure_color_string(pin_color_raw, self.map_config.DEFAULT_PIN_COLOR)
        
        # Ensure pin size is valid integer
        try:
            pin_size = int(pin_size_raw)
            pin_size = max(8, min(32, pin_size))  # Clamp between 8-32
        except (ValueError, TypeError):
            pin_size = self.map_config.DEFAULT_PIN_SIZE
    
        # Debug logging to track pin settings usage
        if settings and pins:
            self.log.debug(f"Using custom pin settings for guild {guild_id}: color={pin_color}, size={pin_size}")
        else:
            self.log.debug(f"Using default pin settings for guild {guild_id}")
    
        return pin_color, pin_size

    def calculate_image_dimensions(self, region: str) -> Tuple[int, int]:
        """Calculate image dimensions based on region bounds and fixed width."""
        config = self.map_configs[region]
        (lat0, lon0), (lat1, lon1) = config["bounds"]
        
        # Calculate aspect ratio from geographic bounds
        lat_range = lat1 - lat0
        lon_range = lon1 - lon0
        
        # Use Web Mercator projection for aspect ratio calculation
        def lat_to_mercator_y(lat):
            return math.log(math.tan((90 + lat) * math.pi / 360))
        
        y0 = lat_to_mercator_y(lat0)
        y1 = lat_to_mercator_y(lat1)
        mercator_y_range = y1 - y0
        
        # Calculate height based on mercator projection ratio
        aspect_ratio = mercator_y_range / (lon_range * math.pi / 180)
        height = int(self.base_image_width * aspect_ratio)
        
        return self.base_image_width, height

    async def render_geopandas_map(self, region: str, width: int, height: int, guild_id: str = None, maps: Dict = None) -> Tuple[Image.Image, Callable]:
        """Render map using geopandas for all regions."""
        try:
            # Get custom colors if guild_id provided - ensure they are RGB tuples
            if guild_id and maps:
                land_color, water_color = self.get_map_colors(guild_id, maps)
                country_color, state_color, river_color = self.get_border_colors(guild_id, maps)
            else:
                land_color = self.map_config.DEFAULT_LAND_COLOR
                water_color = self.map_config.DEFAULT_WATER_COLOR
                country_color = self.map_config.DEFAULT_COUNTRY_BORDER_COLOR
                state_color = self.map_config.DEFAULT_STATE_BORDER_COLOR
                river_color = self.map_config.DEFAULT_RIVER_COLOR
            
            # Ensure all colors are valid tuples (safety check)
            land_color = self._ensure_color_tuple(land_color, self.map_config.DEFAULT_LAND_COLOR)
            water_color = self._ensure_color_tuple(water_color, self.map_config.DEFAULT_WATER_COLOR)
            country_color = self._ensure_color_tuple(country_color, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
            state_color = self._ensure_color_tuple(state_color, self.map_config.DEFAULT_STATE_BORDER_COLOR)
            river_color = self._ensure_color_tuple(river_color, self.map_config.DEFAULT_RIVER_COLOR)
            
            # Load shapefiles
            base = self.data_dir.parent / "data"
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

            # Create base image with custom water color
            img = Image.new("RGB", (width, height), water_color)
            draw = ImageDraw.Draw(img)

            # Draw land with custom land color
            for poly in land.geometry:
                if not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=land_color, outline=None)
                    except:
                        continue

            # Draw lakes with custom water color
            for poly in lakes.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=water_color)
                    except:
                        continue

            # Get line widths using new config system
            map_type = "world" if region == "world" else "europe" if region == "europe" else "default"
            river_width, country_width, state_width = self.map_config.get_line_widths(width, map_type)

            # Draw rivers with custom color
            if region != "world":
                for line in rivers.geometry:
                    if line is None or not line.intersects(bbox):
                        continue
                    for seg in getattr(line, "geoms", [line]):
                        try:
                            pts = [to_px(y, x) for x, y in seg.coords]
                            if len(pts) >= 2:
                                draw.line(pts, fill=river_color, width=river_width)
                        except:
                            continue
                    
            # Draw boundaries with custom colors
            if region != "world":
                for layer, color, width_multiplier in [
                        (world.geometry, country_color, country_width),
                        (states.geometry, state_color, state_width),
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
            # Fallback with safe colors
            fallback_water = self.map_config.DEFAULT_WATER_COLOR
            if guild_id and maps:
                try:
                    _, fallback_water = self.get_map_colors(guild_id, maps)
                except:
                    fallback_water = self.map_config.DEFAULT_WATER_COLOR
            
            img = Image.new("RGB", (width, height), fallback_water)
            
            # Safe bounds for fallback
            config = self.map_configs.get(region, self.map_configs["world"])
            (lat0, lon0), (lat1, lon1) = config["bounds"]
            minx, miny, maxx, maxy = lon0, lat0, lon1, lat1
            
            def fallback_projection(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))
            
            return img, fallback_projection

    async def render_geopandas_map_bounds(self, minx: float, miny: float, maxx: float, maxy: float, width: int, height: int, guild_id: str = None, maps: Dict = None) -> Tuple[Image.Image, Callable]:
        """Render map using geopandas for custom bounds."""
        try:
            # Get custom colors if guild_id provided - ensure they are RGB tuples
            if guild_id and maps:
                land_color, water_color = self.get_map_colors(guild_id, maps)
                country_color, state_color, river_color = self.get_border_colors(guild_id, maps)
            else:
                land_color = self.map_config.DEFAULT_LAND_COLOR
                water_color = self.map_config.DEFAULT_WATER_COLOR
                country_color = self.map_config.DEFAULT_COUNTRY_BORDER_COLOR
                state_color = self.map_config.DEFAULT_STATE_BORDER_COLOR
                river_color = self.map_config.DEFAULT_RIVER_COLOR
            
            # Ensure all colors are valid tuples (safety check)
            land_color = self._ensure_color_tuple(land_color, self.map_config.DEFAULT_LAND_COLOR)
            water_color = self._ensure_color_tuple(water_color, self.map_config.DEFAULT_WATER_COLOR)
            country_color = self._ensure_color_tuple(country_color, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
            state_color = self._ensure_color_tuple(state_color, self.map_config.DEFAULT_STATE_BORDER_COLOR)
            river_color = self._ensure_color_tuple(river_color, self.map_config.DEFAULT_RIVER_COLOR)
            
            # Load shapefiles
            base = self.data_dir.parent / "data"
            world = gpd.read_file(base / "ne_10m_admin_0_countries.shp")
            states = gpd.read_file(base / "ne_10m_admin_1_states_provinces.shp") 
            land = gpd.read_file(base / "ne_10m_land.shp")
            lakes = gpd.read_file(base / "ne_10m_lakes.shp")
            rivers = gpd.read_file(base / "ne_10m_rivers_lake_centerlines.shp")
        
            bbox = box(minx, miny, maxx, maxy)
        
            # Projection function
            def to_px(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))
            
            # Create base image with custom water color
            img = Image.new("RGB", (width, height), water_color)
            draw = ImageDraw.Draw(img)
            
            # Draw land with custom land color
            for poly in land.geometry:
                if not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=land_color, outline=None)
                    except:
                        continue

            # Draw lakes with custom water color
            for poly in lakes.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=water_color)
                    except:
                        continue
                    
            # Calculate line widths for proximity maps using config system
            river_width, country_width, state_width = self.map_config.get_line_widths(width, "proximity")

            # Draw rivers with custom color
            for line in rivers.geometry:
                if line is None or not line.intersects(bbox):
                    continue
                for seg in getattr(line, "geoms", [line]):
                    try:
                        pts = [to_px(y, x) for x, y in seg.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=river_color, width=river_width)
                    except:
                        continue

            # Draw country boundaries with custom color
            for poly in world.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=country_color, width=country_width)
                    except:
                        continue

            # Draw state boundaries with custom color
            for poly in states.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=state_color, width=state_width)
                    except:
                        continue
                
            return img, to_px
    
        except Exception as e:
            self.log.error(f"Failed to render geopandas map for bounds: {e}")
            # Fallback with safe colors
            fallback_water = self.map_config.DEFAULT_WATER_COLOR
            if guild_id and maps:
                try:
                    _, fallback_water = self.get_map_colors(guild_id, maps)
                except:
                    fallback_water = self.map_config.DEFAULT_WATER_COLOR
            
            img = Image.new("RGB", (width, height), fallback_water)
        
            def fallback_projection(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))
    
            return img, fallback_projection

    def group_overlapping_pins(self, pins: Dict, projection_func: Callable, base_pin_size: int) -> List[Dict]:
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

    def draw_pins_on_map(self, image: Image.Image, pin_groups: List[Dict], width: int, height: int, base_pin_size: int, guild_id: str = None, maps: Dict = None):
        """Draw pin groups on the map image with custom colors and sizes."""
        draw = ImageDraw.Draw(image)
        
        # Get custom pin settings if guild_id provided
        if guild_id and maps:
            pin_color, custom_pin_size = self.get_pin_settings(guild_id, maps)
            # Scale the custom size based on image height
            base_pin_size = int(height * custom_pin_size / 2400)
        else:
            pin_color = self.map_config.DEFAULT_PIN_COLOR
        
        for group in pin_groups:
            x, y = group['position']
            count = group['count']
            
            # Skip if pin is outside the image
            if x < base_pin_size or x >= width - base_pin_size or y < base_pin_size or y >= height - base_pin_size:
                continue
            
            # Calculate pin size based on count
            pin_size = base_pin_size + (count - 1) * 3
            
            # Draw pin shadow
            shadow_offset = 2
            draw.ellipse([
                x - pin_size + shadow_offset,
                y - pin_size + shadow_offset,
                x + pin_size + shadow_offset,
                y + pin_size + shadow_offset
            ], fill='#00000080')
            
            # Draw pin with custom color
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

    async def geocode_location(self, location: str) -> Optional[Tuple[float, float, str]]:
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

    def calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two points using Haversine formula (in km)."""
        R = 6371  # Earth's radius in km
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
