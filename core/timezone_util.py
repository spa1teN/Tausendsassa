"""
Timezone utility module for consistent time handling across the bot.
Provides MEZ/MESZ (Central European Time/Central European Summer Time) support
with guild-specific timezone configuration.
"""

import datetime
import pytz
import yaml
import logging
from pathlib import Path
from typing import Optional

# German timezone (default fallback)
GERMAN_TZ = pytz.timezone('Europe/Berlin')

log = logging.getLogger("tausendsassa.timezone")

def _get_guild_timezone_config_path(guild_id: int) -> Path:
    """Get the timezone config file path for a specific guild"""
    config_base = Path(__file__).parents[1] / "config"
    guild_dir = config_base / str(guild_id)
    guild_dir.mkdir(exist_ok=True)
    return guild_dir / "timezone_config.yaml"

def _load_guild_timezone(guild_id: int) -> Optional[str]:
    """Load timezone configuration for a specific guild"""
    config_path = _get_guild_timezone_config_path(guild_id)
    if not config_path.exists():
        return None
    
    try:
        with config_path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            return config.get("timezone")
    except Exception as e:
        log.error(f"Failed to load timezone config for guild {guild_id}: {e}")
        return None

def save_guild_timezone(guild_id: int, timezone_str: str) -> bool:
    """Save timezone configuration for a specific guild"""
    try:
        # Validate timezone
        pytz.timezone(timezone_str)
        
        config_path = _get_guild_timezone_config_path(guild_id)
        config = {"timezone": timezone_str}
        
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        
        log.info(f"Saved timezone {timezone_str} for guild {guild_id}")
        return True
    except Exception as e:
        log.error(f"Failed to save timezone config for guild {guild_id}: {e}")
        return False

def get_guild_timezone(guild_id: Optional[int] = None) -> pytz.BaseTzInfo:
    """Get timezone for a specific guild, falling back to German timezone"""
    if guild_id:
        # Ensure guild_id is int for consistency
        guild_id = int(guild_id) if isinstance(guild_id, str) else guild_id
        timezone_str = _load_guild_timezone(guild_id)
        if timezone_str:
            try:
                return pytz.timezone(timezone_str)
            except Exception as e:
                log.warning(f"Invalid timezone {timezone_str} for guild {guild_id}, falling back to German time: {e}")
    
    return GERMAN_TZ

def get_current_time(guild_id: Optional[int] = None) -> datetime.datetime:
    """
    Get current time in guild's configured timezone or German timezone.
    
    Args:
        guild_id: Guild ID to get timezone for. If None, uses German timezone.
    
    Returns:
        datetime.datetime: Current time in appropriate timezone
    """
    tz = get_guild_timezone(guild_id)
    return datetime.datetime.now(tz)

def get_current_timestamp(guild_id: Optional[int] = None) -> int:
    """
    Get current timestamp for Discord embeds in guild's timezone.
    
    Args:
        guild_id: Guild ID to get timezone for. If None, uses German timezone.
    
    Returns:
        int: Unix timestamp for current time in appropriate timezone
    """
    return int(get_current_time(guild_id).timestamp())

def format_time(dt: datetime.datetime = None, guild_id: Optional[int] = None, format_str: str = "%d.%m.%Y %H:%M:%S") -> str:
    """
    Format a datetime object to guild's timezone string.
    
    Args:
        dt: Datetime object to format. If None, uses current time.
        guild_id: Guild ID to get timezone for. If None, uses German timezone.
        format_str: Format string for datetime formatting
        
    Returns:
        str: Formatted datetime string in appropriate timezone
    """
    tz = get_guild_timezone(guild_id)
    
    if dt is None:
        dt = datetime.datetime.now(tz)
    elif dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = pytz.UTC.localize(dt)
    
    # Convert to appropriate timezone
    target_dt = dt.astimezone(tz)
    return target_dt.strftime(format_str)

def to_guild_timezone(dt: datetime.datetime, guild_id: Optional[int] = None) -> datetime.datetime:
    """
    Convert a datetime object to guild's timezone.
    
    Args:
        dt: Datetime object to convert
        guild_id: Guild ID to get timezone for. If None, uses German timezone.
        
    Returns:
        datetime.datetime: Datetime object in appropriate timezone
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = pytz.UTC.localize(dt)
    
    # Ensure guild_id is int for consistency
    if guild_id:
        guild_id = int(guild_id) if isinstance(guild_id, str) else guild_id
    
    tz = get_guild_timezone(guild_id)
    return dt.astimezone(tz)

# Backward compatibility functions (deprecated, use guild-aware versions)
def get_german_time() -> datetime.datetime:
    """Get current time in German timezone (MEZ/MESZ)."""
    return get_current_time()

def get_german_timestamp() -> int:
    """Get current timestamp in German timezone for Discord embeds."""
    return get_current_timestamp()

def format_german_time(dt: datetime.datetime = None, format_str: str = "%d.%m.%Y %H:%M:%S") -> str:
    """Format a datetime object to German timezone string."""
    return format_time(dt, None, format_str)

def to_german_timezone(dt: datetime.datetime) -> datetime.datetime:
    """Convert a datetime object to German timezone."""
    return to_guild_timezone(dt, None)