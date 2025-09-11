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

from core.map_config import MapConfig


class ShapefileRenderer:
    """Helper class for rendering shapefiles."""
    
    def __init__(self, logger):
        self.log = logger
    
    def load_shapefiles(self, base_path: Path, required_files: List[str] = None) -> Dict:
        """Load required shapefiles."""
        if required_files is None:
            required_files = ['land', 'lakes', 'rivers', 'world', 'states']
        
        shapefiles = {}
        file_mapping = {
            'land': 'ne_10m_land.shp',
            'lakes': 'ne_10m_lakes.shp', 
            'rivers': 'ne_10m_rivers_lake_centerlines.shp',
            'world': 'ne_10m_admin_0_countries.shp',
            'states': 'ne_10m_admin_1_states_provinces.shp'
        }
        
        for key in required_files:
            if key in file_mapping:
                filepath = base_path / file_mapping[key]
                try:
                    if filepath.exists():
                        shapefiles[key] = gpd.read_file(filepath)
                        self.log.debug(f"Loaded {key}: {len(shapefiles[key])} features")
                    else:
                        self.log.warning(f"Shapefile not found: {filepath}")
                        shapefiles[key] = None
                except Exception as e:
                    self.log.error(f"Error loading {key}: {e}")
                    shapefiles[key] = None
        
        return shapefiles
    
    def draw_polygons(self, draw: ImageDraw.Draw, geometries, projection_func: Callable, 
                     bbox, fill_color: tuple, outline_color: tuple = None, width: int = 0):
        """Draw polygon geometries."""
        if geometries is None:
            return
            
        drawn_count = 0
        for poly in geometries:
            if poly is None or not poly.intersects(bbox):
                continue
            for ring in getattr(poly, "geoms", [poly]):
                try:
                    if hasattr(ring, 'exterior'):
                        pts = [projection_func(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=fill_color, outline=outline_color, width=width)
                            drawn_count += 1
                except Exception as e:
                    self.log.debug(f"Error drawing polygon: {e}")
                    continue
        
        self.log.debug(f"Drew {drawn_count} polygons")
    
    def draw_lines(self, draw: ImageDraw.Draw, geometries, projection_func: Callable,
                  bbox, color: tuple, width: int, feature_name: str = ""):
        """Draw line geometries."""
        if width <= 0 or geometries is None:
            return
            
        drawn_count = 0
        intersect_count = 0
        total_count = len(geometries)
        
        for line in geometries:
            if line is None:
                continue
                
            try:
                if feature_name in ["countries", "states"]:
                    buffer_size = 2.0
                else:
                    buffer_size = 0.1
                
                intersects = line.intersects(bbox.buffer(buffer_size))
                if not intersects:
                    continue
                else:
                    intersect_count += 1
                    
            except Exception as e:
                self.log.debug(f"Intersection error for {feature_name}: {e}")
                if feature_name in ["countries", "states"]:
                    intersect_count += 1
                else:
                    continue
                
            if feature_name in ["countries", "states"]:
                try:
                    if hasattr(line, 'exterior'):
                        pts = [projection_func(y, x) for x, y in line.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=color, width=width)
                            drawn_count += 1
                    elif hasattr(line, 'geoms'):
                        for poly in line.geoms:
                            if hasattr(poly, 'exterior'):
                                pts = [projection_func(y, x) for x, y in poly.exterior.coords]
                                if len(pts) >= 2:
                                    draw.line(pts, fill=color, width=width)
                                    drawn_count += 1
                    elif hasattr(line, 'coords'):
                        pts = [projection_func(y, x) for x, y in line.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=color, width=width)
                            drawn_count += 1
                except Exception as e:
                    self.log.debug(f"Error drawing {feature_name}: {e}")
                continue
            
            for seg in getattr(line, "geoms", [line]):
                try:
                    if hasattr(seg, 'coords'):
                        pts = [projection_func(y, x) for x, y in seg.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=color, width=width)
                            drawn_count += 1
                    elif hasattr(seg, 'exterior'):
                        pts = [projection_func(y, x) for x, y in seg.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=color, width=width)
                            drawn_count += 1
                except Exception as e:
                    self.log.debug(f"Error drawing {feature_name} segment: {e}")
                    continue
        
        self.log.info(f"Drew {drawn_count} {feature_name} from {total_count} total")


class MapGenerator:
    """Handles map generation and rendering."""
    
    def __init__(self, data_dir: Path, cache_dir: Path, logger):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.log = logger
        self.map_config = MapConfig()
        self.renderer = ShapefileRenderer(logger)
        self.base_image_width = 1500
        self.map_configs = self.map_config.MAP_REGIONS

    def _ensure_color_tuple(self, color_value, default_tuple: tuple) -> tuple:
        """Ensure color value is a valid RGB tuple."""
        if isinstance(color_value, (tuple, list)) and len(color_value) == 3:
            try:
                r, g, b = color_value
                if all(isinstance(x, (int, float)) and 0 <= x <= 255 for x in [r, g, b]):
                    return (int(r), int(g), int(b))
            except (ValueError, TypeError):
                pass
        elif isinstance(color_value, str) and color_value.startswith('#') and len(color_value) == 7:
            try:
                hex_val = color_value[1:]
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return (r, g, b)
            except ValueError:
                pass
        
        return default_tuple

    def _ensure_color_string(self, color_value, default_string: str) -> str:
        """Ensure color value is a valid hex string."""
        if isinstance(color_value, str) and color_value.startswith('#') and len(color_value) == 7:
            return color_value
        elif isinstance(color_value, tuple) and len(color_value) == 3:
            try:
                r, g, b = color_value
                if all(isinstance(x, (int, float)) and 0 <= x <= 255 for x in [r, g, b]):
                    return f"#{int(r):02x}{int(g):02x}{int(b):02x}".upper()
            except (ValueError, TypeError):
                pass
        
        return default_string
    
    def get_map_colors(self, guild_id: str, maps: Dict) -> Tuple[tuple, tuple]:
        """Get custom colors for land and water."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        colors = settings.get('colors', {})
    
        land_color_raw = colors.get('land', self.map_config.DEFAULT_LAND_COLOR)
        water_color_raw = colors.get('water', self.map_config.DEFAULT_WATER_COLOR)
        
        land_color = self._ensure_color_tuple(land_color_raw, self.map_config.DEFAULT_LAND_COLOR)
        water_color = self._ensure_color_tuple(water_color_raw, self.map_config.DEFAULT_WATER_COLOR)
        
        return land_color, water_color

    def get_border_colors(self, guild_id: str, maps: Dict) -> Tuple[tuple, tuple, tuple]:
        """Get custom colors for borders."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        borders = settings.get('borders', {})
        
        border_color_raw = borders.get('country', self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
        border_color = self._ensure_color_tuple(border_color_raw, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
        
        country_color = border_color
        state_color = border_color
        
        colors = settings.get('colors', {})
        water_color_raw = colors.get('water', self.map_config.DEFAULT_WATER_COLOR)
        river_color = self._ensure_color_tuple(water_color_raw, self.map_config.DEFAULT_WATER_COLOR)
        
        return country_color, state_color, river_color

    def get_pin_settings(self, guild_id: str, maps: Dict) -> Tuple[str, int]:
        """Get custom pin color and size."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        pins = settings.get('pins', {})
        
        pin_color_raw = pins.get('color', self.map_config.DEFAULT_PIN_COLOR)
        pin_size_raw = pins.get('size', self.map_config.DEFAULT_PIN_SIZE)
        
        pin_color = self._ensure_color_string(pin_color_raw, self.map_config.DEFAULT_PIN_COLOR)
        
        try:
            pin_size = int(pin_size_raw)
            pin_size = max(8, min(32, pin_size))
        except (ValueError, TypeError):
            pin_size = self.map_config.DEFAULT_PIN_SIZE
    
        return pin_color, pin_size

    def calculate_image_dimensions(self, region: str) -> Tuple[int, int]:
        """Calculate image dimensions based on region bounds."""
        # Use the new method that checks shapefile bounds first
        data_path = self.data_dir.parent / "data"
        bounds = self.map_config.get_region_bounds(region, data_path)
        (lat0, lon0), (lat1, lon1) = bounds
        
        def lat_to_mercator_y(lat):
            return math.log(math.tan((90 + lat) * math.pi / 360))
        
        y0 = lat_to_mercator_y(lat0)
        y1 = lat_to_mercator_y(lat1)
        mercator_y_range = y1 - y0
        
        aspect_ratio = mercator_y_range / ((lon1 - lon0) * math.pi / 180)
        height = int(self.base_image_width * aspect_ratio)
        
        return self.base_image_width, height

    def create_projection_function(self, minx: float, miny: float, maxx: float, maxy: float, 
                                 width: int, height: int) -> Callable:
        """Create projection function for converting lat/lng to pixel coordinates."""
        def to_px(lat, lon):
            x = (lon - minx) / (maxx - minx) * width
            y = (maxy - lat) / (maxy - miny) * height
            return (int(x), int(y))
        return to_px

    def get_line_widths_for_zoom(self, width: int, map_type: str, zoom_level: str = "normal", 
                                region: str = None, custom_bounds: Tuple[float, float, float, float] = None) -> Tuple[int, int, int]:
        """Get line widths optimized for different zoom levels with geographic scaling.
        
        Updated to use the new geographic scale-aware line width calculation.
        """
        # Use the updated get_line_widths method with geographic scaling
        # FIXED: Correct parameter order matching the function signature
        river_width, country_width, state_width = self.map_config.get_line_widths(
            width=width, 
            map_type=map_type, 
            region=region, 
            custom_bounds=custom_bounds
        )
        
        # Ensure minimum widths
        country_width = max(1, country_width)
        state_width = max(1, state_width)
        river_width = max(1, river_width)
        
        # Apply zoom-specific adjustments (these are additive to the geographic scaling)
        if zoom_level == "state_closeup":
            # For state closeups, slightly increase river visibility
            river_width = max(2, int(river_width * 1.5))
        elif zoom_level == "proximity":
            # For proximity maps, maintain clean thin lines for better clarity
            river_width = max(1, river_width)
        
        return river_width, country_width, state_width

    async def render_base_map(self, minx: float, miny: float, maxx: float, maxy: float,
                            width: int, height: int, map_type: str = "default",
                            guild_id: str = None, maps: Dict = None, zoom_level: str = "normal", 
                            region: str = None, progress_callback=None) -> Tuple[Image.Image, Callable]:
        """Render base map with land, water, rivers, and borders.
        
        Updated to use geographic scale-aware line width calculation.
        """
        self.log.info(f"Rendering base map: {map_type} ({width}x{height}) with geographic scaling")
        
        # Report initial progress
        if progress_callback:
            await progress_callback("Initializing map rendering...", 5)
        
        try:
            if guild_id and maps:
                land_color, water_color = self.get_map_colors(guild_id, maps)
                country_color, state_color, river_color = self.get_border_colors(guild_id, maps)
            else:
                land_color = self.map_config.DEFAULT_LAND_COLOR
                water_color = self.map_config.DEFAULT_WATER_COLOR
                country_color = self.map_config.DEFAULT_COUNTRY_BORDER_COLOR
                state_color = self.map_config.DEFAULT_COUNTRY_BORDER_COLOR
                river_color = self.map_config.DEFAULT_RIVER_COLOR
            
            land_color = self._ensure_color_tuple(land_color, self.map_config.DEFAULT_LAND_COLOR)
            water_color = self._ensure_color_tuple(water_color, self.map_config.DEFAULT_WATER_COLOR)
            country_color = self._ensure_color_tuple(country_color, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
            state_color = self._ensure_color_tuple(state_color, self.map_config.DEFAULT_COUNTRY_BORDER_COLOR)
            river_color = self._ensure_color_tuple(river_color, self.map_config.DEFAULT_RIVER_COLOR)
            
            required_files = ['land', 'lakes', 'rivers', 'world', 'states']
            
            if progress_callback:
                await progress_callback("Loading geographic data...", 15)
            
            base_path = self.data_dir.parent / "data"
            shapefiles = self.renderer.load_shapefiles(base_path, required_files)
            
            bbox = box(minx, miny, maxx, maxy)
            projection_func = self.create_projection_function(minx, miny, maxx, maxy, width, height)
            
            if progress_callback:
                await progress_callback("Creating base canvas...", 25)
            
            img = Image.new("RGB", (width, height), water_color)
            draw = ImageDraw.Draw(img)
            
            if shapefiles['land'] is not None:
                if progress_callback:
                    await progress_callback("Drawing land masses...", 40)
                self.renderer.draw_polygons(draw, shapefiles['land'].geometry, projection_func, bbox, land_color)
                
                # Send intermediate image after land drawing
                if progress_callback:
                    try:
                        intermediate_img = img.copy()
                        img_buffer = BytesIO()
                        intermediate_img.save(img_buffer, format='PNG', optimize=True)
                        await progress_callback("Land masses drawn, adding water bodies...", 45, img_buffer)
                    except Exception as e:
                        await progress_callback("Land masses drawn, adding water bodies...", 45)
            
            if shapefiles['lakes'] is not None:
                if progress_callback:
                    await progress_callback("Drawing lakes and water bodies...", 55)
                self.renderer.draw_polygons(draw, shapefiles['lakes'].geometry, projection_func, bbox, water_color)
                
                # Send intermediate image after lakes drawing
                if progress_callback:
                    try:
                        intermediate_img = img.copy()
                        img_buffer = BytesIO()
                        intermediate_img.save(img_buffer, format='PNG', optimize=True)
                        await progress_callback("Water bodies drawn, adding borders...", 60, img_buffer)
                    except Exception as e:
                        await progress_callback("Water bodies drawn, adding borders...", 60)
            
            # Calculate line widths with geographic scaling
            custom_bounds = (minx, miny, maxx, maxy) if not region else None
            river_width, country_width, state_width = self.get_line_widths_for_zoom(
                width, map_type, zoom_level, region, custom_bounds
            )
            
            # Debug logging for line width calculation
            if region:
                geo_scale = self.map_config.calculate_geographic_scale_factor(region)
                self.log.info(f"Geographic scaling for {region}: factor={geo_scale:.3f}, country_width={country_width}, river_width={river_width}")
            else:
                self.log.info(f"No region specified, using custom bounds for line width calculation")
            
            if map_type != "world" and shapefiles.get('rivers') is not None:
                if progress_callback:
                    await progress_callback("Drawing rivers and waterways...", 70)
                self.renderer.draw_lines(draw, shapefiles['rivers'].geometry, projection_func, bbox, river_color, river_width, "rivers")
            
            # Draw state/province borders only for detailed maps (not continents or world)
            continent_map_types = ["world", "europe", "asia", "africa", "northamerica", "southamerica", "australia"]
            if map_type not in continent_map_types and shapefiles.get('states') is not None:
                if progress_callback:
                    await progress_callback("Drawing state/province borders...", 85)
                self.renderer.draw_lines(draw, shapefiles['states'].geometry, projection_func, bbox, state_color, state_width, "states")
            
            # Draw country borders (admin_0 = international boundaries)
            if shapefiles.get('world') is not None:
                if progress_callback:
                    await progress_callback("Drawing country borders...", 95)
                self.renderer.draw_lines(draw, shapefiles['world'].geometry, projection_func, bbox, country_color, country_width, "countries")
                
                # Send final base map image before completion
                if progress_callback:
                    try:
                        intermediate_img = img.copy()
                        img_buffer = BytesIO()
                        intermediate_img.save(img_buffer, format='PNG', optimize=True)
                        await progress_callback("Base map complete, finalizing...", 98, img_buffer)
                    except Exception as e:
                        await progress_callback("Base map complete, finalizing...", 98)
            
            if progress_callback:
                await progress_callback("Finalizing map rendering...", 100)
            
            return img, projection_func
            
        except Exception as e:
            self.log.error(f"Failed to render base map: {e}")
            fallback_water = water_color if 'water_color' in locals() else self.map_config.DEFAULT_WATER_COLOR
            img = Image.new("RGB", (width, height), fallback_water)
            projection_func = self.create_projection_function(minx, miny, maxx, maxy, width, height)
            return img, projection_func

    async def render_geopandas_map(self, region: str, width: int, height: int, guild_id: str = None, maps: Dict = None, progress_callback=None) -> Tuple[Image.Image, Callable]:
        """Render map for predefined regions with geographic scaling."""
        try:
            # Use the new method that checks shapefile bounds first
            data_path = self.data_dir.parent / "data"
            bounds = self.map_config.get_region_bounds(region, data_path)
            (lat0, lon0), (lat1, lon1) = bounds
            minx, miny, maxx, maxy = lon0, lat0, lon1, lat1
            
            if region == "germany":
                try:
                    base_path = self.data_dir.parent / "data"
                    world = gpd.read_file(base_path / "ne_10m_admin_0_countries.shp")
                    de = world[world["ADMIN"] == "Germany"].geometry.unary_union
                    if de is not None:
                        de_buf = de.buffer(0.1)
                        bounds = de_buf.bounds
                        if all(math.isfinite(v) for v in bounds) and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                            minx, miny, maxx, maxy = bounds
                except Exception as e:
                    self.log.warning(f"Could not get Germany bounds: {e}")
            
            map_type = "world" if region == "world" else "europe" if region == "europe" else "default"
            
            # Pass region to render_base_map for geographic scaling
            return await self.render_base_map(minx, miny, maxx, maxy, width, height, map_type, guild_id, maps, region=region, progress_callback=progress_callback)
            
        except Exception as e:
            self.log.error(f"Failed to render map for {region}: {e}")
            return await self.render_base_map(0, 0, 1, 1, width, height, "default", guild_id, maps)

    async def render_geopandas_map_bounds(self, minx: float, miny: float, maxx: float, maxy: float, 
                                        width: int, height: int, guild_id: str = None, maps: Dict = None, progress_callback=None) -> Tuple[Image.Image, Callable]:
        """Render map for custom bounds with geographic scaling."""
        # Pass custom bounds for geographic scale calculation
        return await self.render_base_map(minx, miny, maxx, maxy, width, height, "proximity", guild_id, maps, "proximity", region=None, progress_callback=progress_callback)

    def group_overlapping_pins(self, pins: Dict, projection_func: Callable, base_pin_size: int) -> List[Dict]:
        """Group overlapping pins together."""
        if not pins:
            return []
        
        pin_positions = []
        for user_id, pin_data in pins.items():
            lat, lng = pin_data['lat'], pin_data['lng']
            x, y = projection_func(lat, lng)
            pin_positions.append({
                'user_id': user_id,
                'position': (x, y),
                'data': pin_data
            })
        
        groups = []
        used_pins = set()
        overlap_threshold = base_pin_size * 2
        
        for i, pin in enumerate(pin_positions):
            if i in used_pins:
                continue
                
            group = {
                'position': pin['position'],
                'count': 1,
                'pins': [pin]
            }
            used_pins.add(i)
            
            for j, other_pin in enumerate(pin_positions):
                if j in used_pins or j == i:
                    continue
                
                dx = pin['position'][0] - other_pin['position'][0]
                dy = pin['position'][1] - other_pin['position'][1]
                distance = math.sqrt(dx*dx + dy*dy)
                
                if distance < overlap_threshold:
                    group['pins'].append(other_pin)
                    group['count'] += 1
                    used_pins.add(j)
            
            if group['count'] > 1:
                center_x = sum(p['position'][0] for p in group['pins']) // group['count']
                center_y = sum(p['position'][1] for p in group['pins']) // group['count']
                group['position'] = (center_x, center_y)
            
            groups.append(group)
        
        return groups

    def draw_pins_on_map(self, image: Image.Image, pin_groups: List[Dict], width: int, height: int, base_pin_size: int, guild_id: str = None, maps: Dict = None):
        """Draw pin groups on the map."""
        draw = ImageDraw.Draw(image)
        
        if guild_id and maps:
            pin_color, custom_pin_size = self.get_pin_settings(guild_id, maps)
            base_pin_size = int(height * custom_pin_size / 2400)
        else:
            pin_color = self.map_config.DEFAULT_PIN_COLOR
        
        for group in pin_groups:
            x, y = group['position']
            count = group['count']
            
            if x < base_pin_size or x >= width - base_pin_size or y < base_pin_size or y >= height - base_pin_size:
                continue
            
            pin_size = base_pin_size + (count - 1) * 3
            
            shadow_offset = 2
            draw.ellipse([
                x - pin_size + shadow_offset,
                y - pin_size + shadow_offset,
                x + pin_size + shadow_offset,
                y + pin_size + shadow_offset
            ], fill='#00000080')
            
            draw.ellipse([x - pin_size, y - pin_size, x + pin_size, y + pin_size],
                       fill=pin_color, outline='white', width=2)
            
            if count > 1:
                try:
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
                    draw.text((x-5, y-5), str(count), fill='white')

    async def geocode_location(self, location: str) -> Optional[Tuple[float, float, str]]:
        """Geocode a location string to coordinates."""
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
            
            return None
            
        except Exception as e:
            self.log.error(f"Geocoding failed for '{location}': {e}")
            return None

    def calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two points using Haversine formula."""
        R = 6371
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c