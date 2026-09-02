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

    async def add_message(
        self,
        feedback_id: int,
        guild_id: int,
        user_id: int,
        direction: str,
        content: str,
        image: bytes | None = None,
        image_mime: str | None = None,
    ) -> asyncpg.Record:
        """Append a message to a feedback conversation thread. Returns the row."""
        return await self.fetchrow(
            """INSERT INTO feedback_messages (feedback_id, guild_id, user_id, direction, content, image, image_mime, image_size, read)
               VALUES ($1, $2, $3, $4, $5, $6, $7,
                       CASE WHEN $6::bytea IS NULL THEN NULL ELSE octet_length($6::bytea) END,
                       $8)
               RETURNING *""",
            feedback_id, guild_id, user_id, direction, content, image, image_mime,
            direction == "out",
        )

    async def get_messages(self, feedback_id: int) -> List[asyncpg.Record]:
        """All stored messages for a feedback thread, oldest first."""
        return await self.fetch(
            """SELECT id, feedback_id, guild_id, user_id, direction, content,
                      image IS NOT NULL AS has_image, image_mime, image_size, created_at
               FROM feedback_messages WHERE feedback_id = $1
               ORDER BY created_at, id""",
            feedback_id,
        )

    async def get_message_image(self, message_id: int) -> asyncpg.Record | None:
        """Fetch a stored image for a message. Returns None if no image."""
        return await self.fetchrow(
            "SELECT image, image_mime FROM feedback_messages WHERE id = $1 AND image IS NOT NULL",
            message_id,
        )

    async def get_conversation(self, user_id: int) -> List[asyncpg.Record]:
        """All stored messages for a user across every feedback thread, oldest first."""
        return await self.fetch(
            """SELECT id, feedback_id, guild_id, user_id, direction, content,
                      image IS NOT NULL AS has_image, image_mime, image_size, created_at
               FROM feedback_messages WHERE user_id = $1
               ORDER BY created_at, id""",
            user_id,
        )

    async def mark_messages_read(
        self,
        user_id: int | None = None,
        feedback_id: int | None = None,
    ) -> int:
        """Mark a user's (or a thread's) incoming messages as read.
        Returns the number of rows updated."""
        if user_id is not None:
            result = await self.execute(
                "UPDATE feedback_messages SET read = TRUE WHERE user_id = $1 AND direction = 'in' AND NOT read",
                user_id,
            )
        elif feedback_id is not None:
            result = await self.execute(
                "UPDATE feedback_messages SET read = TRUE WHERE feedback_id = $1 AND direction = 'in' AND NOT read",
                feedback_id,
            )
        else:
            return 0
        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0

    async def unread_messages(self) -> dict:
        """Aggregate unread incoming messages: {'total': int, 'users': {uid: count}}."""
        rows = await self.fetch(
            """SELECT user_id, COUNT(*)::int AS cnt
               FROM feedback_messages
               WHERE direction = 'in' AND NOT read AND user_id > 0
               GROUP BY user_id""",
        )
        users = {str(r["user_id"]): r["cnt"] for r in rows}
        return {"total": sum(users.values()), "users": users}

    async def get_latest_feedback_for_user(self, user_id: int) -> Optional[asyncpg.Record]:
        """Most recent feedback entry submitted by a user (any guild). Used to
        attach incoming DM replies to the right conversation thread."""
        return await self.fetchrow(
            """SELECT id, guild_id FROM feedback
               WHERE user_id = $1
               ORDER BY created_at DESC LIMIT 1""",
            user_id,
        )
