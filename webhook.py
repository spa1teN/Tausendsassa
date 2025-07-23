import time
import json
import requests
from typing import Any, Dict
from logclient import logger
from errors import send_error_once
from setup import RATE_LIMIT_SECONDS


def _post(cfg: Dict[str, Any], webhook: str, payload: Dict[str, Any]):
    while True:
        r = requests.post(webhook, json=payload)
        if r.status_code == 429:
            time.sleep(r.json().get("retry_after", RATE_LIMIT_SECONDS))
            continue
        if r.status_code >= 400:
            logger.error("Discord %s: %s", r.status_code, r.text)
            err_hook = cfg.get("error_webhook", cfg["webhook"])
            msg = f"Discord {r.status_code}: {r.text} ({cfg['feed_url']})"
            send_error_once(err_hook, r.status_code, r.text, cfg['feed_url'])
        break


def send_to_discord(cfg: Dict[str, Any], embed: Dict[str, Any]):
    payload = {
        "username": cfg.get("username", "RSS Bot"),
        "avatar_url": cfg.get("avatar_url", ""),
        "embeds": [embed],
    }
    webhook = cfg["webhook"]
    if tn := cfg.get("thread_name"):
        payload["thread_name"] = tn[:100]
    if tid := cfg.get("thread_id"):
        webhook += ("&" if "?" in webhook else "?") + f"thread_id={tid}"
    logger.debug("Embed-Payload: %s", json.dumps(payload, indent=2)[:2000])
    _post(cfg, webhook, payload)