"""Map storage and caching utilities for the Discord Map Bot."""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
from io import BytesIO
from PIL import Image
import discord


class MapStorage:
    """Handles data persistence and caching for maps."""
    
    def __init__(self, data_dir: Path, cache_dir: Path, logger):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.log = logger
        
        # Ensure directories exist
        self.data_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Global overview config file
        self.global_config_file = self.data_dir / "map_global_config.json"
        
        # In-memory cache for base maps
        self.base_map_cache = {}

    def load_all_data(self) -> Dict:
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

    async def save_data(self, guild_id: str, maps: Dict):
        """Save map data for specific guild."""
        try:
            guild_dir = self.data_dir / guild_id
            guild_dir.mkdir(exist_ok=True)
            
            map_file = guild_dir / "map.json"
            
            if guild_id in maps:
                # Create backup if exists
                if map_file.exists():
                    backup_file = guild_dir / "map.json.bak"
                    map_file.replace(backup_file)
                
                with map_file.open('w', encoding='utf-8') as f:
                    json.dump(maps[guild_id], f, indent=2, ensure_ascii=False)
            else:
                # Remove file if guild data was deleted
                if map_file.exists():
                    map_file.unlink()
                    
        except Exception as e:
            self.log.error(f"Failed to save map data for guild {guild_id}: {e}")

    def load_global_config(self) -> Dict:
        """Load global overview configuration."""
        try:
            if self.global_config_file.exists():
                with self.global_config_file.open('r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.log.error(f"Failed to load global config: {e}")
        return {}

    async def save_global_config(self, global_config: Dict):
        """Save global overview configuration."""
        try:
            with self.global_config_file.open('w', encoding='utf-8') as f:
                json.dump(global_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log.error(f"Failed to save global config: {e}")

    def get_cache_key(self, guild_id: int, maps: Dict) -> str:
        """Generate a cache key based on guild pins."""
        map_data = maps.get(str(guild_id), {})
        pins = map_data.get('pins', {})
        region = map_data.get('region', 'world')
        
        # Create hash from pins and region
        pin_data = {}
        for user_id, pin in pins.items():
            pin_data[user_id] = (pin['lat'], pin['lng'])
        
        cache_string = f"{region}:{json.dumps(pin_data, sort_keys=True)}"
        return hashlib.md5(cache_string.encode()).hexdigest()

    def get_base_map_cache_key(self, region: str, width: int, height: int) -> str:
        """Generate cache key for base map (without pins)."""
        return f"base_{region}_{width}_{height}"

    async def get_cached_base_map(self, region: str, width: int, height: int) -> Optional[Image.Image]:
        """Get cached base map if available."""
        cache_key = self.get_base_map_cache_key(region, width, height)
        
        # Check in-memory cache first
        if cache_key in self.base_map_cache:
            self.log.info(f"Using in-memory cached base map for {region}")
            return self.base_map_cache[cache_key].copy()
        
        # Check disk cache
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

    async def cache_base_map(self, region: str, width: int, height: int, image: Image.Image):
        """Cache base map both in memory and on disk."""
        cache_key = self.get_base_map_cache_key(region, width, height)
        
        # Store in memory
        self.base_map_cache[cache_key] = image.copy()
        
        # Store on disk
        try:
            cache_file = self.cache_dir / f"{cache_key}.png"
            image.save(cache_file, 'PNG', optimize=True)
            self.log.info(f"Cached base map for {region}")
        except Exception as e:
            self.log.warning(f"Error caching base map to disk: {e}")

    async def get_cached_map(self, guild_id: int, maps: Dict) -> Optional[discord.File]:
        """Get cached final map if available."""
        cache_key = self.get_cache_key(guild_id, maps)
        cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
        
        if cache_file.exists():
            try:
                filename = f"map_{cache_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                self.log.info(f"Using cached final map for guild {guild_id}")
                return discord.File(cache_file, filename=filename)
            except Exception as e:
                self.log.warning(f"Error loading cached map: {e}")
        
        return None

    async def cache_map(self, guild_id: int, maps: Dict, image_buffer: BytesIO):
        """Cache the final map image."""
        try:
            cache_key = self.get_cache_key(guild_id, maps)
            cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
            
            image_buffer.seek(0)
            with open(cache_file, 'wb') as f:
                f.write(image_buffer.read())
            
            self.log.info(f"Cached final map for guild {guild_id}")
        except Exception as e:
            self.log.warning(f"Error caching final map: {e}")

    async def invalidate_map_cache(self, guild_id: int):
        """Invalidate cached maps for a guild."""
        try:
            # Remove all cached maps for this guild
            cache_pattern = f"map_{guild_id}_*.png"
            for cache_file in self.cache_dir.glob(cache_pattern):
                cache_file.unlink()
            self.log.info(f"Invalidated cache for guild {guild_id}")
        except Exception as e:
            self.log.warning(f"Error invalidating cache: {e}")

    async def clear_all_cache(self) -> int:
        """Clear all cached images and return count of deleted files."""
        try:
            # Clear in-memory cache
            self.base_map_cache.clear()
            
            # Clear disk cache
            cache_files = list(self.cache_dir.glob("*.png"))
            for cache_file in cache_files:
                cache_file.unlink()
            
            return len(cache_files)
            
        except Exception as e:
            self.log.error(f"Error clearing cache: {e}")
            return 0
