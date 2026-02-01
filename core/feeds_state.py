# core/feeds_state.py
"""
Enhanced state management using database backend.
Tracks which GUIDs have been posted, when, and the corresponding Discord message IDs
for update functionality.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, Any


class AsyncState:
    """Async database-backed state management for posted entries"""

    def __init__(self, db, guild_id: int):
        self.db = db
        self.guild_id = guild_id
        # In-memory cache for performance
        self._cache: Dict[str, dict] = {}
        self._cache_loaded = False

    async def _ensure_cache(self):
        """Load entries into cache if not already loaded"""
        if self._cache_loaded or not self.db:
            return

        # Load recent entries into cache (last 7 days)
        if self.db and hasattr(self.db, 'feeds'):
            rows = await self.db.feeds.fetch(
                """SELECT guid, message_id, channel_id, content_hash, feed_id, posted_at
                   FROM posted_entries
                   WHERE guild_id = $1
                   AND posted_at > NOW() - INTERVAL '7 days'""",
                self.guild_id
            )
            for row in rows:
                self._cache[row['guid']] = {
                    "timestamp": row['posted_at'].isoformat() if row['posted_at'] else None,
                    "message_id": row['message_id'],
                    "channel_id": row['channel_id'],
                    "content_hash": row['content_hash'],
                    "feed_id": row['feed_id'],
                }
            self._cache_loaded = True

    async def already_sent(self, guid: str) -> bool:
        """Check if GUID has already been sent"""
        await self._ensure_cache()

        # Check cache first
        if guid in self._cache:
            return True

        # Check database
        if self.db:
            return await self.db.feeds.is_entry_posted(self.guild_id, guid)
        return False

    async def get_message_info(self, guid: str) -> Optional[Tuple[int, int]]:
        """Get message_id and channel_id for a GUID if available"""
        await self._ensure_cache()

        # Check cache first
        entry = self._cache.get(guid)
        if entry and entry.get("message_id") and entry.get("channel_id"):
            return entry["message_id"], entry["channel_id"]

        # Check database
        if self.db:
            return await self.db.feeds.get_message_info(self.guild_id, guid)
        return None

    async def get_content_hash(self, guid: str) -> Optional[str]:
        """Get content hash for a GUID"""
        await self._ensure_cache()

        entry = self._cache.get(guid)
        if entry:
            return entry.get("content_hash")

        if self.db:
            entry = await self.db.feeds.get_entry(self.guild_id, guid)
            if entry:
                return entry.content_hash
        return None

    async def mark_sent(
        self,
        guid: str,
        message_id: int = None,
        channel_id: int = None,
        content_hash: str = None,
        feed_id: int = None,
        timestamp: datetime = None
    ) -> None:
        """Mark GUID as sent with message info and timestamp"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Update cache
        self._cache[guid] = {
            "timestamp": timestamp.isoformat(),
            "message_id": message_id,
            "channel_id": channel_id,
            "content_hash": content_hash,
            "feed_id": feed_id,
        }

        # Update database
        if self.db:
            await self.db.feeds.mark_entry_posted(
                self.guild_id, guid, message_id, channel_id, content_hash, feed_id
            )

    async def cleanup_old_entries(self, max_age_days: int = 7) -> int:
        """Remove entries older than max_age_days (default 7 days)"""
        if self.db:
            deleted = await self.db.feeds.cleanup_old_entries(self.guild_id, max_age_days)
            # Clear cache to force reload
            self._cache.clear()
            self._cache_loaded = False
            return deleted
        return 0

    async def get_entry_count(self) -> int:
        """Get total number of tracked entries"""
        await self._ensure_cache()
        return len(self._cache)

    async def get_stats(self) -> Dict[str, int]:
        """Get statistics about the state"""
        if self.db:
            return await self.db.feeds.get_entry_stats(self.guild_id)

        # Fallback to cache stats
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        await self._ensure_cache()

        day_count = sum(1 for entry in self._cache.values()
                       if entry.get("timestamp", "") > day_ago.isoformat())
        week_count = sum(1 for entry in self._cache.values()
                        if entry.get("timestamp", "") > week_ago.isoformat())

        return {
            "total": len(self._cache),
            "last_24h": day_count,
            "last_week": week_count
        }


# Legacy synchronous State class for backward compatibility during transition
# This is kept for any code that still uses the old sync API
class State:
    """Legacy synchronous state - wraps async state for compatibility"""

    def __init__(self, path=None, db=None, guild_id: int = None):
        """
        Initialize state. If db and guild_id provided, uses database.
        Otherwise falls back to file-based storage (deprecated).
        """
        self.db = db
        self.guild_id = guild_id
        self._entries: Dict[str, dict] = {}

        # File-based fallback (deprecated)
        if path and not db:
            self.path = path
            self._load_state_from_file()

    def _load_state_from_file(self):
        """Load state from file (deprecated fallback)"""
        import json
        if not self.path or not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))

            # Handle old format (list of GUIDs)
            if isinstance(data, list):
                current_time = datetime.now(timezone.utc).isoformat()
                self._entries = {
                    guid: {"timestamp": current_time, "message_id": None, "channel_id": None}
                    for guid in data
                }
            elif isinstance(data, dict):
                if data and isinstance(next(iter(data.values())), str):
                    self._entries = {
                        guid: {"timestamp": timestamp, "message_id": None, "channel_id": None}
                        for guid, timestamp in data.items()
                    }
                else:
                    self._entries = data
        except Exception as e:
            print(f"Warning: Corrupted state file, starting fresh: {e}")
            self._entries = {}

    def already_sent(self, guid: str) -> bool:
        """Check if GUID has already been sent"""
        return guid in self._entries

    def get_message_info(self, guid: str) -> Optional[Tuple[int, int]]:
        """Get message_id and channel_id for a GUID if available"""
        entry = self._entries.get(guid)
        if entry and entry.get("message_id") and entry.get("channel_id"):
            return entry["message_id"], entry["channel_id"]
        return None

    def mark_sent(self, guid: str, message_id: int = None, channel_id: int = None, feed_id: int = None, timestamp: datetime = None) -> None:
        """Mark GUID as sent with message info and timestamp"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        timestamp_str = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)

        self._entries[guid] = {
            "timestamp": timestamp_str,
            "message_id": message_id,
            "channel_id": channel_id,
            "feed_id": feed_id
        }

    def save(self) -> None:
        """Save state to file (deprecated)"""
        if not hasattr(self, 'path') or not self.path:
            return
        try:
            import json
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('w', encoding='utf-8') as f:
                json.dump(self._entries, f, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}")

    def cleanup_old_entries(self, max_age_days: int = 7) -> None:
        """Remove entries older than max_age_days"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_iso = cutoff.isoformat()

        old_count = len(self._entries)
        self._entries = {
            guid: entry
            for guid, entry in self._entries.items()
            if entry.get("timestamp", "") > cutoff_iso
        }

        new_count = len(self._entries)
        removed = old_count - new_count

        if removed > 0:
            print(f"Cleaned up {removed} old entries")
            self.save()

    def get_entry_count(self) -> int:
        """Get total number of tracked entries"""
        return len(self._entries)

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the state"""
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        day_count = sum(1 for entry in self._entries.values()
                       if entry.get("timestamp", "") > day_ago.isoformat())
        week_count = sum(1 for entry in self._entries.values()
                        if entry.get("timestamp", "") > week_ago.isoformat())

        return {
            "total": len(self._entries),
            "last_24h": day_count,
            "last_week": week_count
        }
