# Tausendsassa Discord Bot - Technical Documentation

**Last Updated:** March 2026
**Repository:** Tausendsassa Bot  
**Architecture:** Discord.py 2.x with PostgreSQL Database Backend

## Project Overview

Tausendsassa is a multi-purpose Discord bot with RSS feed monitoring, interactive mapping, calendar integration, and administrative tools. The bot uses a modern PostgreSQL database backend with a web-based database browser for administration.

### Core Purpose
- **RSS/Atom Feed Integration**: Real-time monitoring and posting with Bluesky support
- **Interactive Geographic Maps**: User location mapping with customizable regions
- **Calendar Management**: iCal/ICS integration with Discord event automation
- **Server Administration**: Moderation tools and system monitoring
- **Multi-Server Support**: Per-guild configuration with database isolation

## Architecture

### Directory Structure
```
├── bot.py                    # Main entry point with DNS wait logic
├── db_browser.py             # FastAPI internal DB browser (port 8080)
├── webapp/                   # Admin panel (port 8081, Discord OAuth2)
│   ├── main.py              # FastAPI app: OAuth2, CRUD routes, DB proxy
│   └── templates/           # Jinja2 templates
│       ├── base.html        # Nav + layout
│       ├── dashboard.html   # Per-guild: feeds/cal/map/mod forms, map preview, DB tab
│       ├── map.html         # Public MapLibre globe map
│       ├── guild_select.html
│       ├── login.html
│       └── activity.html    # Discord Activity entry point
├── cogs/                     # Feature modules (Discord cogs)
│   ├── feeds.py             # RSS/Atom feed monitoring
│   ├── map.py               # Geographic mapping with user pins
│   ├── calendar.py          # iCal integration with Discord events
│   ├── moderation.py        # Server management
│   ├── monitor.py           # System health monitoring
│   ├── server_monitor.py    # Multi-server statistics
│   ├── help.py              # Dynamic help system
│   ├── whenistrumpgone.py   # Novelty countdown
│   └── map_data/            # Map shapefiles and cache
│       ├── ne_10m_*.shp     # Natural Earth shapefiles
│       ├── map_cache/       # Base map cache
│       ├── avatar_cache/    # Discord CDN avatar cache
│       └── {guild_id}/      # Per-guild map images
├── core/                     # Shared utilities
│   ├── config.py            # Environment-based configuration
│   ├── cache_manager.py     # LRU cache with cleanup
│   ├── http_client.py       # Shared HTTP connection pool
│   ├── retry_handler.py     # Exponential backoff retry
│   ├── validation.py        # Startup validation
│   ├── timezone_util.py     # In-memory timezone cache
│   ├── feeds_*.py           # RSS modules
│   ├── map_gen.py           # Map image generation (PIL + geopandas)
│   ├── map_storage.py       # Map cache management
│   ├── map_views.py         # Discord UI: MapPinButtonView, MapMenuView
│   ├── map_views_admin.py   # Discord UI: AdminToolsView
│   ├── map_config.py        # Region bounds, pin styles
│   ├── map_progress_handler.py  # Progress callbacks for map generation
│   └── mod_views.py         # Moderation UI
├── db/                       # Database layer
│   ├── __init__.py          # Database manager
│   ├── models.py            # Data models
│   └── repositories/        # Repository pattern
│       ├── base.py          # Base repository
│       ├── guild_repository.py
│       ├── feed_repository.py
│       ├── calendar_repository.py
│       ├── map_repository.py
│       ├── moderation_repository.py
│       └── cache_repository.py
├── resources/               # Static resources
│   ├── commands.md          # Help documentation
│   ├── terms-of-service.md
│   └── privacy-policy.md
├── scripts/                  # Utility scripts
│   ├── migrate_data.py      # YAML/JSON to PostgreSQL migration
│   └── backfill_avatars.py  # Backfill missing avatar_hash from Discord API
├── logs/                     # Log files (rotated daily)
├── docker-compose.yml        # Docker orchestration
├── Dockerfile               # Bot container
├── Dockerfile.browser       # DB Browser container
└── Dockerfile.webapp        # Admin webapp container
```

### Database Schema (PostgreSQL)

```sql
-- Core tables
guilds (id, name, icon_hash, member_count, created_at)
guild_timezones (guild_id, timezone)

-- Feeds
feeds (id, guild_id, name, feed_url, channel_id, webhook_url, 
       username, avatar_url, color, max_items, crosspost,
       embed_template, enabled, failure_count, last_success)
posted_entries (id, guild_id, guid, message_id, channel_id, 
                content_hash, feed_id, posted_at)
feed_monitor_channels (guild_id, channel_id)

-- Maps
map_settings (guild_id, channel_id, message_id, region, settings)
map_pins (id, guild_id, user_id, username, display_name, location,
          latitude, longitude, color, avatar_hash, pinned_at)

-- Calendar
calendars (id, guild_id, text_channel_id, voice_channel_id, ical_url,
           blacklist, whitelist, reminder_role_id)
calendar_events (id, calendar_pk, ical_uid, event_title, discord_event_id)
calendar_reminders (id, calendar_pk, reminder_key, sent_at)

-- Moderation
moderation_config (guild_id, log_channel_id, mute_role_id, settings)

-- Cache
webhook_cache (channel_id, webhook_id, webhook_url, webhook_name)
entry_hashes (guid, content_hash, created_at)
feed_cache (feed_url, etag, last_modified, feed_hash, cached_at)

-- Monitoring
monitor_messages (id, channel_id, message_id, monitor_type, auto_update_interval)
```

### Systemd Services

**Bot Service** (`/etc/systemd/system/tausendsassa.service`):
- Runs bot.py with virtual environment
- Network dependency with DNS wait in bot.py
- PID file in /run/tausendsassa/

**Browser Service** (`/etc/systemd/system/tausendsassa-browser.service`):
- FastAPI app on port 8080
- uvicorn server

## Configuration

### Environment Variables (.env)

```bash
# Required
DISCORD_TOKEN=your_token
BOT_OWNER_ID=your_discord_id

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tausendsassa
DB_USER=tausendsassa
DB_PASSWORD=your_password

# Admin webapp (webapp/main.py)
DISCORD_CLIENT_ID=oauth_app_client_id
DISCORD_CLIENT_SECRET=oauth_app_client_secret
WEBAPP_SECRET_KEY=random_32char_secret
WEBAPP_BASE_URL=https://your-domain.com
WEBAPP_URL=https://your-domain.com        # bot uses this for Explore button
DB_BROWSER_URL=http://db-browser:8080     # internal URL for DB proxy

# Optional
LOG_WEBHOOK_URL=discord_webhook_for_logging
RSS_POLL_INTERVAL_MINUTES=1.0
RSS_RATE_LIMIT_SECONDS=30
RSS_FAILURE_THRESHOLD=3
MAP_PIN_COOLDOWN_MINUTES=30
MAX_CACHE_SIZE_MB=25
HTTP_TIMEOUT=30
AUTHORIZED_USERS=id1,id2,id3
```

## Key Features

### Feed System
- Database-backed feed configuration
- Per-guild hash comparison for update detection
- Webhook-based posting with customizable avatars
- Automatic failure tracking and disabling

### Map System
- Natural Earth shapefiles for geographic data (PIL + geopandas rendering)
- Per-guild map image caching in `cogs/map_data/{guild_id}/`
- Avatar hash storage for map pins
- Public interactive globe at `/map/{guild_id}` (MapLibre GL JS v5, no login)
- Bot map message buttons: `[📍 My Pin]` `[🌍 Explore]` `[...]` on one row
- Nearby/Close-up features removed (March 2026)

### Calendar System
- Discord event lifecycle management
- Automatic reminders with role pings
- Weekly summary updates
- Timezone-aware timestamps

### Admin Web Panel (webapp/main.py, port 8081)
- Discord OAuth2 login — only guild admins where the bot is present can access
- Per-guild dashboard with live MapLibre map preview iframe
- Full CRUD for feeds, calendars, map settings, moderation config
- DB Browser tab (owner only): proxied at `/db/{path}`, no separate login needed
- Public routes (no auth): `/map/{guild_id}`, `/api/map/{guild_id}/pins`, `/activity`

### Database Browser (db_browser.py, port 8080)
- Internal only — accessed via webapp proxy at `/db/` (owner session required)
- FastAPI web interface, system metrics, cog status, feed/map/cal detail views
- Log viewer, Discord CDN proxy with avatar caching

## Deployment

### Docker (Production)
```bash
docker-compose up -d

# Rebuild after code changes (always use --build, templates are baked in):
docker-compose up -d --build webapp
docker-compose up -d --build bot

# After rebuilding webapp, reload nginx (it caches the upstream container IP):
docker exec <nginx-container> nginx -s reload
```

#### Docker Volume Mounts

**Bot Container:**
- `./cogs/map_data:/app/cogs/map_data` — Natural Earth shapefiles + map cache
- `./logs:/app/logs` — Log files

**DB Browser Container:**
- `./cogs/map_data:/app/cogs/map_data` — Map images + avatar cache (shared with bot)
- `./logs:/app/logs:ro` — Log viewer (read-only)
- `./resources:/app/resources:ro` — Favicon

**Webapp Container:**
- `./logs:/app/logs:ro` — Log access (read-only)

#### Runtime Mode Detection
Both the bot (Monitor cog) and db_browser automatically detect whether they're running in Docker or Systemd:
- **Docker**: Reads container uptime from PID 1, shows container ID
- **Systemd**: Reads bot uptime from PID file, shows service status

### Systemd (Alternative)
```bash
sudo systemctl enable --now tausendsassa
sudo systemctl enable --now tausendsassa-browser
```

## Development Notes

### Feed Hash Comparison
- Uses `posted_entries.content_hash` (per-guild) instead of global `entry_hashes`
- Prevents cross-guild hash conflicts for shared RSS feeds

### Timezone Storage
- In-memory cache in `core/timezone_util.py`
- Populated from database on demand
- No file-based storage (config/ folder eliminated)

### Map Image Paths
- Guild maps: `cogs/map_data/{guild_id}/base_map_{region}_{w}_{h}_{hash}.png`
- Base maps: `cogs/map_data/map_cache/base_map_{region}_{w}_{h}_default.png`
- Avatar cache: `cogs/map_data/avatar_cache/{type}_{id}_{hash}.{ext}`

## Recent Changes (March 2026)

- **Admin webapp** (`webapp/`): Discord OAuth2 panel with full CRUD for feeds, calendars, map settings, moderation
- **Map preview** in dashboard: live MapLibre globe iframe per guild
- **DB Browser tab** (owner only): proxied through webapp at `/db/`, no separate login
- **MapLibre globe** (`/map/{guild_id}`): upgraded from v4.7.1 → v5.19.0, globe projection via `style.load` event
- **Removed Nearby/Close-up** features from Discord bot map menu (all code + files deleted)
- **Explore button** moved to row 0 between `[📍 My Pin]` and `[...]`
- **Avatar backfill**: `scripts/backfill_avatars.py` to fill missing `avatar_hash` from Discord API
- **Webapp pin images**: WebGL symbol layers (ImageBitmap) instead of DOM markers — no globe lag
- `allow_proximity` removed from `/map_create` slash command

## Previous Changes (February 2026)

- PostgreSQL database backend replacing file-based YAML/JSON
- FastAPI database browser web interface (db_browser.py)
- Systemd service configuration
- DNS wait logic in bot.py for boot reliability
- Per-guild feed hash comparison fix
- Avatar hash storage for map pins
- Moved data/ to cogs/map_data/, documentation to resources/
- Removed backup.py cog (replaced by database)
- Docker/Systemd runtime detection in Monitor cog and db_browser
- Discord CDN proxy with avatar caching in db_browser
- Fixed Docker volume mounts for shared map_data directory
