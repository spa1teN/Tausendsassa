#!/usr/bin/python3
import time
import logging
import feedparser
from setup import FEEDS, MAX_POST_AGE_SECONDS, RATE_LIMIT_SECONDS
from webhook import send_to_discord
from avatars import resolve_avatar
from errors import send_error_once
from feeds import _format_str, build_embed
from state import FeedEntry, _load_state, _save_state

logger = logging.getLogger("rssbot")

def process_feeds():
    state = _load_state()
    for cfg in FEEDS:
        if "avatar_url" in cfg:
            cfg["avatar_url"] = resolve_avatar(cfg["webhook"], cfg["avatar_url"])
        url = cfg["feed_url"]
        # Sicherstellen, dass feed_state immer ein dict ist!
        feed_state = state.get(url, {"last_ts": 0, "posted_ids": set()})
        if not isinstance(feed_state, dict):
            feed_state = {"last_ts": feed_state, "posted_ids": set()}
        posted_ids = set(feed_state.get("posted_ids", []))
        logger.info("\n➡️  %s", url)
        feed = feedparser.parse(url)
        entries = [FeedEntry.from_feedparser(e) for e in feed.entries]
        entries.sort(key=lambda e: e.published_ts or 0)
        last_ts = feed_state.get("last_ts", 0)
        new_entries = [
            e for e in entries
            if e.published_ts and e.published_ts > last_ts and e.id not in posted_ids
        ]
        if cfg.get("max_items"):
            new_entries = new_entries[-cfg["max_items"]:]
        if not new_entries:
            logger.info("   No new posts.")
            continue
        for e in new_entries:
            embed = build_embed(e, cfg)
            tn_tpl = cfg.get("thread_name")
            if tn_tpl:
                cfg["thread_name"] = _format_str(tn_tpl, e)
            logger.info("   → %s", e.link)
            webhooks = cfg["webhook"]
            if isinstance(webhooks, str):
                webhooks = [webhooks]
            for webhook in webhooks:
                cfg_copy = cfg.copy()
                cfg_copy["webhook"] = webhook
                try:
                    send_to_discord(cfg_copy, embed)
                except Exception as err:
                    logger.error("Error sending to Discord: %s", err, exc_info=True)
                    send_error_once(cfg_copy.get("error_webhook", webhook), 500, str(err), url)
                time.sleep(RATE_LIMIT_SECONDS)
            posted_ids.add(e.id)
        if new_entries:
            state[url] = {
                "last_ts": max(e.published_ts for e in new_entries if e.published_ts),
                "posted_ids": list(posted_ids)
            }
            _save_state(state)

if __name__ == "__main__":
    logging.basicConfig(
        filename="logs/rssbot.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    process_feeds()
