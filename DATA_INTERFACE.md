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

## Response-Schema

```jsonc
{
  "generated_at": "2026-07-08T22:15:32.945096",  // Server-Lokalzeit, ISO 8601

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
    "total_pins": 312
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

Alle DB-Schreibvorgänge sind in `try/except` gekapselt und dürfen die
eigentliche Bot-Funktion (Feed posten, Kalender syncen, Log-Webhook senden)
niemals blockieren oder zum Absturz bringen — ein Fehler beim Schreiben wird
nur geloggt.

**Bewusst nicht instrumentiert** (Aufwand/Nutzen unklar, siehe Zusatzvorschläge
in der Dashboard-Diskussion):
- Discord-Gateway-Latenz (`bot.latency`) — nirgends exponiert, bräuchte einen
  eigenen Live-Endpoint direkt im Bot-Prozess (dieser Endpoint läuft im
  separaten `db-browser`-Container, der nur DB-Zugriff hat, kein Zugriff auf
  den laufenden `discord.py`-Client).
- CPU/RAM-Verlaufsdaten aus `cogs/monitor.py` (`cpu_history`/`ram_history`) —
  liegen ebenfalls nur im Bot-Prozess im RAM, nicht in der DB.

## Netzwerk-Integration für `~/dashboard/`

Das separate Dashboard-Projekt läuft aktuell nur im eigenen `dashboard-network`
und hat keinen Zugriff auf `tausendsassa-network`. Um `/api/dashboard` von dort
abzufragen, muss der `dashboard`-Service in dessen `docker-compose.yml` zusätzlich
diesem Netzwerk beitreten:

```yaml
services:
  dashboard:
    networks:
      - dashboard-network
      - tausendsassa-network   # neu — für Zugriff auf tausendsassa-db-browser

networks:
  dashboard-network:
    name: dashboard-network
    driver: bridge
  tausendsassa-network:
    external: true             # existiert bereits, wird von Tausendsassa verwaltet
```

Danach ist der Endpoint aus dem `dashboard`-Container per
`http://tausendsassa-db-browser:8080/api/dashboard` erreichbar.
