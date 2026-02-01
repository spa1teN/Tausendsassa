"""
Base repository class with common database operations.
"""

from typing import List, Optional, Any
import asyncpg


class BaseRepository:
    """
    Abstract base repository with common database operations.
    All repositories should inherit from this class.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def execute(self, query: str, *args) -> str:
        """Execute a query and return the status string."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, args: List[tuple]) -> None:
        """Execute a query multiple times with different arguments."""
        async with self.pool.acquire() as conn:
            await conn.executemany(query, args)

    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """Fetch multiple rows."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """Fetch a single row."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args) -> Any:
        """Fetch a single value."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def exists(self, query: str, *args) -> bool:
        """Check if a row exists."""
        result = await self.fetchval(f"SELECT EXISTS({query})", *args)
        return result

    async def count(self, table: str, where: str = None, *args) -> int:
        """Count rows in a table."""
        query = f"SELECT COUNT(*) FROM {table}"
        if where:
            query += f" WHERE {where}"
        result = await self.fetchval(query, *args)
        return result or 0

    async def transaction(self):
        """Get a connection for a transaction."""
        return self.pool.acquire()
