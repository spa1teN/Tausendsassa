"""
Repository for monitor message operations.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

from db.repositories.base import BaseRepository
from db.models import MonitorMessage


class MonitorRepository(BaseRepository):
    """Repository for monitor-related database operations."""

    async def get_message(self, channel_id: int, monitor_type: str) -> Optional[MonitorMessage]:
        """Get a monitor message by channel and type."""
        row = await self.fetchrow(
            "SELECT * FROM monitor_messages WHERE channel_id = $1 AND monitor_type = $2",
            channel_id, monitor_type
        )
        return MonitorMessage.from_record(row) if row else None

    async def get_messages_by_type(self, monitor_type: str) -> List[MonitorMessage]:
        """Get all monitor messages of a specific type."""
        rows = await self.fetch(
            "SELECT * FROM monitor_messages WHERE monitor_type = $1",
            monitor_type
        )
        return [MonitorMessage.from_record(row) for row in rows]

    async def set_message(
        self,
        channel_id: int,
        message_id: int,
        monitor_type: str,
        auto_update_interval: int = 300
    ) -> MonitorMessage:
        """Set or update a monitor message."""
        row = await self.fetchrow(
            """INSERT INTO monitor_messages
               (channel_id, message_id, monitor_type, auto_update_interval, last_update)
               VALUES ($1, $2, $3, $4, NOW())
               ON CONFLICT (channel_id, monitor_type) DO UPDATE SET
                   message_id = $2,
                   auto_update_interval = $4,
                   last_update = NOW()
               RETURNING *""",
            channel_id, message_id, monitor_type, auto_update_interval
        )
        return MonitorMessage.from_record(row)

    async def update_last_update(self, channel_id: int, monitor_type: str) -> None:
        """Update the last_update timestamp."""
        await self.execute(
            """UPDATE monitor_messages SET last_update = NOW()
               WHERE channel_id = $1 AND monitor_type = $2""",
            channel_id, monitor_type
        )

    async def delete_message(self, channel_id: int, monitor_type: str) -> bool:
        """Delete a monitor message."""
        result = await self.execute(
            "DELETE FROM monitor_messages WHERE channel_id = $1 AND monitor_type = $2",
            channel_id, monitor_type
        )
        return result == "DELETE 1"

    async def get_message_id(self, channel_id: int, monitor_type: str) -> Optional[int]:
        """Get just the message ID for a monitor."""
        result = await self.fetchval(
            "SELECT message_id FROM monitor_messages WHERE channel_id = $1 AND monitor_type = $2",
            channel_id, monitor_type
        )
        return result

    # ==========================================
    # Compatibility methods for existing code
    # ==========================================

    async def get_monitor_config(self, monitor_type: str = 'system') -> Dict[str, Any]:
        """Get monitor config in the format used by monitor.py."""
        rows = await self.fetch(
            "SELECT * FROM monitor_messages WHERE monitor_type = $1",
            monitor_type
        )

        monitor_messages = {}
        last_update = 0
        auto_update_interval = 300

        for row in rows:
            monitor_messages[str(row['channel_id'])] = str(row['message_id'])
            if row['last_update']:
                last_update = max(last_update, row['last_update'].timestamp())
            auto_update_interval = row['auto_update_interval']

        return {
            'monitor_messages': monitor_messages,
            'auto_update_interval': auto_update_interval,
            'last_update': last_update,
        }

    async def save_monitor_config(self, config: Dict[str, Any], monitor_type: str = 'system') -> None:
        """Save monitor config from the format used by monitor.py."""
        monitor_messages = config.get('monitor_messages', {})
        auto_update_interval = config.get('auto_update_interval', 300)

        for channel_id_str, message_id_str in monitor_messages.items():
            await self.set_message(
                channel_id=int(channel_id_str),
                message_id=int(message_id_str),
                monitor_type=monitor_type,
                auto_update_interval=auto_update_interval
            )

    async def get_server_monitor_config(self) -> Dict[str, Any]:
        """Get server monitor config."""
        return await self.get_monitor_config('server')

    async def save_server_monitor_config(self, config: Dict[str, Any]) -> None:
        """Save server monitor config."""
        await self.save_monitor_config(config, 'server')

    async def get_all_monitor_messages_dict(self, monitor_type: str) -> Dict[str, str]:
        """Get all monitor messages as channel_id -> message_id dict."""
        rows = await self.fetch(
            "SELECT channel_id, message_id FROM monitor_messages WHERE monitor_type = $1",
            monitor_type
        )
        return {str(row['channel_id']): str(row['message_id']) for row in rows}
