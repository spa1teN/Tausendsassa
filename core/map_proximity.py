"""Proximity calculation utilities for the Discord Map Bot - FIXED VERSION."""

import math
from typing import Dict, List, Tuple, Optional
from io import BytesIO
from PIL import Image, ImageDraw


class ProximityCalculator:
    """Handles proximity calculations and map generation."""
    
    def __init__(self, map_generator, logger):
        self.map_generator = map_generator
        self.log = logger

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

    def find_nearby_users(self, user_lat: float, user_lng: float, pins: Dict, distance_km: int, exclude_user_id: str) -> List[Dict]:
        """Find users within specified distance from given coordinates."""
        nearby_users = []
        
        for other_user_id, other_pin in pins.items():
            if other_user_id == exclude_user_id:
                continue
            
            other_lat, other_lng = other_pin['lat'], other_pin['lng']
            distance = self.calculate_distance(user_lat, user_lng, other_lat, other_lng)
            
            if distance <= distance_km:
                nearby_users.append({
                    'user_id': other_user_id,
                    'username': other_pin.get('username', 'Unknown'),
                    'location': other_pin.get('display_name', 'Unknown'),
                    'lat': other_lat,
                    'lng': other_lng,
                    'distance': distance
                })
        
        # Sort by distance
        nearby_users.sort(key=lambda x: x['distance'])
        return nearby_users

    def calculate_map_bounds(self, user_lat: float, user_lng: float, distance_km: int) -> Tuple[float, float, float, float]:
        """Calculate map bounds around user location for given distance."""
        # FIXED: More accurate conversion considering latitude
        lat_offset = distance_km / 111.0  # 1 degree latitude ≈ 111 km
        lng_offset = distance_km / (111.0 * math.cos(math.radians(user_lat)))

        # Add buffer so the complete circle is visible
        buffer_factor = 1.2
        lat_offset *= buffer_factor
        lng_offset *= buffer_factor
        
        minx = user_lng - lng_offset
        maxx = user_lng + lng_offset
        miny = user_lat - lat_offset
        maxy = user_lat + lat_offset
        
        return minx, miny, maxx, maxy

    def calculate_radius_pixels(self, distance_km: int, user_lat: float, minx: float, maxx: float, width: int) -> int:
        """Calculate accurate radius in pixels for drawing the circle."""
        # Calculate longitude offset for the given distance at this latitude
        lng_offset_for_distance = distance_km / (111.0 * math.cos(math.radians(user_lat)))
        
        # Convert to pixel space
        lng_range = maxx - minx
        radius_pixels = int((lng_offset_for_distance / lng_range) * width)
        
        return radius_pixels

    async def generate_proximity_map(self, user_id: int, guild_id: int, distance_km: int, maps: Dict) -> Optional[Tuple[BytesIO, List[Dict]]]:
        """Generate proximity map showing nearby users."""
        try:
            map_data = maps.get(str(guild_id), {})
            pins = map_data.get('pins', {})
            user_id_str = str(user_id)
            
            if user_id_str not in pins:
                return None
            
            user_pin = pins[user_id_str]
            user_lat, user_lng = user_pin['lat'], user_pin['lng']
            
            # Find nearby users
            nearby_users = self.find_nearby_users(user_lat, user_lng, pins, distance_km, user_id_str)
            
            # Calculate map bounds
            minx, miny, maxx, maxy = self.calculate_map_bounds(user_lat, user_lng, distance_km)
            
            # Generate map
            width, height = 1200, 900
            
            def to_px(lat, lon):
                x = (lon - minx) / (maxx - minx) * width
                y = (maxy - lat) / (maxy - miny) * height
                return (int(x), int(y))
        
            # Create base map with custom colors and boundaries
            base_map, _ = await self.map_generator.render_geopandas_map_bounds(minx, miny, maxx, maxy, width, height, str(guild_id), maps)
            
            if not base_map:
                # Fallback with custom water color
                land_color, water_color = self.map_generator.get_map_colors(str(guild_id), maps)
                base_map = Image.new('RGB', (width, height), color=water_color)
        
            draw = ImageDraw.Draw(base_map)
            
            # Draw radius circle with accurate calculation
            center_x, center_y = to_px(user_lat, user_lng)
            radius_pixels = self.calculate_radius_pixels(distance_km, user_lat, minx, maxx, width)
            
            # Draw circle outline
            draw.ellipse([
                center_x - radius_pixels, center_y - radius_pixels,
                center_x + radius_pixels, center_y + radius_pixels
            ], outline='#FF0000', width=3)
        
            # Draw user pin (larger, different color)
            user_pin_size = 12
            draw.ellipse([
                center_x - user_pin_size, center_y - user_pin_size,
                center_x + user_pin_size, center_y + user_pin_size
            ], fill='#00FF00', outline='white', width=3)
        
            # Draw nearby user pins with custom pin color
            pin_color, _ = self.map_generator.get_pin_settings(str(guild_id), maps)
            
            for user_data in nearby_users:
                pin_lat, pin_lng = user_data['lat'], user_data['lng']
                
                # Check if pin is within map bounds (visible area)
                if minx <= pin_lng <= maxx and miny <= pin_lat <= maxy:
                    x, y = to_px(pin_lat, pin_lng)
                    pin_size = 8
                    draw.ellipse([x - pin_size, y - pin_size, x + pin_size, y + pin_size],
                                 fill=pin_color, outline='white', width=2)
        
            # Convert to BytesIO
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
        
            return img_buffer, nearby_users
        
        except Exception as e:
            self.log.error(f"Failed to generate proximity map: {e}")
            return None