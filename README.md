## RSS-to-Discord Bot
Ein interaktiver Discord-Bot, der RSS/Atom-Feeds periodisch abruft und als Embeds in Announcement-Channels postet.

### Features
- Periodisches Polling konfigurierbarer Feeds
- Fallbacks für Beschreibung und Bilder
- Auto-Crosspost in Announcement-Channels
- Slash-Commands: `/ping`, `/poll_now`, `/feeds_reload`
- Detailed Logging + RotatingFileHandler

### Voraussetzungen
- Python 3.10+ installiert
- Virtuelle Umgebung (venv)
- Ein Discord-Bot-Token mit **Message Content Intent** aktiviert
- Announcement-Channels in deinem Server

### Installation
```bash
git clone https://github.com/yourname/RSStoDiscord.git
cd RSStoDiscord
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Konfiguration
1. Kopiere das oben gezeigte `config.yaml`-Template in dein Projektverzeichnis.
2. Passe deine `channel_id`, `feed_url` und andere Werte an.
3. Lege Umgebungsvariablen fest:
   ```bash
   export DISCORD_TOKEN="DeinBotToken"
   # Optional für Guild-Scoped Slash-Commands:
   export DISCORD_GUILD_ID=123456789012345678
   ```

### Bot starten
```bash
source .venv/bin/activate
python bot.py
```

### Automatischer Start mit systemd
1. Erstelle `/etc/systemd/system/rssbot.service`:
   ```ini
   [Unit]
   Description=RSS-to-Discord Bot
   After=network.target

   [Service]
   WorkingDirectory=/home/pi/RSStoDiscord
   ExecStart=/home/pi/RSStoDiscord/.venv/bin/python bot.py
   Environment=DISCORD_TOKEN=DeinBotToken
   Restart=always
   User=pi

   [Install]
   WantedBy=multi-user.target
   ```
2. Aktivieren & starten:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rssbot.service
   sudo journalctl -fu rssbot.service
   ```

### Slash-Commands
- `/ping` ‑ Testet Latenz
- `/poll_now` ‑ Sofortiger Poll
- `/feeds_reload` ‑ Konfiguration neu laden

---

**Viel Spaß mit deinem RSS-to-Discord Bot!**

