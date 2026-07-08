# Tausendsassa Discord Bot

A powerful, modular Discord bot with RSS feed integration, interactive maps, calendar management, and comprehensive monitoring. Built with discord.py 2.x and PostgreSQL.

## Features

- 🗞️ **RSS Feed Integration**: Monitor and post RSS/Atom feeds with customizable formatting
- 🗺️ **Interactive Maps**: Globe-view MapLibre map with user location pins, public URL per guild
- 📅 **Calendar Integration**: iCal calendar management with Discord event automation
- 🛡️ **Moderation Tools**: Server management with join-role and member log webhook
- 📊 **System Monitoring**: Health checks and multi-server overview
- 🌐 **Admin Web Panel**: Discord OAuth2-protected panel to manage all guild settings, with live map preview and DB browser tab
- 🗄️ **DB Browser**: Internal read-only database browser (owner-only, accessible via admin panel nav)
- 🐳 **Docker Support**: Full docker-compose deployment

## Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL 13+
- Discord Bot Token + OAuth2 App

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
pip install -r requirements.webapp.txt
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
# Bot
DISCORD_TOKEN=your_bot_token
BOT_OWNER_ID=your_discord_user_id

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tausendsassa
DB_USER=tausendsassa
DB_PASSWORD=your_password

# Admin webapp
DISCORD_CLIENT_ID=your_oauth_app_client_id
DISCORD_CLIENT_SECRET=your_oauth_app_client_secret
WEBAPP_SECRET_KEY=random_secret_32chars
WEBAPP_BASE_URL=https://your-domain.com
WEBAPP_URL=https://your-domain.com        # used by bot for the Explore button URL
```

### Running

```bash
# Bot
python bot.py

# Database Browser (port 8080, internal only)
uvicorn db_browser:app --host 127.0.0.1 --port 8080

# Admin Web Panel (port 8081, public)
uvicorn webapp.main:app --host 0.0.0.0 --port 8081
```

## Production Deployment

### Docker (recommended)

> **Important:** Use `docker compose` (plugin v2), not `docker-compose` (legacy v1).

```bash
docker compose up -d
```

**Containers:**
- `bot` — Discord bot
- `postgres` — PostgreSQL (internal only, not exposed publicly)
- `db-browser` — Internal DB browser (internal only, not exposed publicly)
- `webapp` — Admin panel (port 8081, behind nginx)

**Volume Structure:**
- `cogs/map_data/` — Natural Earth shapefiles, map cache, avatar cache (shared between bot and db-browser)
- `logs/` — Application logs

After code changes, rebuild specific containers:
```bash
docker compose up -d --build webapp   # webapp only
docker compose up -d --build bot      # bot only
# Then reload nginx if behind reverse proxy:
docker exec <nginx-container> nginx -s reload
```

> **Security note:** The `postgres` and `db-browser` containers must NOT have public port mappings.
> Access the DB browser at `https://your-domain.com/db/` (owner login required).

### Systemd

```bash
sudo systemctl enable --now tausendsassa
sudo systemctl enable --now tausendsassa-browser
```

## Project Structure

```
├── bot.py                  # Main entry point
├── db_browser.py           # Internal DB browser (port 8080, internal only)
├── webapp/                 # Admin panel (port 8081)
│   ├── main.py             # FastAPI app, OAuth2, CRUD routes, DB proxy
│   ├── static/             # Static assets (favicon, JS, CSS)
│   └── templates/          # Jinja2 templates (base, dashboard, map, login...)
├── cogs/                   # Discord feature modules
│   ├── feeds.py            # RSS monitoring
│   ├── map.py              # Geographic maps
│   ├── calendar.py         # iCal integration
│   ├── monitor.py          # System monitoring
│   └── map_data/           # Map data directory
│       ├── ne_10m_*.shp    # Natural Earth shapefiles
│       ├── map_cache/      # Base map cache
│       └── avatar_cache/   # Discord CDN cache
├── core/                   # Shared utilities
├── db/                     # Database layer (repositories)
└── resources/              # Static files (help docs, ToS, privacy, favicon)
```

## Admin Web Panel

Located at `WEBAPP_BASE_URL` (requires Discord OAuth2 login).

- **Login**: Discord OAuth2 — only server admins with the bot present can log in
- **Dashboard**: Per-guild view with live MapLibre map preview
- **Feeds**: Full CRUD (create, edit, delete, enable/disable all feeds)
- **Calendar**: Full CRUD for iCal calendars
- **Map**: Region selector with live globe preview
- **Moderation**: Member log webhook + auto-join role
- **DB Browser** (owner only): Link in top nav bar → `/db/` proxy, no separate login needed

## Map System

The Discord bot map message shows three buttons:

```
[📍 My Pin]  [🌍 Explore]  [...]
```

- **My Pin**: Set / update / remove your location pin
- **Explore**: Opens the public MapLibre globe map at `/map/{guild_id}`
- **...**: Info and Admin Tools (for server admins)

The public map at `/map/{guild_id}` requires no login and shows all pins on a globe.

## Commands

### Admin Commands
- `/feeds_add` — Add RSS feed
- `/feeds_list` — Manage feeds
- `/map_create` — Create server map (channel + region)
- `/cal_add` — Add iCal calendar
- `/timezone` — Set server timezone

### User Commands
- `/map_pin` — Set location on map
- `/help` — Show help

### Owner Commands
- `/owner_monitor` — System status
- `/owner_server_monitor` — Multi-server overview
- `/owner_poll_now` — Force RSS poll

## Required Map Data

Download Natural Earth shapefiles to `cogs/map_data/`:
- ne_10m_admin_0_countries.shp
- ne_10m_admin_1_states_provinces.shp
- ne_10m_land.shp
- ne_10m_lakes.shp
- ne_10m_rivers_lake_centerlines.shp

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| DISCORD_TOKEN | Yes | — | Bot token |
| DISCORD_CLIENT_ID | Yes (webapp) | — | OAuth2 app client ID |
| DISCORD_CLIENT_SECRET | Yes (webapp) | — | OAuth2 app client secret |
| WEBAPP_BASE_URL | Yes (webapp) | http://localhost:8081 | Public URL of the admin panel |
| WEBAPP_SECRET_KEY | Yes (webapp) | — | Session secret key |
| WEBAPP_URL | No | — | Used by bot for Explore button link |
| BOT_OWNER_ID | No | — | Discord user ID of bot owner |
| DB_HOST | No | localhost | Database host |
| DB_PORT | No | 5432 | Database port |
| DB_NAME | No | tausendsassa | Database name |
| DB_USER | No | tausendsassa | Database user |
| DB_PASSWORD | Yes | — | Database password |
| DB_BROWSER_URL | No | http://db-browser:8080 | Internal DB browser URL (webapp proxy) |
| LOG_WEBHOOK_URL | No | — | Discord webhook for logs |
| RSS_POLL_INTERVAL_MINUTES | No | 1.0 | Feed poll interval |
| MAP_PIN_COOLDOWN_MINUTES | No | 30 | Pin update cooldown |
| AUTHORIZED_USERS | No | — | Admin user IDs |

## License

MIT License — see LICENSE file
