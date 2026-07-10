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
            "SELECT id, name, feed_url, channel_id, enabled, failure_count "
            "FROM feeds WHERE guild_id = $1 ORDER BY name",
            guild_id,
        )
        calendars = await conn.fetch(
            "SELECT id, ical_url, text_channel_id FROM calendars WHERE guild_id = $1",
            guild_id,
        )
        map_settings = await conn.fetchrow(
            "SELECT region, settings FROM map_settings WHERE guild_id = $1",
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

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "guild": dict(guild),
        "guild_id": guild_id,
        "feeds": [dict(f) for f in feeds],
        "calendars": [dict(c) for c in calendars],
        "map_settings": dict(map_settings) if map_settings else None,
        "pin_count": pin_count or 0,
        "mod_config": dict(mod_config) if mod_config else None,
    })


# ── Public Map Routes (no auth required) ─────────────────────────────────────

@app.get("/api/map/{guild_id}/pins")
async def map_pins_api(guild_id: int):
    """GeoJSON endpoint for all pins of a guild. Public — no login required."""
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
    })


@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Discord Activity entry point — public, no login. SDK provides guild_id at runtime."""
    return templates.TemplateResponse(request, "activity.html", {
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", ""),
    })


@app.get("/activity/api/map/{guild_id}/pins")
async def activity_map_pins_api(guild_id: int):
    """Proxy for map pins API — Discord prepends /activity to all relative paths."""
    return await map_pins_api(guild_id)


@app.get("/map/{guild_id}", response_class=HTMLResponse)
async def map_page(request: Request, guild_id: int):
    """Interactive OSM map for a guild. Public — no login required."""
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


# ── Auth helper for write routes ─────────────────────────────────────────────

async def _require_guild_access(request: Request, guild_id: int):
    """Return user or raise 401/403. Raises HTTPException on failure."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    allowed_ids = {int(g["id"]) for g in user["guilds"]}
    if guild_id not in allowed_ids and not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user


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
    max_items: int = Form(5),
    crosspost: bool = Form(False),
    embed_template: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO feeds
               (guild_id, name, feed_url, channel_id, webhook_url, username, avatar_url,
                color, max_items, crosspost, embed_template, enabled, failure_count)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,true,0)""",
            guild_id, name, feed_url, int(channel_id),
            webhook_url or None, username or None, avatar_url or None,
            color or None, max_items, crosspost, embed_template or None,
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
    max_items: int = Form(5),
    crosspost: bool = Form(False),
    embed_template: Optional[str] = Form(None),
):
    await _require_guild_access(request, guild_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE feeds SET name=$1, feed_url=$2, channel_id=$3, webhook_url=$4,
               username=$5, avatar_url=$6, color=$7, max_items=$8,
               crosspost=$9, embed_template=$10
               WHERE id=$11 AND guild_id=$12""",
            name, feed_url, int(channel_id),
            webhook_url or None, username or None, avatar_url or None,
            color or None, max_items, crosspost, embed_template or None,
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
