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
from core.thumbnails import find_thumbnail  # Optional

# --------------------------------------------------------------------------- #
# Globale Parameter aus config.yaml
# --------------------------------------------------------------------------- #
CONFIG_PATH = Path(__file__).with_name("..").resolve() / "config.yaml"
with CONFIG_PATH.open(encoding="utf-8") as f:
    _GLOBAL = yaml.safe_load(f)

TZ = ZoneInfo(_GLOBAL.get("time_zone", "Europe/Berlin"))
# MAX_AGE initialisieren (sicherstellen, dass es int ist)
max_age_val = _GLOBAL.get("max_post_age_seconds", 360)
try:
    max_age_val = int(max_age_val)
except (TypeError, ValueError):
    max_age_val = 360
MAX_AGE = timedelta(seconds=max_age_val)

STATE_FILE = Path(_GLOBAL.get("state_file", "posted_entries.json")).expanduser()
_state = State(STATE_FILE)

# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def _fmt_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def _entry_published(entry) -> datetime | None:
    if "published_parsed" in entry and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if "updated_parsed" in entry and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return None

# Entfernt HTML-Tags aus einem Text
_REMOVE_TAGS = re.compile(r'<[^>]+>')
def _strip_html(text: str) -> str:
    return _REMOVE_TAGS.sub('', text)

# --------------------------------------------------------------------------- #
#  Öffentliche API
# --------------------------------------------------------------------------- #

def poll(feed_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Holt neue Items, rendert Embeds mit Fallbacks für Description und Image,
    und speichert den State.
    """
    url = feed_cfg.get("feed_url", "")
    parsed = feedparser.parse(url)
    if parsed.bozo:
        return []
    new_embeds: List[Dict[str, Any]] = []
    max_items = feed_cfg.get("max_items", 3)

    for entry in parsed.entries[:max_items]:
        guid = entry.get("id") or entry.get("link")
        if not guid or _state.already_sent(guid):
            continue

        published = _entry_published(entry) or datetime.now(timezone.utc)
        if datetime.now(timezone.utc) - published > MAX_AGE:
            continue

        # Thumbnail suchen
        thumb = find_thumbnail(entry)
        tpl = feed_cfg.get("embed_template", {})
        embed = _render_template(tpl, entry, thumb, published)

        # Description-Fallbacks
        desc = embed.get("description", "").strip()
        if not desc:
            desc = entry.get("summary", "")
        embed["description"] = _strip_html(desc)

        # Image-Fallbacks
        img = embed.get("image", {}) or {}
        if not img.get("url") and thumb:
            embed["image"] = {"url": thumb}

        new_embeds.append(embed)
        _state.mark_sent(guid)

    if new_embeds:
        _state.save()
    return new_embeds

# --------------------------------------------------------------------------- #
#  Internes Rendering
# --------------------------------------------------------------------------- #

def _render_template(template: Dict[str, Any],
                     entry,
                     thumb_url: str | None,
                     published: datetime) -> Dict[str, Any]:
    from collections import defaultdict

    def _fmt(value: Any) -> Any:
        if isinstance(value, str):
            safe = defaultdict(str)
            # Alle Entry-Felder rein
            for k, v in entry.items():
                safe[k] = v
            # Reservierte Felder
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
