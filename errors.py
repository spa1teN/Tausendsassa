# errors.py
import time
import json
import hashlib
import requests
from pathlib import Path

ERR_CACHE = Path("data/error_cache.json")
ERR_CACHE.parent.mkdir(exist_ok=True, parents=True)
_cache = json.loads(ERR_CACHE.read_text()) if ERR_CACHE.exists() else {}
TTL_SECONDS = 2 * 60 * 60  # 2 hours

def _fingerprint(status, text, feed_url):
    raw = f"{status}|{text}|{feed_url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def send_error_once(webhook: str, status: int, text: str, feed_url: str):
    """
    Sends an error message to Discord, but at most once per error (by fingerprint) within TTL_SECONDS.
    """
    now = time.time()
    fp = _fingerprint(status, text, feed_url)
    last = _cache.get(fp, 0)
    if now - last < TTL_SECONDS:
        return
    payload = {
        "username": "RSS BOT ERROR",
        "embeds": [{
            "title": f"Discord Error {status}"[:256],
            "description": str(text)[:4000] or "Unknown error",
            "color": 0xFF0000,
            "footer": {"text": str(feed_url)[:2048]},
        }],
        "allowed_mentions": {"parse": []}
    }
    try:
        requests.post(webhook, json=payload, timeout=10)
    except Exception:
        pass
    finally:
        _cache[fp] = now
        ERR_CACHE.write_text(json.dumps(_cache))