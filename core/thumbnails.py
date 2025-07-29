# core/thumbnails.py
from typing import Any, Optional
import requests
import re
import feedparser

# Regex, um das erste <img src="..."> im HTML zu finden
_IMG_REGEX = re.compile(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', re.IGNORECASE)


APPVIEW = "https://public.api.bsky.app/xrpc"

def _resolve_handle_to_did(handle: str) -> str:
    """Turn a handle (e.g. `alice.bsky.social`) into a DID."""
    r = requests.get(
        f"{APPVIEW}/com.atproto.identity.resolveHandle",
        params={"handle": handle},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["did"]

def _parse_post_url(post_url: str):
    """
    Extract the user's handle / DID and the post rkey
    from URLs like:
        https://bsky.app/profile/<handle-or-did>/post/<rkey>
    """
    m = re.match(
        r"https?://bsky\.app/profile/([^/]+)/post/([^/?#]+)", post_url
    )
    if not m:
        raise ValueError("Unrecognised Bluesky post URL format")
    return m.group(1), m.group(2)  # (handle_or_did, rkey)

def get_image_urls(post_url: str) -> list[str]:
    handle_or_did, rkey = _parse_post_url(post_url)

    # Resolve the handle to a DID if necessary
    did = (
        handle_or_did
        if handle_or_did.startswith("did:")
        else _resolve_handle_to_did(handle_or_did)
    )

    at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"

    # Depth 0 → only the target post, no replies
    r = requests.get(
        f"{APPVIEW}/app.bsky.feed.getPostThread",
        params={"uri": at_uri, "depth": 0},
        timeout=10,
    )
    r.raise_for_status()
    thread = r.json().get("thread", {})

    # Helper to pull full-size (or thumb) image URLs
    def extract(node):
        images = []
        post = node.get("post") if "post" in node else node
        embed = post.get("embed", {})
        if embed.get("$type") == "app.bsky.embed.images#view":
            for img in embed.get("images", []):
                images.append(img.get("fullsize") or img.get("thumb"))
        return images

    return extract(thread)

def find_thumbnail(entry: Any) -> Optional[str]:
    """
    Versucht, ein Vorschaubild für einen RSS-Eintrag zu ermitteln.
    Reihenfolge:
      1. media_thumbnail
      2. media_content
      3. enclosures
      4. entry.links (type=image)
      5. content[...] HTML img
      6. summary HTML img
    """
    # 1. media_thumbnail
    if getattr(entry, 'media_thumbnail', None):
        url = entry.media_thumbnail[0].get('url')
        if url:
            return url

    # 2. media_content
    if getattr(entry, 'media_content', None):
        url = entry.media_content[0].get('url')
        if url:
            return url

    # 3. enclosures
    if getattr(entry, 'enclosures', None):
        for enc in entry.enclosures:
            href = enc.get('href') or enc.get('url')
            if href and enc.get('type', '').startswith('image/'):
                return href

    # 4. entry.links (RSS <link> tags)
    for link in getattr(entry, 'links', []):
        href = link.get('href')
        if href and link.get('type', '').startswith('image/'):
            return href

    # 5. HTML <img> in content[]
    for c in entry.get('content', []):
        html = c.get('value', '')
        m = _IMG_REGEX.search(html)
        if m:
            return m.group(1)

    # 6. HTML <img> in summary
    summary = entry.get('summary', '')
    m = _IMG_REGEX.search(summary)
    if m:
        return m.group(1)

    # 7. Bluesky
    bsky_link = entry.get("link")
    if bsky_link and "bsky.app/profile" in bsky_link:
        img = get_image_urls(bsky_link)
        if img:
            return img[0]
    
    return None
