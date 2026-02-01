"""
Repository for guild and timezone operations.
"""

from typing import List, Optional
from datetime import datetime

from db.repositories.base import BaseRepository
from db.models import Guild, GuildTimezone


class GuildRepository(BaseRepository):
    """Repository for guild-related database operations."""

    async def get(self, guild_id: int) -> Optional[Guild]:
        """Get a guild by ID."""
        row = await self.fetchrow(
            "SELECT * FROM guilds WHERE id = $1",
            guild_id
        )
        return Guild.from_record(row) if row else None

    async def get_all(self) -> List[Guild]:
        """Get all guilds."""
        rows = await self.fetch("SELECT * FROM guilds ORDER BY id")
        return [Guild.from_record(row) for row in rows]

    async def ensure_exists(self, guild_id: int, name: str = None, icon_hash: str = None, member_count: int = None) -> Guild:
        """Ensure a guild exists, creating it if necessary."""
        row = await self.fetchrow(
            """INSERT INTO guilds (id, name, icon_hash, member_count)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (id) DO UPDATE SET
                   name = COALESCE($2, guilds.name),
                   icon_hash = COALESCE($3, guilds.icon_hash),
                   member_count = COALESCE($4, guilds.member_count),
                   updated_at = NOW()
               RETURNING *""",
            guild_id, name, icon_hash, member_count
        )
        return Guild.from_record(row)

    async def update_name(self, guild_id: int, name: str) -> None:
        """Update guild name."""
        await self.execute(
            "UPDATE guilds SET name = $2, updated_at = NOW() WHERE id = $1",
            guild_id, name
        )

    async def delete(self, guild_id: int) -> bool:
        """Delete a guild and all related data (cascades)."""
        result = await self.execute(
            "DELETE FROM guilds WHERE id = $1",
            guild_id
        )
        return result == "DELETE 1"

    # Timezone operations

    async def get_timezone(self, guild_id: int) -> str:
        """Get timezone for a guild, defaulting to Europe/Berlin."""
        row = await self.fetchrow(
            "SELECT timezone FROM guild_timezones WHERE guild_id = $1",
            guild_id
        )
        return row['timezone'] if row else 'Europe/Berlin'

    async def set_timezone(self, guild_id: int, timezone: str) -> None:
        """Set timezone for a guild."""
        # Ensure guild exists first
        await self.ensure_exists(guild_id)

        await self.execute(
            """INSERT INTO guild_timezones (guild_id, timezone)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET
                   timezone = $2,
                   updated_at = NOW()""",
            guild_id, timezone
        )

    async def get_all_timezones(self) -> dict:
        """Get all guild timezones as a dict."""
        rows = await self.fetch("SELECT guild_id, timezone FROM guild_timezones")
        return {row['guild_id']: row['timezone'] for row in rows}
