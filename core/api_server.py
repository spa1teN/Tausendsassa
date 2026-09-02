"""Lightweight aiohttp API server for Dashboard user/bot lookups.

Shares the bot's asyncio event loop. Exposes Discord-dependent endpoints
that db_browser (separate container) cannot serve. See DATA_INTERFACE.md.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import discord
from aiohttp import web

log = logging.getLogger("tausendsassa.api")

# ── Simple in-memory cache ───────────────────────────────────────────────

_guild_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 60  # seconds


def _cache_get(key: str) -> Any | None:
    entry = _guild_cache.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _guild_cache[key] = (time.time(), value)


# ── Helpers ──────────────────────────────────────────────────────────────

def _user_info(bot: Any, user_id: int) -> dict[str, str | None]:
    """Look up user name + avatar URL from Discord. Returns None values on miss."""
    try:
        user = bot.get_user(user_id)
        if user is None:
            return {"user_name": None, "user_avatar_url": None}
        name = user.display_name or user.name
        avatar = str(user.avatar.url) if user.avatar else str(user.default_avatar.url)
        return {"user_name": name, "user_avatar_url": avatar}
    except Exception:
        return {"user_name": None, "user_avatar_url": None}


def _bot_avatar(bot: Any) -> str | None:
    """Return the bot's avatar URL, or None."""
    try:
        if bot.user and bot.user.avatar:
            return str(bot.user.avatar.url)
    except Exception:
        pass
    return None


def _guild_data(bot: Any, guild_id: int) -> dict | None:
    """Get basic guild info."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": str(guild.icon.url) if guild.icon else None,
        "member_count": guild.member_count,
        "channels_count": len(guild.channels),
        "roles_count": len(guild.roles),
    }


def _guild_channels(bot: Any, guild_id: int) -> list[dict] | None:
    """List text channels for a guild."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    channels = []
    for ch in guild.text_channels:
        channels.append({
            "id": str(ch.id),
            "name": ch.name,
            "category": ch.category.name if ch.category else None,
            "position": ch.position,
        })
    channels.sort(key=lambda c: c["position"])
    return channels


def _guild_voice_channels(bot: Any, guild_id: int) -> list[dict] | None:
    """List voice channels for a guild."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    channels = []
    for ch in guild.voice_channels:
        channels.append({
            "id": str(ch.id),
            "name": ch.name,
            "category": ch.category.name if ch.category else None,
            "position": ch.position,
        })
    channels.sort(key=lambda c: c["position"])
    return channels


def _guild_roles(bot: Any, guild_id: int) -> list[dict] | None:
    """List roles for a guild."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    roles = []
    for role in guild.roles:
        if role.is_default():  # skip @everyone
            continue
        roles.append({
            "id": str(role.id),
            "name": role.name,
            "color": role.color.value,
            "position": role.position,
            "managed": role.managed,
        })
    roles.sort(key=lambda r: r["position"], reverse=True)
    return roles


# ── Route handlers ───────────────────────────────────────────────────────

async def handle_bot_avatar(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    return web.json_response({"bot_avatar_url": _bot_avatar(bot)})


async def handle_user_info(request: web.Request) -> web.Response:
    """GET /api/bot/user/{user_id} → {user_name, user_avatar_url}"""
    bot = request.app["bot"]
    try:
        user_id = int(request.match_info["user_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid user_id"}, status=400)

    info = _user_info(bot, user_id)
    return web.json_response(info)


async def handle_users_batch(request: web.Request) -> web.Response:
    """GET /api/bot/users?ids=1,2,3 → {id: {user_name, user_avatar_url}}"""
    bot = request.app["bot"]
    ids_str = request.query.get("ids", "")
    if not ids_str:
        return web.json_response({"error": "missing ids"}, status=400)

    result: dict[str, dict[str, str | None]] = {}
    for part in ids_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            uid = int(part)
        except ValueError:
            continue
        result[str(uid)] = _user_info(bot, uid)

    return web.json_response(result)


# ── Guild data handlers ──────────────────────────────────────────────────

async def handle_guild_info(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid guild_id"}, status=400)
    cache_key = f"guild:{guild_id}"
    data = _cache_get(cache_key)
    if data is None:
        data = _guild_data(bot, guild_id)
        if data is None:
            return web.json_response({"error": "guild not found"}, status=404)
        _cache_set(cache_key, data)
    return web.json_response(data)


async def handle_guild_channels(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid guild_id"}, status=400)
    cache_key = f"channels:{guild_id}"
    data = _cache_get(cache_key)
    if data is None:
        data = _guild_channels(bot, guild_id)
        if data is None:
            return web.json_response({"error": "guild not found"}, status=404)
        _cache_set(cache_key, data)
    return web.json_response(data)


async def handle_guild_voice_channels(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid guild_id"}, status=400)
    cache_key = f"voice:{guild_id}"
    data = _cache_get(cache_key)
    if data is None:
        data = _guild_voice_channels(bot, guild_id)
        if data is None:
            return web.json_response({"error": "guild not found"}, status=404)
        _cache_set(cache_key, data)
    return web.json_response(data)


async def handle_guild_roles(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid guild_id"}, status=400)
    cache_key = f"roles:{guild_id}"
    data = _cache_get(cache_key)
    if data is None:
        data = _guild_roles(bot, guild_id)
        if data is None:
            return web.json_response({"error": "guild not found"}, status=404)
        _cache_set(cache_key, data)
    return web.json_response(data)


async def handle_guild_webhooks(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid guild_id"}, status=400)
    cache_key = f"webhooks:{guild_id}"
    data = _cache_get(cache_key)
    if data is not None:
        return web.json_response(data)
    guild = bot.get_guild(guild_id)
    if not guild:
        return web.json_response({"error": "guild not found"}, status=404)
    webhooks = []
    try:
        for wh in await guild.webhooks():
            webhooks.append({
                "id": str(wh.id),
                "name": wh.name or "",
                "channel_id": str(wh.channel_id),
                "channel_name": wh.channel.name if wh.channel else "",
                "url": wh.url,
            })
    except Exception:
        pass  # bot may lack manage_webhooks permission
    _cache_set(cache_key, webhooks)
    return web.json_response(webhooks)


async def handle_dm(request: web.Request) -> web.Response:
    """POST /api/bot/dm — send a DM to a user from the bot.

    Body: {"user_id": int, "message": str, "feedback_id": int (optional)}
    Returns 200 {"ok": true} on success, 4xx/5xx {"ok": false, "error"} on failure.
    """
    bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)

    try:
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid user_id"}, status=400)
    message = (data.get("message") or "").strip()
    if user_id <= 0:
        return web.json_response({"ok": False, "error": "invalid user_id"}, status=400)
    if not message:
        return web.json_response({"ok": False, "error": "empty message"}, status=400)
    feedback_id = None
    try:
        raw_fid = data.get("feedback_id")
        if raw_fid is not None:
            feedback_id = int(raw_fid)
    except (TypeError, ValueError):
        feedback_id = None

    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            return web.json_response({"ok": False, "error": "user not found"}, status=404)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"failed to fetch user: {exc}"}, status=500)

    try:
        await user.send(message)
    except discord.Forbidden:
        return web.json_response(
            {"ok": False, "error": "user has DMs disabled or shares no guild with the bot"},
            status=403,
        )
    except discord.HTTPException as exc:
        return web.json_response({"ok": False, "error": f"failed to send DM: {exc}"}, status=500)

    # Persist the outgoing message to the feedback conversation thread.
    # Must never fail the request — logging is best-effort.
    try:
        db = getattr(bot, "db", None)
        if db and db.is_connected:
            if feedback_id:
                row = await db.feedback.fetchrow(
                    "SELECT guild_id FROM feedback WHERE id = $1", feedback_id)
                guild_id = row["guild_id"] if row else 0
            else:
                guild_id = 0
            await db.feedback.add_message(
                feedback_id=feedback_id or 0,
                guild_id=guild_id,
                user_id=user_id,
                direction="out",
                content=message,
            )
    except Exception:
        log.exception("Failed to record outgoing DM for user=%s", user_id)

    log.info("DM sent to user=%s", user_id)
    return web.json_response({"ok": True})


# ── App factory ──────────────────────────────────────────────────────────

def create_app(bot: Any) -> web.Application:
    app = web.Application()
    app["bot"] = bot

    app.router.add_get("/api/bot/avatar", handle_bot_avatar)
    app.router.add_get("/api/bot/user/{user_id}", handle_user_info)
    app.router.add_get("/api/bot/users", handle_users_batch)
    app.router.add_post("/api/bot/dm", handle_dm)
    app.router.add_get("/api/bot/guild/{guild_id}", handle_guild_info)
    app.router.add_get("/api/bot/guild/{guild_id}/channels", handle_guild_channels)
    app.router.add_get("/api/bot/guild/{guild_id}/voice-channels", handle_guild_voice_channels)
    app.router.add_get("/api/bot/guild/{guild_id}/roles", handle_guild_roles)
    app.router.add_get("/api/bot/guild/{guild_id}/webhooks", handle_guild_webhooks)

    return app


async def start_api_server(bot: Any, port: int = 8090) -> web.AppRunner:
    """Start the API server on the bot's event loop. Returns the runner for cleanup."""
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"API server listening on port {port}")
    return runner
