"""Map storage and caching utilities for the Discord Map Bot."""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple
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
                                # Log loaded settings for debugging
                                if 'settings' in maps[guild_id]:
                                    self.log.info(f"Loaded custom settings for guild {guild_id}: {maps[guild_id]['settings']}")
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
                    
                # Log saved settings for debugging
                if 'settings' in maps[guild_id]:
                    self.log.info(f"Saved custom settings for guild {guild_id}: {maps[guild_id]['settings']}")
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
        """Generate a cache key based on guild pins and settings."""
        map_data = maps.get(str(guild_id), {})
        pins = map_data.get('pins', {})
        region = map_data.get('region', 'world')
        settings = map_data.get('settings', {})
    
        # Create hash from pins, region, and settings
        pin_data = {}
        for user_id, pin in pins.items():
            pin_data[user_id] = (pin['lat'], pin['lng'])
            
        # Create comprehensive settings hash including all custom values
        settings_for_cache = {}
        if settings:
            # Include all custom settings in cache key
            if 'colors' in settings:
                settings_for_cache['colors'] = settings['colors']
            if 'borders' in settings:
                settings_for_cache['borders'] = settings['borders']
            if 'pins' in settings:
                settings_for_cache['pins'] = settings['pins']
    
        # Create cache string with guaranteed order
        cache_data = {
            'region': region,
            'pins': pin_data,
            'settings': settings_for_cache
        }
    
        cache_string = json.dumps(cache_data, sort_keys=True)
        cache_key = hashlib.md5(cache_string.encode()).hexdigest()
    
        # Debug logging for custom settings
        if settings_for_cache:
            self.log.debug(f"Cache key for guild {guild_id} with custom settings: {cache_key}")
            self.log.debug(f"Settings included in cache: {settings_for_cache}")
    
        return cache_key

    def get_base_map_cache_key(self, region: str, width: int, height: int, guild_id: str = None, maps: Dict = None) -> str:
        """Generate cache key for base map including custom colors if present."""
        base_key = f"base_{region}_{width}_{height}"
    
        # Add custom settings to cache key if guild has them
        if guild_id and maps:
            map_data = maps.get(guild_id, {})
            settings = map_data.get('settings', {})
            if settings:
                # Create comprehensive hash of all visual settings that affect base map
                visual_settings = {}
                if 'colors' in settings:
                    visual_settings['colors'] = settings['colors']
                if 'borders' in settings:
                    visual_settings['borders'] = settings['borders']
            
                if visual_settings:
                    settings_hash = hashlib.md5(json.dumps(visual_settings, sort_keys=True).encode()).hexdigest()[:8]
                    base_key = f"{base_key}_{settings_hash}"
                    self.log.debug(f"Base map cache key for guild {guild_id} with custom settings: {base_key}")
    
        return base_key

    async def get_cached_base_map(self, region: str, width: int, height: int, guild_id: str = None, maps: Dict = None) -> Optional[Image.Image]:
        """Get cached base map if available."""
        cache_key = self.get_base_map_cache_key(region, width, height, guild_id, maps)
    
        # Check in-memory cache first
        if cache_key in self.base_map_cache:
            self.log.info(f"Using in-memory cached base map for {region} (guild {guild_id})")
            return self.base_map_cache[cache_key].copy()
    
        # Determine cache location based on custom settings
        if guild_id and maps:
            map_data = maps.get(guild_id, {})
            has_custom_settings = bool(map_data.get('settings'))
            
            if has_custom_settings:
                # Look for base map cache in guild-specific directory for custom maps
                guild_cache_dir = self.data_dir / guild_id
                cache_file = guild_cache_dir / f"base_{cache_key}.png"
                cache_location = "guild directory"
            else:
                # Use shared cache directory for default maps
                cache_file = self.cache_dir / f"{cache_key}.png"
                cache_location = "shared cache"
        else:
            # Default location for maps without guild context
            cache_file = self.cache_dir / f"{cache_key}.png"
            cache_location = "shared cache"
    
        if cache_file.exists():
            try:
                image = Image.open(cache_file)
                # Store in memory cache too
                self.base_map_cache[cache_key] = image.copy()
                self.log.info(f"Using disk cached base map for {region} (guild {guild_id}) from {cache_location}")
                return image.copy()
            except Exception as e:
                self.log.warning(f"Error loading cached base map: {e}")
    
        self.log.info(f"No cached base map found for {region} (guild {guild_id})")
        return None

    async def cache_base_map(self, region: str, width: int, height: int, image: Image.Image, guild_id: str = None, maps: Dict = None):
        """Cache base map both in memory and on disk."""
        cache_key = self.get_base_map_cache_key(region, width, height, guild_id, maps)
    
        # Store in memory
        self.base_map_cache[cache_key] = image.copy()
    
        # Determine cache location based on custom settings
        if guild_id and maps:
            map_data = maps.get(guild_id, {})
            has_custom_settings = bool(map_data.get('settings'))
        
            if has_custom_settings:
                # Store base map cache in guild-specific directory for custom maps
                guild_cache_dir = self.data_dir / guild_id
                guild_cache_dir.mkdir(exist_ok=True)
                cache_file = guild_cache_dir / f"base_{cache_key}.png"
                cache_location = "guild directory"
            else:
                # Store in shared cache directory for default maps
                cache_file = self.cache_dir / f"{cache_key}.png"
                cache_location = "shared cache"
        else:
            # Default location for maps without guild context
            cache_file = self.cache_dir / f"{cache_key}.png"
            cache_location = "shared cache"
    
        # Store on disk
        try:
            image.save(cache_file, 'PNG', optimize=True)
            self.log.info(f"Cached base map for {region} (guild {guild_id}) in {cache_location}")
        except Exception as e:
            self.log.warning(f"Error caching base map to disk: {e}")

    async def get_cached_map(self, guild_id: int, maps: Dict) -> Optional[discord.File]:
        """Get cached final map if available - checks guild directory for custom maps."""
        guild_id_str = str(guild_id)
        map_data = maps.get(guild_id_str, {})
        
        # Check if guild has custom settings
        has_custom_settings = bool(map_data.get('settings'))
        cache_key = self.get_cache_key(guild_id, maps)
        
        if has_custom_settings:
            # Look for cache in guild-specific directory
            guild_cache_dir = self.data_dir / guild_id_str
            cache_file = guild_cache_dir / f"map_cache_{cache_key}.png"
            cache_location = "guild directory"
        else:
            # Use shared cache directory for default maps
            cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
            cache_location = "shared cache"
        
        if cache_file.exists():
            try:
                filename = f"map_{cache_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                self.log.info(f"Using cached final map for guild {guild_id} from {cache_location}")
                return discord.File(cache_file, filename=filename)
            except Exception as e:
                self.log.warning(f"Error loading cached map: {e}")
        
        self.log.info(f"No cached final map found for guild {guild_id}")
        return None

    async def cache_map(self, guild_id: int, maps: Dict, image_buffer: BytesIO):
        """Cache the final map image - in guild directory if customized, otherwise in shared cache."""
        try:
            guild_id_str = str(guild_id)
            map_data = maps.get(guild_id_str, {})
            cache_key = self.get_cache_key(guild_id, maps)
            
            # Check if guild has custom settings
            has_custom_settings = bool(map_data.get('settings'))
            
            if has_custom_settings:
                # Save to guild-specific directory
                guild_cache_dir = self.data_dir / guild_id_str
                guild_cache_dir.mkdir(exist_ok=True)
                cache_file = guild_cache_dir / f"map_cache_{cache_key}.png"
                cache_location = "guild directory"
            else:
                # Save to shared cache directory
                cache_file = self.cache_dir / f"map_{guild_id}_{cache_key}.png"
                cache_location = "shared cache"
            
            image_buffer.seek(0)
            with open(cache_file, 'wb') as f:
                f.write(image_buffer.read())
            
            self.log.info(f"Cached final map for guild {guild_id} in {cache_location}")
        except Exception as e:
            self.log.warning(f"Error caching final map: {e}")

    async def invalidate_map_cache(self, guild_id: int):
        """Invalidate cached maps for a guild - checks both locations and base maps."""
        try:
            guild_id_str = str(guild_id)
            deleted_count = 0
        
            # Remove final map cache from shared cache directory
            cache_pattern = f"map_{guild_id}_*.png"
            for cache_file in self.cache_dir.glob(cache_pattern):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared final cache file: {cache_file.name}")
        
            # Remove final map cache from guild-specific directory
            guild_cache_dir = self.data_dir / guild_id_str
            if guild_cache_dir.exists():
                cache_pattern = "map_cache_*.png"
                for cache_file in guild_cache_dir.glob(cache_pattern):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild final cache file: {cache_file.name}")
            
                # WICHTIG: Auch base map cache aus guild directory entfernen
                base_cache_pattern = "base_*.png"
                for cache_file in guild_cache_dir.glob(base_cache_pattern):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild base cache file: {cache_file.name}")
        
            # Remove base map cache from shared cache directory  
            base_cache_pattern = "base_*.png"
            for cache_file in self.cache_dir.glob(base_cache_pattern):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared base cache file: {cache_file.name}")
        
            # Clear in-memory base map cache completely to force regeneration
            self.base_map_cache.clear()
            self.log.info(f"Cleared all in-memory base map cache")
                
            self.log.info(f"Invalidated all cache for guild {guild_id} ({deleted_count} files removed)")
        except Exception as e:
            self.log.warning(f"Error invalidating cache: {e}")

    async def invalidate_final_map_cache_only(self, guild_id: int):
        """Invalidate only final map cache, preserve base maps for efficiency."""
        try:
            guild_id_str = str(guild_id)
            deleted_count = 0
        
            # Remove only final map cache from shared cache directory
            cache_pattern = f"map_{guild_id}_*.png"
            for cache_file in self.cache_dir.glob(cache_pattern):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared final cache file: {cache_file.name}")
        
            # Remove only final map cache from guild-specific directory
            guild_cache_dir = self.data_dir / guild_id_str
            if guild_cache_dir.exists():
                cache_pattern = "map_cache_*.png"
                for cache_file in guild_cache_dir.glob(cache_pattern):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild final cache file: {cache_file.name}")
        
            # WICHTIG: Base maps bleiben erhalten!
            self.log.info(f"Invalidated final map cache for guild {guild_id} ({deleted_count} files removed), preserved base maps")
        except Exception as e:
            self.log.warning(f"Error invalidating final cache: {e}")

    async def invalidate_base_map_cache_only(self, guild_id: int):
        """Invalidate only base map cache when colors/settings change."""
        try:
            guild_id_str = str(guild_id)
            deleted_count = 0
        
            # Remove base map cache from guild-specific directory
            guild_cache_dir = self.data_dir / guild_id_str
            if guild_cache_dir.exists():
                base_cache_pattern = "base_*.png"
                for cache_file in guild_cache_dir.glob(base_cache_pattern):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild base cache file: {cache_file.name}")
        
            # Remove base map cache from shared cache directory  
            base_cache_pattern = "base_*.png"
            for cache_file in self.cache_dir.glob(base_cache_pattern):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared base cache file: {cache_file.name}")
        
            # Clear in-memory base map cache for this guild
            keys_to_remove = []
            for key in self.base_map_cache.keys():
                if guild_id_str in key:  # Guild-specific base map cache keys
                    keys_to_remove.append(key)
        
            for key in keys_to_remove:
                del self.base_map_cache[key]
        
            self.log.info(f"Invalidated base map cache for guild {guild_id} ({deleted_count} files removed)")
        except Exception as e:
            self.log.warning(f"Error invalidating base cache: {e}")
            
    async def clear_all_cache(self) -> int:
        """Clear all cached images and return count of deleted files."""
        try:
            # Clear in-memory cache
            self.base_map_cache.clear()
        
            deleted_count = 0
        
            # Clear shared cache directory (both final and base maps)
            cache_files = list(self.cache_dir.glob("*.png"))
            for cache_file in cache_files:
                cache_file.unlink()
                deleted_count += 1
        
            # Clear guild-specific caches (both final and base maps)
            for guild_dir in self.data_dir.iterdir():
                if guild_dir.is_dir() and guild_dir.name.isdigit():
                    # Final map cache
                    guild_cache_files = list(guild_dir.glob("map_cache_*.png"))
                    for cache_file in guild_cache_files:
                        cache_file.unlink()
                        deleted_count += 1
                
                    # Base map cache
                    base_cache_files = list(guild_dir.glob("base_*.png"))
                    for cache_file in base_cache_files:
                        cache_file.unlink()
                        deleted_count += 1
        
            return deleted_count
        
        except Exception as e:
            self.log.error(f"Error clearing cache: {e}")
            return 0
            
