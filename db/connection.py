"""
Database connection management using asyncpg.
Provides a singleton DatabaseManager with connection pooling.
"""

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from db.repositories.feed_repository import FeedRepository
    from db.repositories.calendar_repository import CalendarRepository
    from db.repositories.map_repository import MapRepository
    from db.repositories.moderation_repository import ModerationRepository
    from db.repositories.cache_repository import CacheRepository
    from db.repositories.monitor_repository import MonitorRepository
    from db.repositories.guild_repository import GuildRepository

log = logging.getLogger("tausendsassa.db")


class DatabaseManager:
    """
    Manages PostgreSQL connection pool and provides access to repositories.

    Usage:
        db = await get_db()
        feeds = await db.feeds.get_guild_feeds(guild_id)
    """

    _instance: Optional['DatabaseManager'] = None
    _pool: Optional[asyncpg.Pool] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._repositories = {}
        self._connected = False

    @classmethod
    async def get_instance(cls) -> 'DatabaseManager':
        """Get or create the singleton DatabaseManager instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            if not cls._instance._connected:
                await cls._instance.connect()
            return cls._instance

    async def connect(
        self,
        host: str = None,
        port: int = None,
        database: str = None,
        user: str = None,
        password: str = None,
    ) -> None:
        """Initialize the connection pool."""
        import os

        host = host or os.getenv('DB_HOST', 'localhost')
        port = port or int(os.getenv('DB_PORT', 5432))
        database = database or os.getenv('DB_NAME', 'tausendsassa')
        user = user or os.getenv('DB_USER', 'tausendsassa')
        password = password or os.getenv('DB_PASSWORD', '')

        try:
            self._pool = await asyncpg.create_pool(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                min_size=2,
                max_size=10,
                command_timeout=60,
                statement_cache_size=100,
            )
            self._connected = True
            log.info(f"Database connection pool established: {host}:{port}/{database}")
        except Exception as e:
            log.error(f"Failed to connect to database: {e}")
            raise

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._connected = False
            self._repositories.clear()
            log.info("Database connection pool closed")

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not connected."""
        if not self._pool:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._connected and self._pool is not None

    # Repository accessors with lazy initialization

    @property
    def guilds(self) -> 'GuildRepository':
        """Get the guild repository."""
        if 'guilds' not in self._repositories:
            from db.repositories.guild_repository import GuildRepository
            self._repositories['guilds'] = GuildRepository(self.pool)
        return self._repositories['guilds']

    @property
    def feeds(self) -> 'FeedRepository':
        """Get the feed repository."""
        if 'feeds' not in self._repositories:
            from db.repositories.feed_repository import FeedRepository
            self._repositories['feeds'] = FeedRepository(self.pool)
        return self._repositories['feeds']

    @property
    def calendars(self) -> 'CalendarRepository':
        """Get the calendar repository."""
        if 'calendars' not in self._repositories:
            from db.repositories.calendar_repository import CalendarRepository
            self._repositories['calendars'] = CalendarRepository(self.pool)
        return self._repositories['calendars']

    @property
    def maps(self) -> 'MapRepository':
        """Get the map repository."""
        if 'maps' not in self._repositories:
            from db.repositories.map_repository import MapRepository
            self._repositories['maps'] = MapRepository(self.pool)
        return self._repositories['maps']

    @property
    def moderation(self) -> 'ModerationRepository':
        """Get the moderation repository."""
        if 'moderation' not in self._repositories:
            from db.repositories.moderation_repository import ModerationRepository
            self._repositories['moderation'] = ModerationRepository(self.pool)
        return self._repositories['moderation']

    @property
    def cache(self) -> 'CacheRepository':
        """Get the cache repository (webhooks, feed cache, entry hashes)."""
        if 'cache' not in self._repositories:
            from db.repositories.cache_repository import CacheRepository
            self._repositories['cache'] = CacheRepository(self.pool)
        return self._repositories['cache']

    @property
    def monitor(self) -> 'MonitorRepository':
        """Get the monitor repository."""
        if 'monitor' not in self._repositories:
            from db.repositories.monitor_repository import MonitorRepository
            self._repositories['monitor'] = MonitorRepository(self.pool)
        return self._repositories['monitor']


# Global accessor function
async def get_db() -> DatabaseManager:
    """Get the database manager instance."""
    return await DatabaseManager.get_instance()
