#!/bin/bash
# Read-only smoke test for Tausendsassa (multi-guild Discord bot).
# Does NOT restart anything — the bot serves ~84 guilds live.
#
# Four containers: tausendsassa-bot (+API :8090), tausendsassa-db-browser
# (dashboard API :8080), tausendsassa-webapp (published :8081), tausendsassa-db.
#
#   .claude/skills/run-tausendsassa/smoke.sh            # full run (~30 s)
#   SKIP_UI=1 .claude/skills/run-tausendsassa/smoke.sh  # no screenshot (~10 s)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
FAIL=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAIL=1; }

# 1. containers
for c in tausendsassa-bot tausendsassa-db-browser tausendsassa-webapp tausendsassa-db; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = true ] \
    && pass "container $c running" || fail "container $c running"
done

# 2. status.json freshness (ISO string; dashboard rule: >120 s = down)
AGE=$(python3 - <<'EOF'
import json, datetime
d = json.load(open('/root/Tausendsassa/data/status.json'))
ts = datetime.datetime.fromisoformat(d['generated_at'])
if ts.tzinfo is None: ts = ts.replace(tzinfo=datetime.timezone.utc)
print(int((datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()))
EOF
)
if [ -n "${AGE:-}" ] && [ "$AGE" -lt 120 ] 2>/dev/null; then
  pass "status.json fresh (${AGE}s old)"
else
  fail "status.json stale (age: '${AGE:-unreadable}', limit 120 s)"
fi

# 3. internal APIs via tausendsassa-network (no published ports)
CURL="docker run --rm --network tausendsassa-network curlimages/curl -sf -m 15"
GC=$($CURL "http://tausendsassa-db-browser:8080/api/dashboard" 2>/dev/null \
     | python3 -c "import json,sys; print(json.load(sys.stdin)['stats']['guild_count'])" 2>/dev/null)
case "$GC" in
  ''|*[!0-9]*) fail "db-browser /api/dashboard (guild_count: '$GC')" ;;
  *)           pass "db-browser /api/dashboard: $GC guilds" ;;
esac
$CURL -o /dev/null "http://tausendsassa-bot:8090/api/bot/avatar" \
  && pass "bot API /api/bot/avatar" || fail "bot API /api/bot/avatar"

# 4. webapp — the ONLY published port (:8081). 307 -> /login is the healthy
#    unauthenticated response (Discord OAuth behind it).
CODE=$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://localhost:8081/)
if [ "$CODE" = 307 ] || [ "$CODE" = 200 ]; then
  pass "webapp :8081 alive (HTTP $CODE)"
else
  fail "webapp :8081 (HTTP $CODE)"
fi

# 5. Postgres read-only query
N=$(docker exec tausendsassa-db psql -U tausendsassa -d tausendsassa -tAc \
  "select count(*) from feeds;" 2>/dev/null)
case "$N" in
  ''|*[!0-9]*) fail "postgres query (got: '$N')" ;;
  *)           pass "postgres query: $N feed rows" ;;
esac

# 6. webapp login page renders
if [ "${SKIP_UI:-0}" != 1 ]; then
  mkdir -p /tmp/shots && chmod 777 /tmp/shots   # chrome runs as uid 1000
  docker run --rm --network tausendsassa-network -v /tmp/shots:/out zenika/alpine-chrome \
    --no-sandbox --headless --disable-gpu --hide-scrollbars \
    --window-size=1400,900 --virtual-time-budget=10000 \
    --screenshot=/out/ts-webapp.png http://tausendsassa-webapp:8081/ >/dev/null 2>&1
  python3 "$HERE/verify_png.py" /tmp/shots/ts-webapp.png \
    && pass "webapp screenshot non-blank -> /tmp/shots/ts-webapp.png" \
    || fail "webapp screenshot non-blank"
fi

# 7. recent log errors (informational)
ERR=$(docker logs tausendsassa-bot --since 1h 2>&1 | grep -ciE 'ERROR|Traceback' || true)
echo "info  ERROR/Traceback lines in last hour of bot logs: $ERR"

if [ "$FAIL" = 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$FAIL"
