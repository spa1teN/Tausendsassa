"""
Repository for cache operations (webhooks, feed cache, entry hashes).
"""

from typing import Optional, Dict, Any
from datetime import datetime

from db.repositories.base import BaseRepository
from db.models import WebhookCache, FeedCache


class CacheRepository(BaseRepository):
    """Repository for cache-related database operations."""

    # ==========================================
    # Webhook Cache
    # ==========================================

    async def get_webhook(self, channel_id: int) -> Optional[WebhookCache]:
        """Get cached webhook for a channel."""
        row = await self.fetchrow(
            "SELECT * FROM webhook_cache WHERE channel_id = $1",
            channel_id
        )
        return WebhookCache.from_record(row) if row else None

    async def get_webhook_dict(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get cached webhook as a dictionary (compatibility)."""
        webhook = await self.get_webhook(channel_id)
        if not webhook:
            return None
        return {
            'id': webhook.webhook_id,
            'token': webhook.webhook_token,
            'name': webhook.webhook_name,
        }

    async def set_webhook(
        self,
        channel_id: int,
        webhook_id: int,
        webhook_token: str,
        webhook_name: str = None
    ) -> WebhookCache:
        """Cache webhook information."""
        row = await self.fetchrow(
            """INSERT INTO webhook_cache (channel_id, webhook_id, webhook_token, webhook_name)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (channel_id) DO UPDATE SET
                   webhook_id = $2,
                   webhook_token = $3,
                   webhook_name = COALESCE($4, webhook_cache.webhook_name),
                   created_at = NOW()
               RETURNING *""",
            channel_id, webhook_id, webhook_token, webhook_name
        )
        return WebhookCache.from_record(row)

    async def delete_webhook(self, channel_id: int) -> bool:
        """Delete cached webhook."""
        result = await self.execute(
            "DELETE FROM webhook_cache WHERE channel_id = $1",
            channel_id
        )
        return result == "DELETE 1"

    async def get_all_webhooks(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached webhooks as a dictionary."""
        rows = await self.fetch("SELECT * FROM webhook_cache")
        result = {}
        for row in rows:
            result[str(row['channel_id'])] = {
                'id': row['webhook_id'],
                'token': row['webhook_token'],
                'name': row['webhook_name'],
            }
        return result

    # ==========================================
    # Feed HTTP Cache
    # ==========================================

    async def get_feed_cache(self, url: str) -> Optional[FeedCache]:
        """Get HTTP cache for a feed URL."""
        row = await self.fetchrow(
            "SELECT * FROM feed_cache WHERE url = $1",
            url
        )
        return FeedCache.from_record(row) if row else None

    async def get_feed_cache_dict(self, url: str) -> Optional[Dict[str, Any]]:
        """Get feed cache as a dictionary."""
        cache = await self.get_feed_cache(url)
        if not cache:
            return None
        return {
            'etag': cache.etag,
            'last_modified': cache.last_modified,
            'content_hash': cache.content_hash,
            'last_check': cache.last_check.isoformat() if cache.last_check else None,
        }

    async def set_feed_cache(
        self,
        url: str,
        etag: str = None,
        last_modified: str = None,
        content_hash: str = None
    ) -> FeedCache:
        """Update feed HTTP cache."""
        row = await self.fetchrow(
            """INSERT INTO feed_cache (url, etag, last_modified, content_hash, last_check)
               VALUES ($1, $2, $3, $4, NOW())
               ON CONFLICT (url) DO UPDATE SET
                   etag = COALESCE($2, feed_cache.etag),
                   last_modified = COALESCE($3, feed_cache.last_modified),
                   content_hash = COALESCE($4, feed_cache.content_hash),
                   last_check = NOW()
               RETURNING *""",
            url, etag, last_modified, content_hash
        )
        return FeedCache.from_record(row)

    async def delete_feed_cache(self, url: str) -> bool:
        """Delete feed cache entry."""
        result = await self.execute(
            "DELETE FROM feed_cache WHERE url = $1",
            url
        )
        return result == "DELETE 1"

    async def get_all_feed_cache(self) -> Dict[str, Dict[str, Any]]:
        """Get all feed cache as a dictionary."""
        rows = await self.fetch("SELECT * FROM feed_cache")
        result = {}
        for row in rows:
            result[row['url']] = {
                'etag': row['etag'],
                'last_modified': row['last_modified'],
                'content_hash': row['content_hash'],
                'last_check': row['last_check'].isoformat() if row['last_check'] else None,
            }
        return result

    # ==========================================
    # Entry Hashes (for change detection)
    # ==========================================

    async def get_entry_hash(self, guid: str) -> Optional[str]:
        """Get content hash for an entry."""
        result = await self.fetchval(
            "SELECT content_hash FROM entry_hashes WHERE guid = $1",
            guid
        )
        return result

    async def set_entry_hash(self, guid: str, content_hash: str) -> None:
        """Set content hash for an entry."""
        await self.execute(
            """INSERT INTO entry_hashes (guid, content_hash)
               VALUES ($1, $2)
               ON CONFLICT (guid) DO UPDATE SET content_hash = $2""",
            guid, content_hash
        )

    async def delete_entry_hash(self, guid: str) -> bool:
        """Delete an entry hash."""
        result = await self.execute(
            "DELETE FROM entry_hashes WHERE guid = $1",
            guid
        )
        return result == "DELETE 1"

    async def get_all_entry_hashes(self) -> Dict[str, str]:
        """Get all entry hashes as a dictionary."""
        rows = await self.fetch("SELECT guid, content_hash FROM entry_hashes")
        return {row['guid']: row['content_hash'] for row in rows}

    async def set_many_entry_hashes(self, hashes: Dict[str, str]) -> None:
        """Set multiple entry hashes at once."""
        if not hashes:
            return

        # Use executemany for efficiency
        await self.executemany(
            """INSERT INTO entry_hashes (guid, content_hash)
               VALUES ($1, $2)
               ON CONFLICT (guid) DO UPDATE SET content_hash = $2""",
            [(guid, hash_) for guid, hash_ in hashes.items()]
        )

    async def cleanup_old_hashes(self, days: int = 30) -> int:
        """Remove old entry hashes."""
        result = await self.execute(
            f"DELETE FROM entry_hashes WHERE created_at < NOW() - INTERVAL '{days} days'"
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
