"""Lightweight aiohttp API server for Dashboard user/bot lookups.

Shares the bot's asyncio event loop. Exposes Discord-dependent endpoints
that db_browser (separate container) cannot serve. See DATA_INTERFACE.md.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

log = logging.getLogger("tausendsassa.api")

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


# ── App factory ──────────────────────────────────────────────────────────

def create_app(bot: Any) -> web.Application:
    app = web.Application()
    app["bot"] = bot

    app.router.add_get("/api/bot/avatar", handle_bot_avatar)
    app.router.add_get("/api/bot/user/{user_id}", handle_user_info)
    app.router.add_get("/api/bot/users", handle_users_batch)

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
