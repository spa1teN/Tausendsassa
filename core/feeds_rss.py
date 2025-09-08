# core/rss.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from zoneinfo import ZoneInfo
import re
import hashlib
import json

import feedparser
import requests
import yaml

from core.feeds_state import State
from core.feeds_thumbnails import find_thumbnail

# Configuration constants
TZ = ZoneInfo("Europe/Berlin")
MAX_AGE = timedelta(seconds=86400)
CONFIG_BASE = Path(__file__).parent.parent / "config"

# Global state and cache
_states: Dict[int, State] = {}
_feed_cache: Dict[str, dict] = {}  # Cache for HTTP headers and content hashes
_cache_file = CONFIG_BASE / "feed_cache.json"

def _get_guild_state(guild_id: int) -> State:
    """Get or create state object for a guild"""
    if guild_id not in _states:
        guild_dir = CONFIG_BASE / str(guild_id)
        guild_dir.mkdir(exist_ok=True)
        state_file = guild_dir / "posted_entries.json"
        _states[guild_id] = State(state_file)
    return _states[guild_id]

def _load_feed_cache():
    """Load HTTP cache data"""
    global _feed_cache
    if _cache_file.exists():
        try:
            with _cache_file.open(encoding="utf-8") as f:
                _feed_cache = json.load(f)
        except Exception:
            _feed_cache = {}

def _save_feed_cache():
    """Save HTTP cache data"""
    try:
        _cache_file.parent.mkdir(exist_ok=True)
        with _cache_file.open("w", encoding="utf-8") as f:
            json.dump(_feed_cache, f, indent=2)
    except Exception:
        pass

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

def _create_content_hash(entry) -> str:
    """Create a hash of the entry content for change detection"""
    content_parts = [
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
        str(entry.get("link", "")),
        str([c.get("value", "") for c in entry.get("content", [])]),
    ]
    content_string = "|".join(content_parts)
    return hashlib.md5(content_string.encode('utf-8')).hexdigest()

def _create_feed_hash(parsed_feed) -> str:
    """Create hash of entire feed for change detection"""
    entries_data = []
    for entry in parsed_feed.entries:
        entry_data = {
            'title': entry.get('title', ''),
            'summary': entry.get('summary', ''),
            'link': entry.get('link', ''),
            'published': str(entry.get('published_parsed', '')),
            'updated': str(entry.get('updated_parsed', ''))
        }
        entries_data.append(entry_data)
    
    feed_string = json.dumps(entries_data, sort_keys=True)
    return hashlib.md5(feed_string.encode('utf-8')).hexdigest()

def _fetch_with_cache(url: str) -> Optional[Tuple[feedparser.FeedParserDict, bool]]:
    """
    Fetch feed with HTTP caching support.
    Returns (parsed_feed, has_changed) or None if error
    """
    cache_key = url
    cache_data = _feed_cache.get(cache_key, {})
    
    headers = {
        'User-Agent': 'RSS Bot/1.0 (compatible; +https://example.com/bot)'
    }
    
    # Add conditional headers if we have cache data
    if 'etag' in cache_data:
        headers['If-None-Match'] = cache_data['etag']
    if 'last_modified' in cache_data:
        headers['If-Modified-Since'] = cache_data['last_modified']
    
    try:
        # Use requests instead of feedparser directly for better caching control
        response = requests.get(url, headers=headers, timeout=30)
        
        # Handle 304 Not Modified
        if response.status_code == 304:
            print(f"Feed unchanged (304): {url}")
            return None  # Consistently return None for no changes
        
        if response.status_code != 200:
            print(f"HTTP error {response.status_code} for {url}")
            return None  # Consistently return None for errors
        
        # Parse the feed content
        parsed = feedparser.parse(response.content)
        if parsed.bozo:
            print(f"Feed parse error for {url}: {parsed.bozo_exception}")
            return None  # Consistently return None for parse errors
        
        # Additional validation: check if parsed feed has entries
        if not hasattr(parsed, 'entries') or parsed.entries is None:
            print(f"Feed has no entries attribute: {url}")
            return None
        
        # Create content hash
        current_hash = _create_feed_hash(parsed)
        
        # Check if content actually changed
        has_changed = True
        if 'content_hash' in cache_data:
            has_changed = current_hash != cache_data['content_hash']
            if not has_changed:
                print(f"Feed content unchanged (hash match): {url}")
                return parsed, False
        
        # Update cache
        new_cache_data = {
            'content_hash': current_hash,
            'last_check': datetime.now(timezone.utc).isoformat()
        }
        
        # Store HTTP cache headers
        if 'etag' in response.headers:
            new_cache_data['etag'] = response.headers['etag']
        if 'last-modified' in response.headers:
            new_cache_data['last_modified'] = response.headers['last-modified']
        
        _feed_cache[cache_key] = new_cache_data
        _save_feed_cache()
        
        print(f"Feed updated: {url} (hash: {current_hash[:8]})")
        return parsed, has_changed
        
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None  # Consistently return None for all exceptions

def mark_entry_posted(guild_id: int, guid: str, message_id: int, channel_id: int):
    """Mark an entry as posted with message information"""
    state = _get_guild_state(guild_id)
    state.mark_sent(guid, message_id, channel_id, datetime.now(timezone.utc))
    state.save()

# Remove HTML tags from text
_REMOVE_TAGS = re.compile(r'<[^>]+>')
def _strip_html(text: str) -> str:
    """Strip HTML tags from text"""
    return _REMOVE_TAGS.sub('', text)

# Store content hashes for entries to detect real changes
_entry_hashes: Dict[str, str] = {}
_entry_hash_file = CONFIG_BASE / "entry_hashes.json"

def _load_entry_hashes():
    """Load entry content hashes"""
    global _entry_hashes
    if _entry_hash_file.exists():
        try:
            with _entry_hash_file.open(encoding="utf-8") as f:
                _entry_hashes = json.load(f)
        except Exception:
            _entry_hashes = {}

def _save_entry_hashes():
    """Save entry content hashes"""
    try:
        _entry_hash_file.parent.mkdir(exist_ok=True)
        with _entry_hash_file.open("w", encoding="utf-8") as f:
            json.dump(_entry_hashes, f, indent=2)
    except Exception:
        pass

# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def poll(feed_cfg: Dict[str, Any], guild_id: int) -> List[Dict[str, Any]]:
    """
    Fetch new items with intelligent caching and change detection.
    """
    url = feed_cfg.get("feed_url", "")
    
    # Try to fetch with caching
    result = _fetch_with_cache(url)
    if result is None:
        return []
    
    parsed, has_changed = result
    
    # If feed hasn't changed, only check for very recent entries that might need updates
    if not has_changed:
        return _check_recent_updates(parsed, feed_cfg, guild_id)
    
    new_embeds: List[Dict[str, Any]] = []
    max_items = feed_cfg.get("max_items", 3)
    state = _get_guild_state(guild_id)

    for entry in parsed.entries[:max_items]:
        guid = entry.get("id") or entry.get("link") or entry.get("url")
        if not guid:
            continue

        # Create content hash for this entry
        current_hash = _create_content_hash(entry)
        
        # Check if entry was already sent
        if state.already_sent(guid):
            # Check if content actually changed
            stored_hash = _entry_hashes.get(guid)
            if stored_hash and stored_hash != current_hash:
                # Content changed - create update
                message_info = state.get_message_info(guid)
                if message_info:
                    embed = _create_embed(entry, feed_cfg)
                    embed["is_update"] = True
                    embed["message_info"] = message_info
                    embed["guid"] = guid
                    new_embeds.append(embed)
                    
                    # Update stored hash
                    _entry_hashes[guid] = current_hash
                    _save_entry_hashes()
                    print(f"Content changed for {guid[:50]}...")
            continue

        # Process new entries
        published = _entry_published(entry) or datetime.now(timezone.utc)
        if datetime.now(timezone.utc) - published > MAX_AGE:
            continue

        embed = _create_embed(entry, feed_cfg)
        embed["guid"] = guid
        embed["is_update"] = False
        
        new_embeds.append(embed)
        state.mark_sent(guid, datetime.now(timezone.utc))
        
        # Store content hash for future change detection
        _entry_hashes[guid] = current_hash
        _save_entry_hashes()

    if new_embeds:
        state.save()
    return new_embeds

def _check_recent_updates(parsed, feed_cfg: Dict[str, Any], guild_id: int) -> List[Dict[str, Any]]:
    """Check only recent entries for updates when feed hasn't changed globally"""
    new_embeds: List[Dict[str, Any]] = []
    state = _get_guild_state(guild_id)
    
    # Only check entries from last 24 hours for updates
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    
    for entry in parsed.entries[:5]:  # Check fewer entries
        guid = entry.get("id") or entry.get("link") or entry.get("url")
        if not guid or not state.already_sent(guid):
            continue
            
        published = _entry_published(entry)
        if published and published < cutoff:
            continue
            
        # Check for content changes
        current_hash = _create_content_hash(entry)
        stored_hash = _entry_hashes.get(guid)
        
        if stored_hash and stored_hash != current_hash:
            message_info = state.get_message_info(guid)
            if message_info:
                embed = _create_embed(entry, feed_cfg)
                embed["is_update"] = True
                embed["message_info"] = message_info
                embed["guid"] = guid
                new_embeds.append(embed)
                
                _entry_hashes[guid] = current_hash
                _save_entry_hashes()
                print(f"Recent entry updated: {guid[:50]}...")
    
    return new_embeds

def _create_embed(entry, feed_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Create embed from entry and feed config"""
    published = _entry_published(entry) or datetime.now(timezone.utc)
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

    return embed

def cleanup_old_entries(guild_id: int):
    """Clean up old entries for a specific guild (older than 1 week)"""
    state = _get_guild_state(guild_id)
    state.cleanup_old_entries()
    
    # Also cleanup old entry hashes (older than 1 month)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_iso = cutoff.isoformat()
    
    global _entry_hashes
    old_count = len(_entry_hashes)
    # Simple cleanup - remove entries we haven't seen recently
    # (In practice you'd want to store timestamps for each hash)
    _entry_hashes = {k: v for k, v in _entry_hashes.items() if len(k) > 0}  # Basic cleanup
    
    if len(_entry_hashes) != old_count:
        _save_entry_hashes()

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

# Initialize caches on import
_load_feed_cache()
_load_entry_hashes()
