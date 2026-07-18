---
name: run-tausendsassa
description: Run, smoke-test, deploy, and health-check Tausendsassa (multi-guild Discord bot with feeds, calendar, map, webapp). Use when asked to run, start, restart, test, verify, or screenshot the bot, db-browser API, or webapp.
---

# Run: Tausendsassa

Multi-guild Discord bot (~84 guilds), four containers: `tausendsassa-bot`
(discord.py + API :8090), `tausendsassa-db-browser` (dashboard API :8080),
`tausendsassa-webapp` (FastAPI, **published** :8081, proxied at
`tausendsassa.casparsadenius.de`), `tausendsassa-db` (Postgres). Discord is the
main user surface — not headless-drivable; verification goes through
status.json, the two APIs, the webapp, and Postgres. Paths relative to
`/root/Tausendsassa/`.

## Smoke test (agent path — run this first)

```bash
.claude/skills/run-tausendsassa/smoke.sh            # full run (~30 s)
SKIP_UI=1 .claude/skills/run-tausendsassa/smoke.sh  # no screenshot (~10 s)
```

Checks: 4 containers, `status.json` < 120 s old, db-browser `/api/dashboard`
(parses `guild_count`), bot API avatar, webapp :8081 alive, Postgres read-only
query, webapp login-page screenshot (`/tmp/shots/ts-webapp.png`).

## Individual probes

```bash
# Aggregate stats the dashboard consumes (feeds, maps, moderation, feedback)
docker run --rm --network tausendsassa-network curlimages/curl -sf \
  http://tausendsassa-db-browser:8080/api/dashboard | python3 -m json.tool | head -30

# Webapp is the only published port
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8081/   # 307 = healthy

# Bot logs / db-browser logs
docker logs tausendsassa-bot --tail 100
docker logs tausendsassa-db-browser --tail 50
```

## Deploy (documented — NOT re-run when authoring this skill)

Restarting disconnects the bot from ~84 live guilds for a few seconds:

```bash
cd /root/Tausendsassa && docker compose up -d --build
```

After deploy: verify all cogs loaded (`docker logs tausendsassa-bot --tail 50`)
and run the smoke test — status.json freshness confirms the reporter loop.

## Gotchas

- **Webapp `/` answers 307 → `/login` when unauthenticated — that IS the healthy
  signal.** A real session needs Discord OAuth in a browser (human path:
  `https://tausendsassa.casparsadenius.de`).
- Bot API (:8090) and db-browser (:8080) have **no published ports** — docker
  network `tausendsassa-network` only. Don't confuse the two: db-browser serves
  `/api/dashboard` + feedback CRUD; the bot serves `/api/bot/*` (Discord-
  dependent lookups).
- `generated_at` in `status.json` is an ISO string, not epoch.
- Discord CV2 dashboards (`/feeds`, `/calendar`, `/map`, `/mod_dashboard`) can
  only be click-tested by a human in a test guild.
- `DATA_INTERFACE.md` is the consumer contract for the ops dashboard — change
  producer shape here first, then fix the dashboard in a separate session.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/dashboard` parse fails | Endpoint may be mid-restart; raw-curl it and check `docker logs tausendsassa-db-browser` |
| status.json stale, container up | `docker logs tausendsassa-bot` — cog exception can kill the reporter loop |
| webapp screenshot blank | Login page is minimal; if verify_png flags it, check `docker logs tausendsassa-webapp` for 500s |
