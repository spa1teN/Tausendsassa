from copy import deepcopy
from datetime import datetime, timezone
import time
from typing import Any, Dict

from setup import TZ_Custom
from state import FeedEntry

def _format_str(template: str, entry: FeedEntry) -> str:
    """
    Formats a string template with entry data.
    Supports placeholders like {title}, {author}, {published_custom}, etc.
    """
    if "{" not in template:
        return template
    ts = entry.published_ts or time.time()
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    dt_custom = dt_utc.astimezone(TZ_Custom)
    mapping = {
        "title": entry.title,
        "author": entry.author,
        "link": entry.link,
        "published": dt_utc,
        "published_iso": dt_utc.isoformat(),
        "published_custom": dt_custom,
        "description": entry.description,
        "thumbnail": entry.thumbnail,
    }

    class Safe(dict):
        def __missing__(self, k):
            return "{" + k + "}"

    return template.format_map(Safe(mapping))

def _subst(obj: Any, entry: FeedEntry) -> Any:
    """
    Recursively substitute all string templates in obj with entry data.
    """
    if isinstance(obj, str):
        return _format_str(obj, entry)
    if isinstance(obj, dict):
        return {k: _subst(v, entry) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, entry) for v in obj]
    return obj

def _clean(obj: Any) -> Any:
    """
    Recursively remove None or empty structures from obj.
    """
    if isinstance(obj, dict):
        out = {k: _clean(v) for k, v in obj.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        cleaned = [_clean(v) for v in obj]
        return [v for v in cleaned if v not in (None, "", [], {})]
    return obj

def build_embed(entry: FeedEntry, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds a Discord embed dictionary from a FeedEntry and config.
    Uses the embed_template from config if available, otherwise falls back to a minimal embed.
    """
    if tpl := cfg.get("embed_template"):
        embed = _clean(_subst(deepcopy(tpl), entry))
        embed.setdefault("title", entry.title)
        embed.setdefault("url", entry.link)
        return embed
    # Fallback
    embed = {"title": entry.title, "url": entry.link}
    if entry.published:
        embed["timestamp"] = entry.published
    if entry.author:
        embed["author"] = {"name": entry.author}
    if entry.thumbnail:
        embed["thumbnail"] = {"url": entry.thumbnail}
    return embed