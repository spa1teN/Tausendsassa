# Dashboard-Schnittstelle

Ein einzelner Endpoint, der den Live-Status aller Bot-Funktionen (Feeds, Kalender,
Karte, Moderation, Backups, Datenbank) als JSON liefert — gedacht für das externe
Ops-Dashboard unter `~/dashboard/`.

## Endpoint

```
GET http://tausendsassa-db-browser:8080/api/dashboard
```

- Läuft im `db-browser`-Container (internal FastAPI-Service, `db_browser.py`).
- **Nicht öffentlich erreichbar** — nur innerhalb des Docker-Netzwerks
  `tausendsassa-network`. Ein Consumer (z.B. `~/dashboard/`) muss diesem Netzwerk
  beitreten, um den Hostnamen `tausendsassa-db-browser` auflösen zu können.
- Kein Auth-Layer (wie die übrigen `db_browser.py`-Routen) — Schutz erfolgt rein
  über Netzwerk-Isolation, nicht über Login.
- Keine Query-Parameter, kein Request-Body. Antwort ist reines JSON (`Content-Type:
  application/json`), keine HTML-Seite.

Alle Discord-Snowflake-IDs (`guild_id`) werden als **String** ausgegeben, nicht als
Zahl — 64-Bit-IDs verlieren sonst beim Parsen in JavaScript Präzision
(`Number.MAX_SAFE_INTEGER` liegt bei ~9×10¹⁵, Snowflakes liegen bei ~1.5×10¹⁸).

## Bot-Prozess-Status (`data/status.json`)

Da der `db-browser`-Container keinen Zugriff auf den laufenden `discord.py`-Client
hat, schreibt der Bot-Prozess selbst periodisch `data/status.json` (siehe
`core/status_reporter.py`, mirror von RoaringBots gleichnamigem Modul). Das
Dashboard liest diese Datei zusätzlich zum `/api/dashboard`-Endpoint und mergt
ihren `"bot"`-Abschnitt in die Antwort (`app/tausendsassa_status.py` im
Dashboard-Projekt). Relevanter Ausschnitt:

```jsonc
{
  "bot": {
    "updated_at": "2026-07-09T12:00:00Z",
    "gateway_status": "connected",
    "loaded_cogs": ["feeds", "map", "moderation", "calendar", "help"],
    "latency_ms": 45,
    "counters": {
      "slash_commands": {"15m": 3, "1h": 45, "24h": 1200},    // Slash-Command-Ausführungen
      "interactions": {"15m": 8, "1h": 110, "24h": 2900},     // alle Interaktionen (Slash + Component)
      "component_interactions": {"15m": 5, "1h": 65, "24h": 1700},  // Button/Select
      "log_errors": {"15m": 0, "1h": 0, "24h": 1},
      "log_messages": {"15m": 8, "1h": 210, "24h": 5100}
    },
    "error_log": [                          // rollierendes Log der letzten WARNING+-Einträge
      {"at": "2026-07-09T12:00:00Z", "level": "ERROR", "logger": "tausendsassa.feeds", "message": "..."}
  }
}
```

## Response-Schema

```jsonc
{
  "generated_at": "2026-07-08T22:15:32.945096",  // Server-Lokalzeit, ISO 8601

  "stats": {
    "guild_count": 32,        // COUNT(*) FROM guilds
    "total_members": 48213    // SUM(guilds.member_count)
  },

  "feeds": {
    "guilds": [
      {
        "id": 151,                       // feeds.id (SERIAL)
        "guild_id": "1522670285281558620",
        "guild_name": "Die Grünen",
        "name": "Tagesschau",
        "enabled": true,
        "failure_count": 0,               // aufeinanderfolgende Fehlversuche seit letztem Erfolg
        "last_success": "2026-07-08T21:58:03+00:00"  // ISO 8601 oder null
      }
    ],
    "posts_per_day": [
      { "date": "2026-07-08", "count": 639 }  // letzte 7 Tage, guild-übergreifend, aus posted_entries
    ],
    "totals": { "active": 82, "disabled": 0, "in_failure": 0 }  // in_failure = failure_count > 0
  },

  "calendars": [
    {
      "id": 1,                            // calendars.id
      "guild_id": "1236376790516367392",
      "guild_name": "Uni",
      "calendar_id": "FCSP",              // benutzerdefinierter Bezeichner
      "last_sync": "2026-01-31T17:34:48.166695+00:00",  // ISO 8601 oder null
      "consecutive_sync_failures": 0       // aufeinanderfolgende iCal-Fetch-Fehler
    }
  ],

  "map": {
    "guilds": [
      {
        "guild_id": "1296491429102616676",
        "guild_name": "Die Grünen",
        "region": "world",
        "pin_count": 32,
        "last_generated": "2026-07-08T18:35:31.438688"  // mtime der neuesten PNG in cogs/map_data/{guild_id}/, oder null
      }
    ],
    "total_pins": 312,
    "region_counts": [
      { "region": "world", "guild_count": 9 }           // GROUP BY map_settings.region, absteigend
    ],
    "pins_by_country": [
      { "country_code": "de", "count": 141 }             // GROUP BY map_pins.country_code, absteigend; ISO 3166-1 alpha-2, lowercase (aus Nominatim address.country_code). Pins ohne country_code (vor der Einführung dieses Felds gesetzt) sind ausgeschlossen, nicht null gezählt.
    ]
  },

  "moderation": [
    {
      "guild_id": "1374489236215955506",
      "guild_name": "Die Grünen",
      "log_webhook_configured": true,     // moderation_config.member_log_webhook gesetzt?
      "actions_24h": 2,                   // aus moderation_log
      "actions_7d": 11
    }
  ],

  "moderation_events": [
    {
      "guild_id": "1374489236215955506",
      "guild_name": "Die Grünen",
      "action": "kick",                    // join | leave | kick | ban | unban | timeout
      "target_id": "485051896655249419",   // Discord-Snowflake als String
      "moderator_id": "485051896655249419",
      "reason": "Spam",                    // oder null
      "created_at": "2026-07-08T21:12:03.512+00:00"
    }
  ],                                       // rohe moderation_log-Zeilen, guild-übergreifend, letzte 7 Tage, aufsteigend sortiert

  "feedback": [
    {
      "guild_id": "1236376790516367392",
      "guild_name": "Uni",
      "total": 12,
      "new": 3,                             // status = 'new'
      "important": 1,                       // status = 'important'
      "in_progress": 2,                     // status = 'in_progress'
      "archived": 6                         // status = 'archived'
    }
  ],                                       // feedback table, per-guild counts by status, nur Guilds mit ≥1 Eintrag


  "analytics": {
    "page_views_today": 1391,                  // page_view events for CURRENT_DATE
    "page_views_1h": 10,                       // page_view events for current hour
    "by_type": [
      {"event_type": "page_view", "total": 1391},
      {"event_type": "map_view", "total": 42},
      {"event_type": "slash_command", "total": 315},
      {"event_type": "component_interaction", "total": 87}
    ],                                         // SUM der letzten 30 Tage, per event_type
    "alltime": [
      {"event_type": "page_view", "total": 1391}
    ]                                          // SUM aller Zeiten, gleiche Struktur wie by_type
  },
  "backups": {
    "latest_file": "dump_20260301_094502.sql.gz",  // Dateiname oder null wenn keins vorhanden
    "latest_at": "2026-03-01T09:45:03.302452",
    "age_hours": 3108.5                              // Alter des jüngsten Backups in Stunden
  },

  "database": {
    "pool_size": 1,       // aktuelle asyncpg-Poolgröße (db_browser-eigener Pool, min=1/max=5)
    "pool_idle": 1,
    "pool_max": 5,
    "db_size_mb": 18.5    // pg_database_size() der gesamten DB
  }
}
```

## Was neu instrumentiert wurde, um diese Daten live zu halten

Vorher waren `feeds.failure_count`/`last_success` unbenutzte Spalten (das
Failure-Tracking lief nur flüchtig im RAM über `core/retry_handler.py`) und es
gab keinerlei Zähler für Kalender-Sync-Fehler oder Moderationsaktionen. Damit
der Endpoint echte, aktuelle Werte liefert statt für immer bei 0/NULL zu
verharren, wurden folgende Stellen angeschlossen:

| Datei | Änderung |
|---|---|
| `db/schema.sql` | `calendars.consecutive_sync_failures` (Spalte), neue Tabelle `moderation_log` |
| `db/repositories/calendar_repository.py` | `update_last_sync()` setzt Fehlerzähler zurück; neue Methode `increment_sync_failure()` |
| `db/repositories/moderation_repository.py` | neu: `log_action()`, `get_action_counts()` |
| `cogs/feeds.py` | `_poll_single_feed()` ruft bei Erfolg/Fehlschlag `FeedRepository.reset_failure_count()` / `increment_failure_count()` — nutzt die bereits vorhandenen, bis dahin unbenutzten Repository-Methoden |
| `cogs/calendar.py` | `_sync_calendar()` ruft `increment_sync_failure()` auf, wenn der iCal-Fetch `None` liefert |
| `cogs/moderation.py` | `send_log_message()` bekommt einen `action`-Parameter und schreibt jede Moderationsaktion (join/leave/kick/ban/unban/timeout) in `moderation_log`, bevor der Discord-Webhook gesendet wird |
| `db_browser.py` | neuer Endpoint `GET /api/dashboard`, Helper `_newest_map_file_mtime()` und `_latest_backup()` |
| `docker-compose.yml` | `./backups:/app/backups:ro` in den `db-browser`-Service gemountet (für die Backup-Altersprüfung) |
| `db/schema.sql` | `map_pins.country_code` (Spalte, VARCHAR(2)) |
| `core/map_gen.py` | `geocode_location()` liest zusätzlich `address.country_code` aus der Nominatim-Antwort aus und gibt es zurück |
| `cogs/map.py` | `country_code` wird durchgereicht bis zum Pin-Insert/-Update |
| `db/repositories/map_repository.py` | `set_pin()` bekommt Parameter `country_code` |
| `db/repositories/moderation_repository.py` | neu: `get_recent_actions(hours=24)` (rohe Zeilen, guild-übergreifend — ungenutzt von `db_browser.py`, das dieselbe Query direkt fährt, siehe unten) |
| `db_browser.py` | `map.region_counts`, `map.pins_by_country`, `moderation_events` (letzte 7 Tage, guild-übergreifend) im `/api/dashboard`-Response ergänzt |
| `db/schema.sql` | neue Tabelle `feedback` (Feedback/Contact-Form-Submissions) |
| `cogs/feedback.py` | `/feedback` Slash-Command + Feedback-Modal, schreibt in `feedback`-Tabelle |
| `core/feedback_menu.py` | CV2-Menü für Subject + Anonym vor Modal-Öffnung |
| `db/repositories/feedback_repository.py` | `submit()` für das Schreiben von Feedback-Einträgen |
| `db_browser.py` | `feedback`-Key im `/api/dashboard`-Response (per-guild counts by status); `GET /api/feedback` + `PATCH /api/feedback/{id}/status` als separate Endpoints |
| `core/analytics.py` | `track_event()` UPSERT-Helfer für `analytics`-Tabelle (Pattern der Webapp-Middleware) |
| `bot.py` | `on_interaction` + `on_app_command_completion` schreiben `component_interaction` / `slash_command` in `analytics` |
| `webapp/main.py` | Middleware trackt jetzt zusätzlich `map_view` für Seiten unter `/map/{guild_id}` |
| `db_browser.py` | `GET /api/analytics/daily` (tägliche Breakdowns, kumulativ), `GET /api/analytics/totals` (all-time Summen), `analytics.alltime` im `/api/dashboard` |

**Hinweis zu `pins_by_country`:** `country_code` wird nur für Pins gesetzt, die
*nach* diesem Rollout erstellt/aktualisiert wurden — bestehende Pins bleiben
`NULL`, bis ihr Nutzer den Pin neu setzt. Kein Backfill (gleiches Vorgehen wie
bei `posted_entries.entry_link`).

Alle DB-Schreibvorgänge sind in `try/except` gekapselt und dürfen die
eigentliche Bot-Funktion (Feed posten, Kalender syncen, Log-Webhook senden)
niemals blockieren oder zum Absturz bringen — ein Fehler beim Schreiben wird
nur geloggt.

**Bewusst nicht instrumentiert** (Aufwand/Nutzen unklar, siehe Zusatzvorschläge
in der Dashboard-Diskussion):
- Discord-Gateway-Latenz (`bot.latency`) — wird nur via `status.json` exposed, kein DB-Backing.
- CPU/RAM-Verlaufsdaten aus `cogs/monitor.py` (`cpu_history`/`ram_history`) —
  liegen ebenfalls nur im Bot-Prozess im RAM, nicht in der DB.

**Neu instrumentiert (Juli 2026):**
- Slash-Commands + Component-Interactions → `analytics`-Tabelle (all-time kumulativ via `/api/analytics/daily?cumulative=true`)
- 3D-Karten-Aufrufe → `analytics`-Tabelle als `map_view` (separat von `page_view`)

## Feedback API

Für schreibende Zugriffe auf das Feedback-System (Status ändern, als gelesen
markieren, Admin-Notizen setzen) stellt `db_browser.py` zusätzliche REST-Endpoints
bereit. Alle Antworten sind `application/json`.

### Endpunkte

| Methode | Pfad | Query/Body | Antwort |
|---|---|---|---|
| `GET` | `/api/feedback` | `?guild_id=X&status=Y` (status optional) | `[{id, guild_id, guild_name, user_id, is_anonymous, subject, message, status, read, admin_note, created_at}]` |
| `GET` | `/api/feedback/unread-count` | `?guild_id=X` (required) | `{"count": 3}` |
| `PATCH` | `/api/feedback/{id}/read` | — | `{"ok": true}` |
| `PATCH` | `/api/feedback/{id}/status` | `?status=X` | `{"ok": true}` |
| `PATCH` | `/api/feedback/{id}/note` | `?note=...` | `{"ok": true}` |
| `GET` | `/api/bot/avatar` | — | `{"bot_avatar_url": "..."}` |

**Status-Werte:** `new` | `important` | `in_progress` | `archived`

**`guild_name`** wird via JOIN mit der `guilds`-Tabelle angereichert.
**User-Info (Name, Avatar)** ist im `db_browser` nicht direkt auflösbar (kein Discord-Client).
Sie wird vom Dashboard-Prozess über die Bot-API (`tausendsassa-bot:8090`) angereichert:
Der Dashboard-Proxy (`app/main.py`) ruft nach dem Feedback-Fetch `GET /api/bot/users?ids=…` auf
und merged `user_name`/`user_avatar_url` in die Antwort. Siehe Abschnitt [Bot-eigene API](#bot-eigene-api-port-8090-im-bot-prozess).

**`admin_note`** ist eine freie Text-Notiz, die das Dashboard für interne
Vermerke nutzen kann. `null` wenn keine gesetzt wurde.

## Analytics API

Die `analytics`-Tabelle speichert Event-Zähler (slash commands, component interactions,
page views, map views) als stündliche Rollups mit UPSERT. Der Bot-Prozess schreibt seit
Juli 2026 selbst in diese Tabelle (`core/analytics.py` → `bot.py:on_interaction` +
`on_app_command_completion`). Die Webapp schreibt `page_view` und `map_view`-Events
via Middleware (`webapp/main.py:95-120`).

### Endpunkte

| Methode | Pfad | Query | Antwort |
|---|---|---|---|
| `GET` | `/api/analytics/daily` | `?event_type=X&days=N&cumulative=true` | `{"slash_command": [{day, count}, …], …}` |
| `GET` | `/api/analytics/totals` | — | `[{"event_type": "slash_command", "total": 12345}, …]` |

**Query-Parameter für `/api/analytics/daily`:**
- `event_type` — Komma-separierte Filter (z.B. `slash_command,component_interaction`). Leer = alle Typen.
- `days` — 1–3650 (default 30). `3650` ≈ 10 Jahre = "all time".
- `cumulative` — `true` summiert jeden Tag auf den laufenden Gesamtwert (für kumulative Graphen).

**Event-Typen** (wachsend):
- `page_view` — Webseiten-Besuche (Middleware, seit immer)
- `map_view` — 3D-Karten-Aufrufe unter `/map/{guild_id}` (Middleware, seit Juli 2026)
- `slash_command` — Slash-Command-Ausführungen (Bot, seit Juli 2026)
- `component_interaction` — Button/Select-Menü-Interaktionen (Bot, seit Juli 2026)

**Im `/api/dashboard`-Response** ist das `analytics`-Objekt um ein `alltime`-Feld
## Bot-eigene API (Port 8090, im Bot-Prozess)

Der Bot-Prozess hostet einen eigenen aiohttp-Server auf Port **8090**
(implementiert in [`core/api_server.py`](core/api_server.py)).
Dieser hat Zugriff auf den Discord-Client (`bot.get_user()`, `bot.user`)
und kann daher User-Informationen und das Bot-Avatar auflösen.

| Methode | Pfad | Query | Antwort |
|---|---|---|---|
| `GET` | `/api/bot/avatar` | — | `{"bot_avatar_url": "https://cdn.discordapp.com/avatars/…"}` |
| `GET` | `/api/bot/user/{user_id}` | — | `{"user_name": "spa1teN", "user_avatar_url": "https://…"}` |
| `GET` | `/api/bot/users` | `?ids=1,2,3` | `{"1": {"user_name": …, "user_avatar_url": …}, …}` |

Für nicht gefundene User (User nicht im Cache / nicht in mutual Guilds)
liefern die Endpoints `"user_name": null, "user_avatar_url": null`.

**Netzwerk:** Der Bot-Container exposed Port 8090 im `tausendsassa-network`.
## Webapp Map-Endpunkte (Port 8081, öffentlich via nginx)

Die Webapp (`webapp/main.py`) stellt interaktive Karten-Seiten und GeoJSON-
Endpunkte bereit, die das Dashboard einbetten oder verlinken kann. **Alle
benötigen Discord-Login** (Session-Cookie vom OAuth2-Flow) — bis auf die
Activity-Proxy-Route, die auch Anfragen von `discord.com` / `*.discordsays.com`
zulässt.

### Seiten (HTML)

| Pfad | Auth | Beschreibung |
|---|---|---|
| `/map/all` | Login | 3D-Globus mit allen Pins aller Gilden |
| `/map/{guild_id}` | Guild-Admin | 3D-Globus mit Pins einer Gilde |
| `/map/region-density` | Login | Weltkarte mit farbigen Regions-Overlays (Verteilung der Map-Typen) |
| `/activity` | Public | Discord-Activity-Einstieg (ohne Login, SDK liefert Guild-Kontext) |

### JSON/GeoJSON

| Methode | Pfad | Auth | Beschreibung |
|---|---|---|---|
| `GET` | `/api/map/all/pins` | Login | GeoJSON FeatureCollection aller Pins aller Gilden (inkl. `guild_id`, `guild_name`) |
| `GET` | `/api/map/{guild_id}/pins` | Guild-Admin | GeoJSON FeatureCollection der Pins einer Gilde + `region`, `guild_name`, `guild_icon`, `pin_count` |
| `GET` | `/api/map/{guild_id}/pins-by-country` | Guild-Admin | `[{country_code, count}]` — aggregierte Pin-Zahlen pro Land |

### Einbindung ins Dashboard

Das Dashboard (`~/dashboard/`) kann diese Seiten per `<iframe>` oder Link
einbinden. Für `<iframe>`-Einbettung muss der Nutzer im Webapp-Tab bereits
eingeloggt sein (Session-Cookie wird vom Browser mitgesendet). Alternativ
können die Seiten als eigenständige Tabs verlinkt werden.

Beispiel: `<a href="https://tausendsassa.casparsadenius.de/map/region-density">Region Density</a>`

## Netzwerk-Integration für `~/dashboard/`

Das Dashboard-Projekt läuft im eigenen `dashboard-network` und tritt zusätzlich
dem `tausendsassa-network` bei (externes Network, `external: true`). Damit kann es:
- `tausendsassa-db-browser:8080` — DB-gestützte Daten (Feeds, Maps, Moderation, Analytics, Feedback)
- `tausendsassa-bot:8090` — Discord-abhängige Daten (Bot-Avatar, User-Namen/Avatare)

Beide Hostnamen werden über Dockers interne DNS aufgelöst. Kein Auth-Layer nötig —
Schutz erfolgt rein über Netzwerk-Isolation (keine öffentlichen Ports).

Der `db_browser`-Container mounted zusätzlich `./data:/app/data` (read-write für
Cookie-Upload) und `./backups:/app/backups:ro` (Backup-Altersprüfung).
