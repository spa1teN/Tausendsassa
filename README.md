# Tausendsassa Discord Bot (this README is outdated, will fix)

A flexible, modular Discord bot featuring map pinning and RSS feed cogs, plus comprehensive console, file, and webhook logging.

## 📦 Features

### General
- **Modular Cogs**: `MapCog` and `FeedCog`  
- **Slash Commands** with per-guild scope  
- **Automatic Cog Loading** and synchronization on startup  
- **Intents**: default + `message_content` enabled  

### MapCog (Map Pinning)
- `/create_map` – Creates a map image (`world`, `europe`, `germany`) in a text channel  
- `/remove_map` – Deletes the map and all pins  
- `/pin_on_map <location>` – Geocodes via OpenStreetMap Nominatim, pins user location on the map  
- `/unpin_on_map` – Removes your own pin & updates the map  
- `/map_info` – Shows map stats (pin count, region, creator, your pin info)  
- **Data Storage** in `map_data.json` (auto-backups, human-readable JSON)  
- **Image Generation** with Pillow: stitching tiles, pixel scaling, colored user pins  

### FeedCog (RSS Feeds)
- `/ping` – Health check (Pong + latency)  
- `/poll_now` – Manually trigger a feed poll  
- `/feeds_reload` – Reload `config.yaml`, restart polling loop  
- `/feeds_status` – Show last run, last success, consecutive error count  
- `/feeds_add` & `/feeds_remove` – Dynamically manage feeds & embed template (title, description, link, color, image)  
- `/feeds_list` – List all configured feeds with colors and target channels  
- **Polling Loop** every 5 minutes (async tasks, timeout, thread offloading)  
- **Error Monitoring**: configurable threshold, alerts in a monitor channel  
- **Interactive Posts**: embed buttons and discussion threads for each new item  

### Logging
- **File Logging**:  
  - Root: `rssbot.log` (max 5 MB, 3 backups)  
  - Cog-specific: `logs/<cog>.log` (max 5 MB, 2 backups)  
- **Console Output**: INFO+ messages  
- **Discord Webhook**: embeds for INFO+ level logs (icons, module, function, timestamp, exception)  
- **Logger Hierarchy**: root `rssbot` logger + child `rssbot.<cog>` loggers sharing handlers  

## 🚀 Installation

```bash
git clone https://github.com/YourUser/TausendsassaBot.git
cd TausendsassaBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 🔧 Configuration
- Set the `DISCORD_TOKEN` environment variable.
- (Optional) Configure `LOG_WEBHOOK_URL` in `bot.py` or via env var.
- Create or edit `config.yaml`:
```yaml
feeds:
  - name: MyFeed
    feed_url: https://example.com/rss
    channel_id: 123456789012345678
    max_items: 3
    crosspost: false
    username: BotName
    avatar_url: https://...
    embed_template:
      title: "{title}"
      description: "{description}"
      url: "{link}"
      color: 0x3498DB
      timestamp: "{published}"
      footer: { text: MyFeed }
      image: { url: "{thumbnail}" }

monitor_channel_id: 987654321098765432
failure_threshold: 3
```
## 🎮 Usage
- Start the bot:
```bash
python bot.py
```
- Grant the bot **Manage Guild** permission to use commands like `/create_map` and `/feeds_add`.

### ⚙️ Development & Extension
- **Add New Cogs**: drop your module into `cogs/` and include it in `COGS` in `bot.py`.
- **Use the logger**: in your cog's constructor, call `self.log = bot.get_cog_logger("<cog_name>")`.
- **Dependencies**:
  - `discord.py`
  - `aiohttp`, `Pillow`, `PyYAML`