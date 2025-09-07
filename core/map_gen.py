"""Map generation utilities for the Discord Map Bot."""

import math
import asyncio
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Callable
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import geopandas as gpd
from shapely.geometry import box
import aiohttp


class MapGenerator:
    """Handles map generation and rendering."""
    
    def __init__(self, data_dir: Path, cache_dir: Path, logger):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.log = logger
        
        # Map region configurations
        self.base_image_width = 1500
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

    async def render_geopandas_map(self, region: str, width: int, height: int) -> Tuple[Image.Image, Callable]:
        """Render map using geopandas for all regions."""
        try:
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
                state_width = 0
            elif region == "europe":
                river_width = max(1, int(width / 2000))
                country_width = max(1, int(width / 1000))
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

    async def render_geopandas_map_bounds(self, minx: float, miny: float, maxx: float, maxy: float, width: int, height: int) -> Tuple[Image.Image, Callable]:
        """Render map using geopandas for custom bounds."""
        try:
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
                    
            # Calculate line widths for proximity maps
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

            # NEW: Draw country boundaries (thick black lines)
            for poly in world.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=(0, 0, 0), width=country_width)
                    except:
                        continue

            # NEW: Draw state boundaries (gray lines) 
            for poly in states.geometry:
                if poly is None or not poly.intersects(bbox):
                    continue
                for ring in getattr(poly, "geoms", [poly]):
                    try:
                        pts = [to_px(y, x) for x, y in ring.exterior.coords]
                        if len(pts) >= 2:
                            draw.line(pts, fill=(100, 100, 100), width=state_width)
                    except:
                        continue
                
            return img, to_px
    
        except Exception as e:
            self.log.error(f"Failed to render geopandas map for bounds: {e}")
            # Fallback
            img = Image.new("RGB", (width, height), (168, 213, 242))
        
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

    def draw_pins_on_map(self, image: Image.Image, pin_groups: List[Dict], width: int, height: int, base_pin_size: int):
        """Draw pin groups on the map image."""
        draw = ImageDraw.Draw(image)
        
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
