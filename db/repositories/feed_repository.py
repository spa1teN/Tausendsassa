"""
Repository for RSS feed operations.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import json

from db.repositories.base import BaseRepository
from db.models import Feed, PostedEntry


class FeedRepository(BaseRepository):
    """Repository for RSS feed database operations."""

    # ==========================================
    # Feed Configuration
    # ==========================================

    async def get_guild_feeds(self, guild_id: int, enabled_only: bool = True) -> List[Feed]:
        """Get all feeds for a guild."""
        query = "SELECT * FROM feeds WHERE guild_id = $1"
        if enabled_only:
            query += " AND enabled = TRUE"
        query += " ORDER BY name"

        rows = await self.fetch(query, guild_id)
        return [Feed.from_record(row) for row in rows]

    async def get_feed(self, feed_id: int) -> Optional[Feed]:
        """Get a feed by ID."""
        row = await self.fetchrow("SELECT * FROM feeds WHERE id = $1", feed_id)
        return Feed.from_record(row) if row else None

    async def get_feed_by_name(self, guild_id: int, name: str) -> Optional[Feed]:
        """Get a feed by guild and name."""
        row = await self.fetchrow(
            "SELECT * FROM feeds WHERE guild_id = $1 AND name = $2",
            guild_id, name
        )
        return Feed.from_record(row) if row else None

    async def create_feed(self, guild_id: int, feed_data: Dict[str, Any]) -> Feed:
        """Create a new feed."""
        embed_template = feed_data.get('embed_template')
        if embed_template and not isinstance(embed_template, str):
            embed_template = json.dumps(embed_template)

        row = await self.fetchrow(
            """INSERT INTO feeds
               (guild_id, name, feed_url, channel_id, webhook_url, username,
                avatar_url, color, max_items, crosspost, embed_template)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               RETURNING *""",
            guild_id,
            feed_data['name'],
            feed_data['feed_url'],
            feed_data['channel_id'],
            feed_data.get('webhook_url'),
            feed_data.get('username'),
            feed_data.get('avatar_url'),
            feed_data.get('color'),
            feed_data.get('max_items', 3),
            feed_data.get('crosspost', False),
            embed_template
        )
        return Feed.from_record(row)

    async def update_feed(self, feed_id: int, **kwargs) -> Optional[Feed]:
        """Update a feed."""
        if not kwargs:
            return await self.get_feed(feed_id)

        # Handle embed_template JSON conversion
        if 'embed_template' in kwargs and kwargs['embed_template'] is not None:
            if not isinstance(kwargs['embed_template'], str):
                kwargs['embed_template'] = json.dumps(kwargs['embed_template'])

        # Build dynamic update query
        set_parts = []
        values = []
        for i, (key, value) in enumerate(kwargs.items(), start=1):
            set_parts.append(f"{key} = ${i}")
            values.append(value)

        values.append(feed_id)
        query = f"""UPDATE feeds SET {', '.join(set_parts)}, updated_at = NOW()
                    WHERE id = ${len(values)} RETURNING *"""

        row = await self.fetchrow(query, *values)
        return Feed.from_record(row) if row else None

    async def delete_feed(self, feed_id: int) -> bool:
        """Delete a feed."""
        result = await self.execute("DELETE FROM feeds WHERE id = $1", feed_id)
        return result == "DELETE 1"

    async def delete_feed_by_name(self, guild_id: int, name: str) -> bool:
        """Delete a feed by name."""
        result = await self.execute(
            "DELETE FROM feeds WHERE guild_id = $1 AND name = $2",
            guild_id, name
        )
        return result == "DELETE 1"

    async def increment_failure_count(self, feed_id: int) -> int:
        """Increment failure count and return new value."""
        row = await self.fetchrow(
            """UPDATE feeds SET failure_count = failure_count + 1, updated_at = NOW()
               WHERE id = $1 RETURNING failure_count""",
            feed_id
        )
        return row['failure_count'] if row else 0

    async def reset_failure_count(self, feed_id: int) -> None:
        """Reset failure count and update last_success."""
        await self.execute(
            """UPDATE feeds SET failure_count = 0, last_success = NOW(), updated_at = NOW()
               WHERE id = $1""",
            feed_id
        )

    async def disable_feed(self, feed_id: int) -> None:
        """Disable a feed."""
        await self.execute(
            "UPDATE feeds SET enabled = FALSE, updated_at = NOW() WHERE id = $1",
            feed_id
        )

    async def enable_feed(self, feed_id: int) -> None:
        """Enable a feed."""
        await self.execute(
            "UPDATE feeds SET enabled = TRUE, failure_count = 0, updated_at = NOW() WHERE id = $1",
            feed_id
        )

    # ==========================================
    # Monitor Channel
    # ==========================================

    async def get_monitor_channel(self, guild_id: int) -> Optional[int]:
        """Get the monitor channel for a guild."""
        row = await self.fetchrow(
            "SELECT channel_id FROM feed_monitor_channels WHERE guild_id = $1",
            guild_id
        )
        return row['channel_id'] if row else None

    async def set_monitor_channel(self, guild_id: int, channel_id: int) -> None:
        """Set the monitor channel for a guild."""
        await self.execute(
            """INSERT INTO feed_monitor_channels (guild_id, channel_id)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2""",
            guild_id, channel_id
        )

    # ==========================================
    # Posted Entries (Deduplication)
    # ==========================================

    async def is_entry_posted(self, guild_id: int, guid: str) -> bool:
        """Check if an entry has been posted."""
        result = await self.fetchval(
            "SELECT EXISTS(SELECT 1 FROM posted_entries WHERE guild_id = $1 AND guid = $2)",
            guild_id, guid
        )
        return result

    async def get_entry(self, guild_id: int, guid: str) -> Optional[PostedEntry]:
        """Get a posted entry by GUID."""
        row = await self.fetchrow(
            "SELECT * FROM posted_entries WHERE guild_id = $1 AND guid = $2",
            guild_id, guid
        )
        return PostedEntry.from_record(row) if row else None

    async def get_message_info(self, guild_id: int, guid: str) -> Optional[Tuple[int, int]]:
        """Get message_id and channel_id for an entry."""
        row = await self.fetchrow(
            """SELECT message_id, channel_id FROM posted_entries
               WHERE guild_id = $1 AND guid = $2
               AND message_id IS NOT NULL AND channel_id IS NOT NULL""",
            guild_id, guid
        )
        return (row['message_id'], row['channel_id']) if row else None

    async def mark_entry_posted(
        self,
        guild_id: int,
        guid: str,
        message_id: int = None,
        channel_id: int = None,
        content_hash: str = None,
        feed_id: int = None
    ) -> None:
        """Mark an entry as posted."""
        await self.execute(
            """INSERT INTO posted_entries
               (guild_id, guid, message_id, channel_id, content_hash, feed_id)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (guild_id, guid) DO UPDATE SET
                   message_id = COALESCE($3, posted_entries.message_id),
                   channel_id = COALESCE($4, posted_entries.channel_id),
                   content_hash = COALESCE($5, posted_entries.content_hash),
                   feed_id = COALESCE($6, posted_entries.feed_id),
                   posted_at = NOW()""",
            guild_id, guid, message_id, channel_id, content_hash, feed_id
        )

    async def update_entry_message(
        self,
        guild_id: int,
        guid: str,
        message_id: int,
        channel_id: int
    ) -> None:
        """Update message info for an entry."""
        await self.execute(
            """UPDATE posted_entries
               SET message_id = $3, channel_id = $4, posted_at = NOW()
               WHERE guild_id = $1 AND guid = $2""",
            guild_id, guid, message_id, channel_id
        )

    async def cleanup_old_entries(self, guild_id: int, days: int = 7) -> int:
        """Remove entries older than specified days. Returns count deleted."""
        result = await self.execute(
            f"""DELETE FROM posted_entries
               WHERE guild_id = $1
               AND posted_at < NOW() - INTERVAL '{days} days'""",
            guild_id
        )
        # Parse "DELETE N" to get count
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def get_entry_stats(self, guild_id: int) -> Dict[str, int]:
        """Get statistics about posted entries."""
        row = await self.fetchrow(
            """SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE posted_at > NOW() - INTERVAL '24 hours') as last_24h,
                COUNT(*) FILTER (WHERE posted_at > NOW() - INTERVAL '7 days') as last_week
               FROM posted_entries WHERE guild_id = $1""",
            guild_id
        )
        return {
            'total': row['total'],
            'last_24h': row['last_24h'],
            'last_week': row['last_week'],
        }

    async def get_entries_by_feed(self, feed_id: int, limit: int = 50) -> List[PostedEntry]:
        """Get posted entries for a specific feed."""
        rows = await self.fetch(
            """SELECT * FROM posted_entries
               WHERE feed_id = $1
               ORDER BY posted_at DESC
               LIMIT $2""",
            feed_id, limit
        )
        return [PostedEntry.from_record(row) for row in rows]
