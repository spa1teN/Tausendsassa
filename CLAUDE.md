# Tausendsassa — Discord Bot

Multi-server Discord bot (discord.py 2.7.1) with RSS/Reddit/Bluesky feed polling, iCal calendar integration, world-map pin board, and moderation logging. Posts via Discord Components V2 (CV2) LayoutView messages through webhooks.

## Features

### Map CV2 Cards
Maps use **discord.ui.LayoutView** with Container-based CV2 rendering:
- TextDisplay (guild name, pin count, region, timestamp)
- MediaGallery (rendered map image as `attachment://map.png`)
- Separator + ActionRow with Pin, 3D View (link), and Feedback buttons
- `/map` slash command for admins to configure, users to set pins
- Temporary apology card — deployed to all live maps, 24h auto-expiry via `cogs/map_data/.apology_expiry`

### Feedback System (`cogs/feedback.py`)
`/feedback` slash command and map CV2 Feedback button:
- Ephemeral CV2 menu: subject Select (Feeds/Map/Moderation/Calendar/Proposals/Other), anonymous toggle, "Write Message" button
- Message-only modal (subject + anonymity pre-set from menu)
- On submit: CV2 menu dismissed via `delete_original_response()`, ephemeral "✅ Feedback sent!" confirmation
- Stored in `feedback` table (PostgreSQL) with status tracking (new/important/in_progress/archived)

### RedGifs → GIF in CV2 Feeds
RedGifs links in RSS feeds are resolved via RedGifs API v2 (temporary auth token):
- Downloads HD MP4, converts to animated GIF via ffmpeg (palette-based, 10fps, 480px)
- GIF attached as `attachment://redgifs.gif` and shown in MediaGallery
- Falls back to MP4 attachment if conversion fails, poster JPG if download fails
- Gated to guild `694270970558546051` (cookie-whitelisted private server)
- `_raw_description` field preserved through HTML cleaning for URL extraction

### Dashboard & Data Interface
FastAPI admin panel at `https://dashboard.casparsadenius.de/#tausendsassa`:
- Cookie status chip (green/yellow/red, click-to-upload modal); gated to guild `694270970558546051`
- Pi Proxy status chip (green/yellow) — now a fallback, rarely needed
- Moderation chart + stats box
- Feedback inbox tab with status workflow (new → important → in_progress → archived)
- CV2 posting toggle per feed

**Data interface** (`/api/dashboard` + separate endpoints):
| Source | URL | Provides |
|---|---|---|
| `db_browser:8080` | `/api/dashboard` | Aggregate stats: feeds, maps, calendars, moderation, feedback counts, analytics |
| `db_browser:8080` | `/api/feedback` | CRUD: list, status, read, admin_note, unread-count |
| `bot:8090` | `/api/bot/*` | Discord-dependent: bot avatar, user name/avatar, guild channels/roles/webhooks |

See [`DATA_INTERFACE.md`](DATA_INTERFACE.md) for the full schema.

## Architecture

```
cogs/           Discord cogs (slash commands, listeners)
  feeds.py      Feed polling, posting, /feeds dashboard
  calendar.py   iCal sync, Discord events, reminders
  map.py        World map with user pins (CV2 LayoutView)
  moderation.py Join/leave logs, kick/ban/timeout, purge
  help.py       /help command
  feedback.py   /feedback command, modal, CV2 menu

core/           Business logic
  api_server.py      Internal API (port 8090) — bot avatar, user/guild lookups, channel/role/webhook listing for dashboard dropdowns
  feeds_cv2.py       CV2 LayoutView builder, Reddit gallery resolution (cookie-based JSON API)
  feeds_add.py       Feed creation UI (type selector, preview)
  feeds_rss.py       RSS fetch, parse, embed creation (preserves _raw_description)
  feeds_thumbnails.py  Image extraction (Bluesky API, OG images)
  feeds_dashboard.py   /feeds CV2 management interface
  feeds_config.py      Feed color presets, Bluesky detection
  media_downloader.py  RedGifs API + GIF conversion, Reddit gallery resolution
  feedback_menu.py     CV2 subject/anonymity selector
  config.py           Central config (env vars)
  cache_manager.py    LRU + file cache
  http_client.py      aiohttp session pool

db/             PostgreSQL via asyncpg, repository pattern
  schema.sql          Tables: feeds, calendars, map_settings, posted_entries (media_count), feedback, moderation_log
  repositories/       Per-table query classes including feedback_repository.py

webapp/         FastAPI admin panel (Discord OAuth2)
scripts/        Backfill/migration/health-check scripts
```
## Feed Posting

All 89 feeds use **CV2 LayoutView** (flag `cv2: true` in `embed_template` JSONB).

**Layout:**
```
## [Title](url)           ← emoji-stripped, clickable
-# <t:unix:f>              ← dynamic timestamp (user's timezone)
Description text...        ← ≤800 chars, Reddit boilerplate stripped
[MediaGallery]             ← images (SVGs filtered, RedGifs → GIF attachment)
─────────────────
[Open]                     ← link button
```

**Per-type handling:**
- **RSS/Atom**: Standard feed parsing, thumbnail from OpenGraph/media tags
- **Reddit**: `/new.rss` for chronological posts, `i.redd.it` full-res images
- **Reddit gallery**: Cookie-authenticated Reddit JSON API (no browser needed); Pi proxy as fallback
- **Bluesky**: `get_image_urls()` for all post images, template for static titles
- **BBC**: `/976/` upscaled CDN images
- **RedGifs**: API v2 → ffmpeg GIF conversion → `attachment://` in MediaGallery (guild `694270970558546051` only)

Posts via webhook with per-feed `username`/`avatar_url`.

## Feed Creation UI (`/feeds`)

| Type | Input | Auto-filled |
|---|---|---|
| RSS/Atom | Full URL | — |
| Reddit Forum | Subreddit name | `r/{name}`, `/new.rss`, color |
| Reddit User | Username | `u/{name}`, `/new.rss`, color |
| Bluesky | Handle | `@{name}`, avatar (AT Protocol API) |

Flow: type → modal → preview webhook → confirm. All new feeds get `cv2: true`.

## Reddit Gallery Resolution (cookie-based)

Gallery images from Reddit posts are resolved via the **Reddit JSON API**
(`reddit.com/comments/{id}.json`) authenticated with the browser cookie from
`cookies.txt`. This is a lightweight HTTP GET — no headless browser, no Pi proxy.

The Pi proxy (`scripts/reddit_gallery_proxy.py`) is kept as an optional fallback
(`GALLERY_PROXY_URL` env var). It only runs if direct API fails and is configured.

## Configuration

See `.env.example` for all options. Key ones:

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Bot token |
| `DB_PASSWORD` | PostgreSQL password |
| `COOKIES_PATH` | Reddit cookies file for gallery/API auth (default `/app/data/cookies.txt`) |
| `GALLERY_PROXY_URL` | Pi gallery proxy fallback (optional, rarely needed) |
| `RSS_POLL_INTERVAL_MINUTES` | Poll frequency (default 1.0) |

## Database

| Table | Purpose |
|---|---|
| `feeds` | Feed configurations per guild |
| `map_settings` | Map region, pin data, message_id per guild |
| `posted_entries` | Posted feed entries with `media_count` tracking |
| `feedback` | User feedback with `status`, `read`, `admin_note` columns |
| `moderation_log` | Join/leave, kick/ban/timeout events |

## Data Interface

Two internal API servers serve the external dashboard:

| Container | Port | Provides |
|---|---|---|
| `db-browser` | 8080 | `/api/dashboard` (aggregate), `/api/feedback` (CRUD), `/api/cookies/status` |
| `bot` | 8090 | `/api/bot/avatar`, `/api/bot/user/{id}`, `/api/bot/users?ids=`, `/api/bot/guild/{id}`, `/api/bot/guild/{id}/channels`, `/api/bot/guild/{id}/voice-channels`, `/api/bot/guild/{id}/roles`, `/api/bot/guild/{id}/webhooks` |

Full schema documented in [`DATA_INTERFACE.md`](DATA_INTERFACE.md).

## Known Limitations

- **Reddit JSON API** blocked from datacenter IPs without cookies — `cookies.txt` with `reddit_session` required for gallery resolution
- **Queer.de** feed: Latin-1 encoding, not UTF-8
- **Helsinki Times**: HTTP 202 (not a real RSS response)
- **CV2 button alignment**: Single buttons in ActionRows are always left-aligned; Discord has no alignment API
- **CV2 Container limit**: 5 items per container
- **Stale map channels**: Channels deleted or bot lacks permissions → auto-cleaned on restart (404 = clear refs, 403 = skip)
