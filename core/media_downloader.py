"""Cookie-authenticated media downloader for Reddit, RedGifs, and galleries.

Uses a Netscape-format cookies.txt (e.g. from "Get cookies.txt LOCALLY" extension)
to download media that requires Reddit authentication (i.redd.it, galleries).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import aiohttp

log = logging.getLogger(__name__)

# Patterns
_REDDIT_POST_RE = re.compile(r"reddit\.com/r/\w+/comments/([a-z0-9]+)")
_REDDIT_GALLERY_RE = re.compile(r'<a[^>]+href="https://(?:www\.)?reddit\.com/gallery/([a-z0-9]+)"')
_REDGIFS_WATCH_RE = re.compile(r"https?://(?:www\.|v3\.)?redgifs\.com/(?:watch|ifr)/([a-z0-9]+)", re.IGNORECASE)
_PREVIEW_GIF_RE = re.compile(r"https?://preview\.redd\.it/([a-z0-9]+)\.gif")
_I_REDD_IT_RE = re.compile(r"https?://i\.redd\.it/([a-z0-9]+\.\w+)")


def load_cookies(cookie_path: str) -> dict[str, str]:
    """Parse Netscape-format cookies.txt into a {name: value} dict."""
    cookies = {}
    path = Path(cookie_path)
    if not path.exists():
        log.warning("Cookie file not found: %s", cookie_path)
        return cookies

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies[name] = value
    log.debug("Loaded %d cookies from %s", len(cookies), cookie_path)
    return cookies


class MediaDownloader:
    """Cookie-authenticated media fetcher for Reddit and RedGifs."""

    def __init__(self, cookie_path: str | None = None):
        self._cookie_path = cookie_path
        self._cookies: dict[str, str] = {}
        self._cookies_loaded_at = 0.0
        self._session: aiohttp.ClientSession | None = None

    @property
    def cookies(self) -> dict[str, str]:
        """Lazy-load cookies, refreshing every hour."""
        now = time.time()
        if not self._cookies or (now - self._cookies_loaded_at > 3600):
            if self._cookie_path:
                self._cookies = load_cookies(self._cookie_path)
                self._cookies_loaded_at = now
        return self._cookies

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=5)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TausendsassaBot/1.0)"},
            )
        return self._session

    async def download(self, url: str, max_size: int = 25 * 1024 * 1024) -> BytesIO | None:
        """Download a URL to BytesIO. Uses cookies for Reddit domains. Returns None on failure."""
        session = await self._get_session()
        cookies = self.cookies if ("redd.it" in url or "reddit.com" in url) else None
        try:
            async with session.get(url, cookies=cookies, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    log.debug("Download failed %s: %s", resp.status, url[:80])
                    return None
                data = BytesIO()
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > max_size:
                        log.warning("Download too large: %s", url[:80])
                        return None
                    data.write(chunk)
                data.seek(0)
                return data
        except Exception as exc:
            log.debug("Download error for %s: %s", url[:80], exc)
            return None

    async def download_as_attachment(
        self, url: str, filename: str, max_size: int = 25 * 1024 * 1024
    ) -> tuple[str, BytesIO] | None:
        """Download and return (attachment_ref, BytesIO) for CV2 `attachment://` references.
        Returns None on failure.
        """
        data = await self.download(url, max_size)
        if data is None:
            return None
        return (f"attachment://{filename}", data)

    async def convert_mp4_to_gif(
        self, mp4_data: BytesIO,
        max_fps: int = 10,
        max_width: int = 480,
        max_duration: float = 30.0,
        max_size: int = 24 * 1024 * 1024,
    ) -> BytesIO | None:
        """Convert MP4 BytesIO to animated GIF via ffmpeg. Returns None on failure."""
        import asyncio
        import tempfile

        mp4_data.seek(0)
        # Write MP4 to temp file (ffmpeg needs a seekable input)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
            tmp_in.write(mp4_data.read())
            mp4_path = tmp_in.name
        mp4_data.seek(0)

        gif_path = mp4_path + ".gif"
        try:
            # High-quality GIF: generate palette for better colour
            vf = (
                f"fps={max_fps},scale={max_width}:-1:flags=lanczos,"
                f"split[s0][s1];[s0]palettegen=max_colors=128[p];"
                f"[s1][p]paletteuse=dither=bayer:bayer_scale=2"
            )
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y", "-t", str(max_duration),
                "-i", mp4_path,
                "-vf", vf,
                "-loop", "0",
                "-f", "gif",
                gif_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                stderr_str = stderr.decode()[:200] if stderr else ""
                log.debug("ffmpeg GIF conversion failed (rc=%d): %s", proc.returncode, stderr_str)
                return None

            # Read result and check size
            result = BytesIO()
            with open(gif_path, "rb") as f:
                total = 0
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_size:
                        log.debug("GIF too large: %d bytes", total)
                        return None
                    result.write(chunk)
            result.seek(0)
            log.debug("Converted MP4 to GIF: %d bytes", total)
            return result
        except FileNotFoundError:
            log.warning("ffmpeg not found — install ffmpeg for GIF conversion")
            return None
        except Exception as exc:
            log.debug("GIF conversion error: %s", exc)
            return None
        finally:
            # Clean up temp files
            try:
                Path(mp4_path).unlink(missing_ok=True)
            except OSError:
                pass
            try:
                Path(gif_path).unlink(missing_ok=True)
            except OSError:
                pass

    # -- RedGifs API ---------------------------------------------------

    async def fetch_redgifs_media(self, watch_url: str) -> dict | None:
        """Get RedGifs poster/HD URLs via API. Returns {poster, hd, sd} or None."""
        m = _REDGIFS_WATCH_RE.search(watch_url)
        if not m:
            return None
        slug = m.group(1)

        # Get temp auth token
        session = await self._get_session()
        try:
            async with session.get(
                "https://api.redgifs.com/v2/auth/temporary",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                token = data.get("token")
                if not token:
                    return None
        except Exception:
            return None

        # Fetch gif data
        try:
            async with session.get(
                f"https://api.redgifs.com/v2/gifs/{slug}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                gif_data = data.get("gif", data)
                urls = gif_data.get("urls", {})
                return {
                    "poster": urls.get("poster"),
                    "hd": urls.get("hd"),
                    "sd": urls.get("sd"),
                    "thumbnail": urls.get("thumbnail"),
                }
        except Exception:
            return None

    # -- Reddit galleries -----------------------------------------------

    async def fetch_reddit_gallery(self, post_url: str) -> list[str] | None:
        """Fetch gallery image URLs from a Reddit gallery post using cookies.
        Returns list of i.redd.it URLs or None on failure.
        """
        m = _REDDIT_POST_RE.search(post_url)
        if not m:
            return None
        post_id = m.group(1)

        session = await self._get_session()
        try:
            async with session.get(
                f"https://www.reddit.com/comments/{post_id}.json",
                cookies=self.cookies,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.debug("Gallery fetch failed: %s", resp.status)
                    return None
                data = await resp.json()
        except Exception as exc:
            log.debug("Gallery fetch error: %s", exc)
            return None

        try:
            post_data = data[0]["data"]["children"][0]["data"]
            if "media_metadata" not in post_data and "gallery_data" not in post_data:
                return None

            media_ids = []
            if "gallery_data" in post_data:
                media_ids = [item["media_id"] for item in post_data["gallery_data"]["items"]]

            images = []
            media_meta = post_data.get("media_metadata", {})
            for mid in media_ids:
                if mid in media_meta:
                    img = media_meta[mid]
                    # Prefer the largest preview from Reddit API
                    previews = img.get("p", [])
                    img_url = ""
                    if previews:
                        largest = previews[-1]
                        img_url = largest.get("u", "").replace("&amp;", "&")
                    if img_url:
                        images.append(img_url)
                    else:
                        # Fallback to derived i.redd.it URL
                        ext = img.get("m", "image/jpeg").split("/")[-1]
                        img_id = img.get("id", mid)
                        if ext == "jpg":
                            ext = "jpeg"
                        images.append(f"https://i.redd.it/{img_id}.{ext}")
            return images if images else None
        except Exception as exc:
            log.debug("Gallery parse error: %s", exc)
            return None

    async def resolve_entry_media(
        self,
        entry_data: dict,
        entry_link: str,
    ) -> tuple[list[str] | None, list[tuple[str, BytesIO]] | None]:
        """Resolve media for a feed entry. Returns (gallery_urls, attachments).

        gallery_urls: list of URLs for MediaGallery (URL-based, no cookies needed server-side)
        attachments: list of (attachment_ref, BytesIO) for attachment:// references

        If cookies aren't available, falls back to URL-based gallery.
        """
        gallery_urls = None
        attachments = None

        if not entry_link or "reddit.com" not in entry_link:
            return gallery_urls, attachments

        cookies_available = bool(self.cookies)

        # Try Reddit gallery (replaces Pi proxy)
        gallery_images = await self.fetch_reddit_gallery(entry_link)
        if gallery_images:
            if cookies_available:
                # Download and attach
                attachments = []
                for i, img_url in enumerate(gallery_images):
                    m = _I_REDD_IT_RE.search(img_url)
                    fname = f"img{i}.{m.group(1).split('.')[-1]}" if m else f"img{i}.jpg"
                    result = await self.download_as_attachment(img_url, fname)
                    if result:
                        attachments.append(result)
                gallery_urls = [ref for ref, _ in attachments] if attachments else gallery_images
            else:
                gallery_urls = gallery_images
        else:
            # Fall back to Pi proxy
            from core import feeds_cv2

            gallery_images = await feeds_cv2.fetch_gallery_images(entry_link)
            if gallery_images:
                gallery_urls = gallery_images

        # Try RedGifs: download HD video, convert to GIF for CV2 attachment
        desc = entry_data.get("description", "") or entry_data.get("summary", "")
        if desc:
            rg_match = _REDGIFS_WATCH_RE.search(desc)
            if rg_match:
                media = await self.fetch_redgifs_media(rg_match.group(0))
                if media:
                    hd_url = media.get("hd") or media.get("sd")
                    if hd_url:
                        mp4_data = await self.download(hd_url)
                        if mp4_data:
                            gif_data = await self.convert_mp4_to_gif(mp4_data)
                            if gif_data:
                                ref = "attachment://redgifs.gif"
                                attachments = [(ref, gif_data)] if attachments is None else attachments + [(ref, gif_data)]
                                # Show GIF in MediaGallery
                                gallery_urls = [ref]
                            else:
                                # Conversion failed — attach MP4 as fallback
                                result = (f"attachment://redgifs.mp4", mp4_data)
                                attachments = [result] if attachments is None else attachments + [result]
                    # Always fall back to poster for gallery if no GIF/MP4
                    if media.get("poster") and not gallery_urls:
                        gallery_urls = [media["poster"]]

        return gallery_urls, attachments


    def cookie_status(self) -> dict:
        """Return {valid: bool, expires: str|None, error: str|None} for dashboard."""
        if not self._cookie_path:
            return {"valid": False, "expires": None, "error": "No cookie path configured"}
        path = Path(self._cookie_path)
        if not path.exists():
            return {"valid": False, "expires": None, "error": "Cookie file not found"}
        # Parse cookies and find the reddit_session expiry
        cookies = load_cookies(self._cookie_path)
        reddit_session = cookies.get("reddit_session")
        if not reddit_session:
            return {"valid": False, "expires": None, "error": "No reddit_session cookie found"}
        # Check expiry from the cookie file (column 5)
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7 and parts[5] == "reddit_session":
                        exp_ts = int(parts[4]) if parts[4] and parts[4] != "0" else None
                        if exp_ts and exp_ts < time.time():
                            return {"valid": False, "expires": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(exp_ts)),
                                    "error": "Cookie expired"}
                        if exp_ts:
                            return {"valid": True, "expires": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(exp_ts))}
                        return {"valid": True, "expires": "session"}
        except Exception as exc:
            return {"valid": False, "expires": None, "error": str(exc)}
        return {"valid": True, "expires": "unknown"}
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# Global singleton
_downloader: MediaDownloader | None = None


def get_downloader(cookie_path: str | None = None) -> MediaDownloader:
    global _downloader
    if _downloader is None:
        _downloader = MediaDownloader(cookie_path)
    return _downloader
