# RSStoDiscord

A Python script that reads RSS feeds and automatically sends new entries as Discord embed messages to defined webhooks.

## Features

- Multiple feeds and Discord webhooks configurable
- Each feed can be individually formatted (embed template)
- Only new entries are posted (state tracking via timestamp)
- Error notifications to a separate Discord webhook
- Automatic migration of old state files
- Easy customization via configuration files

## Requirements

- Python 3.8+
- Dependencies from `requirements.txt` (e.g. `feedparser`, `requests`)

## Installation

```bash
git clone https://github.com/deinuser/RSStoDiscord.git
cd RSStoDiscord
pip install -r requirements.txt
```

## Configuration

### Feeds & Webhooks

Edit the `setup.py` file and adjust the `FEEDS` list.  
Each feed requires at least:

- `feed_url`: RSS feed URL
- `webhook`: Discord webhook URL
- `username`: Display name in Discord
- `avatar_url`: Avatar image (optional)
- `embed_template`: Dict for the Discord embed

Example:
```python
FEEDS = [
    {
        "feed_url": "https://www.fcstpauli.com/en/rss",
        "webhook": "https://discord.com/api/webhooks/...",
        "username": "FC Sankt Pauli",
        "avatar_url": "...",
        "embed_template": {
            "title": "{title}",
            "description": "{description}",
            "url": "{link}",
            "footer": {"text": "As of: {published_custom:%d.%m.%Y %H:%M}"},
            "image": {"url": "{thumbnail}"},
        },
    },
    # more feeds ...
]
```

### Error Notification

Optionally, you can set an `error_webhook` for each feed to which errors will be reported.

## Usage

```bash
python3 main.py
```

The script reads all feeds, posts new entries, and updates the state in `posted_entries.json`.

## Notes

- The script uses **webhooks only** – buttons or interactions are not possible with webhooks.
- For buttons or automatic thread creation, a proper Discord bot is required.
- Errors are reported to the error webhook at most every 2 hours per feed/error type.

## Directory Structure

```
RSStoDiscord/
├── main.py
├── feeds.py
├── state.py
├── webhook.py
├── errors.py
├── setup.py
├── utils.py
├── thumbnails.py
├── data/
│   └── error_cache.json
├── logs/
│   └── rssbot.log
└── posted_entries.json
```


**Questions or problems?**  
Open an issue or contact