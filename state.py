import calendar
from dataclasses import dataclass
import json
import time
from typing import Dict, Optional

import feedparser

from setup import STATE_FILE
from thumbnails import _extract_thumbnail
from utils import cleanhtml


@dataclass
class FeedEntry:
    id: str
    title: str
    link: str
    author: str
    published: str
    published_ts: Optional[int]
    description: str
    thumbnail: str

    @classmethod
    def from_feedparser(cls, e: feedparser.FeedParserDict) -> "FeedEntry":
        entry_id = e.get("id") or e.get("guid") or e.get("link")
        tm = e.get("published_parsed") or e.get("updated_parsed")
        iso, ts = (time.strftime("%Y-%m-%dT%H:%M:%SZ", tm), calendar.timegm(tm)) if tm else ("", None)
        return cls(
            id=entry_id,
            title=e.get("title", "(no title)"),
            link=e.get("link", ""),
            author=e.get("author", ""),
            published=iso,
            published_ts=ts,
            description=cleanhtml(e.get("description", "") or e.get("summary", "")),
            thumbnail=_extract_thumbnail(e),
        )


def _load_state() -> Dict[str, float]:
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Migration: if value is a list, take the max (old format)
        for k, v in list(data.items()):
            if isinstance(v, list):
                data[k] = max(v) if v else 0
        return data
    return {}


def _save_state(state: Dict[str, float]):
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

