"""Tausendsassa Web Admin Panel.

Discord OAuth2 login + per-guild settings interface.

Run (dev):
    uvicorn webapp.main:app --host 0.0.0.0 --port 8081 --reload

Endpoints:
    /                    -> Redirect to login or guilds
    /login               -> Login page
    /auth/discord        -> Start Discord OAuth2 flow
    /auth/callback       -> OAuth2 callback
    /logout              -> Clear session
    /guilds              -> Guild selection
    /guild/{id}          -> Guild dashboard
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
WEBAPP_SECRET_KEY     = os.getenv("WEBAPP_SECRET_KEY", secrets.token_hex(32))
WEBAPP_BASE_URL       = os.getenv("WEBAPP_BASE_URL", "http://localhost:8081").rstrip("/")
BOT_OWNER_ID          = int(os.getenv("BOT_OWNER_ID", "485051896655249419"))

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "tausendsassa")
DB_USER     = os.getenv("DB_USER", "tausendsassa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
MAP_ACCESS_TOKEN    = os.getenv("MAP_ACCESS_TOKEN", "")  # shared secret for dashboard iframe embeds

DISCORD_API = "https://discord.com/api/v10"
REDIRECT_URI = f"{WEBAPP_BASE_URL}/auth/callback"
OAUTH_SCOPES = "identify guilds"

ADMINISTRATOR_PERMISSION = 0x8

# ── App Setup ────────────────────────────────────────────────────────────────
pool: Optional[asyncpg.Pool] = None
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        min_size=2, max_size=10,
    )
    yield
    if pool:
        await pool.close()


app = FastAPI(title="Tausendsassa Admin", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=WEBAPP_SECRET_KEY,
    max_age=86400 * 7,  # 7 days
    https_only=WEBAPP_BASE_URL.startswith("https"),
)

# CORS for public API endpoints (used by Discord Activity iframe on *.discordsays.com)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.discordsays\.com",
    allow_origins=["https://discord.com"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Analytics middleware ──────────────────────────────────────────────────────
import time as _time
@app.middleware("http")
async def analytics_middleware(request: Request, call_next):
    start = _time.time()
    response = await call_next(request)
    # Only count actual page loads (HTML), not API calls or static assets
    ct = response.headers.get("content-type", "")
    if response.status_code < 400 and "text/html" in ct and "/static/" not in request.url.path:
        try:
            if pool:
                async with pool.acquire() as conn:
                    # General page_view
                    await conn.execute("""
                        INSERT INTO analytics (event_type, source, count, day, hour)
                        VALUES ('page_view', 'web', 1, CURRENT_DATE, EXTRACT(HOUR FROM NOW()))
                        ON CONFLICT (event_type, guild_id, source, day, hour)
                        DO UPDATE SET count = analytics.count + 1
                    """)
                    # Specific event type for 3D map views
                    if "/map/" in request.url.path:
                        await conn.execute("""
                            INSERT INTO analytics (event_type, source, count, day, hour)
                            VALUES ('map_view', 'web', 1, CURRENT_DATE, EXTRACT(HOUR FROM NOW()))
                            ON CONFLICT (event_type, guild_id, source, day, hour)
                            DO UPDATE SET count = analytics.count + 1
                        """)
        except Exception:
            pass  # never fail a request because of analytics
    return response

try:
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
    # Discord Activity proxy prepends /activity to all relative paths
    app.mount("/activity/static", StaticFiles(directory=str(BASE / "static")), name="activity_static")
except RuntimeError:
    pass  # static dir not populated yet


# ── Helpers ──────────────────────────────────────────────────────────────────

async def get_bot_guild_ids() -> set[int]:
    """Return all guild IDs the bot is present in (from DB)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM guilds")
        return {int(r["id"]) for r in rows}


def has_admin_permission(permissions: int) -> bool:
    return bool(permissions & ADMINISTRATOR_PERMISSION)


def guild_icon_url(guild_id: str, icon_hash: Optional[str]) -> Optional[str]:
    if not icon_hash:
        return None
    ext = "gif" if icon_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}"


def user_avatar_url(user_id: str, avatar_hash: Optional[str]) -> str:
    if not avatar_hash:
        discriminator = int(user_id) % 5
        return f"https://cdn.discordapp.com/embed/avatars/{discriminator}.png"
    ext = "gif" if avatar_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}"


# Register helpers as template globals
templates.env.globals["guild_icon_url"] = guild_icon_url
templates.env.globals["user_avatar_url"] = user_avatar_url

BOT_API_BASE = os.getenv("BOT_API_BASE", "http://tausendsassa-bot:8090")


async def _fetch_bot_api(path: str) -> list[dict] | dict | None:
    """Fetch data from the bot's internal API. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BOT_API_BASE}{path}")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/guilds")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/guilds")
    error = request.query_params.get("error")
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.get("/auth/discord")
async def auth_discord(request: Request):
    """Redirect user to Discord OAuth2 authorization page."""
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    url = (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={OAUTH_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Discord OAuth2 callback, establish session."""
    if error:
        return RedirectResponse("/login?error=access_denied")
    if not code:
        return RedirectResponse("/login?error=no_code")

    expected_state = request.session.pop("oauth_state", None)
    if not state or state != expected_state:
        return RedirectResponse("/login?error=invalid_state")

    async with httpx.AsyncClient() as client:
        # 1. Exchange authorization code for access token
        token_resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse("/login?error=token_exchange_failed")

        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Fetch user identity
        user_resp = await client.get(f"{DISCORD_API}/users/@me", headers=headers)
        if user_resp.status_code != 200:
            return RedirectResponse("/login?error=user_fetch_failed")
        user_data = user_resp.json()

        # 3. Fetch user's guild list
        guilds_resp = await client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)
        if guilds_resp.status_code != 200:
            return RedirectResponse("/login?error=guilds_fetch_failed")
        guilds_data = guilds_resp.json()

    user_id = int(user_data["id"])
    is_owner = user_id == BOT_OWNER_ID

    # Filter to guilds where user is admin AND bot is present
    bot_guild_ids = await get_bot_guild_ids()
    admin_guilds = []
    for g in guilds_data:
        gid = int(g["id"])
        perms = int(g.get("permissions", 0))
        if (is_owner or has_admin_permission(perms)) and gid in bot_guild_ids:
            admin_guilds.append({
                "id": g["id"],
                "name": g["name"],
                "icon": g.get("icon"),
            })

    if not admin_guilds and not is_owner:
        return RedirectResponse("/login?error=no_admin_guilds")

    request.session["user"] = {
        "id": str(user_data["id"]),
        "username": user_data["username"],
        "avatar": user_data.get("avatar"),
        "is_owner": is_owner,
        "guilds": admin_guilds,
    }
    return RedirectResponse("/guilds")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/guilds", response_class=HTMLResponse)
async def guild_select(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "guild_select.html", {
        "user": user,
        "guilds": user["guilds"],
    })


@app.get("/guild/{guild_id}", response_class=HTMLResponse)
async def dashboard(request: Request, guild_id: int):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")

    allowed_ids = {int(g["id"]) for g in user["guilds"]}
    if guild_id not in allowed_ids and not user["is_owner"]:
        raise HTTPException(status_code=403, detail="Access denied")

    async with pool.acquire() as conn:
        guild = await conn.fetchrow("SELECT * FROM guilds WHERE id = $1", guild_id)
        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        feeds = await conn.fetch(
            "SELECT id, name, feed_url, channel_id, webhook_url, username, "
            "avatar_url, color, enabled, failure_count "
            "FROM feeds WHERE guild_id = $1 ORDER BY name",
            guild_id,
        )
        calendars = await conn.fetch(
            "SELECT id, ical_url, text_channel_id, voice_channel_id, "
            "reminder_role_id, blacklist, whitelist "
            "FROM calendars WHERE guild_id = $1",
            guild_id,
        )
        map_settings = await conn.fetchrow(
            "SELECT region, channel_id, settings FROM map_settings WHERE guild_id = $1",
            guild_id,
        )
        pin_count = await conn.fetchval(
            "SELECT COUNT(*) FROM map_pins WHERE guild_id = $1",
            guild_id,
        )
        mod_config = await conn.fetchrow(
            "SELECT member_log_webhook, join_role_id FROM moderation_config WHERE guild_id = $1",
            guild_id,
        )
        tz_row = await conn.fetchrow(
            "SELECT timezone FROM guild_timezones WHERE guild_id = $1",
            guild_id,
        )
        monitor_row = await conn.fetchrow(
            "SELECT channel_id FROM feed_monitor_channels WHERE guild_id = $1",
            guild_id,
        )

        # Moderation log + stats
        mod_log = await conn.fetch(
            "SELECT action, target_id, moderator_id, reason, created_at "
            "FROM moderation_log WHERE guild_id = $1 "
            "ORDER BY created_at DESC LIMIT 100",
            guild_id,
        )
        mod_stats = await conn.fetchrow(
            "SELECT "
            "  COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as actions_24h, "
            "  COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as actions_7d, "
            "  COUNT(*) FILTER (WHERE action='ban' AND created_at > NOW() - INTERVAL '7 days') as bans_7d, "
            "  COUNT(*) FILTER (WHERE action='kick' AND created_at > NOW() - INTERVAL '7 days') as kicks_7d, "
            "  COUNT(*) FILTER (WHERE action='timeout' AND created_at > NOW() - INTERVAL '7 days') as timeouts_7d, "
            "  COUNT(*) FILTER (WHERE action='join' AND created_at > NOW() - INTERVAL '7 days') as joins_7d, "
            "  COUNT(*) FILTER (WHERE action='leave' AND created_at > NOW() - INTERVAL '7 days') as leaves_7d "
            "FROM moderation_log WHERE guild_id = $1",
            guild_id,
        )

        # Feedback for this guild
        feedback_rows = await conn.fetch(
            "SELECT id, user_id, is_anonymous, subject, message, status, read, admin_note, created_at "
            "FROM feedback WHERE guild_id = $1 "
            "ORDER BY created_at DESC LIMIT 50",
            guild_id,
        )
        feedback_unread = await conn.fetchval(
            "SELECT COUNT(*) FROM feedback WHERE guild_id = $1 AND NOT read", guild_id,
        )
        # Top countries by pin count for this guild
        top_countries = await conn.fetch(
            "SELECT country_code, COUNT(*) as cnt FROM map_pins "
            "WHERE guild_id = $1 AND country_code IS NOT NULL "
            "GROUP BY country_code ORDER BY cnt DESC LIMIT 10",
            guild_id,
        )

    timezone = tz_row["timezone"] if tz_row else "Europe/Berlin"
    monitor_channel_id = str(monitor_row["channel_id"]) if monitor_row else None

    # Fetch Discord-side data from bot API (drops gracefully if bot unreachable)
    bot_channels = await _fetch_bot_api(f"/api/bot/guild/{guild_id}/channels") or []
    bot_voice_channels = await _fetch_bot_api(f"/api/bot/guild/{guild_id}/voice-channels") or []
    bot_roles = await _fetch_bot_api(f"/api/bot/guild/{guild_id}/roles") or []
    bot_webhooks = await _fetch_bot_api(f"/api/bot/guild/{guild_id}/webhooks") or []

    # ID sets for stale-reference checking in dropdowns
    channel_id_set = {ch["id"] for ch in bot_channels}
    voice_channel_id_set = {ch["id"] for ch in bot_voice_channels}
    role_id_set = {r["id"] for r in bot_roles}
    webhook_url_set = {wh["url"] for wh in bot_webhooks}

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "guild": dict(guild),
        "guild_id": guild_id,
        "feeds": [dict(f) for f in feeds],
        "calendars": [dict(c) for c in calendars],
        "map_settings": dict(map_settings) if map_settings else None,
        "pin_count": pin_count or 0,
        "mod_config": dict(mod_config) if mod_config else None,
        "bot_channels": bot_channels,
        "bot_voice_channels": bot_voice_channels,
        "bot_roles": bot_roles,
        "bot_webhooks": bot_webhooks,
        "channel_id_set": channel_id_set,
        "voice_channel_id_set": voice_channel_id_set,
        "role_id_set": role_id_set,
        "webhook_url_set": webhook_url_set,
        "timezone": timezone,
        "timezones": COMMON_TIMEZONES,
        "monitor_channel_id": monitor_channel_id,
        "mod_log": [dict(r) for r in mod_log],
        "mod_stats": dict(mod_stats) if mod_stats else {},
        "feedback_rows": [dict(r) for r in feedback_rows],
        "feedback_unread": feedback_unread or 0,
        "top_countries": [dict(r) for r in top_countries],
    })


# ── Public Map Routes (no auth required) ─────────────────────────────────────

@app.get("/api/map/{guild_id}/pins-by-country")
async def map_pins_by_country(guild_id: int):
    """Aggregated pin counts per country for choropleth maps."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT country_code, COUNT(*) as cnt FROM map_pins "
            "WHERE guild_id = $1 AND country_code IS NOT NULL "
            "GROUP BY country_code ORDER BY cnt DESC",
            guild_id,
        )
    return JSONResponse([
        {"country_code": r["country_code"], "count": r["cnt"]} for r in rows
    ])

@app.get("/api/map/all/pins")
async def map_all_pins_api(request: Request):
    """GeoJSON endpoint for all pins across ALL guilds. Requires login."""
    _require_login(request)
    async with pool.acquire() as conn:
        pins = await conn.fetch(
            "SELECT p.user_id, p.username, p.display_name, p.latitude, p.longitude, "
            "p.color, p.avatar_hash, p.guild_id, g.name as guild_name "
            "FROM map_pins p JOIN guilds g ON p.guild_id = g.id"
        )

    import json as _json

    features = []
    for pin in pins:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(pin["longitude"]), float(pin["latitude"])],
            },
            "properties": {
                "name": pin["display_name"] or pin["username"],
                "username": pin["username"],
                "color": pin["color"] or "#FF4444",
                "avatar_hash": pin["avatar_hash"],
                "user_id": str(pin["user_id"]),
                "guild_id": str(pin["guild_id"]),
                "guild_name": pin["guild_name"],
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@app.get("/map/all", response_class=HTMLResponse)
async def map_all_page(request: Request):
    """Interactive globe showing all pins from all guilds. Requires login."""
    _require_login(request)
    async with pool.acquire() as conn:
        total_pins = await conn.fetchval("SELECT COUNT(*) FROM map_pins")

    return templates.TemplateResponse(request, "map.html", {
        "guild_id": "all",
        "guild_name": "Alle Server",
        "guild_icon": None,
        "region": "world",
        "pin_count": total_pins or 0,
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", ""),
    })


@app.get("/api/map/{guild_id}/pins")
async def map_pins_api(request: Request, guild_id: int):
    """GeoJSON endpoint for all pins of a guild. Public — no auth needed."""
    # No auth — guild-specific maps are public
    async with pool.acquire() as conn:
        pins = await conn.fetch(
            "SELECT user_id, username, display_name, latitude, longitude, color, avatar_hash "
            "FROM map_pins WHERE guild_id = $1",
            guild_id,
        )
        settings_row = await conn.fetchrow(
            "SELECT region, settings FROM map_settings WHERE guild_id = $1",
            guild_id,
        )
        guild = await conn.fetchrow("SELECT name, icon_hash FROM guilds WHERE id = $1", guild_id)

    import json as _json

    features = []
    for pin in pins:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(pin["longitude"]), float(pin["latitude"])],
            },
            "properties": {
                "name": pin["display_name"] or pin["username"],
                "username": pin["username"],
                "color": pin["color"] or "#FF4444",
                "avatar_hash": pin["avatar_hash"],
                "user_id": str(pin["user_id"]),
            },
        })

    settings = {}
    if settings_row and settings_row["settings"]:
        try:
            settings = _json.loads(settings_row["settings"])
        except Exception:
            pass

    return JSONResponse({
        "type": "FeatureCollection",
        "features": features,
        "guild_name": guild["name"] if guild else str(guild_id),
        "guild_icon": guild_icon_url(str(guild_id), guild["icon_hash"]) if guild else None,
        "region": settings_row["region"] if settings_row else "world",
        "settings": settings,
        "pin_count": len(features),
    })


@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Discord Activity entry point — public, no login. SDK provides guild_id at runtime."""
    return templates.TemplateResponse(request, "activity.html", {
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", ""),
    })


@app.get("/activity/api/map/{guild_id}/pins")
async def activity_map_pins_api(request: Request, guild_id: int):
    """Proxy for map pins API — Discord prepends /activity to all relative paths."""
    if not _is_discord_activity(request):
        await _require_guild_access(request, guild_id)
    return await map_pins_api(request, guild_id)


@app.get("/map/region-density", response_class=HTMLResponse)
async def map_region_density(request: Request):
    """Map showing how many guilds use each region type. Requires login."""
    _require_login(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT region, COUNT(*) as guild_count "
            "FROM map_settings GROUP BY region ORDER BY guild_count DESC"
        )
    region_counts = [
        {"region": r["region"], "label": REGION_LABELS.get(r["region"], r["region"]),
         "guild_count": r["guild_count"]}
        for r in rows
    ]
    total = sum(r["guild_count"] for r in region_counts)

    return templates.TemplateResponse(request, "region-density.html", {
        "region_counts": region_counts,
        "total_guilds": total,
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", ""),
    })


@app.get("/map/{guild_id}", response_class=HTMLResponse)
async def map_page(request: Request, guild_id: int):
    """Interactive map for a guild. Public — no auth needed."""
    # No auth — guild-specific maps are public
    async with pool.acquire() as conn:
        guild = await conn.fetchrow("SELECT name, icon_hash FROM guilds WHERE id = $1", guild_id)
        settings_row = await conn.fetchrow(
            "SELECT region, settings FROM map_settings WHERE guild_id = $1",
            guild_id,
        )
        pin_count = await conn.fetchval(
            "SELECT COUNT(*) FROM map_pins WHERE guild_id = $1",
            guild_id,
        )

    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    return templates.TemplateResponse(request, "map.html", {
        "guild_id": guild_id,
        "guild_name": guild["name"],
        "guild_icon": guild_icon_url(str(guild_id), guild["icon_hash"]),
        "region": settings_row["region"] if settings_row else "world",
        "pin_count": pin_count or 0,
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", ""),
    })


# ── Region density map ─────────────────────────────────────────────────────

REGION_LABELS = {
    "world": "🌍 World", "europe": "🇪🇺 Europe", "germany": "🇩🇪 Germany",
    "france": "🇫🇷 France", "spain": "🇪🇸 Spain", "italy": "🇮🇹 Italy",
    "poland": "🇵🇱 Poland", "netherlands": "🇳🇱 Netherlands", "belgium": "🇧🇪 Belgium",
    "switzerland": "🇨🇭 Switzerland", "sweden": "🇸🇪 Sweden", "russia": "🇷🇺 Russia",
    "ukraine": "🇺🇦 Ukraine", "unitedkingdom": "🇬🇧 UK",
    "asia": "🌏 Asia", "japan": "🇯🇵 Japan", "southkorea": "🇰🇷 South Korea",
    "northamerica": "🌎 North America", "usmainland": "🇺🇸 US Mainland",
    "canada": "🇨🇦 Canada", "mexico": "🇲🇽 Mexico",
    "southamerica": "🌎 South America", "brazil": "🇧🇷 Brazil",
    "africa": "🌍 Africa", "australia": "🇦🇺 Australia",
    "austria": "🇦🇹 Austria", "czech": "🇨🇿 Czechia", "hungary": "🇭🇺 Hungary",
    "portugal": "🇵🇹 Portugal", "greece": "🇬🇷 Greece", "norway": "🇳🇴 Norway",
    "denmark": "🇩🇰 Denmark", "finland": "🇫🇮 Finland", "romania": "🇷🇴 Romania",
    "bulgaria": "🇧🇬 Bulgaria", "croatia": "🇭🇷 Croatia", "slovenia": "🇸🇮 Slovenia",
    "slovakia": "🇸🇰 Slovakia", "ireland": "🇮🇪 Ireland",
    "lithuania": "🇱🇹 Lithuania", "latvia": "🇱🇻 Latvia", "estonia": "🇪🇪 Estonia",
    "luxembourg": "🇱🇺 Luxembourg", "malta": "🇲🇹 Malta", "cyprus": "🇨🇾 Cyprus",
    "turkey": "🇹🇷 Turkey",
}


# ── Auth helper for write routes ─────────────────────────────────────────────

def _has_access_token(request: Request) -> bool:
    """Check for shared secret token (query param or header) for dashboard iframe embeds."""
    if not MAP_ACCESS_TOKEN:
        return False
    token = request.query_params.get("token") or request.headers.get("X-Map-Access-Token", "")
    return token == MAP_ACCESS_TOKEN


def _require_login(request: Request):
    """Return user dict or raise 401. Bypassed by valid MAP_ACCESS_TOKEN."""
    if _has_access_token(request):
        return {"username": "dashboard", "guilds": [], "is_owner": True}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


async def _require_guild_access(request: Request, guild_id: int):
    """Return user or raise 401/403. Bypassed by valid MAP_ACCESS_TOKEN."""
    if _has_access_token(request):
        return {"username": "dashboard", "guilds": [], "is_owner": True}
    user = _require_login(request)
    allowed_ids = {int(g["id"]) for g in user["guilds"]}
    if guild_id not in allowed_ids and not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user


def _is_discord_activity(request: Request) -> bool:
    """Check if request originates from a Discord Activity iframe."""
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    return any(d in origin or d in referer
               for d in ("discord.com", "discordsays.com"))


# ── Feed CRUD routes ──────────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/feeds")
async def feed_create(
    request: Request,
    guild_id: int,
    name: str = Form(...),
    feed_url: str = Form(...),
    channel_id: str = Form(...),
    webhook_url: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    avatar_url: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO feeds
               (guild_id, name, feed_url, channel_id, webhook_url, username, avatar_url,
                color, enabled, failure_count)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,0)""",
            guild_id, name, feed_url, int(channel_id),
            webhook_url or None, username or None, avatar_url or None,
            color or None,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/feeds/{feed_id}/update")
async def feed_update(
    request: Request,
    guild_id: int,
    feed_id: int,
    name: str = Form(...),
    feed_url: str = Form(...),
    channel_id: str = Form(...),
    webhook_url: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    avatar_url: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE feeds SET name=$1, feed_url=$2, channel_id=$3, webhook_url=$4,
               username=$5, avatar_url=$6, color=$7
               WHERE id=$8 AND guild_id=$9""",
            name, feed_url, int(channel_id),
            webhook_url or None, username or None, avatar_url or None,
            color or None,
            feed_id, guild_id,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/feeds/{feed_id}/delete")
async def feed_delete(request: Request, guild_id: int, feed_id: int):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM feeds WHERE id=$1 AND guild_id=$2", feed_id, guild_id
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/feeds/{feed_id}/toggle")
async def feed_toggle(request: Request, guild_id: int, feed_id: int):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE feeds SET enabled = NOT enabled WHERE id=$1 AND guild_id=$2",
            feed_id, guild_id,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Calendar CRUD routes ──────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/calendars")
async def calendar_create(
    request: Request,
    guild_id: int,
    ical_url: str = Form(...),
    text_channel_id: Optional[str] = Form(None),
    voice_channel_id: Optional[str] = Form(None),
    reminder_role_id: Optional[str] = Form(None),
    blacklist: Optional[str] = Form(None),
    whitelist: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO calendars
               (guild_id, ical_url, text_channel_id, voice_channel_id, reminder_role_id,
                blacklist, whitelist)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            guild_id, ical_url,
            int(text_channel_id) if text_channel_id else None,
            int(voice_channel_id) if voice_channel_id else None,
            int(reminder_role_id) if reminder_role_id else None,
            blacklist or None, whitelist or None,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/calendars/{cal_id}/update")
async def calendar_update(
    request: Request,
    guild_id: int,
    cal_id: int,
    ical_url: str = Form(...),
    text_channel_id: Optional[str] = Form(None),
    voice_channel_id: Optional[str] = Form(None),
    reminder_role_id: Optional[str] = Form(None),
    blacklist: Optional[str] = Form(None),
    whitelist: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE calendars SET ical_url=$1, text_channel_id=$2,
               voice_channel_id=$3, reminder_role_id=$4, blacklist=$5, whitelist=$6
               WHERE id=$7 AND guild_id=$8""",
            ical_url,
            int(text_channel_id) if text_channel_id else None,
            int(voice_channel_id) if voice_channel_id else None,
            int(reminder_role_id) if reminder_role_id else None,
            blacklist or None, whitelist or None,
            cal_id, guild_id,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/calendars/{cal_id}/delete")
async def calendar_delete(request: Request, guild_id: int, cal_id: int):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM calendars WHERE id=$1 AND guild_id=$2", cal_id, guild_id
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Map settings route ────────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/map/settings")
async def map_settings_update(
    request: Request,
    guild_id: int,
    region: str = Form(...),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO map_settings (guild_id, region)
               VALUES ($1,$2)
               ON CONFLICT (guild_id) DO UPDATE SET region=$2""",
            guild_id, region,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


@app.post("/guild/{guild_id}/map/delete")
async def map_delete(request: Request, guild_id: int):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM map_settings WHERE guild_id=$1", guild_id
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Feed URL validation ─────────────────────────────────────────────────────

@app.post("/api/validate/feed-url")
async def validate_feed_url(request: Request):
    """Validate a feed URL — checks reachability and content type."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"valid": False, "error": "Invalid JSON"}, status_code=400)
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"valid": False, "error": "URL required"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Tausendsassa/1.0 (Feed Validator)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            })
        content_type = resp.headers.get("content-type", "")
        is_xml = any(t in content_type for t in ("xml", "rss", "atom"))
        return JSONResponse({
            "valid": resp.status_code < 400,
            "status": resp.status_code,
            "content_type": content_type,
            "is_feed": is_xml or ".xml" in url or "/feed" in url or "/rss" in url,
        })
    except Exception as e:
        return JSONResponse({"valid": False, "error": str(e)[:200]})


# ── Privacy & Terms ──────────────────────────────────────────────────────────

import re as _re

def _simple_md_to_html(text: str) -> str:
    """Minimal markdown → HTML: headers, bold, links, lists, paragraphs."""
    out = []
    in_list = None  # None, "ul", or "ol"
    for line in text.split("\n"):
        # Bold
        line = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        # Inline links [text](url)
        line = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" class="text-discord hover:underline">\1</a>', line)
        # H2
        if line.startswith("## "):
            if in_list:
                out.append(f"</{in_list}>")
                in_list = None
            out.append(f'<h2 class="text-xl font-semibold text-white mt-8 mb-3">{line[3:]}</h2>')
        # H1
        elif line.startswith("# "):
            if in_list:
                out.append(f"</{in_list}>")
                in_list = None
            out.append(f'<h1 class="text-2xl font-bold text-white mt-6 mb-4">{line[2:]}</h1>')
        # Unordered list
        elif line.startswith("- "):
            if in_list != "ul":
                if in_list:
                    out.append(f"</{in_list}>")
                out.append('<ul class="list-disc pl-5 space-y-1 text-text-2 mb-3">')
                in_list = "ul"
            out.append(f"<li>{line[2:]}</li>")
        # Numbered list
        elif _re.match(r"^\d+\. ", line):
            if in_list != "ol":
                if in_list:
                    out.append(f"</{in_list}>")
                out.append('<ol class="list-decimal pl-5 space-y-1 text-text-2 mb-3">')
                in_list = "ol"
            list_text = _re.sub(r"^\d+\. ", "", line)
            out.append(f"<li>{list_text}</li>")
        # Empty line
        elif line.strip() == "":
            if in_list:
                out.append(f"</{in_list}>")
                in_list = None
        # Paragraph
        else:
            if in_list:
                out.append(f"</{in_list}>")
                in_list = None
            out.append(f'<p class="text-text-2 mb-3">{line}</p>')
    if in_list:
        out.append(f"</{in_list}>")
    return "\n".join(out)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    from webapp.legal import PRIVACY_POLICY
    return templates.TemplateResponse(request, "privacy.html", {
        "title": "Privacy Policy",
        "content_html": _simple_md_to_html(PRIVACY_POLICY),
    })


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    from webapp.legal import TERMS_OF_SERVICE
    return templates.TemplateResponse(request, "terms.html", {
        "title": "Terms of Service",
        "content_html": _simple_md_to_html(TERMS_OF_SERVICE),
    })


# ── Guild timezone ──────────────────────────────────────────────────────────

COMMON_TIMEZONES = [
    "Europe/Berlin", "Europe/London", "Europe/Paris", "Europe/Madrid",
    "Europe/Rome", "Europe/Warsaw", "Europe/Amsterdam", "Europe/Brussels",
    "Europe/Vienna", "Europe/Stockholm", "Europe/Zurich", "Europe/Moscow",
    "Europe/Kiev", "Europe/Istanbul",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "America/Vancouver", "America/Mexico_City",
    "America/Sao_Paulo", "America/Buenos_Aires",
    "Asia/Tokyo", "Asia/Seoul", "Asia/Shanghai", "Asia/Hong_Kong",
    "Asia/Singapore", "Asia/Kolkata", "Asia/Dubai", "Asia/Jerusalem",
    "Australia/Sydney", "Australia/Melbourne",
    "Pacific/Auckland", "Africa/Cairo", "Africa/Johannesburg",
    "UTC",
]

@app.post("/guild/{guild_id}/timezone")
async def timezone_update(
    request: Request,
    guild_id: int,
    timezone: str = Form(...),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO guild_timezones (guild_id, timezone)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET timezone=$2""",
            guild_id, timezone,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Feed monitor channel ────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/monitor-channel")
async def monitor_channel_update(
    request: Request,
    guild_id: int,
    channel_id: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        if channel_id:
            await conn.execute(
                """INSERT INTO feed_monitor_channels (guild_id, channel_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET channel_id=$2""",
                guild_id, int(channel_id),
            )
        else:
            await conn.execute(
                "DELETE FROM feed_monitor_channels WHERE guild_id=$1", guild_id,
            )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Map channel ─────────────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/map/channel")
async def map_channel_update(
    request: Request,
    guild_id: int,
    channel_id: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE map_settings SET channel_id=$1 WHERE guild_id=$2",
            int(channel_id) if channel_id else None, guild_id,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Feedback management ─────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/feedback/{feedback_id}/status")
async def feedback_status_update(
    request: Request,
    guild_id: int,
    feedback_id: int,
    status: str = Form(...),
    admin_note: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE feedback SET status=$1, admin_note=$2, read=true WHERE id=$3 AND guild_id=$4",
            status, admin_note or None, feedback_id, guild_id,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)


# ── Moderation route ──────────────────────────────────────────────────────────

@app.post("/guild/{guild_id}/moderation")
async def moderation_update(
    request: Request,
    guild_id: int,
    member_log_webhook: Optional[str] = Form(None),
    join_role_id: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO moderation_config (guild_id, member_log_webhook, join_role_id)
               VALUES ($1,$2,$3)
               ON CONFLICT (guild_id) DO UPDATE
               SET member_log_webhook=$2, join_role_id=$3""",
            guild_id,
            member_log_webhook or None,
            int(join_role_id) if join_role_id else None,
        )
    return RedirectResponse(f"/guild/{guild_id}", status_code=303)
