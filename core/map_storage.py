"""Map storage and caching utilities for the Discord Map Bot - Improved Cache System."""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple, Literal, Union
from datetime import datetime
from io import BytesIO
from PIL import Image
import discord
from core.cache_manager import cache_manager


class UnifiedCacheManager:
    """Unified cache management system for all map types."""
    
    def __init__(self, data_dir: Path, cache_dir: Path, logger):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.log = logger
        
        # Ensure directories exist
        self.data_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Use global managed cache
        self.memory_cache = cache_manager.memory_cache
    
    def _get_guild_cache_dir(self, guild_id: str) -> Path:
        """Get guild-specific cache directory."""
        guild_dir = self.data_dir / guild_id
        guild_dir.mkdir(exist_ok=True)
        return guild_dir
    
    def _has_custom_settings(self, guild_id: str, maps: Dict) -> bool:
        """Check if guild has custom visual settings."""
        map_data = maps.get(guild_id, {})
        return bool(map_data.get('settings'))
    
    def _get_cache_location(self, guild_id: str, maps: Dict) -> Tuple[Path, str]:
        """Determine cache location based on custom settings."""
        if self._has_custom_settings(guild_id, maps):
            return self._get_guild_cache_dir(guild_id), "guild directory"
        else:
            return self.cache_dir, "shared cache"
    
    def generate_base_map_cache_key(self, guild_id: str, maps: Dict, region: str, width: int, height: int) -> str:
        """Generate cache key specifically for base maps (excludes pin data)."""
        base_parts = ["base_map", region, str(width), str(height)]
        
        # Only include visual settings that affect the BASE MAP (not pins)
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        
        if settings:
            # Create hash only for settings that affect base map rendering
            base_map_settings = {}
            
            # Colors affect base map
            if 'colors' in settings:
                base_map_settings['colors'] = settings['colors']
            
            # Borders affect base map  
            if 'borders' in settings:
                borders = settings['borders'].copy()
                # Remove pin-specific settings that don't affect base map
                borders.pop('pin', None)  # Remove any pin-related border settings
                if borders:  # Only include if there are actual border settings
                    base_map_settings['borders'] = borders
            
            # Pins settings do NOT affect base map, so exclude them
            # This allows base map reuse when only pin color/size changes
            
            if base_map_settings:
                settings_str = json.dumps(base_map_settings, sort_keys=True)
                settings_hash = hashlib.md5(settings_str.encode()).hexdigest()[:8]
                base_parts.append(settings_hash)
            else:
                base_parts.append("default")
        else:
            base_parts.append("default")
        
        return "_".join(base_parts)

    def generate_settings_hash(self, guild_id: str, maps: Dict) -> str:
        """Generate hash for visual settings that affect rendering."""
        map_data = maps.get(guild_id, {})
        settings = map_data.get('settings', {})
        
        if not settings:
            return "default"
        
        # Include all visual settings
        visual_settings = {}
        for key in ['colors', 'borders', 'pins']:
            if key in settings:
                visual_settings[key] = settings[key]
        
        if not visual_settings:
            return "default"
        
        settings_str = json.dumps(visual_settings, sort_keys=True)
        return hashlib.md5(settings_str.encode()).hexdigest()[:8]
    
    def generate_cache_key(self, cache_type: str, guild_id: str, maps: Dict, **params) -> str:
        """Generate unified cache key for any cache type."""
        base_parts = [cache_type]
        
        # Add type-specific parameters
        if cache_type == "base_map":
            # Use specialized base map key generation
            return self.generate_base_map_cache_key(guild_id, maps, params['region'], params['width'], params['height'])
        elif cache_type == "closeup_base_map":
            # New cache type for closeup base maps (without pins)
            base_parts.extend([params['closeup_type'], params['closeup_name'], str(params['width']), str(params['height'])])
            # Only include visual settings that affect the BASE MAP (not pins)
            map_data = maps.get(guild_id, {})
            settings = map_data.get('settings', {})
            
            if settings:
                base_map_settings = {}
                
                # Colors affect base map
                if 'colors' in settings:
                    base_map_settings['colors'] = settings['colors']
                
                # Borders affect base map
                if 'borders' in settings:
                    borders = settings['borders'].copy()
                    borders.pop('pin', None)  # Remove pin-specific settings
                    if borders:
                        base_map_settings['borders'] = borders
                
                if base_map_settings:
                    settings_str = json.dumps(base_map_settings, sort_keys=True)
                    settings_hash = hashlib.md5(settings_str.encode()).hexdigest()[:8]
                    base_parts.append(settings_hash)
                else:
                    base_parts.append("default")
            else:
                base_parts.append("default")
        elif cache_type == "final_map":
            base_parts.append(params['region'])
            # Add pin hash
            pins = maps.get(guild_id, {}).get('pins', {})
            pin_data = {uid: (pin['lat'], pin['lng']) for uid, pin in pins.items()}
            pin_str = json.dumps(pin_data, sort_keys=True)
            pin_hash = hashlib.md5(pin_str.encode()).hexdigest()[:8]
            base_parts.append(pin_hash)
        elif cache_type == "closeup":
            base_parts.extend([params['closeup_type'], params['closeup_name']])
            # Add pin hash for closeups too
            pins = maps.get(guild_id, {}).get('pins', {})
            pin_data = {uid: (pin['lat'], pin['lng']) for uid, pin in pins.items()}
            pin_str = json.dumps(pin_data, sort_keys=True)
            pin_hash = hashlib.md5(pin_str.encode()).hexdigest()[:8]
            base_parts.append(pin_hash)
        
        # Add settings hash for non-base-map types
        if cache_type not in ["base_map", "closeup_base_map"]:
            settings_hash = self.generate_settings_hash(guild_id, maps)
            base_parts.append(settings_hash)
        
        return "_".join(base_parts)
    
    async def get_cached_item(self, cache_type: str, guild_id: str, maps: Dict, **params) -> Optional[Union[Image.Image, discord.File, BytesIO]]:
        """Get cached item of any type."""
        cache_key = self.generate_cache_key(cache_type, guild_id, maps, **params)
        
        # Check memory cache for base maps (including closeup base maps)
        if cache_type in ["base_map", "closeup_base_map"]:
            cached_image = await self.memory_cache.get(cache_key)
            if cached_image:
                self.log.info(f"Using in-memory cached {cache_type} for guild {guild_id}")
                return cached_image
        
        # Check disk cache
        cache_dir, cache_location = self._get_cache_location(guild_id, maps)
        cache_file = cache_dir / f"{cache_key}.png"
        
        if cache_file.exists():
            try:
                if cache_type in ["base_map", "closeup_base_map"]:
                    image = Image.open(cache_file)
                    # Store in memory cache too
                    await self.memory_cache.set(cache_key, image)
                    self.log.info(f"Using disk cached {cache_type} for guild {guild_id} from {cache_location}")
                    return image.copy()
                elif cache_type == "final_map":
                    filename = f"map_{cache_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    self.log.info(f"Using cached {cache_type} for guild {guild_id} from {cache_location}")
                    return discord.File(cache_file, filename=filename)
                elif cache_type == "closeup":
                    with open(cache_file, 'rb') as f:
                        image_data = f.read()
                    img_buffer = BytesIO(image_data)
                    self.log.info(f"Using cached {cache_type} for guild {guild_id} from {cache_location}")
                    return img_buffer
            except Exception as e:
                self.log.warning(f"Error loading cached {cache_type}: {e}")
        
        self.log.info(f"No cached {cache_type} found for guild {guild_id}")
        return None
    
    async def cache_item(self, cache_type: str, guild_id: str, maps: Dict, item: Union[Image.Image, BytesIO], **params):
        """Cache item of any type."""
        cache_key = self.generate_cache_key(cache_type, guild_id, maps, **params)
        cache_dir, cache_location = self._get_cache_location(guild_id, maps)
        cache_file = cache_dir / f"{cache_key}.png"
        
        try:
            if cache_type in ["base_map", "closeup_base_map"] and isinstance(item, Image.Image):
                # Store in memory
                await self.memory_cache.set(cache_key, item)
                # Store on disk
                item.save(cache_file, 'PNG', optimize=True)
            elif isinstance(item, BytesIO):
                # Store on disk
                item.seek(0)
                with open(cache_file, 'wb') as f:
                    f.write(item.read())
            
            self.log.info(f"Cached {cache_type} for guild {guild_id} in {cache_location}")
        except Exception as e:
            self.log.warning(f"Error caching {cache_type}: {e}")
    
    async def invalidate_cache(self, guild_id: str, cache_types: Optional[list] = None):
        """Invalidate specific cache types for a guild - PRESERVES default base maps."""
        if cache_types is None:
            cache_types = ["base_map", "final_map", "closeup", "closeup_base_map"]
        
        deleted_count = 0
        
        # Only remove CUSTOM base maps from guild cache, NOT shared default cache
        if "base_map" in cache_types:
            # Remove from guild cache only (custom base maps)
            guild_cache_dir = self.data_dir / guild_id
            if guild_cache_dir.exists():
                for cache_file in guild_cache_dir.glob("base_map_*.png"):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed custom base map cache file: {cache_file.name}")
            
            # Clear memory cache for base maps (affects both custom and default)
            await self.memory_cache.clear()
            self.log.info("Cleared base map memory cache")

        # Remove closeup base maps when requested (preserve default ones)
        if "closeup_base_map" in cache_types:
            # Remove from guild cache only (custom closeup base maps)
            guild_cache_dir = self.data_dir / guild_id
            if guild_cache_dir.exists():
                for cache_file in guild_cache_dir.glob("closeup_base_map_*.png"):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed custom closeup base map cache file: {cache_file.name}")
            
            # Clear memory cache for closeup base maps too
            await self.memory_cache.clear()
            self.log.info("Cleared closeup base map memory cache")
        
        # Remove final maps from both shared and guild cache
        if "final_map" in cache_types:
            for cache_file in self.cache_dir.glob("final_map_*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared final map cache file: {cache_file.name}")
            
            guild_cache_dir = self.data_dir / guild_id
            if guild_cache_dir.exists():
                for cache_file in guild_cache_dir.glob("final_map_*.png"):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild final map cache file: {cache_file.name}")
        
        # Remove closeups from both shared and guild cache
        if "closeup" in cache_types:
            for cache_file in self.cache_dir.glob("closeup_*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed shared closeup cache file: {cache_file.name}")
            
            guild_cache_dir = self.data_dir / guild_id
            if guild_cache_dir.exists():
                for cache_file in guild_cache_dir.glob("closeup_*.png"):
                    cache_file.unlink()
                    deleted_count += 1
                    self.log.info(f"Removed guild closeup cache file: {cache_file.name}")
        
        self.log.info(f"Invalidated {cache_types} cache for guild {guild_id} ({deleted_count} files removed) - PRESERVED default base maps")
        
    async def invalidate_all_cache_for_guild_deletion(self, guild_id: str):
        """Complete cache invalidation when a guild map is deleted - removes everything."""
        deleted_count = 0
        
        # Remove ALL base maps (both shared and guild)
        for cache_file in self.cache_dir.glob("base_map_*.png"):
            cache_file.unlink()
            deleted_count += 1
            self.log.info(f"Removed shared base map cache file: {cache_file.name}")
        
        # Remove from guild cache completely
        guild_cache_dir = self.data_dir / guild_id
        if guild_cache_dir.exists():
            for cache_file in guild_cache_dir.glob("*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed guild cache file: {cache_file.name}")
        
        # Clear memory cache
        await self.memory_cache.clear()
        self.log.info("Cleared all in-memory cache")
        
        self.log.info(f"Complete cache invalidation for guild {guild_id} deletion ({deleted_count} files removed)")
    
    async def invalidate_all_png_files_for_settings_change(self, guild_id: str):
        """Radical cleanup: remove ALL PNG files for a guild when settings are saved."""
        deleted_count = 0
        
        # Remove ALL PNG files from guild cache
        guild_cache_dir = self.data_dir / guild_id
        if guild_cache_dir.exists():
            for cache_file in guild_cache_dir.glob("*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed guild PNG file: {cache_file.name}")
        
        # Clear memory cache to ensure no stale references
        await self.memory_cache.clear()
        self.log.info("Cleared all in-memory cache")
        
        self.log.info(f"Complete PNG cleanup for guild {guild_id} settings change ({deleted_count} files removed)")
    
    async def clear_all_cache(self) -> int:
        """Clear all cached items."""
        await self.memory_cache.clear()
        deleted_count = 0
        
        # Clear shared cache
        cache_files = list(self.cache_dir.glob("*.png"))
        for cache_file in cache_files:
            cache_file.unlink()
            deleted_count += 1
        
        # Clear guild-specific caches
        for guild_dir in self.data_dir.iterdir():
            if guild_dir.is_dir() and guild_dir.name.isdigit():
                guild_cache_files = list(guild_dir.glob("*.png"))
                for cache_file in guild_cache_files:
                    cache_file.unlink()
                    deleted_count += 1
        
        return deleted_count


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
        
        # Unified cache manager
        self.cache = UnifiedCacheManager(data_dir, cache_dir, logger)
        
        # Legacy property for backwards compatibility - removed as it's no longer needed
        # The new cache manager handles this internally

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

    # OPTIMIZED cache interface methods
    async def get_cached_base_map(self, region: str, width: int, height: int, guild_id: str = None, maps: Dict = None) -> Optional[Image.Image]:
        """Get cached base map with improved key generation."""
        if not guild_id or not maps:
            return None
        
        # Use specialized base map cache key
        cache_key = self.cache.generate_base_map_cache_key(guild_id, maps, region, width, height)
        
        # Check memory cache
        cached_image = await self.cache.memory_cache.get(cache_key)
        if cached_image:
            self.log.info(f"Using in-memory cached base map for guild {guild_id}")
            return cached_image
        
        # Check disk cache
        cache_dir, cache_location = self.cache._get_cache_location(guild_id, maps)
        cache_file = cache_dir / f"{cache_key}.png"
        
        if cache_file.exists():
            try:
                image = Image.open(cache_file)
                # Store in memory cache too
                await self.cache.memory_cache.set(cache_key, image)
                self.log.info(f"Using disk cached base map for guild {guild_id} from {cache_location}")
                return image.copy()
            except Exception as e:
                self.log.warning(f"Error loading cached base map: {e}")
        
        self.log.info(f"No cached base map found for guild {guild_id}")
        return None

    async def cache_base_map(self, region: str, width: int, height: int, image: Image.Image, guild_id: str = None, maps: Dict = None):
        """Cache base map with improved key generation."""
        if guild_id and maps:
            cache_key = self.cache.generate_base_map_cache_key(guild_id, maps, region, width, height)
            cache_dir, cache_location = self.cache._get_cache_location(guild_id, maps)
            cache_file = cache_dir / f"{cache_key}.png"
            
            try:
                # Store in memory
                await self.cache.memory_cache.set(cache_key, image)
                # Store on disk
                image.save(cache_file, 'PNG', optimize=True)
                self.log.info(f"Cached base map for guild {guild_id} in {cache_location}")
            except Exception as e:
                self.log.warning(f"Error caching base map: {e}")

    async def get_cached_map(self, guild_id: int, maps: Dict) -> Optional[discord.File]:
        """Get cached final map if available."""
        map_data = maps.get(str(guild_id), {})
        region = map_data.get('region', 'world')
        return await self.cache.get_cached_item("final_map", str(guild_id), maps, region=region)

    async def cache_map(self, guild_id: int, maps: Dict, image_buffer: BytesIO):
        """Cache the final map image."""
        map_data = maps.get(str(guild_id), {})
        region = map_data.get('region', 'world')
        await self.cache.cache_item("final_map", str(guild_id), maps, image_buffer, region=region)

    async def get_cached_closeup(self, guild_id: int, maps: Dict, closeup_type: str, closeup_name: str) -> Optional[BytesIO]:
        """Get cached closeup map if available."""
        return await self.cache.get_cached_item("closeup", str(guild_id), maps, closeup_type=closeup_type, closeup_name=closeup_name)

    async def cache_closeup(self, guild_id: int, maps: Dict, closeup_type: str, closeup_name: str, image_buffer: BytesIO):
        """Cache closeup map image."""
        await self.cache.cache_item("closeup", str(guild_id), maps, image_buffer, closeup_type=closeup_type, closeup_name=closeup_name)

    async def get_cached_closeup_base_map(self, guild_id: int, maps: Dict, closeup_type: str, closeup_name: str, width: int, height: int) -> Optional[Image.Image]:
        """Get cached closeup base map if available."""
        return await self.cache.get_cached_item("closeup_base_map", str(guild_id), maps, 
                                               closeup_type=closeup_type, closeup_name=closeup_name, 
                                               width=width, height=height)

    async def cache_closeup_base_map(self, guild_id: int, maps: Dict, closeup_type: str, closeup_name: str, width: int, height: int, image: Image.Image):
        """Cache closeup base map image."""
        await self.cache.cache_item("closeup_base_map", str(guild_id), maps, image,
                                   closeup_type=closeup_type, closeup_name=closeup_name,
                                   width=width, height=height)

    async def invalidate_final_map_cache_only(self, guild_id: int):
        """Invalidate only final map cache, preserve base maps for efficiency - IMPROVED targeting."""
        guild_id_str = str(guild_id)
        deleted_count = 0
        
        # Remove from shared cache - target final_map files specifically
        for cache_file in self.cache_dir.glob("final_map_*.png"):
            cache_file.unlink()
            deleted_count += 1
            self.log.info(f"Removed shared final map cache file: {cache_file.name}")
        
        # Remove from guild cache - target final_map files specifically
        guild_cache_dir = self.data_dir / guild_id_str
        if guild_cache_dir.exists():
            for cache_file in guild_cache_dir.glob("final_map_*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed guild final map cache file: {cache_file.name}")
        
        # Do NOT clear memory cache - preserve base maps
        self.log.info(f"Invalidated final map cache for guild {guild_id} ({deleted_count} files removed) - preserved base maps")

    async def invalidate_base_map_cache_only(self, guild_id: int):
        """Invalidate base map cache when visual settings change - ONLY custom base maps and closeup base maps."""
        guild_id_str = str(guild_id)
        deleted_count = 0
        
        # Only remove CUSTOM base maps from guild cache, preserve shared default cache
        guild_cache_dir = self.data_dir / guild_id_str
        if guild_cache_dir.exists():
            for cache_file in guild_cache_dir.glob("base_map_*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed custom base map cache file: {cache_file.name}")
            
            # Also remove closeup base maps since they are affected by color changes
            for cache_file in guild_cache_dir.glob("closeup_base_map_*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Removed custom closeup base map cache file: {cache_file.name}")
        
        # Clear memory cache for base maps (affects both custom and default)
        await self.cache.memory_cache.clear()
        self.log.info("Cleared base map memory cache")
        
        self.log.info(f"Invalidated custom base map cache for guild {guild_id} ({deleted_count} files removed) - PRESERVED shared default base maps")
    
    # IMPROVED cache invalidation methods
    async def invalidate_map_cache(self, guild_id: int):
        """Invalidate cached maps for a guild - PRESERVES default base maps."""
        await self.cache.invalidate_cache(str(guild_id), ["base_map", "final_map", "closeup", "closeup_base_map"])
        
    async def admin_clear_cache(self, guild_id: int):
        """Admin-triggered cache clear - removes CUSTOM base maps only, preserves defaults.""" 
        guild_id_str = str(guild_id)
        deleted_count = 0
        
        # Remove ALL cache from guild directory (custom base maps, closeup base maps, final maps, closeups)
        guild_cache_dir = self.data_dir / guild_id_str
        if guild_cache_dir.exists():
            for cache_file in guild_cache_dir.glob("*.png"):
                cache_file.unlink()
                deleted_count += 1
                self.log.info(f"Admin cleared guild cache file: {cache_file.name}")
        
        # Remove final maps and closeups from shared cache (but NOT default base maps)
        for cache_file in self.cache_dir.glob("final_map_*.png"):
            cache_file.unlink()
            deleted_count += 1
            self.log.info(f"Admin cleared shared final map: {cache_file.name}")
            
        for cache_file in self.cache_dir.glob("closeup_*.png"):
            cache_file.unlink()
            deleted_count += 1
            self.log.info(f"Admin cleared shared closeup: {cache_file.name}")
        
        # Clear memory cache (affects all base maps including default and closeup base maps)
        await self.cache.memory_cache.clear()
        self.log.info("Admin cleared memory cache")
        
        self.log.info(f"Admin cleared cache for guild {guild_id} ({deleted_count} files removed) - PRESERVED shared default base maps")
        return deleted_count
            
    async def clear_all_cache(self) -> int:
        """Clear all cached images and return count of deleted files."""
        return await self.cache.clear_all_cache()