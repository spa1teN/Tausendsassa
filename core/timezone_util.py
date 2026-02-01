"""
Timezone utility module for consistent time handling across the bot.
"""

import datetime
import pytz
import logging
from typing import Optional

GERMAN_TZ = pytz.timezone("Europe/Berlin")
log = logging.getLogger("tausendsassa.timezone")
_timezone_cache: dict[int, str] = {}


def set_timezone_cache(guild_id: int, timezone_str: str) -> None:
    _timezone_cache[guild_id] = timezone_str


def clear_timezone_cache(guild_id: int = None) -> None:
    if guild_id:
        _timezone_cache.pop(guild_id, None)
    else:
        _timezone_cache.clear()


def get_guild_timezone(guild_id: Optional[int] = None) -> pytz.BaseTzInfo:
    if guild_id:
        guild_id = int(guild_id) if isinstance(guild_id, str) else guild_id
        timezone_str = _timezone_cache.get(guild_id)
        if timezone_str:
            try:
                return pytz.timezone(timezone_str)
            except Exception:
                pass
    return GERMAN_TZ


def get_current_time(guild_id: Optional[int] = None) -> datetime.datetime:
    tz = get_guild_timezone(guild_id)
    return datetime.datetime.now(tz)


def get_current_timestamp(guild_id: Optional[int] = None) -> int:
    return int(get_current_time(guild_id).timestamp())


def format_time(dt: datetime.datetime = None, guild_id: Optional[int] = None, format_str: str = "%d.%m.%Y %H:%M:%S") -> str:
    tz = get_guild_timezone(guild_id)
    if dt is None:
        dt = datetime.datetime.now(tz)
    elif dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(tz).strftime(format_str)


def to_guild_timezone(dt: datetime.datetime, guild_id: Optional[int] = None) -> datetime.datetime:
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(get_guild_timezone(guild_id))


def get_german_time() -> datetime.datetime:
    return datetime.datetime.now(GERMAN_TZ)


def get_german_timestamp() -> int:
    return int(get_german_time().timestamp())


def format_german_time(dt: datetime.datetime = None, format_str: str = "%d.%m.%Y %H:%M:%S") -> str:
    return format_time(dt, None, format_str)


def to_german_timezone(dt: datetime.datetime) -> datetime.datetime:
    return to_guild_timezone(dt, None)


def save_guild_timezone(guild_id: int, timezone_str: str) -> bool:
    try:
        pytz.timezone(timezone_str)
        set_timezone_cache(guild_id, timezone_str)
        return True
    except Exception:
        return False
