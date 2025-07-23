from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo


TZ_Custom = ZoneInfo("Europe/Berlin") # Custom timezone for formatting dates
MAX_POST_AGE_SECONDS = 30 * 24 * 60 * 60   # Maximum age of posts to consider (30 days)
RATE_LIMIT_SECONDS = 1.2
STATE_FILE = Path("posted_entries.json")


FEEDS: List[Dict[str, str]] = [

    {
        "feed_url": "", # Insert your feed URL here
        "webhook": "", # Insert your Discord webhook URL here
        "error_webhook": "", # Optional: Insert a separate webhook for error notifications
        "username": "", # Optional: Custom username for the bot
        "thread_name": "", # Optional: Custom thread name template
        "avatar_url": "", # Optional: Custom avatar URL for the bot
        "max_items": 3, # Optional: Limit the number of items to process per feed
        "thread_id": "", # Optional: ID of the thread to post in
        "embed_template": {
            "title": "{title}", # Title of the embed
            "url": "{link}", # URL of the article
            "author": "{author}", # Author of the article
            "timestamp": "{published_ts}", # Timestamp of the article
            "thumbnail": "{thumbnail}", # Thumbnail image URL
            "description": "{description}", # Description of the article
            "color": 0x5B3A29, # Color of the embed
            "footer": {"text": "{published_custom:%d.%m.%Y  %H:%M} {TZ_Custom}"}, # Custom footer text with date and time
            "image": {"url": "{thumbnail}"}, # Image URL for the embed
        },
    },
    
]
