# avatars.py
import json
import requests
import mimetypes
from pathlib import Path

CACHE_FILE = Path("data/avatar_cache.json")
CACHE_FILE.parent.mkdir(exist_ok=True, parents=True)
_cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}

def resolve_avatar(webhook: str, avatar_source: str) -> str:
    """
    Accepts http(s) URLs directly. For a local file path, uploads the file to Discord,
    caches the resulting Discord CDN URL, and always returns a URL.
    """
    if avatar_source.startswith(("http://", "https://")):
        return avatar_source

    p = Path(avatar_source)
    if not p.exists():
        raise FileNotFoundError(p)

    # Already uploaded and cached?
    if avatar_source in _cache:
        return _cache[avatar_source]

    files = {
        "file": (
            p.name,
            p.read_bytes(),
            mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        )
    }
    payload = {
        "content": "avatar upload (temp)",
        "allowed_mentions": {"parse": []}
    }
    r = requests.post(
        webhook,
        data={"payload_json": json.dumps(payload)},
        files=files,
        timeout=15
    )
    r.raise_for_status()
    cdn_url = r.json()["attachments"][0]["url"]
    _cache[avatar_source] = cdn_url
    CACHE_FILE.write_text(json.dumps(_cache, indent=2))
    return cdn_url