"""
Repository for calendar operations.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime

from db.repositories.base import BaseRepository
from db.models import Calendar, CalendarEvent, CalendarReminder


class CalendarRepository(BaseRepository):
    """Repository for calendar database operations."""

    # ==========================================
    # Calendar Configuration
    # ==========================================

    async def get_guild_calendars(self, guild_id: int) -> List[Calendar]:
        """Get all calendars for a guild."""
        rows = await self.fetch(
            "SELECT * FROM calendars WHERE guild_id = $1 ORDER BY calendar_id",
            guild_id
        )
        return [Calendar.from_record(row) for row in rows]

    async def get_calendar(self, calendar_pk: int) -> Optional[Calendar]:
        """Get a calendar by primary key."""
        row = await self.fetchrow("SELECT * FROM calendars WHERE id = $1", calendar_pk)
        return Calendar.from_record(row) if row else None

    async def get_calendar_by_id(self, guild_id: int, calendar_id: str) -> Optional[Calendar]:
        """Get a calendar by guild and calendar_id."""
        row = await self.fetchrow(
            "SELECT * FROM calendars WHERE guild_id = $1 AND calendar_id = $2",
            guild_id, calendar_id
        )
        return Calendar.from_record(row) if row else None

    async def create_calendar(self, guild_id: int, calendar_data: Dict[str, Any]) -> Calendar:
        """Create a new calendar."""
        row = await self.fetchrow(
            """INSERT INTO calendars
               (guild_id, calendar_id, text_channel_id, voice_channel_id, ical_url,
                blacklist, whitelist, reminder_role_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING *""",
            guild_id,
            calendar_data['calendar_id'],
            calendar_data['text_channel_id'],
            calendar_data['voice_channel_id'],
            calendar_data['ical_url'],
            calendar_data.get('blacklist', []),
            calendar_data.get('whitelist', []),
            calendar_data.get('reminder_role_id')
        )
        return Calendar.from_record(row)

    async def update_calendar(self, calendar_pk: int, **kwargs) -> Optional[Calendar]:
        """Update a calendar."""
        if not kwargs:
            return await self.get_calendar(calendar_pk)

        set_parts = []
        values = []
        for i, (key, value) in enumerate(kwargs.items(), start=1):
            set_parts.append(f"{key} = ${i}")
            values.append(value)

        values.append(calendar_pk)
        query = f"""UPDATE calendars SET {', '.join(set_parts)}, updated_at = NOW()
                    WHERE id = ${len(values)} RETURNING *"""

        row = await self.fetchrow(query, *values)
        return Calendar.from_record(row) if row else None

    async def delete_calendar(self, calendar_pk: int) -> bool:
        """Delete a calendar and all related data."""
        result = await self.execute("DELETE FROM calendars WHERE id = $1", calendar_pk)
        return result == "DELETE 1"

    async def delete_calendar_by_id(self, guild_id: int, calendar_id: str) -> bool:
        """Delete a calendar by guild and calendar_id."""
        result = await self.execute(
            "DELETE FROM calendars WHERE guild_id = $1 AND calendar_id = $2",
            guild_id, calendar_id
        )
        return result == "DELETE 1"

    async def update_last_message(
        self,
        calendar_pk: int,
        message_id: int,
        week_start: datetime = None
    ) -> None:
        """Update last message ID and week start."""
        await self.execute(
            """UPDATE calendars SET
               last_message_id = $2,
               current_week_start = COALESCE($3, current_week_start),
               updated_at = NOW()
               WHERE id = $1""",
            calendar_pk, message_id, week_start
        )

    async def update_last_sync(self, calendar_pk: int) -> None:
        """Update last sync timestamp."""
        await self.execute(
            "UPDATE calendars SET last_sync = NOW(), updated_at = NOW() WHERE id = $1",
            calendar_pk
        )

    async def update_filters(
        self,
        calendar_pk: int,
        blacklist: List[str] = None,
        whitelist: List[str] = None
    ) -> None:
        """Update blacklist and whitelist filters."""
        if blacklist is not None and whitelist is not None:
            await self.execute(
                """UPDATE calendars SET blacklist = $2, whitelist = $3, updated_at = NOW()
                   WHERE id = $1""",
                calendar_pk, blacklist, whitelist
            )
        elif blacklist is not None:
            await self.execute(
                "UPDATE calendars SET blacklist = $2, updated_at = NOW() WHERE id = $1",
                calendar_pk, blacklist
            )
        elif whitelist is not None:
            await self.execute(
                "UPDATE calendars SET whitelist = $2, updated_at = NOW() WHERE id = $1",
                calendar_pk, whitelist
            )

    # ==========================================
    # Calendar Events (Discord Events)
    # ==========================================

    async def get_calendar_events(self, calendar_pk: int) -> List[CalendarEvent]:
        """Get all Discord events for a calendar."""
        rows = await self.fetch(
            "SELECT * FROM calendar_events WHERE calendar_pk = $1 ORDER BY created_at",
            calendar_pk
        )
        return [CalendarEvent.from_record(row) for row in rows]

    async def get_event_by_title(self, calendar_pk: int, title: str) -> Optional[CalendarEvent]:
        """Get a Discord event by title."""
        row = await self.fetchrow(
            "SELECT * FROM calendar_events WHERE calendar_pk = $1 AND event_title = $2",
            calendar_pk, title
        )
        return CalendarEvent.from_record(row) if row else None

    async def get_event_id_map(self, calendar_pk: int) -> Dict[str, int]:
        """Get title -> discord_event_id mapping."""
        rows = await self.fetch(
            "SELECT event_title, discord_event_id FROM calendar_events WHERE calendar_pk = $1",
            calendar_pk
        )
        return {row['event_title']: row['discord_event_id'] for row in rows}

    async def add_event(self, calendar_pk: int, title: str, discord_event_id: int) -> CalendarEvent:
        """Add a Discord event."""
        row = await self.fetchrow(
            """INSERT INTO calendar_events (calendar_pk, event_title, discord_event_id)
               VALUES ($1, $2, $3)
               ON CONFLICT DO NOTHING
               RETURNING *""",
            calendar_pk, title, discord_event_id
        )
        return CalendarEvent.from_record(row) if row else None

    async def remove_event(self, calendar_pk: int, title: str) -> bool:
        """Remove a Discord event by title."""
        result = await self.execute(
            "DELETE FROM calendar_events WHERE calendar_pk = $1 AND event_title = $2",
            calendar_pk, title
        )
        return result == "DELETE 1"

    async def remove_event_by_discord_id(self, calendar_pk: int, discord_event_id: int) -> bool:
        """Remove a Discord event by its Discord ID."""
        result = await self.execute(
            "DELETE FROM calendar_events WHERE calendar_pk = $1 AND discord_event_id = $2",
            calendar_pk, discord_event_id
        )
        return result == "DELETE 1"

    async def get_created_event_ids(self, calendar_pk: int) -> List[int]:
        """Get list of created Discord event IDs."""
        rows = await self.fetch(
            "SELECT discord_event_id FROM calendar_events WHERE calendar_pk = $1",
            calendar_pk
        )
        return [row['discord_event_id'] for row in rows]

    # ==========================================
    # Calendar Reminders
    # ==========================================

    async def is_reminder_sent(self, calendar_pk: int, reminder_key: str) -> bool:
        """Check if a reminder has been sent."""
        result = await self.fetchval(
            """SELECT EXISTS(
               SELECT 1 FROM calendar_reminders
               WHERE calendar_pk = $1 AND reminder_key = $2)""",
            calendar_pk, reminder_key
        )
        return result

    async def mark_reminder_sent(self, calendar_pk: int, reminder_key: str) -> None:
        """Mark a reminder as sent."""
        await self.execute(
            """INSERT INTO calendar_reminders (calendar_pk, reminder_key, sent_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (calendar_pk, reminder_key) DO UPDATE SET sent_at = NOW()""",
            calendar_pk, reminder_key
        )

    async def get_sent_reminders(self, calendar_pk: int) -> Dict[str, datetime]:
        """Get all sent reminders for a calendar."""
        rows = await self.fetch(
            "SELECT reminder_key, sent_at FROM calendar_reminders WHERE calendar_pk = $1",
            calendar_pk
        )
        return {row['reminder_key']: row['sent_at'] for row in rows}

    async def cleanup_old_reminders(self, calendar_pk: int, days: int = 7) -> int:
        """Remove old reminders."""
        result = await self.execute(
            f"""DELETE FROM calendar_reminders
               WHERE calendar_pk = $1
               AND sent_at < NOW() - INTERVAL '{days} days'""",
            calendar_pk
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0
