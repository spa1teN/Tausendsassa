"""Fire-and-forget analytics event tracking.

Writes slash command usage, component interactions, and other bot events
to the `analytics` table in PostgreSQL. Hourly rollup with UPSERT — the
same pattern as the webapp's page_view tracking (webapp/main.py:105-109).

All writes are best-effort: a failure never affects bot operation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger("tausendsassa.analytics")

# SQL matching the webapp + schema UNIQUE constraint:
#   UNIQUE(event_type, guild_id, source, day, hour)
_UPSERT = """
    INSERT INTO analytics (event_type, guild_id, source, count, day, hour)
    VALUES ($1, $2, $3, 1, CURRENT_DATE, EXTRACT(HOUR FROM NOW()))
    ON CONFLICT (event_type, guild_id, source, day, hour)
    DO UPDATE SET count = analytics.count + 1
"""


async def track_event(
    pool: asyncpg.Pool,
    event_type: str,
    guild_id: int | None = None,
    source: str = "bot",
) -> None:
    """UPSERT one event occurrence into the analytics table.

    Args:
        pool: asyncpg connection pool (from DatabaseManager.pool).
        event_type: ``slash_command``, ``component_interaction``, ``map_view``,
                    or any other short identifier.
        guild_id: Discord guild ID, or None for global / non-guild events.
        source: ``bot`` (default) or ``web`` for the webapp.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(_UPSERT, event_type, guild_id, source)
    except Exception:
        pass  # never fail a request because of analytics
