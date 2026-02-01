# Tausendsassa Database Layer
"""
Database access layer using asyncpg and repository pattern.

Usage:
    from db import get_db

    db = await get_db()
    feeds = await db.feeds.get_guild_feeds(guild_id)
"""

from db.connection import get_db, DatabaseManager

__all__ = ['get_db', 'DatabaseManager']
