"""
Repository for moderation operations.
"""

from typing import Optional, Dict, Any

from db.repositories.base import BaseRepository
from db.models import ModerationConfig


class ModerationRepository(BaseRepository):
    """Repository for moderation database operations."""

    async def get_config(self, guild_id: int) -> Optional[ModerationConfig]:
        """Get moderation config for a guild."""
        row = await self.fetchrow(
            "SELECT * FROM moderation_config WHERE guild_id = $1",
            guild_id
        )
        return ModerationConfig.from_record(row) if row else None

    async def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get moderation config as a dictionary (compatibility method)."""
        config = await self.get_config(guild_id)
        if not config:
            return {}
        return {
            'member_log_webhook': config.member_log_webhook,
            'join_role': config.join_role_id,
        }

    async def set_config(
        self,
        guild_id: int,
        member_log_webhook: str = None,
        join_role_id: int = None
    ) -> ModerationConfig:
        """Set moderation config for a guild."""
        row = await self.fetchrow(
            """INSERT INTO moderation_config (guild_id, member_log_webhook, join_role_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (guild_id) DO UPDATE SET
                   member_log_webhook = COALESCE($2, moderation_config.member_log_webhook),
                   join_role_id = COALESCE($3, moderation_config.join_role_id),
                   updated_at = NOW()
               RETURNING *""",
            guild_id, member_log_webhook, join_role_id
        )
        return ModerationConfig.from_record(row)

    async def set_webhook(self, guild_id: int, webhook_url: str) -> None:
        """Set the member log webhook."""
        await self.execute(
            """INSERT INTO moderation_config (guild_id, member_log_webhook)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET
                   member_log_webhook = $2,
                   updated_at = NOW()""",
            guild_id, webhook_url
        )

    async def clear_webhook(self, guild_id: int) -> None:
        """Clear the member log webhook."""
        await self.execute(
            """UPDATE moderation_config SET member_log_webhook = NULL, updated_at = NOW()
               WHERE guild_id = $1""",
            guild_id
        )

    async def set_join_role(self, guild_id: int, role_id: int) -> None:
        """Set the auto-join role."""
        await self.execute(
            """INSERT INTO moderation_config (guild_id, join_role_id)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET
                   join_role_id = $2,
                   updated_at = NOW()""",
            guild_id, role_id
        )

    async def clear_join_role(self, guild_id: int) -> None:
        """Clear the auto-join role."""
        await self.execute(
            """UPDATE moderation_config SET join_role_id = NULL, updated_at = NOW()
               WHERE guild_id = $1""",
            guild_id
        )

    async def delete_config(self, guild_id: int) -> bool:
        """Delete moderation config for a guild."""
        result = await self.execute(
            "DELETE FROM moderation_config WHERE guild_id = $1",
            guild_id
        )
        return result == "DELETE 1"

    async def get_all_configs(self) -> Dict[int, Dict[str, Any]]:
        """Get all moderation configs as a dictionary (for migration)."""
        rows = await self.fetch("SELECT * FROM moderation_config")
        result = {}
        for row in rows:
            result[row['guild_id']] = {
                'member_log_webhook': row['member_log_webhook'],
                'join_role': row['join_role_id'],
            }
        return result

    async def save_guild_config(self, guild_id: int, key: str, value: Any) -> None:
        """Save a single config key (compatibility method)."""
        if key == 'member_log_webhook':
            await self.set_webhook(guild_id, value)
        elif key == 'join_role':
            if value:
                await self.set_join_role(guild_id, value)
            else:
                await self.clear_join_role(guild_id)
