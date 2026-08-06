<p align="center">
  <img src="resources/favicon.png" width="96" alt="Tausendsassa logo">
</p>

<h1 align="center">Tausendsassa</h1>

<p align="center">
  <strong>Multi-purpose Discord bot</strong> — RSS/Reddit/Bluesky news feeds,
  interactive world map, iCal calendar sync, moderation logging, and a web
  admin dashboard. Built with discord.py and PostgreSQL, deployed via Docker.
</p>

<p align="center">
  <a href="https://discord.com/oauth2/authorize?client_id=1398477775828029645&permissions=537259968&scope=bot%20applications.commands">
    <img src="https://img.shields.io/badge/Invite%20Bot-5865F2?logo=discord&logoColor=white&style=for-the-badge" alt="Invite Bot">
  </a>
  <a href="https://discord.gg/yVNkpH6vDS">
    <img src="https://img.shields.io/badge/Support%20Server-5865F2?logo=discord&logoColor=white&style=for-the-badge" alt="Support Server">
  </a>
  <a href="https://tausendsassa.casparsadenius.de">
    <img src="https://img.shields.io/badge/Web%20Panel-4285F4?logo=googlechrome&logoColor=white&style=for-the-badge" alt="Web Panel">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white" alt="discord.py 2.7">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
</p>

---

## ✨ Features

| | | |
|---|---|---|
| 📰 **News Feeds** | RSS, Atom, Reddit (subreddits & users), Bluesky — 89+ feeds across 65+ servers. Rich CV2 embeds with MediaGallery, RedGifs → GIF conversion, per-feed webhook avatars |
| 🗺️ **World Map** | Interactive pinboard with Natural Earth rendering, 3D globe view, per-guild regions. Users set pins via slash commands; Discord CV2 cards with media + action buttons |
| 📅 **Calendar** | iCal/ICS sync with automatic Discord event lifecycle (create → start → end), weekly summaries, blacklist/whitelist filtering |
| 🛡️ **Moderation** | Join/leave logging, kick/ban/timeout tracking with moderator attribution, purge command, auto-join role |
| 💬 **Feedback** | Per-server `/feedback` with subject categories, anonymous toggle, status workflow (new → important → in_progress → archived) |
| 🌐 **Web Panel** | Discord OAuth2 admin dashboard at [tausendsassa.casparsadenius.de](https://tausendsassa.casparsadenius.de) — manage feeds, calendars, maps, moderation, and feedback across all your servers |

## 🚀 Quick Links

- **[Invite the Bot](https://discord.com/oauth2/authorize?client_id=1398477775828029645&permissions=537259968&scope=bot%20applications.commands)** — add Tausendsassa to your server
- **[Web Admin Panel](https://tausendsassa.casparsadenius.de)** — manage your server's feeds, maps, and calendars
- **[Support Server](https://discord.gg/yVNkpH6vDS)** — get help, report bugs, suggest features
- **[Privacy Policy](https://tausendsassa.casparsadenius.de/privacy)** · **[Terms of Service](https://tausendsassa.casparsadenius.de/terms)**

## 📸 Screenshots

| Feed Post (CV2) | Map with Pins | Web Panel |
|---|---|---|
| *Coming soon* | *Coming soon* | *Coming soon* |

> Getting clean screenshots from a test guild — PRs welcome!

## 🏗️ Architecture

```
cogs/           Discord cogs (slash commands, listeners)
  feeds.py      Feed polling, posting, /feeds dashboard
  calendar.py   iCal sync, Discord events, reminders
  map.py        World map with user pins (CV2 LayoutView)
  moderation.py Join/leave logs, kick/ban/timeout, purge
  help.py       /help command
  feedback.py   /feedback command, modal, CV2 menu

core/           Business logic
  feeds_cv2.py        CV2 LayoutView builder
  feeds_rss.py        RSS fetch, parse, embed creation
  feeds_thumbnails.py Image extraction (Bluesky, OG images)
  media_downloader.py RedGifs API + GIF conversion
  map_storage.py      Map image cache management
  api_server.py       Internal API (port 8090)

db/             PostgreSQL via asyncpg, repository pattern
webapp/         FastAPI admin panel (Discord OAuth2)
scripts/        Backfill, migration, and health-check scripts
```

| Container | Role | Port |
|---|---|---|
| `tausendsassa-bot` | Discord bot + internal API | :8090 (internal) |
| `tausendsassa-db-browser` | Dashboard API + feedback CRUD | :8080 (internal) |
| `tausendsassa-webapp` | FastAPI admin panel | :8081 (published, proxied) |
| `tausendsassa-db` | PostgreSQL 16 | — |

## 🔧 Self-Hosting

### Prerequisites

- Docker & Docker Compose
- A [Discord Bot Application](https://discord.com/developers/applications) with token
- (Optional) Discord OAuth2 client for the web panel

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/spa1teN/Tausendsassa.git
cd Tausendsassa

# 2. Configure environment
cp .env.example .env
# Edit .env — set DISCORD_TOKEN, DB_PASSWORD, and other values

# 3. Start all services
docker compose up -d

# 4. Check health
docker compose logs bot --tail 20
curl -s http://localhost:8081/  # should return 307 (redirect to /login)
```

### Required Bot Permissions

The bot needs these permissions to function:
- **Send Messages** & **Embed Links** — feed posts and embeds
- **Manage Webhooks** — per-feed webhook posting
- **Attach Files** — map images, feed media, GIFs
- **Create Events** — calendar → Discord event sync
- **Read Message History** — map message editing
- **Use External Emojis** — feed formatting

## 📄 License

MIT © [spa1teN](https://github.com/spa1teN)

The bot's [Privacy Policy](https://tausendsassa.casparsadenius.de/privacy) and
[Terms of Service](https://tausendsassa.casparsadenius.de/terms) apply to all
users of the hosted instance.

---

<p align="center">
  <sub>Built with ❤️ using Python, discord.py, PostgreSQL, and Docker</sub>
</p>
