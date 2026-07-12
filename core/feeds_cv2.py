"""Components-V2 feed entry rendering for feed posts.

Each entry -> Container(accent=feed_color) inside LayoutView:
  ## [emoji-stripped title](url)
  description (cleaned, <=800 chars)
  MediaGallery (if images)
  ---------
  [timestamp (disabled)] [Open (link button)]

Sent via webhook with per-feed username/avatar.

Reddit gallery support:
  Set GALLERY_PROXY_URL env var to the Pi's address (e.g. http://192.168.1.50:8090).
  When configured, Reddit posts are checked for gallery images via the proxy.
  Falls back to RSS thumbnail if the proxy is unreachable.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
import discord
from zoneinfo import ZoneInfo

from core.feeds_rss import _strip_html

log = logging.getLogger("tausendsassa.feeds_cv2")
TZ = ZoneInfo("Europe/Berlin")
GALLERY_PROXY_URL = os.getenv("GALLERY_PROXY_URL", "").rstrip("/")
_EMOJI_RE = re.compile(r"[^\w\s@#\-.,!?(){}|&+/'\":;—–]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_BOILERPLATE = re.compile(r"\s*submitted\s+by\s+/?u?/?[^\s\]]+", re.IGNORECASE)
_META = re.compile(r"\s*\[link\]\s*\[comments\]\s*", re.IGNORECASE)
_REDDIT_POST_RE = re.compile(r"reddit\.com/r/\w+/comments/")
_REDDIT_POST_ID_RE = re.compile(r"reddit\.com/r/\w+/comments/([a-z0-9]+)")
_PREVIEW_REDD_RE = re.compile(r"https?://preview\.redd\.it/([^?]+)\?")
_SVG_RE = re.compile(r"\.svg(\?|#|$)", re.IGNORECASE)
_REDGIFS_RE = re.compile(r"https?://(?:www\.|v3\.)?redgifs\.com/(?:watch|ifr)/([a-z0-9]+)", re.IGNORECASE)
_IMGUR_GIF_RE = re.compile(r"https?://(?:i\.)?imgur\.com/[a-zA-Z0-9]+\.(?:gif|gifv|mp4)", re.IGNORECASE)
_GFYCAT_RE = re.compile(r"https?://(?:www\.)?gfycat\.com/[a-z0-9]+", re.IGNORECASE)
_GIPHY_RE = re.compile(r"https?://(?:www\.)?giphy\.com/(?:gifs|embed)/[a-zA-Z0-9\-]+", re.IGNORECASE)
_TENOR_RE = re.compile(r"https?://(?:www\.)?tenor\.com/view/[^\s]+", re.IGNORECASE)
_VIDEO_HOSTS = [_REDGIFS_RE, _IMGUR_GIF_RE, _GFYCAT_RE, _GIPHY_RE, _TENOR_RE]

def find_raw_video_url(entry_data: dict, entry_link: str = "") -> str | None:
    """Return an external video/GIF host URL for Discord auto-embed, or None.

    CV2 MediaGallery can't play video; posting a raw URL lets Discord's
    native auto-embed handle the player.

    Only returns URLs from known external hosts (RedGifs, Imgur GIFs, etc.).
    Does NOT return Reddit post URLs — Discord doesn't auto-embed those.
    v.redd.it posts are not detected (Reddit RSS doesn't expose the direct URL).
    """
    # Check both the cleaned description and the raw (pre-HTML-stripped) description
    desc = entry_data.get("description", "") or entry_data.get("summary", "")
    raw = entry_data.get("_raw_description", "")
    search_texts = [desc]
    if raw and raw != desc:
        search_texts.append(raw)
    for text in search_texts:
        if not text:
            continue
        for pat in _VIDEO_HOSTS:
            m = pat.search(text)
            if m:
                return m.group(0)
    return None

def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def _clean_description(text: str, title: str = "") -> str:
    text = _strip_html(text).strip()
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _BOILERPLATE.sub("", text)
    text = _META.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if title and text:
        tlen = min(len(text), len(title))
        if text[:tlen].lower() == title[:tlen].lower():
            return ""
    return text if len(text) >= 1 else ""


def _fmt_timestamp(iso_str: str | None) -> str | None:
    """Convert ISO timestamp to Discord dynamic timestamp format (<t:unix:f>).
    Discord renders this in the user's local timezone automatically."""
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return f"<t:{int(dt.timestamp())}:f>"
    except (ValueError, TypeError):
        return None


def _load_cookies() -> dict[str, str]:
    """Parse Netscape-format cookies.txt into {name: value} dict."""
    cookie_path = os.environ.get("COOKIES_PATH", "/app/data/cookies.txt")
    cookies: dict[str, str] = {}
    try:
        with open(cookie_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except Exception:
        pass
    return cookies


def _extract_gallery_images(data: list) -> list[str]:
    """Extract gallery image URLs from Reddit JSON API response."""
    try:
        post_data = data[0]["data"]["children"][0]["data"]
        if "media_metadata" not in post_data and "gallery_data" not in post_data:
            return []

        media_ids = []
        if "gallery_data" in post_data:
            media_ids = [item["media_id"] for item in post_data["gallery_data"]["items"]]

        images = []
        media_meta = post_data.get("media_metadata", {})
        for mid in media_ids:
            if mid in media_meta:
                img = media_meta[mid]
                previews = img.get("p", [])
                if previews:
                    img_url = previews[-1].get("u", "").replace("&amp;", "&")
                    if img_url:
                        images.append(img_url)
                        continue
                # Fallback to derived i.redd.it URL
                ext = img.get("m", "image/jpeg").split("/")[-1]
                if ext == "jpg":
                    ext = "jpeg"
                img_id = img.get("id", mid)
                images.append(f"https://i.redd.it/{img_id}.{ext}")
        return images
    except Exception:
        return []

async def fetch_gallery_images(post_url: str) -> list[str] | None:
    """Resolve Reddit gallery images via JSON API with cookies (no browser).

    Falls back to the Pi proxy (GALLERY_PROXY_URL) only if direct API fails
    and the proxy is configured.
    """
    m = _REDDIT_POST_ID_RE.search(post_url)
    if not m:
        return None
    post_id = m.group(1)

    # Try direct Reddit JSON API with cookies first
    cookies = _load_cookies()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://www.reddit.com/comments/{post_id}.json",
                cookies=cookies if cookies else None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    images = _extract_gallery_images(data)
                    if images:
                        return images
    except Exception:
        pass

    # Fall back to Pi proxy if configured
    if GALLERY_PROXY_URL and _REDDIT_POST_RE.search(post_url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GALLERY_PROXY_URL}/gallery",
                    json={"url": post_url},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        images = data.get("images", [])
                        if images:
                            return images
        except Exception:
            pass
    return None


def build_entry_view(
    entry_data: dict[str, Any],
    feed_name: str,
    feed_color: int = 0x3498DB,
    *,
    gallery_images: list[str] | None = None,
) -> discord.ui.LayoutView:
    """Build a single-entry CV2 LayoutView from _create_embed output.

    gallery_images: Optional list from the Pi proxy. If provided, replaces the
    single RSS thumbnail with all gallery images in the MediaGallery.
    """
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour(feed_color))

    title = entry_data.get("title", feed_name)
    url = entry_data.get("url") or entry_data.get("entry_link", "")
    clean_title = _strip_emoji(title)
    container.add_item(discord.ui.TextDisplay(
        f"## [{clean_title}]({url})" if url and clean_title else f"## {clean_title or title}"
    ))

    # Timestamp + optional author (Reddit: "Posted by u/username · 2h ago")
    ts = _fmt_timestamp(entry_data.get("timestamp"))
    author = entry_data.get("author", "").strip()
    if author and author.startswith("/u/"):
        author = author[1:]  # "/u/username" → "u/username"
    byline_parts = [f"Posted by {author}"] if author else []
    if ts:
        byline_parts.append(ts)
    if byline_parts:
        container.add_item(discord.ui.TextDisplay("-# " + " · ".join(byline_parts)))
    desc = _clean_description(entry_data.get("description", ""), title)
    if desc:
        if len(desc) > 800:
            desc = desc[:800].rsplit(" ", 1)[0] + "[...]"
        container.add_item(discord.ui.TextDisplay(desc))

    # Collect images: gallery from Pi > entry data image
    images = []
    if gallery_images:
        images = gallery_images
    else:
        img = (entry_data.get("image") or {}).get("url", "")
        if img and not _SVG_RE.search(img):
            # Reddit: strip preview params → full-res i.redd.it
            pm = _PREVIEW_REDD_RE.match(img) if "reddit.com" in (entry_data.get("url") or "") else None
            if pm:
                img = f"https://i.redd.it/{pm.group(1)}"
            images = [img]

    if images:
        gallery = discord.ui.MediaGallery()
        for img in images:
            gallery.add_item(media=img)
        container.add_item(gallery)

    # Open button

    # Open button (link buttons are fine in webhooks)
    if url:
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(
            label="Open", style=discord.ButtonStyle.link, url=url))
        container.add_item(row)

    view.add_item(container)
    return view
