# core/thumbnails.py
from typing import Any, Optional
import requests
import re
import feedparser
from urllib.parse import urljoin, urlparse

# Regex patterns for finding images in HTML
_IMG_REGEX = re.compile(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
_OG_IMAGE_REGEX = re.compile(r'<meta[^>]+property=[\'"]og:image[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
_OG_IMAGE_REGEX_ALT = re.compile(r'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+property=[\'"]og:image[\'"]', re.IGNORECASE)

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
    """Extract image URLs from Bluesky post"""
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

def _fetch_og_image_from_url(url: str) -> Optional[str]:
    """
    Fetch the URL and try to extract OpenGraph image meta tag.
    Returns the first og:image URL found, or None.
    """
    try:
        # Set reasonable timeout and headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; RSS Bot/1.0; +https://example.com/bot)'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Only process HTML content
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            return None
            
        html = response.text
        
        # Try both variants of og:image meta tag
        match = _OG_IMAGE_REGEX.search(html)
        if not match:
            match = _OG_IMAGE_REGEX_ALT.search(html)
            
        if match:
            og_image_url = match.group(1)
            # Handle relative URLs
            if og_image_url.startswith('//'):
                og_image_url = 'https:' + og_image_url
            elif og_image_url.startswith('/'):
                parsed = urlparse(url)
                og_image_url = f"{parsed.scheme}://{parsed.netloc}{og_image_url}"
            elif not og_image_url.startswith(('http://', 'https://')):
                og_image_url = urljoin(url, og_image_url)
                
            return og_image_url
            
    except Exception as e:
        # Log error but don't fail completely
        print(f"Warning: Failed to fetch OpenGraph image from {url}: {e}")
    
    return None

def find_thumbnail(entry: Any) -> Optional[str]:
    """
    Try to find a thumbnail image for an RSS entry.
    Order of precedence:
      1. OpenGraph image from the entry URL (NEW)
      2. media_thumbnail
      3. media_content
      4. enclosures
      5. entry.links (type=image)
      6. content[...] HTML img
      7. summary HTML img
      8. Bluesky post images
    """
    # 1. OpenGraph image from entry URL (NEW - highest priority)
    entry_url = entry.get('link') or entry.get('url')
    if entry_url:
        og_image = _fetch_og_image_from_url(entry_url)
        if og_image:
            return og_image
    
    # 2. media_thumbnail
    if getattr(entry, 'media_thumbnail', None):
        url = entry.media_thumbnail[0].get('url')
        if url:
            return url

    # 3. media_content
    if getattr(entry, 'media_content', None):
        url = entry.media_content[0].get('url')
        if url:
            return url

    # 4. enclosures
    if getattr(entry, 'enclosures', None):
        for enc in entry.enclosures:
            href = enc.get('href') or enc.get('url')
            if href and enc.get('type', '').startswith('image/'):
                return href

    # 5. entry.links (RSS <link> tags)
    for link in getattr(entry, 'links', []):
        href = link.get('href')
        if href and link.get('type', '').startswith('image/'):
            return href

    # 6. HTML <img> in content[]
    for c in entry.get('content', []):
        html = c.get('value', '')
        m = _IMG_REGEX.search(html)
        if m:
            img_url = m.group(1)
            # Handle relative URLs
            if img_url and entry_url:
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                elif img_url.startswith('/'):
                    parsed = urlparse(entry_url)
                    img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
                elif not img_url.startswith(('http://', 'https://')):
                    img_url = urljoin(entry_url, img_url)
            return img_url

    # 7. HTML <img> in summary
    summary = entry.get('summary', '')
    m = _IMG_REGEX.search(summary)
    if m:
        img_url = m.group(1)
        # Handle relative URLs
        if img_url and entry_url:
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            elif img_url.startswith('/'):
                parsed = urlparse(entry_url)
                img_url = f"{parsed.scheme}://{parsed.netlook}{img_url}"
            elif not img_url.startswith(('http://', 'https://')):
                img_url = urljoin(entry_url, img_url)
        return img_url

    # 8. Bluesky post images
    bsky_link = entry.get("link")
    if bsky_link and "bsky.app/profile" in bsky_link:
        try:
            images = get_image_urls(bsky_link)
            if images:
                print(f"Debug: Found {len(images)} Bluesky images for post: {bsky_link}")
                return images[0]
            else:
                print(f"Debug: No images found in Bluesky post: {bsky_link}")
        except Exception as e:
            print(f"Warning: Failed to get Bluesky images from {bsky_link}: {e}")
    
    return None
