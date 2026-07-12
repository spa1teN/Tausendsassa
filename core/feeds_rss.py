# core/feeds_rss.py
"""
Async RSS feed polling with database-backed state management.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from zoneinfo import ZoneInfo
import re
import hashlib
import json
import asyncio

import feedparser
import aiohttp

from core.feeds_thumbnails import find_thumbnail
from core.config import config

# Configuration constants
TZ = ZoneInfo("Europe/Berlin")
MAX_AGE = timedelta(seconds=86400)

# Fetch-once/fan-out state: each feed URL is fetched a single time per poll cycle
# and the parsed result is handed to every guild that uses that URL. NOT_MODIFIED
# distinguishes an HTTP 304 (reuse the last parse) from a fetch error (None); the
# last successful parse per URL is kept so a 304 can still fan out to guilds that
# haven't posted the current entries yet (e.g. a freshly added feed).
NOT_MODIFIED = object()
_last_parsed: Dict[str, "feedparser.FeedParserDict"] = {}


def _fmt_timestamp(dt: datetime, guild_id: int = None) -> str:
    """Format datetime as ISO timestamp for Discord embed"""
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


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


def _get_feed_timeout(url: str) -> int:
    """Get appropriate timeout for a feed URL based on known slow feeds"""
    feed_timeouts = config.feed_specific_timeouts
    url_lower = url.lower()

    for pattern, timeout in feed_timeouts.items():
        if pattern in url_lower:
            return timeout

    return config.http_timeout


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


# Remove HTML tags from text
_REMOVE_TAGS = re.compile(r'<[^>]+>')
_HTML_ENTITIES = {
    '&quot;': '"',
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&apos;': "'",
    '&nbsp;': ' ',
    '&#39;': "'",
    '&#34;': '"',
    '&#38;': '&',
    '&#60;': '<',
    '&#62;': '>',
}


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode HTML entities from text"""
    if not text:
        return text

    text = _REMOVE_TAGS.sub('', text)

    for entity, replacement in _HTML_ENTITIES.items():
        text = text.replace(entity, replacement)

    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)

    return text.strip()

def _normalize_guid(guid: str, feed_url: str) -> str:
    """
    Normalize GUID to ensure stable deduplication.

    isthereanydeal.com uses GUIDs like 'game-name@1769911251' where the
    timestamp part changes on every feed update, causing false duplicates.
    We strip the timestamp to get a stable identifier.
    """
    if not guid:
        return guid

    # For isthereanydeal.com feeds, strip the @timestamp suffix
    if 'isthereanydeal.com' in feed_url:
        # Pattern: game-slug@timestamp (timestamp is a Unix epoch)
        match = re.match(r'^(.+)@\d{10}$', guid)
        if match:
            return match.group(1)

    return guid


async def _fetch_feed(url: str, session: aiohttp.ClientSession,
                      cache_data: Optional[Dict] = None, force: bool = False):
    """
    Fetch and parse a feed, using conditional GET (ETag/Last-Modified) for politeness.

    Returns one of:
      - NOT_MODIFIED  — server answered 304 (caller reuses the last parse)
      - None          — error / non-200 / unparseable
      - (parsed_feed, new_cache_data) — a fresh 200 parse

    With force=True the conditional headers are skipped, forcing a full 200 (used
    after a restart when there is no cached parse to reuse on a 304).
    """
    headers = {
        'User-Agent': 'RSS Bot/1.0 (compatible; +https://example.com/bot)'
    }

    if cache_data and not force:
        if cache_data.get('etag'):
            headers['If-None-Match'] = cache_data['etag']
        if cache_data.get('last_modified'):
            headers['If-Modified-Since'] = cache_data['last_modified']

    try:
        timeout = aiohttp.ClientTimeout(total=_get_feed_timeout(url))
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 304:
                return NOT_MODIFIED

            if response.status != 200:
                return None

            content = await response.read()

            # Parse feed in thread pool (feedparser is sync)
            parsed = await asyncio.to_thread(feedparser.parse, content)
            if parsed.bozo:
                return None

            if not hasattr(parsed, 'entries') or parsed.entries is None:
                return None

            new_cache_data = {
                'content_hash': _create_feed_hash(parsed),
                'etag': response.headers.get('etag'),
                'last_modified': response.headers.get('last-modified'),
            }

            return parsed, new_cache_data

    except Exception:
        return None


async def fetch_parsed(url: str, session: aiohttp.ClientSession, db):
    """Fetch a feed URL once and return its parsed form (or None on error).

    Fetched a single time per poll cycle regardless of how many guilds use the
    URL; the per-guild "already posted?" check lives in extract_new_embeds(). The
    global feed_cache (ETag/Last-Modified/hash) only saves bandwidth here — it no
    longer gates whether a guild posts, which is what previously made a shared
    feed land in only one server.
    """
    cache_data = await db.cache.get_feed_cache_dict(url)
    result = await _fetch_feed(url, session, cache_data)

    if result is NOT_MODIFIED:
        cached = _last_parsed.get(url)
        if cached is not None:
            return cached
        # No in-memory parse to reuse (e.g. right after a restart): force a full
        # fetch so guilds still receive the current entries.
        result = await _fetch_feed(url, session, cache_data, force=True)

    if result is None or result is NOT_MODIFIED:
        return None

    parsed, new_cache_data = result
    await db.cache.set_feed_cache(
        url,
        etag=new_cache_data.get('etag'),
        last_modified=new_cache_data.get('last_modified'),
        content_hash=new_cache_data.get('content_hash'),
    )
    _last_parsed[url] = parsed
    return parsed


async def extract_new_embeds(parsed, feed_cfg: Dict[str, Any], guild_id: int, db) -> List[Dict[str, Any]]:
    """Per-guild posting decision against an already-parsed feed.

    Runs once per (guild, feed) using the guild's own posted_entries as the sole
    dedup — so the same URL in several guilds posts independently. Handles both
    new entries (within MAX_AGE, up to max_items) and edits to entries this guild
    has already posted. Fetching happens once per URL in fetch_parsed().
    """
    new_embeds: List[Dict[str, Any]] = []
    max_items = feed_cfg.get("max_items", 3)
    url = feed_cfg.get("feed_url", "")

    for entry in parsed.entries[:max_items]:
        guid = entry.get("id") or entry.get("link") or entry.get("url")
        if not guid:
            continue
        guid = _normalize_guid(guid, url)
        entry_link = entry.get("link") or entry.get("url")

        current_hash = _create_content_hash(entry)

        # Already posted in THIS guild? Then only re-emit if the content changed.
        stored_entry = await db.feeds.get_entry(guild_id, guid)
        if stored_entry:
            stored_hash = stored_entry.content_hash
            if stored_hash and stored_hash != current_hash:
                message_info = await db.feeds.get_message_info(guild_id, guid)
                if message_info:
                    embed = _create_embed(entry, feed_cfg, guild_id)
                    embed["is_update"] = True
                    embed["message_info"] = message_info
                    embed["guid"] = guid
                    embed["entry_link"] = entry_link
                    new_embeds.append(embed)
                    await db.feeds.mark_entry_posted(guild_id, guid, content_hash=current_hash, entry_link=entry_link)
            continue

        # New entry for this guild — skip anything older than MAX_AGE so a freshly
        # added feed posts only recent items, not the whole backlog.
        published = _entry_published(entry) or datetime.now(timezone.utc)
        if datetime.now(timezone.utc) - published > MAX_AGE:
            continue

        embed = _create_embed(entry, feed_cfg, guild_id)
        embed["guid"] = guid
        embed["entry_link"] = entry_link
        embed["is_update"] = False
        new_embeds.append(embed)

        # Mark as sent (message info is filled in after the post succeeds)
        await db.feeds.mark_entry_posted(guild_id, guid, content_hash=current_hash, entry_link=entry_link)

    return new_embeds


def _create_embed(entry, feed_cfg: Dict[str, Any], guild_id: int = None) -> Dict[str, Any]:
    """Create embed from entry and feed config"""
    published = _entry_published(entry) or datetime.now(timezone.utc)
    thumb = find_thumbnail(entry)
    tpl = feed_cfg.get("embed_template", {})
    embed = _render_template(tpl, entry, thumb, published, guild_id)

    raw_desc = entry.get("summary", "") or entry.get("description", "")
    desc = embed.get("description", "").strip()
    if not desc:
        desc = raw_desc

    desc = _strip_html(desc)

    if len(desc) > 500:
        desc = desc[:500].rsplit(' ', 1)[0] + "[...]"

    embed["description"] = desc
    embed["_raw_description"] = raw_desc  # kept for video/GIF URL detection

    img = embed.get("image", {}) or {}
    if not img.get("url") and thumb:
        embed["image"] = {"url": thumb}

    # Propagate author for "Posted by u/..." display
    author = entry.get("author", "").strip()
    if author:
        embed["author"] = author
    return embed


async def mark_entry_posted(guild_id: int, guid: str, message_id: int,
                            channel_id: int, db, feed_id: int = None,
                            entry_link: str = None, media_count: int = None) -> None:
    """Mark an entry as posted with message information"""
    await db.feeds.mark_entry_posted(guild_id, guid, message_id, channel_id, feed_id=feed_id, entry_link=entry_link, media_count=media_count)


async def cleanup_old_entries(guild_id: int, db) -> int:
    """Clean up old entries for a specific guild (older than 1 week)"""
    deleted = await db.feeds.cleanup_old_entries(guild_id, days=7)

    # Also cleanup old entry hashes
    await db.cache.cleanup_old_hashes(days=30)

    return deleted


def _render_template(template: Dict[str, Any],
                     entry,
                     thumb_url: str | None,
                     published: datetime,
                     guild_id: int = None) -> Dict[str, Any]:
    """Render embed template with entry data"""
    from collections import defaultdict
    from core.timezone_util import to_guild_timezone

    def _fmt(value: Any) -> Any:
        if isinstance(value, str):
            safe = defaultdict(str)
            for k, v in entry.items():
                if v is not None:
                    if k == 'title':
                        safe[k] = _strip_html(str(v))
                    else:
                        safe[k] = str(v)
                else:
                    safe[k] = ""
            safe['link'] = entry.get('link', '')
            safe['thumbnail'] = thumb_url or ''

            if guild_id:
                guild_published = to_guild_timezone(published, guild_id)
                safe['published_custom'] = guild_published.strftime("%d.%m.%Y %H:%M")
            else:
                safe['published_custom'] = published.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
            return value.format_map(safe)
        if isinstance(value, dict):
            return {k: _fmt(v) for k, v in value.items()}
        return value

    embed = _fmt(template)
    embed["timestamp"] = _fmt_timestamp(published, guild_id)
    return embed
