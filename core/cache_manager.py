# core/cache_manager.py
import asyncio
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import logging
from core.config import config

log = logging.getLogger("tausendsassa.cache")

class LRUCache:
    """LRU Cache with size limits and automatic cleanup"""
    
    def __init__(self, max_items: int):
        self.max_items = max_items
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get item from cache, updating access time"""
        async with self._lock:
            if key in self.cache:
                value, _ = self.cache[key]
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                # Update access time
                self.cache[key] = (value, time.time())
                return value
            return None
    
    async def set(self, key: str, value: Any):
        """Set item in cache, evicting oldest if necessary"""
        async with self._lock:
            if key in self.cache:
                # Update existing item
                self.cache[key] = (value, time.time())
                self.cache.move_to_end(key)
            else:
                # Add new item
                self.cache[key] = (value, time.time())
                
                # Evict oldest if over limit
                while len(self.cache) > self.max_items:
                    oldest_key = next(iter(self.cache))
                    evicted_value, _ = self.cache.pop(oldest_key)
                    log.debug(f"Evicted cache item: {oldest_key}")
                    
                    # Clean up if it's a file path
                    if isinstance(evicted_value, (str, Path)) and os.path.exists(evicted_value):
                        try:
                            os.unlink(evicted_value)
                        except Exception as e:
                            log.warning(f"Failed to cleanup evicted cache file {evicted_value}: {e}")
    
    async def remove(self, key: str) -> bool:
        """Remove item from cache"""
        async with self._lock:
            if key in self.cache:
                value, _ = self.cache.pop(key)
                
                # Clean up if it's a file path
                if isinstance(value, (str, Path)) and os.path.exists(value):
                    try:
                        os.unlink(value)
                    except Exception as e:
                        log.warning(f"Failed to cleanup removed cache file {value}: {e}")
                return True
            return False
    
    async def clear(self):
        """Clear all items from cache"""
        async with self._lock:
            for key, (value, _) in self.cache.items():
                if isinstance(value, (str, Path)) and os.path.exists(value):
                    try:
                        os.unlink(value)
                    except Exception as e:
                        log.warning(f"Failed to cleanup cache file {value}: {e}")
            self.cache.clear()
    
    def size(self) -> int:
        """Get current cache size"""
        return len(self.cache)
    
    def keys(self) -> list:
        """Get all cache keys"""
        return list(self.cache.keys())

class ManagedFileCache:
    """File-based cache with size management and automatic cleanup"""
    
    def __init__(self, cache_dir: Path, max_size_mb: int):
        self.cache_dir = cache_dir
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
    
    async def get_cache_size(self) -> int:
        """Get current cache size in bytes"""
        total_size = 0
        try:
            for file_path in self.cache_dir.rglob("*"):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
        except Exception as e:
            log.warning(f"Error calculating cache size: {e}")
        return total_size
    
    async def cleanup_if_needed(self):
        """Clean up old files if cache exceeds size limit"""
        async with self._lock:
            current_size = await self.get_cache_size()
            
            if current_size <= self.max_size_bytes:
                return
            
            log.info(f"Cache size ({current_size / 1024 / 1024:.1f}MB) exceeds limit ({self.max_size_bytes / 1024 / 1024:.1f}MB), cleaning up...")
            
            # Get all files with their access times
            files_with_times = []
            try:
                for file_path in self.cache_dir.rglob("*"):
                    if file_path.is_file():
                        stat = file_path.stat()
                        files_with_times.append((file_path, stat.st_atime, stat.st_size))
            except Exception as e:
                log.error(f"Error listing cache files: {e}")
                return
            
            # Sort by access time (oldest first)
            files_with_times.sort(key=lambda x: x[1])
            
            # Delete oldest files until under limit
            deleted_count = 0
            deleted_size = 0
            
            for file_path, _, file_size in files_with_times:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    deleted_size += file_size
                    current_size -= file_size
                    
                    if current_size <= self.max_size_bytes * 0.8:  # Leave 20% headroom
                        break
                except Exception as e:
                    log.warning(f"Failed to delete cache file {file_path}: {e}")
            
            log.info(f"Cleaned up {deleted_count} files ({deleted_size / 1024 / 1024:.1f}MB)")
    
    async def store_file(self, key: str, file_path: Path) -> bool:
        """Store a file in cache with the given key"""
        try:
            cache_file = self.cache_dir / f"{key}.cache"
            
            # Create parent directories if needed
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file to cache
            import shutil
            shutil.copy2(file_path, cache_file)
            
            # Clean up if needed
            await self.cleanup_if_needed()
            
            return True
        except Exception as e:
            log.error(f"Failed to store file in cache: {e}")
            return False
    
    async def get_file(self, key: str) -> Optional[Path]:
        """Get a file from cache"""
        cache_file = self.cache_dir / f"{key}.cache"
        
        if cache_file.exists():
            # Update access time
            try:
                cache_file.touch()
                return cache_file
            except Exception as e:
                log.warning(f"Failed to update access time for {cache_file}: {e}")
                return cache_file
        
        return None
    
    async def remove_file(self, key: str) -> bool:
        """Remove a file from cache"""
        cache_file = self.cache_dir / f"{key}.cache"
        
        if cache_file.exists():
            try:
                cache_file.unlink()
                return True
            except Exception as e:
                log.warning(f"Failed to remove cache file {cache_file}: {e}")
        
        return False
    
    async def clear_all(self) -> int:
        """Clear all cached files"""
        deleted_count = 0
        
        try:
            for file_path in self.cache_dir.rglob("*.cache"):
                if file_path.is_file():
                    file_path.unlink()
                    deleted_count += 1
        except Exception as e:
            log.error(f"Error clearing cache: {e}")
        
        return deleted_count

class CacheManager:
    """Centralized cache management for the bot"""
    
    def __init__(self):
        self.memory_cache = LRUCache(config.max_memory_cache_items)
        self.file_cache = ManagedFileCache(
            Path("data/cache"), 
            config.max_cache_size_mb
        )
        
        # Start cleanup task
        self.cleanup_task = None
        
    async def start_cleanup_task(self):
        """Start the periodic cleanup task"""
        if self.cleanup_task is None or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
            log.info("Started cache cleanup task")
    
    async def stop_cleanup_task(self):
        """Stop the periodic cleanup task"""
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _periodic_cleanup(self):
        """Periodic cleanup task"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self.file_cache.cleanup_if_needed()
                
                # Log cache statistics
                memory_size = self.memory_cache.size()
                file_size = await self.file_cache.get_cache_size()
                log.info(f"Cache stats - Memory: {memory_size} items, File: {file_size / 1024 / 1024:.1f}MB")
                
            except Exception as e:
                log.error(f"Error in cache cleanup task: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying

# Global cache manager instance
cache_manager = CacheManager()