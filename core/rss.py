# core/rss.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from zoneinfo import ZoneInfo
import re

import feedparser
import yaml

from core.state import State
from core.thumbnails import find_thumbnail

# Configuration constants
TZ = ZoneInfo("Europe/Berlin")
MAX_AGE = timedelta(seconds=360)  # 6 minutes
CONFIG_BASE = Path(__file__).parent.parent / "config"

# Global state cache
_states: Dict[int, State] = {}

def _get_guild_state(guild_id: int) -> State:
    """Get or create state object for a guild"""
    if guild_id not in _states:
        guild_dir = CONFIG_BASE / str(guild_id)
        guild_dir.mkdir(exist_ok=True)
        state_file = guild_dir / "posted_entries.json"
        _states[guild_id] = State(state_file)
    return _states[guild_id]

def _fmt_timestamp(dt: datetime) -> str:
    """Format datetime as ISO timestamp"""
    return dt.astimezone(timezone.utc).isoformat()

def _entry_published(entry) -> datetime | None:
    """Extract published datetime from feed entry"""
    if "published_parsed" in entry and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if "updated_parsed" in entry and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return None

# Remove HTML tags from text
_REMOVE_TAGS = re.compile(r'<[^>]+>')
def _strip_html(text: str) -> str:
    """Strip HTML tags from text"""
    return _REMOVE_TAGS.sub('', text)

# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def poll(feed_cfg: Dict[str, Any], guild_id: int) -> List[Dict[str, Any]]:
    """
    Fetch new items, render embeds with fallbacks for description and image,
    and save state. Now guild-aware.
    """
    url = feed_cfg.get("feed_url", "")
    parsed = feedparser.parse(url)
    if parsed.bozo:
        return []
    
    new_embeds: List[Dict[str, Any]] = []
    max_items = feed_cfg.get("max_items", 3)
    state = _get_guild_state(guild_id)

    for entry in parsed.entries[:max_items]:
        guid = entry.get("id") or entry.get("link") or entry.get("url")
        if not guid or state.already_sent(guid):
            continue

        published = _entry_published(entry) or datetime.now(timezone.utc)
        if datetime.now(timezone.utc) - published > MAX_AGE:
            continue

        # Find thumbnail
        thumb = find_thumbnail(entry)
        tpl = feed_cfg.get("embed_template", {})
        embed = _render_template(tpl, entry, thumb, published)

        # Description fallbacks
        desc = embed.get("description", "").strip()
        if not desc:
            desc = entry.get("summary", "")
        embed["description"] = _strip_html(desc)

        # Image fallbacks
        img = embed.get("image", {}) or {}
        if not img.get("url") and thumb:
            embed["image"] = {"url": thumb}

        embed["guid"] = guid
            
        new_embeds.append(embed)
        state.mark_sent(guid, datetime.now(timezone.utc))

    if new_embeds:
        state.save()
    return new_embeds

def cleanup_old_entries(guild_id: int):
    """Clean up old entries for a specific guild (older than 1 week)"""
    state = _get_guild_state(guild_id)
    state.cleanup_old_entries()

# --------------------------------------------------------------------------- #
# Internal rendering
# --------------------------------------------------------------------------- #

def _render_template(template: Dict[str, Any],
                     entry,
                     thumb_url: str | None,
                     published: datetime) -> Dict[str, Any]:
    """Render embed template with entry data"""
    from collections import defaultdict

    def _fmt(value: Any) -> Any:
        if isinstance(value, str):
            safe = defaultdict(str)
            # All entry fields
            for k, v in entry.items():
                safe[k] = str(v) if v is not None else ""
            # Reserved fields
            safe['link'] = entry.get('link', '')
            safe['thumbnail'] = thumb_url or ''
            safe['published_custom'] = published.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
            return value.format_map(safe)
        if isinstance(value, dict):
            return {k: _fmt(v) for k, v in value.items()}
        return value

    embed = _fmt(template)
    embed["timestamp"] = _fmt_timestamp(published)
    return embed
