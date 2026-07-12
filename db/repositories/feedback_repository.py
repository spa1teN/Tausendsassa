"""Feedback repository — user-submitted feedback storage."""

from typing import List, Optional
import asyncpg
from db.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository):
    """CRUD operations for the feedback table."""

    async def submit(
        self,
        guild_id: int,
        user_id: int,
        is_anonymous: bool,
        subject: str,
        message: str,
    ) -> asyncpg.Record:
        """Submit a new feedback message. Returns the inserted row."""
        return await self.fetchrow(
            """INSERT INTO feedback (guild_id, user_id, is_anonymous, subject, message)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING *""",
            guild_id, user_id, is_anonymous, subject, message,
        )


    STATUSES = ("new", "important", "in_progress", "archived")
    async def list_feedback(
        self, guild_id: int, limit: int = 50, status: str | None = None
    ) -> List[asyncpg.Record]:
        """List feedback for a guild, newest first. Optionally filter by status."""
        query = """SELECT id, guild_id,
                          CASE WHEN is_anonymous THEN 0 ELSE user_id END AS user_id,
                          is_anonymous, subject, message, status, created_at, read, admin_note
                   FROM feedback
                   WHERE guild_id = $1"""
        args: list = [guild_id]
        idx = 2
        if status:
            query += f" AND status = ${idx}"
            args.append(status)
            idx += 1
        query += f" ORDER BY created_at DESC LIMIT ${idx}"
        args.append(limit)
        return await self.fetch(query, *args)

    async def set_status(self, feedback_id: int, status: str) -> None:
        """Update the status of a feedback message."""
        if status not in self.STATUSES:
            raise ValueError(f"Invalid status: {status}")
        await self.execute(
            "UPDATE feedback SET status = $1 WHERE id = $2", status, feedback_id
        )

    async def mark_read(self, feedback_id: int) -> bool:
        """Mark a feedback entry as read. Returns True if a row was updated."""
        result = await self.execute(
            "UPDATE feedback SET read = TRUE WHERE id = $1", feedback_id)
        return "UPDATE 1" in result

    async def set_admin_note(self, feedback_id: int, note: str) -> bool:
        """Set/update the admin note on a feedback entry."""
        result = await self.execute(
            "UPDATE feedback SET admin_note = $2 WHERE id = $1", feedback_id, note)
        return "UPDATE 1" in result

    async def get_unread_count(self, guild_id: int) -> int:
        """Count unread feedback entries for a guild."""
        return await self.fetchval(
            "SELECT COUNT(*)::int FROM feedback WHERE guild_id = $1 AND read = FALSE",
            guild_id) or 0
