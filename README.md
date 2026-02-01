# Tausendsassa Discord Bot

A powerful, modular Discord bot with RSS feed integration, interactive maps, calendar management, and comprehensive monitoring. Built with discord.py 2.x and PostgreSQL.

## Features

- 🗞️ **RSS Feed Integration**: Monitor and post RSS/Atom feeds with customizable formatting
- 🗺️ **Interactive Maps**: World, regional, and local maps with user location pins
- 📅 **Calendar Integration**: iCal calendar management with Discord event automation
- 🛡️ **Moderation Tools**: Server management capabilities
- 📊 **System Monitoring**: Health checks and server overview
- 🌐 **Web Interface**: Database browser for administration (port 8080)
- 🐳 **Docker Support**: Container deployment available

## Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL 13+
- Discord Bot Token

### Installation

```bash
# Clone repository
git clone https://github.com/your-repo/Tausendsassa.git
cd Tausendsassa

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Database Setup

```sql
CREATE USER tausendsassa WITH PASSWORD your_password;
CREATE DATABASE tausendsassa OWNER tausendsassa;
```

Run the schema from `db/schema.sql`.

### Configuration

Create `.env` file:

```bash
DISCORD_TOKEN=your_token
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tausendsassa
DB_USER=tausendsassa
DB_PASSWORD=your_password
```

### Running

```bash
# Bot
python bot.py

# Database Browser (separate terminal)
uvicorn db_browser:app --host 0.0.0.0 --port 8080
```

## Production Deployment

### Systemd Services

```bash
# Enable and start services
sudo systemctl enable --now tausendsassa
sudo systemctl enable --now tausendsassa-browser
```

### Docker

```bash
docker-compose up -d
```

**Volume Structure:**
- `cogs/map_data/` - Natural Earth shapefiles, map cache, avatar cache (shared between bot and db-browser)
- `logs/` - Application logs

The bot and db-browser automatically detect Docker vs Systemd runtime and adjust their monitoring displays accordingly.

## Project Structure

```
├── bot.py              # Main entry point
├── db_browser.py       # Web interface
├── cogs/               # Feature modules
│   ├── feeds.py        # RSS monitoring
│   ├── map.py          # Geographic maps
│   ├── calendar.py     # iCal integration
│   ├── monitor.py      # System monitoring
│   └── map_data/       # Map data directory
│       ├── ne_10m_*.shp    # Natural Earth shapefiles
│       ├── map_cache/      # Base map cache
│       └── avatar_cache/   # Discord CDN cache
├── core/               # Shared utilities
├── db/                 # Database layer
└── resources/          # Static files
```

## Database Browser

Access at `http://your-server:8080`

Features:
- System metrics (CPU, RAM, Disk, Uptime)
- Runtime mode indicator (Docker/Systemd)
- Guild, feed, calendar, map overview
- Log viewer
- Cog status monitoring
- Discord CDN proxy for avatars/icons

## Commands

### Admin Commands
- `/feeds_add` - Add RSS feed
- `/feeds_list` - Manage feeds
- `/map_create` - Create server map
- `/cal_add` - Add iCal calendar
- `/timezone` - Set server timezone

### User Commands
- `/map_pin` - Set location on map
- `/help` - Show help

### Owner Commands
- `/owner_monitor` - System status
- `/owner_server_monitor` - Multi-server overview
- `/owner_poll_now` - Force RSS poll

## Required Data

Download Natural Earth shapefiles to `cogs/map_data/`:
- ne_10m_admin_0_countries.shp
- ne_10m_admin_1_states_provinces.shp
- ne_10m_land.shp
- ne_10m_lakes.shp
- ne_10m_rivers_lake_centerlines.shp

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| DISCORD_TOKEN | Yes | - | Bot token |
| DB_HOST | No | localhost | Database host |
| DB_PORT | No | 5432 | Database port |
| DB_NAME | No | tausendsassa | Database name |
| DB_USER | No | tausendsassa | Database user |
| DB_PASSWORD | No | - | Database password |
| LOG_WEBHOOK_URL | No | - | Discord webhook for logs |
| BOT_OWNER_ID | No | - | Bot owner ID |
| RSS_POLL_INTERVAL_MINUTES | No | 1.0 | Feed poll interval |
| MAP_PIN_COOLDOWN_MINUTES | No | 30 | Pin update cooldown |
| AUTHORIZED_USERS | No | - | Admin user IDs |

## License

MIT License - see LICENSE file
