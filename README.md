# RSStoDiscord

Ein Python-Skript, das RSS-Feeds ausliest und neue Einträge automatisch als Discord-Embed-Nachrichten an definierte Webhooks sendet.

## Features

- Mehrere Feeds und Discord-Webhooks konfigurierbar
- Jeder Feed kann individuell formatiert werden (Embed-Template)
- Nur neue Einträge werden gepostet (State-Tracking per Timestamp)
- Fehlerbenachrichtigung an separaten Discord-Webhook
- Automatische Migration alter State-Dateien
- Einfache Anpassung durch Konfigurationsdateien

## Voraussetzungen

- Python 3.8+
- Abhängigkeiten aus `requirements.txt` (z.B. `feedparser`, `requests`)

## Installation

```bash
git clone https://github.com/deinuser/RSStoDiscord.git
cd RSStoDiscord
pip install -r requirements.txt
```

## Konfiguration

### Feeds & Webhooks

Bearbeite die Datei `setup.py` und passe die Liste `FEEDS` an.  
Jeder Feed benötigt mindestens:

- `feed_url`: RSS-Feed-URL
- `webhook`: Discord-Webhook-URL
- `username`: Anzeigename im Discord
- `avatar_url`: Avatar-Bild (optional)
- `embed_template`: Dict für das Discord-Embed

Beispiel:
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
            "footer": {"text": "Stand: {published_custom:%d.%m.%Y %H:%M}"},
            "image": {"url": "{thumbnail}"},
        },
    },
    # weitere Feeds ...
]
```

### Fehlerbenachrichtigung

Optional kann für jeden Feed ein `error_webhook` gesetzt werden, an den Fehler gemeldet werden.

## Nutzung

```bash
python3 main.py
```

Das Skript liest alle Feeds, postet neue Einträge und aktualisiert den State in `posted_entries.json`.

## Hinweise

- Das Skript verwendet **nur Webhooks** – Buttons oder Interaktionen sind mit Webhooks nicht möglich.
- Für Buttons oder automatische Thread-Erstellung ist ein richtiger Discord-Bot nötig.
- Fehler werden maximal alle 2 Stunden pro Feed/Fehlertyp an den Error-Webhook gemeldet.

## Verzeichnisstruktur

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

## Lizenz

MIT License

---

**Fragen oder Probleme?**  
Erstelle ein Issue oder kontaktiere