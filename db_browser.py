"""Tausendsassa Read-Only Database Browser.

Run:
    uvicorn db_browser:app --host 0.0.0.0 --port 8080

Endpoints:
    /                    -> Landing page with overview
    /guilds              -> List all guilds
    /guilds/{id}         -> Guild detail with all related data
    /feeds               -> Paginated feed list
    /feeds/{id}          -> Feed detail with posted entries
    /calendars           -> Paginated calendar list
    /calendars/{id}      -> Calendar detail with events
    /maps                -> Map settings overview
    /maps/{guild_id}     -> Map detail with pins
    /logs                -> Log viewer

Deps: fastapi, uvicorn, asyncpg, psutil
"""

from __future__ import annotations

import base64
import html
import json
import os
import glob as glob_module
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

import asyncpg
import httpx
import psutil
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, Response

# Database connection pool
pool: Optional[asyncpg.Pool] = None

# Bot start time (approximate - read from PID file or use process start time)
BOT_START_TIME: Optional[datetime] = None

# Base path
BASE_PATH = Path(__file__).parent

# Favicon as base64 (will be loaded on startup)
FAVICON_B64: Optional[str] = None

# Discord Bot Token for API calls
DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")

# Cache for Discord attachment URLs (message_id -> url)
_attachment_url_cache: Dict[int, str] = {}


async def get_discord_attachment_url(channel_id: int, message_id: int) -> Optional[str]:
    """Fetch the first attachment URL from a Discord message via REST API."""
    if not DISCORD_TOKEN:
        return None

    # Check cache first
    if message_id in _attachment_url_cache:
        return _attachment_url_cache[message_id]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}",
                headers={
                    "Authorization": f"Bot {DISCORD_TOKEN}",
                    "User-Agent": "TausendsassaDBBrowser/1.0",
                },
                timeout=10.0,
            )

            if resp.status_code == 200:
                data = resp.json()
                attachments = data.get("attachments", [])
                if attachments:
                    url = attachments[0].get("url")
                    if url:
                        # Cache the URL
                        _attachment_url_cache[message_id] = url
                        return url
    except Exception:
        pass

    return None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "tausendsassa"),
            user=os.getenv("DB_USER", "tausendsassa"),
            password=os.getenv("DB_PASSWORD", ""),
            min_size=1,
            max_size=5,
        )
    return pool


def load_favicon():
    """Load favicon as base64."""
    global FAVICON_B64
    favicon_path = BASE_PATH / "resources"  / "favicon.png"
    if favicon_path.exists():
        with open(favicon_path, "rb") as f:
            FAVICON_B64 = base64.b64encode(f.read()).decode()


def is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    # Check for .dockerenv file
    if Path("/.dockerenv").exists():
        return True
    # Check cgroup for docker/container references
    try:
        with open("/proc/1/cgroup", "r") as f:
            content = f.read()
            if "docker" in content or "container" in content:
                return True
    except (FileNotFoundError, PermissionError):
        pass
    return False


def format_uptime(start_time: datetime) -> str:
    """Format uptime from a start timestamp."""
    uptime = datetime.now() - start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def get_bot_uptime_from_log() -> Optional[str]:
    """Try to get bot uptime from the main log file (first log entry)."""
    log_file = BASE_PATH / "logs" / "tausendsassa.log"
    if not log_file.exists():
        return None

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            # Read first line to get bot start time
            first_line = f.readline()
            if first_line:
                # Log format: "2024-01-15 10:30:45 - INFO - ..."
                timestamp_str = first_line[:19]  # "2024-01-15 10:30:45"
                start_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                return format_uptime(start_time)
    except (ValueError, IndexError, OSError):
        pass
    return None


def get_bot_uptime() -> tuple[str, str]:
    """Get bot uptime and runtime mode.

    Returns:
        Tuple of (uptime_string, mode) where mode is 'systemd' or 'docker'
    """
    # Check if running in Docker
    if is_running_in_docker():
        # In Docker: Try to get uptime from log file
        uptime = get_bot_uptime_from_log()
        if uptime:
            return (uptime, "docker")

        # Fallback: Use this container's uptime (PID 1)
        try:
            proc = psutil.Process(1)
            start_time = datetime.fromtimestamp(proc.create_time())
            return (format_uptime(start_time), "docker")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return ("Unknown", "docker")

    # Systemd mode: Use PID file
    pid_file = Path("/run/tausendsassa/bot.pid")
    try:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            proc = psutil.Process(pid)
            start_time = datetime.fromtimestamp(proc.create_time())
            return (format_uptime(start_time), "systemd")
    except (FileNotFoundError, psutil.NoSuchProcess, ValueError):
        pass
    return ("Unknown", "systemd")


def get_system_metrics() -> Dict[str, Any]:
    """Get system metrics."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime, runtime_mode = get_bot_uptime()

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "memory_used_gb": memory.used / (1024**3),
        "memory_total_gb": memory.total / (1024**3),
        "disk_percent": disk.percent,
        "disk_used_gb": disk.used / (1024**3),
        "disk_total_gb": disk.total / (1024**3),
        "uptime": uptime,
        "runtime_mode": runtime_mode,
    }


def get_cog_status() -> List[Dict[str, Any]]:
    """Get cog status by reading log files."""
    cogs = []
    log_dir = BASE_PATH / "logs"
    
    # Expected cogs based on bot.py
    expected_cogs = ["feeds", "map", "monitor", "server_monitor", "moderation", "whenistrumpgone", "help", "calendar"]
    
    for cog_name in expected_cogs:
        log_file = log_dir / f"{cog_name}.log"
        status = "unknown"
        last_activity = None
        
        if log_file.exists():
            try:
                stat = log_file.stat()
                last_activity = datetime.fromtimestamp(stat.st_mtime)
                # If log was modified in last 5 minutes, cog is likely active
                if (datetime.now() - last_activity).seconds < 300:
                    status = "active"
                else:
                    status = "idle"
            except Exception:
                status = "error"
        else:
            status = "no_log"
        
        cogs.append({
            "name": cog_name,
            "status": status,
            "last_activity": last_activity,
        })
    
    return cogs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    load_favicon()
    await get_pool()
    yield
    # Shutdown
    global pool
    if pool:
        await pool.close()


app = FastAPI(
    title="Tausendsassa DB Browser",
    version="1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────



def find_map_file(guild_id: int, region: str = None) -> Optional[tuple[str, str]]:
    """Find the best map file for a guild.

    Returns (url_path, filename) or None if not found.
    Prefers final_map (has pins) over base_map.
    Checks guild-specific directory first, then shared map_cache.
    """
    # 1. Check guild-specific directory (personalized maps)
    guild_cache_dir = BASE_PATH / "cogs" / "map_data" / str(guild_id)
    if guild_cache_dir.exists():
        # Prefer final_map (has pins) over base_map
        for pattern in ["final_map_*.png", "base_map_*.png"]:
            for map_file in guild_cache_dir.glob(pattern):
                return (f"/static/maps/{guild_id}/{map_file.name}", map_file.name)

    # 2. Check shared map_cache directory (default maps)
    shared_cache_dir = BASE_PATH / "cogs" / "map_data" / "map_cache"
    if shared_cache_dir.exists():
        # If we know the region, try to find a matching map
        if region:
            region_lower = region.lower().replace(" ", "").replace("-", "")
            # Prefer final_map over base_map
            for pattern in ["final_map_*.png", "base_map_*.png"]:
                for map_file in shared_cache_dir.glob(pattern):
                    if region_lower in map_file.name.lower():
                        return (f"/static/maps/shared/{map_file.name}", map_file.name)
        # Fallback: return any final_map or base_map
        for pattern in ["final_map_*.png", "base_map_*.png"]:
            for map_file in shared_cache_dir.glob(pattern):
                return (f"/static/maps/shared/{map_file.name}", map_file.name)

    return None


def get_map_preview_html(guild_id: int, map_settings, discord_attachment_url: Optional[str] = None) -> str:
    """Generate HTML for map preview in guild detail.

    Priority: Discord attachment URL > local file > Discord link
    """
    # First choice: Discord attachment URL (always up-to-date)
    if discord_attachment_url:
        return f'<img src="{html.escape(discord_attachment_url)}" class="map-preview" alt="Map Preview" style="max-width:400px;">'

    # Fallback: local cached file
    region = map_settings.get("region") if map_settings else None
    map_info = find_map_file(guild_id, region)
    if map_info:
        url_path, _ = map_info
        return f'<img src="{url_path}" class="map-preview" alt="Map Preview" style="max-width:400px;">'

    # Final fallback: Discord link
    if map_settings and map_settings.get("channel_id") and map_settings.get("message_id"):
        discord_link = f"https://discord.com/channels/{guild_id}/{map_settings['channel_id']}/{map_settings['message_id']}"
        return f'<p><a href="{discord_link}" target="_blank">View Map Image in Discord</a></p>'
    return ""


def format_text(value: Optional[Any]) -> str:
    if value is None:
        return "—"
    escaped = html.escape(str(value))
    return escaped.replace("\n", "<br>")


def format_json(value: Optional[Any]) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        pretty = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        return html.escape(pretty)
    try:
        parsed = json.loads(str(value))
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
        return html.escape(pretty)
    except Exception:
        return html.escape(str(value))


def format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_guild(guild_id: int, name: str = None, icon_hash: str = None, link: bool = True) -> str:
    """Format guild display with name and optional icon."""
    display_name = html.escape(name) if name else str(guild_id)

    # Use proxy for Discord CDN icons to bypass restrictions
    if icon_hash:
        ext = "gif" if icon_hash.startswith("a_") else "png"
        icon_url = f"/proxy/discord/icons/{guild_id}/{icon_hash}.{ext}?size=32"
        icon_html = f'<img src="{icon_url}" alt="" style="width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display=&apos;none&apos;">'
    else:
        icon_html = '<span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#e5e7eb;vertical-align:middle;margin-right:6px;text-align:center;line-height:20px;font-size:10px;">?</span>'

    if link:
        return f'{icon_html}<a href="/guilds/{guild_id}">{display_name}</a><span class="meta" style="margin-left:6px;font-size:11px;">({guild_id})</span>'
    else:
        return f'{icon_html}{display_name}<span class="meta" style="margin-left:6px;font-size:11px;">({guild_id})</span>'


def format_user(user_id: int, username: str = None, display_name: str = None, avatar_hash: str = None) -> str:
    """Format user display with username and optional avatar.

    Note: For map_pins, display_name is the geocoded location, not the user's name.
    So we always prefer username over display_name.
    """
    name = username

    # Use proxy for Discord CDN avatars to bypass restrictions
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = f"/proxy/discord/avatars/{user_id}/{avatar_hash}.{ext}?size=32"
        avatar_html = f'<img src="{avatar_url}" alt="" style="width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display=&apos;none&apos;">'
    else:
        avatar_html = '<span style="display:inline-block;width:20px;height:20px;border-radius:50%;background:#e5e7eb;vertical-align:middle;margin-right:6px;text-align:center;line-height:20px;font-size:10px;">?</span>'

    if name:
        return f'{avatar_html}{html.escape(name)}<span class="meta" style="margin-left:6px;font-size:11px;">({user_id})</span>'
    return f'{avatar_html}{user_id}'


def render_page(title: str, body: str, nav_active: str = "") -> HTMLResponse:
    def nav_class(name: str) -> str:
        return "active" if name == nav_active else ""

    favicon_link = ""
    if FAVICON_B64:
        favicon_link = f'<link rel="icon" type="image/png" href="data:image/png;base64,{FAVICON_B64}">'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="de">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Tausendsassa DB</title>
        {favicon_link}
        <style>
          * {{ box-sizing: border-box; }}
          body {{
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            margin: 0;
            padding: 24px;
            color: #111827;
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            min-height: 100vh;
          }}
          a {{ color: #0284c7; text-decoration: none; }}
          a:hover {{ text-decoration: underline; }}
          header {{
            background: linear-gradient(135deg, #0369a1 0%, #0284c7 100%);
            padding: 16px 24px;
            margin: -24px -24px 24px -24px;
            box-shadow: 0 4px 12px rgba(3,105,161,0.2);
          }}
          header h1 {{
            margin: 0 0 12px 0;
            color: white;
            font-size: 24px;
            font-weight: 700;
          }}
          nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
          nav a {{
            color: rgba(255,255,255,0.9);
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            transition: background 0.2s;
          }}
          nav a:hover {{ background: rgba(255,255,255,0.15); text-decoration: none; }}
          nav a.active {{ background: rgba(255,255,255,0.25); }}
          .container {{ max-width: 1200px; margin: 0 auto; }}
          table {{
            border-collapse: collapse;
            width: 100%;
            background: white;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            border-radius: 12px;
            overflow: hidden;
            margin-top: 16px;
          }}
          th, td {{
            padding: 12px 16px;
            border-bottom: 1px solid #e5e7eb;
            text-align: left;
          }}
          th {{
            background: #f8fafc;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            font-size: 11px;
            font-weight: 700;
          }}
          tr:last-child td {{ border-bottom: none; }}
          tr:hover td {{ background: #f8fafc; }}
          .card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            padding: 24px;
            margin-top: 16px;
          }}
          .card h2 {{ margin-top: 0; color: #0369a1; }}
          .card h3 {{ color: #475569; margin-top: 24px; margin-bottom: 12px; }}
          .meta {{ color: #64748b; font-size: 13px; }}
          .pill {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            background: #dbeafe;
            color: #1d4ed8;
            font-size: 12px;
            font-weight: 600;
          }}
          .pill.green {{ background: #dcfce7; color: #166534; }}
          .pill.red {{ background: #fee2e2; color: #991b1b; }}
          .pill.yellow {{ background: #fef9c3; color: #854d0e; }}
          .pill.gray {{ background: #f1f5f9; color: #475569; }}
          .btn {{
            display: inline-block;
            padding: 10px 18px;
            border-radius: 8px;
            background: #0284c7;
            color: white;
            font-weight: 600;
            transition: all 0.2s;
          }}
          .btn:hover {{
            background: #0369a1;
            transform: translateY(-1px);
            text-decoration: none;
          }}
          .btn-secondary {{ background: #e2e8f0; color: #475569; }}
          .btn-secondary:hover {{ background: #cbd5e1; }}
          .pagination {{
            margin-top: 16px;
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: center;
          }}
          .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-top: 16px;
          }}
          .stat-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
          }}
          .stat-card h3 {{
            margin: 0 0 8px 0;
            color: #64748b;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }}
          .stat-card .value {{
            font-size: 32px;
            font-weight: 700;
            color: #0369a1;
          }}
          .stat-card .sub {{
            font-size: 12px;
            color: #64748b;
            margin-top: 4px;
          }}
          pre {{
            background: #f1f5f9;
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            font-size: 13px;
            line-height: 1.5;
          }}
          details {{ margin-top: 12px; }}
          summary {{
            cursor: pointer;
            color: #64748b;
            font-size: 13px;
            user-select: none;
          }}
          summary:hover {{ color: #0284c7; }}
          .progress-bar {{
            background: #e5e7eb;
            border-radius: 4px;
            height: 8px;
            overflow: hidden;
            margin-top: 8px;
          }}
          .progress-bar .fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
          }}
          .progress-bar .fill.green {{ background: #22c55e; }}
          .progress-bar .fill.yellow {{ background: #eab308; }}
          .progress-bar .fill.red {{ background: #ef4444; }}
          .cog-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-top: 12px;
          }}
          .cog-item {{
            background: white;
            border-radius: 8px;
            padding: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
          }}
          .cog-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
          }}
          .cog-dot.active {{ background: #22c55e; }}
          .cog-dot.idle {{ background: #eab308; }}
          .cog-dot.error {{ background: #ef4444; }}
          .cog-dot.unknown {{ background: #94a3b8; }}
          .log-viewer {{
            background: #1e293b;
            color: #e2e8f0;
            padding: 16px;
            border-radius: 8px;
            font-family: 'Fira Code', 'Monaco', monospace;
            font-size: 12px;
            line-height: 1.6;
            max-height: 600px;
            overflow-y: auto;
          }}
          .log-line {{ white-space: pre-wrap; word-break: break-all; }}
          .log-line.error {{ color: #fca5a5; }}
          .log-line.warning {{ color: #fcd34d; }}
          .log-line.info {{ color: #93c5fd; }}
          .avatar-img {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            vertical-align: middle;
            margin-right: 8px;
          }}
          .map-preview {{
            max-width: 100%;
            border-radius: 8px;
            margin-top: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
          }}
        </style>
      </head>
      <body>
        <header>
          <h1>Tausendsassa Database Browser</h1>
          <nav>
            <a href="/" class="{nav_class('home')}">Home</a>
            <a href="/guilds" class="{nav_class('guilds')}">Guilds</a>
            <a href="/feeds" class="{nav_class('feeds')}">Feeds</a>
            <a href="/calendars" class="{nav_class('calendars')}">Calendars</a>
            <a href="/maps" class="{nav_class('maps')}">Maps</a>
            <a href="/cache" class="{nav_class('cache')}">Cache</a>
            <a href="/monitor" class="{nav_class('monitor')}">Monitor</a>
            <a href="/logs" class="{nav_class('logs')}">Logs</a>
          </nav>
        </header>
        <div class="container">
          {body}
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html_content)


def paginator(page: int, total_pages: int, base_url: str, page_size: int) -> str:
    prev_link = (
        f"<a class='btn btn-secondary' href='{base_url}?page={page-1}&page_size={page_size}'>Zurück</a>"
        if page > 1
        else "<span class='btn btn-secondary' style='opacity:0.5'>Zurück</span>"
    )
    next_link = (
        f"<a class='btn' href='{base_url}?page={page+1}&page_size={page_size}'>Weiter</a>"
        if page < total_pages
        else "<span class='btn' style='opacity:0.5'>Weiter</span>"
    )
    return f"<div class='pagination'>{prev_link}<span class='meta'>Seite {page}/{total_pages}</span>{next_link}</div>"


def progress_bar_color(percent: float) -> str:
    if percent < 60:
        return "green"
    elif percent < 85:
        return "yellow"
    return "red"


# ─── Routes ──────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    p = await get_pool()
    metrics = get_system_metrics()
    cogs = get_cog_status()

    async with p.acquire() as conn:
        stats = await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM guilds) as guilds,
                (SELECT COUNT(*) FROM feeds) as feeds,
                (SELECT COUNT(*) FROM posted_entries) as posted_entries,
                (SELECT COUNT(*) FROM calendars) as calendars,
                (SELECT COUNT(*) FROM calendar_events) as calendar_events,
                (SELECT COUNT(*) FROM map_settings) as maps,
                (SELECT COUNT(*) FROM map_pins) as pins,
                (SELECT COUNT(*) FROM entry_hashes) as hashes,
                (SELECT COALESCE(SUM(member_count), 0) FROM guilds) as total_members
        """)

    # Build cog status grid
    cog_items = ""
    for cog in cogs:
        status_class = cog["status"]
        last_activity = format_datetime(cog["last_activity"]) if cog["last_activity"] else "—"
        cog_items += f'''
        <div class="cog-item" title="Last activity: {last_activity}">
            <span class="cog-dot {status_class}"></span>
            <span>{cog["name"]}</span>
        </div>
        '''

    body = f"""
    <h1 style="margin-top: 0;">Übersicht</h1>
    
    <!-- System Metrics -->
    <h2>System</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <h3>CPU</h3>
        <div class="value">{metrics['cpu_percent']:.1f}%</div>
        <div class="progress-bar"><div class="fill {progress_bar_color(metrics['cpu_percent'])}" style="width: {metrics['cpu_percent']}%"></div></div>
      </div>
      <div class="stat-card">
        <h3>Memory</h3>
        <div class="value">{metrics['memory_percent']:.1f}%</div>
        <div class="sub">{metrics['memory_used_gb']:.1f} / {metrics['memory_total_gb']:.1f} GB</div>
        <div class="progress-bar"><div class="fill {progress_bar_color(metrics['memory_percent'])}" style="width: {metrics['memory_percent']}%"></div></div>
      </div>
      <div class="stat-card">
        <h3>Disk</h3>
        <div class="value">{metrics['disk_percent']:.1f}%</div>
        <div class="sub">{metrics['disk_used_gb']:.1f} / {metrics['disk_total_gb']:.1f} GB</div>
        <div class="progress-bar"><div class="fill {progress_bar_color(metrics['disk_percent'])}" style="width: {metrics['disk_percent']}%"></div></div>
      </div>
      <div class="stat-card">
        <h3>Uptime</h3>
        <div class="value">{metrics['uptime']}</div>
        <div class="sub"><span class="pill {'green' if metrics['runtime_mode'] == 'docker' else 'gray'}">{metrics['runtime_mode'].upper()}</span></div>
      </div>
    </div>

    <!-- Cog Status -->
    <h2>Cog Status</h2>
    <div class="cog-grid">
      {cog_items}
    </div>
    
    <!-- Database Stats -->
    <h2>Datenbank</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <h3>Guilds</h3>
        <div class="value">{stats['guilds']}</div>
        <div class="sub">{stats['total_members']:,} Mitglieder gesamt</div>
      </div>
      <div class="stat-card">
        <h3>Feeds</h3>
        <div class="value">{stats['feeds']}</div>
      </div>
      <div class="stat-card">
        <h3>Posted Entries</h3>
        <div class="value">{stats['posted_entries']:,}</div>
        <div class="sub">last 7 days</div>
    </div>
      <div class="stat-card">
        <h3>Calendars</h3>
        <div class="value">{stats['calendars']}</div>
      </div>
      <div class="stat-card">
        <h3>Calendar Events</h3>
        <div class="value">{stats['calendar_events']:,}</div>
      </div>
      <div class="stat-card">
        <h3>Maps</h3>
        <div class="value">{stats['maps']}</div>
      </div>
      <div class="stat-card">
        <h3>Map Pins</h3>
        <div class="value">{stats['pins']:,}</div>
      </div>
      <div class="stat-card">
        <h3>Entry Hashes</h3>
        <div class="value">{stats['hashes']:,}</div>
      </div>
    </div>
    """
    return render_page("Übersicht", body, "home")


@app.get("/guilds", response_class=HTMLResponse)
async def list_guilds(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> HTMLResponse:
    p = await get_pool()
    offset = (page - 1) * page_size

    async with p.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM guilds")
        rows = await conn.fetch("""
            SELECT g.id as guild_id, g.name, g.icon_hash, g.member_count, g.created_at,
                   (SELECT COUNT(*) FROM feeds f WHERE f.guild_id = g.id) as feed_count,
                   (SELECT COUNT(*) FROM calendars c WHERE c.guild_id = g.id) as calendar_count,
                   (SELECT COUNT(*) FROM map_pins p WHERE p.guild_id = g.id) as pin_count,
                   gt.timezone
            FROM guilds g
            LEFT JOIN guild_timezones gt ON g.id = gt.guild_id
            ORDER BY g.created_at DESC
            LIMIT $1 OFFSET $2
        """, page_size, offset)

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for row in rows:
        tz = row['timezone'] or 'UTC'
        member_count = row['member_count'] or 0
        items.append(f"""
            <tr>
                <td>{format_guild(row['guild_id'], row['name'], row['icon_hash'])}</td>
                <td>{member_count:,}</td>
                <td>{format_datetime(row['created_at'])}</td>
                <td><span class="pill">{row['feed_count']} Feeds</span></td>
                <td><span class="pill green">{row['calendar_count']} Calendars</span></td>
                <td><span class="pill yellow">{row['pin_count']} Pins</span></td>
                <td class="meta">{tz}</td>
            </tr>
        """)

    body = f"""
    <h1>Guilds</h1>
    <p class="meta">Gesamt: {total} Guilds</p>
    <table>
        <thead>
            <tr>
                <th>Server</th>
                <th>Mitglieder</th>
                <th>Erstellt</th>
                <th>Feeds</th>
                <th>Calendars</th>
                <th>Pins</th>
                <th>Timezone</th>
            </tr>
        </thead>
        <tbody>
            {''.join(items) if items else '<tr><td colspan="7">Keine Daten.</td></tr>'}
        </tbody>
    </table>
    {paginator(page, total_pages, '/guilds', page_size)}
    """
    return render_page("Guilds", body, "guilds")


@app.get("/guilds/{guild_id}", response_class=HTMLResponse)
async def guild_detail(guild_id: int) -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        guild = await conn.fetchrow("SELECT * FROM guilds WHERE id = $1", guild_id)
        if not guild:
            raise HTTPException(404, "Guild not found")

        timezone = await conn.fetchrow(
            "SELECT * FROM guild_timezones WHERE guild_id = $1", guild_id
        )
        feeds = await conn.fetch(
            "SELECT * FROM feeds WHERE guild_id = $1 ORDER BY name", guild_id
        )
        calendars = await conn.fetch(
            "SELECT * FROM calendars WHERE guild_id = $1", guild_id
        )
        map_settings = await conn.fetchrow(
            "SELECT * FROM map_settings WHERE guild_id = $1", guild_id
        )
        pins = await conn.fetch(
            "SELECT * FROM map_pins WHERE guild_id = $1 ORDER BY pinned_at DESC", guild_id
        )
        moderation = await conn.fetchrow(
            "SELECT * FROM moderation_config WHERE guild_id = $1", guild_id
        )

    # Try to get Discord attachment URL for map preview
    discord_attachment_url = None
    if map_settings and map_settings.get("channel_id") and map_settings.get("message_id"):
        discord_attachment_url = await get_discord_attachment_url(
            map_settings["channel_id"], map_settings["message_id"]
        )

    # Feeds table
    feeds_rows = "".join(f"""
        <tr>
            <td><a href="/feeds/{f['id']}">{html.escape(f['name'])}</a></td>
            <td class="meta">{html.escape(f['feed_url'][:50])}...</td>
            <td><span class="pill {'green' if f['enabled'] else 'red'}">{'Aktiv' if f['enabled'] else 'Inaktiv'}</span></td>
            <td>{f['failure_count']}</td>
        </tr>
    """ for f in feeds) or '<tr><td colspan="4">Keine Feeds.</td></tr>'

    # Calendars table
    calendars_rows = "".join(f"""
        <tr>
            <td><a href="/calendars/{c['id']}">{c['text_channel_id']}</a></td>
            <td class="meta">{html.escape(c['ical_url'][:50])}...</td>
        </tr>
    """ for c in calendars) or '<tr><td colspan="2">Keine Calendars.</td></tr>'

    # Pins table with avatar
    pins_rows = "".join(f"""
        <tr>
            <td>{format_user(p['user_id'], p['username'], p['display_name'], p.get('avatar_hash'))}</td>
            <td>{p['latitude']:.4f}, {p['longitude']:.4f}</td>
            <td style="background-color: {p['color'] or '#FF0000'}; width: 30px;"></td>
            <td class="meta">{html.escape(p['location'] or '—')}</td>
        </tr>
    """ for p in pins) or '<tr><td colspan="4">Keine Pins.</td></tr>'

    guild_name = guild['name'] or str(guild_id)
    guild_icon = guild.get('icon_hash')
    member_count = guild.get('member_count') or 0
    
    body = f"""
    <div class="card">
        <h2>{format_guild(guild_id, guild_name, guild_icon, link=False)}</h2>
        <p class="meta">Erstellt: {format_datetime(guild['created_at'])}</p>
        <p class="meta">Timezone: {timezone['timezone'] if timezone else 'UTC'}</p>
        <p class="meta">Mitglieder: {member_count:,}</p>

        <h3>Feeds ({len(feeds)})</h3>
        <table>
            <thead><tr><th>Name</th><th>URL</th><th>Status</th><th>Fehler</th></tr></thead>
            <tbody>{feeds_rows}</tbody>
        </table>

        <h3>Calendars ({len(calendars)})</h3>
        <table>
            <thead><tr><th>Channel</th><th>iCal URL</th></tr></thead>
            <tbody>{calendars_rows}</tbody>
        </table>

        <h3>Map Pins ({len(pins)})</h3>
        <table>
            <thead><tr><th>User</th><th>Koordinaten</th><th>Farbe</th><th>Ort</th></tr></thead>
            <tbody>{pins_rows}</tbody>
        </table>

        {f'''
        <h3>Map</h3>
        <p><a href="/maps/{guild_id}" class="btn">View Map Details</a></p>
        {get_map_preview_html(guild_id, map_settings, discord_attachment_url)}
        <details>
            <summary>Map Settings JSON</summary>
            <pre>{format_json(dict(map_settings) if map_settings else None)}</pre>
        </details>
        ''' if map_settings else ''}

        {f'''
        <h3>Moderation Config</h3>
        <pre>{format_json(dict(moderation) if moderation else None)}</pre>
        ''' if moderation else ''}
    </div>
    """
    return render_page(f"{guild_name}", body, "guilds")


@app.get("/feeds", response_class=HTMLResponse)
async def list_feeds(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> HTMLResponse:
    p = await get_pool()
    offset = (page - 1) * page_size

    async with p.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM feeds")
        rows = await conn.fetch("""
            SELECT f.*, g.name as guild_name, g.icon_hash,
                   (SELECT COUNT(*) FROM posted_entries pe WHERE pe.feed_id = f.id) as posted_count
            FROM feeds f
            LEFT JOIN guilds g ON g.id = f.guild_id
            ORDER BY f.name
            LIMIT $1 OFFSET $2
        """, page_size, offset)

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for f in rows:
        status = "green" if f['enabled'] else "red"
        avatar_html = ""
        if f.get('avatar_url'):
            avatar_html = f'<img src="{html.escape(f["avatar_url"])}" class="avatar-img" alt="" onerror="this.style.display=&apos;none&apos;">'
        items.append(f"""
            <tr>
                <td>{avatar_html}<a href="/feeds/{f['id']}">{html.escape(f['name'])}</a></td>
                <td>{format_guild(f['guild_id'], f['guild_name'], f['icon_hash'])}</td>
                <td class="meta">{html.escape(f['feed_url'][:40])}...</td>
                <td><span class="pill {status}">{'Aktiv' if f['enabled'] else 'Inaktiv'}</span></td>
                <td>{f['posted_count']:,}</td>
                <td>{f['failure_count']}</td>
            </tr>
        """)

    body = f"""
    <h1>Feeds</h1>
    <p class="meta">Gesamt: {total} Feeds</p>
    <table>
        <thead>
            <tr>
                <th>Name</th>
                <th>Server</th>
                <th>URL</th>
                <th>Status</th>
                <th>Gepostet</th>
                <th>Fehler</th>
            </tr>
        </thead>
        <tbody>
            {''.join(items) if items else '<tr><td colspan="6">Keine Feeds.</td></tr>'}
        </tbody>
    </table>
    {paginator(page, total_pages, '/feeds', page_size)}
    """
    return render_page("Feeds", body, "feeds")


@app.get("/feeds/{feed_id}", response_class=HTMLResponse)
async def feed_detail(feed_id: int) -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        feed = await conn.fetchrow("""
            SELECT f.*, g.name as guild_name, g.icon_hash
            FROM feeds f
            LEFT JOIN guilds g ON g.id = f.guild_id
            WHERE f.id = $1
        """, feed_id)
        if not feed:
            raise HTTPException(404, "Feed not found")

        # Query by feed_id instead of guild_id
        posted = await conn.fetch("""
            SELECT * FROM posted_entries
            WHERE feed_id = $1
            ORDER BY posted_at DESC
            LIMIT 50
        """, feed_id)

    posted_rows = "".join(f"""
        <tr>
            <td class="meta">{html.escape(str(p['guid'])[:40])}...</td>
            <td>{format_datetime(p['posted_at'])}</td>
        </tr>
    """ for p in posted) or '<tr><td colspan="2">Keine Einträge.</td></tr>'

    embed_template = feed['embed_template'] or {}
    
    # Avatar display
    avatar_html = ""
    if feed.get('avatar_url'):
        avatar_html = f'<img src="{html.escape(feed["avatar_url"])}" style="width:64px;height:64px;border-radius:50%;margin-bottom:16px;" onerror="this.style.display=&apos;none&apos;">'

    body = f"""
    <div class="card">
        {avatar_html}
        <h2>{html.escape(feed['name'])}</h2>
        <p class="meta">Feed ID: {feed['id']}</p>
        <p class="meta">Server: {format_guild(feed['guild_id'], feed['guild_name'], feed['icon_hash'])}</p>

        <h3>Konfiguration</h3>
        <table>
            <tr><th style="width: 200px">Feed URL</th><td><a href="{html.escape(feed['feed_url'])}" target="_blank">{html.escape(feed['feed_url'])}</a></td></tr>
            <tr><th>Channel ID</th><td>{feed['channel_id']}</td></tr>
            <tr><th>Status</th><td><span class="pill {'green' if feed['enabled'] else 'red'}">{'Aktiv' if feed['enabled'] else 'Inaktiv'}</span></td></tr>
            <tr><th>Fehler</th><td>{feed['failure_count']}</td></tr>
            <tr><th>Letzter Erfolg</th><td>{format_datetime(feed['last_success'])}</td></tr>
            <tr><th>Erstellt</th><td>{format_datetime(feed['created_at'])}</td></tr>
            <tr><th>Aktualisiert</th><td>{format_datetime(feed['updated_at'])}</td></tr>
        </table>

        <h3>Embed Template</h3>
        <pre>{format_json(embed_template)}</pre>

        <h3>Letzte 50 gepostete Einträge</h3>
        <table>
            <thead><tr><th>Entry ID</th><th>Gepostet</th></tr></thead>
            <tbody>{posted_rows}</tbody>
        </table>
    </div>
    """
    return render_page(f"Feed: {feed['name']}", body, "feeds")


@app.get("/calendars", response_class=HTMLResponse)
async def list_calendars(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> HTMLResponse:
    p = await get_pool()
    offset = (page - 1) * page_size

    async with p.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM calendars")
        rows = await conn.fetch("""
            SELECT c.*, g.name as guild_name, g.icon_hash,
                   (SELECT COUNT(*) FROM calendar_events ce WHERE ce.calendar_pk = c.id) as event_count
            FROM calendars c
            LEFT JOIN guilds g ON g.id = c.guild_id
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
        """, page_size, offset)

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for c in rows:
        items.append(f"""
            <tr>
                <td><a href="/calendars/{c['id']}">{c['id']}</a></td>
                <td>{format_guild(c['guild_id'], c['guild_name'], c['icon_hash'])}</td>
                <td>{c['text_channel_id']}</td>
                <td class="meta">{html.escape(c['ical_url'][:40])}...</td>
                <td><span class="pill green">{c['event_count']} Events</span></td>
            </tr>
        """)

    body = f"""
    <h1>Calendars</h1>
    <p class="meta">Gesamt: {total} Calendars</p>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Server</th>
                <th>Text Channel</th>
                <th>iCal URL</th>
                <th>Events</th>
            </tr>
        </thead>
        <tbody>
            {''.join(items) if items else '<tr><td colspan="5">Keine Calendars.</td></tr>'}
        </tbody>
    </table>
    {paginator(page, total_pages, '/calendars', page_size)}
    """
    return render_page("Calendars", body, "calendars")


@app.get("/calendars/{calendar_id}", response_class=HTMLResponse)
async def calendar_detail(calendar_id: int) -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        cal = await conn.fetchrow("""
            SELECT c.*, g.name as guild_name, g.icon_hash
            FROM calendars c
            LEFT JOIN guilds g ON g.id = c.guild_id
            WHERE c.id = $1
        """, calendar_id)
        if not cal:
            raise HTTPException(404, "Calendar not found")

        events = await conn.fetch("""
            SELECT * FROM calendar_events
            WHERE calendar_pk = $1
            ORDER BY created_at DESC
            LIMIT 50
        """, calendar_id)

        reminders = await conn.fetch("""
            SELECT * FROM calendar_reminders
            WHERE calendar_pk = $1
            ORDER BY sent_at DESC
            LIMIT 20
        """, calendar_id)

    events_rows = "".join(f"""
        <tr>
            <td>{html.escape(e['event_title'])}</td>
            <td>{e['discord_event_id'] or '—'}</td>
            <td>{format_datetime(e['created_at'])}</td>
        </tr>
    """ for e in events) or '<tr><td colspan="3">Keine Events.</td></tr>'

    reminders_rows = "".join(f"""
        <tr>
            <td>{html.escape(r['reminder_key'])}</td>
            <td>{format_datetime(r['sent_at'])}</td>
        </tr>
    """ for r in reminders) or '<tr><td colspan="2">Keine Reminders.</td></tr>'

    body = f"""
    <div class="card">
        <h2>Calendar {calendar_id}</h2>
        <p class="meta">Server: {format_guild(cal['guild_id'], cal['guild_name'], cal['icon_hash'])}</p>

        <h3>Konfiguration</h3>
        <table>
            <tr><th style="width: 200px">iCal URL</th><td><a href="{html.escape(cal['ical_url'])}" target="_blank">{html.escape(cal['ical_url'])}</a></td></tr>
            <tr><th>Text Channel</th><td>{cal['text_channel_id']}</td></tr>
            <tr><th>Voice Channel</th><td>{cal['voice_channel_id'] or '—'}</td></tr>
            <tr><th>Reminder Role</th><td>{cal['reminder_role_id'] or '—'}</td></tr>
            <tr><th>Blacklist</th><td>{format_json(cal['blacklist'])}</td></tr>
            <tr><th>Whitelist</th><td>{format_json(cal['whitelist'])}</td></tr>
        </table>

        <h3>Events (letzte 50)</h3>
        <table>
            <thead><tr><th>Title</th><th>Discord Event</th><th>Erstellt</th></tr></thead>
            <tbody>{events_rows}</tbody>
        </table>

        <h3>Reminders (letzte 20)</h3>
        <table>
            <thead><tr><th>Reminder Key</th><th>Gesendet</th></tr></thead>
            <tbody>{reminders_rows}</tbody>
        </table>
    </div>
    """
    return render_page(f"Calendar {calendar_id}", body, "calendars")


@app.get("/maps", response_class=HTMLResponse)
async def list_maps(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> HTMLResponse:
    p = await get_pool()
    offset = (page - 1) * page_size

    async with p.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM map_settings")
        rows = await conn.fetch("""
            SELECT ms.*, g.name as guild_name, g.icon_hash,
                   (SELECT COUNT(*) FROM map_pins mp WHERE mp.guild_id = ms.guild_id) as pin_count
            FROM map_settings ms
            LEFT JOIN guilds g ON g.id = ms.guild_id
            ORDER BY ms.created_at DESC
            LIMIT $1 OFFSET $2
        """, page_size, offset)

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for m in rows:
        items.append(f"""
            <tr>
                <td><a href="/maps/{m['guild_id']}">{format_guild(m['guild_id'], m['guild_name'], m['icon_hash'], link=False)}</a></td>
                <td>{html.escape(m['region'] or 'World')}</td>
                <td>{m['channel_id'] or '—'}</td>
                <td><span class="pill yellow">{m['pin_count']} Pins</span></td>
            </tr>
        """)

    body = f"""
    <h1>Maps</h1>
    <p class="meta">Gesamt: {total} Maps</p>
    <table>
        <thead>
            <tr>
                <th>Server</th>
                <th>Region</th>
                <th>Channel</th>
                <th>Pins</th>
            </tr>
        </thead>
        <tbody>
            {''.join(items) if items else '<tr><td colspan="4">Keine Maps.</td></tr>'}
        </tbody>
    </table>
    {paginator(page, total_pages, '/maps', page_size)}
    """
    return render_page("Maps", body, "maps")


@app.get("/maps/{guild_id}", response_class=HTMLResponse)
async def map_detail(guild_id: int) -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        settings = await conn.fetchrow("""
            SELECT ms.*, g.name as guild_name, g.icon_hash
            FROM map_settings ms
            LEFT JOIN guilds g ON g.id = ms.guild_id
            WHERE ms.guild_id = $1
        """, guild_id)
        if not settings:
            raise HTTPException(404, "Map not found")

        pins = await conn.fetch("""
            SELECT * FROM map_pins
            WHERE guild_id = $1
            ORDER BY pinned_at DESC
        """, guild_id)

    # Pins table with avatar
    pins_rows = "".join(f"""
        <tr>
            <td>{format_user(p['user_id'], p['username'], p['display_name'], p.get('avatar_hash'))}</td>
            <td>{p['latitude']:.4f}</td>
            <td>{p['longitude']:.4f}</td>
            <td style="background-color: {p['color'] or '#FF0000'}; width: 30px;"></td>
            <td>{html.escape(p['location'] or '—')}</td>
            <td>{format_datetime(p['pinned_at'])}</td>
        </tr>
    """ for p in pins) or '<tr><td colspan="6">Keine Pins.</td></tr>'

    # Find map image - Discord first, local file as fallback
    map_image_html = ""

    # First choice: Discord attachment URL (always up-to-date)
    if settings["channel_id"] and settings["message_id"]:
        discord_attachment_url = await get_discord_attachment_url(
            settings["channel_id"], settings["message_id"]
        )
        if discord_attachment_url:
            map_image_html = f'<img src="{html.escape(discord_attachment_url)}" class="map-preview" alt="Map Preview">'

    # Fallback: local cached file
    if not map_image_html:
        region = settings.get("region")
        map_info = find_map_file(guild_id, region)
        if map_info:
            url_path, _ = map_info
            map_image_html = f'<img src="{url_path}" class="map-preview" alt="Map Preview">'

    # Final fallback: Discord link
    if not map_image_html and settings["channel_id"] and settings["message_id"]:
        discord_link = f"https://discord.com/channels/{guild_id}/{settings['channel_id']}/{settings['message_id']}"
        map_image_html = f'<p><a href="{discord_link}" target="_blank" class="btn">View Map in Discord</a></p>'

    guild_display = format_guild(settings['guild_id'], settings['guild_name'], settings['icon_hash'], link=False)
    body = f"""
    <div class="card">
        <h2>Map für {guild_display}</h2>

        {map_image_html}

        <h3>Einstellungen</h3>
        <table>
            <tr><th style="width: 200px">Region</th><td>{html.escape(settings['region'] or 'World')}</td></tr>
            <tr><th>Channel</th><td>{settings['channel_id'] or '—'}</td></tr>
            <tr><th>Message ID</th><td>{settings['message_id'] or '—'}</td></tr>
            <tr><th>Settings</th><td><pre>{format_json(settings['settings'])}</pre></td></tr>
        </table>

        <h3>Pins ({len(pins)})</h3>
        <table>
            <thead><tr><th>User</th><th>Lat</th><th>Lon</th><th>Farbe</th><th>Label</th><th>Erstellt</th></tr></thead>
            <tbody>{pins_rows}</tbody>
        </table>
    </div>
    """
    map_name = settings['guild_name'] or str(guild_id)
    return render_page(f"Map: {map_name}", body, "maps")


@app.get("/static/maps/shared/{filename}")
async def get_shared_map_image(filename: str):
    """Serve cached map images from shared map_cache directory."""
    # Sanitize filename to prevent directory traversal
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe_filename.endswith(".png"):
        raise HTTPException(400, "Invalid file type")

    shared_cache_dir = BASE_PATH / "cogs" / "map_data" / "map_cache"
    map_file = shared_cache_dir / safe_filename
    if not map_file.exists():
        raise HTTPException(404, "Map image not found")
    return FileResponse(map_file, media_type="image/png")


@app.get("/static/maps/{guild_id}/{filename}")
async def get_map_image(guild_id: int, filename: str):
    """Serve cached map images from guild-specific directories."""
    # Sanitize filename to prevent directory traversal
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe_filename.endswith(".png"):
        raise HTTPException(400, "Invalid file type")

    guild_cache_dir = BASE_PATH / "cogs" / "map_data" / str(guild_id)
    map_file = guild_cache_dir / safe_filename
    if not map_file.exists():
        raise HTTPException(404, "Map image not found")
    return FileResponse(map_file, media_type="image/png")


@app.get("/proxy/discord/{path:path}")
async def proxy_discord_cdn(path: str, size: int = Query(32, ge=16, le=512)):
    """Proxy Discord CDN images to bypass hotlinking restrictions.

    Discord CDN may block direct embedding from external sites.
    This endpoint fetches the image server-side and serves it to the browser.
    """
    # Validate path format (avatars/user_id/hash.ext or icons/guild_id/hash.ext)
    parts = path.split("/")
    if len(parts) != 3:
        raise HTTPException(400, "Invalid path format")

    resource_type, resource_id, filename = parts

    if resource_type not in ("avatars", "icons"):
        raise HTTPException(400, "Invalid resource type")

    # Validate resource_id is numeric
    if not resource_id.isdigit():
        raise HTTPException(400, "Invalid resource ID")

    # Validate filename format (hash.png or hash.gif)
    if not (filename.endswith(".png") or filename.endswith(".gif")):
        raise HTTPException(400, "Invalid file extension")

    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")

    # Build Discord CDN URL
    discord_url = f"https://cdn.discordapp.com/{resource_type}/{resource_id}/{safe_filename}?size={size}"

    # Cache directory for proxied images
    cache_dir = BASE_PATH / "cogs" / "map_data" / "avatar_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{resource_type}_{resource_id}_{safe_filename}"

    # Check cache first (cache for 24 hours)
    if cache_file.exists():
        cache_age = datetime.now().timestamp() - cache_file.stat().st_mtime
        if cache_age < 86400:  # 24 hours
            content_type = "image/gif" if filename.endswith(".gif") else "image/png"
            return FileResponse(cache_file, media_type=content_type)

    # Fetch from Discord CDN
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                discord_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TausendsassaBot/1.0)",
                    "Accept": "image/png,image/gif,image/*",
                },
                follow_redirects=True,
                timeout=10.0,
            )

            if resp.status_code == 404:
                raise HTTPException(404, "Image not found on Discord CDN")
            if resp.status_code != 200:
                raise HTTPException(502, f"Discord CDN returned {resp.status_code}")

            content = resp.content
            content_type = resp.headers.get("content-type", "image/png")

            # Cache the image
            with open(cache_file, "wb") as f:
                f.write(content)

            return Response(content=content, media_type=content_type)

    except httpx.TimeoutException:
        raise HTTPException(504, "Timeout fetching image from Discord CDN")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Error fetching image: {str(e)}")


@app.get("/cache", response_class=HTMLResponse)
async def cache_overview() -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        webhook_count = await conn.fetchval("SELECT COUNT(*) FROM webhook_cache")
        feed_cache_count = await conn.fetchval("SELECT COUNT(*) FROM feed_cache")
        hash_count = await conn.fetchval("SELECT COUNT(*) FROM entry_hashes")

        webhooks = await conn.fetch("SELECT * FROM webhook_cache ORDER BY created_at DESC LIMIT 20")
        hashes = await conn.fetch("""
            SELECT guid, content_hash, created_at
            FROM entry_hashes
            ORDER BY created_at DESC
            LIMIT 20
        """)

    webhooks_rows = "".join(f"""
        <tr>
            <td>{w['channel_id']}</td>
            <td>{w['webhook_id']}</td>
            <td class="meta">{html.escape(w['webhook_name'] or '—')}</td>
            <td>{format_datetime(w['created_at'])}</td>
        </tr>
    """ for w in webhooks) or '<tr><td colspan="4">Keine Webhooks.</td></tr>'

    hashes_rows = "".join(f"""
        <tr>
            <td class="meta">{html.escape(str(h['guid'])[:50])}...</td>
            <td class="meta">{h['content_hash'][:16]}...</td>
            <td>{format_datetime(h['created_at'])}</td>
        </tr>
    """ for h in hashes) or '<tr><td colspan="3">Keine Hashes.</td></tr>'

    body = f"""
    <h1>Cache</h1>

    <div class="stats-grid">
        <div class="stat-card">
            <h3>Webhook Cache</h3>
            <div class="value">{webhook_count}</div>
        </div>
        <div class="stat-card">
            <h3>Feed Cache</h3>
            <div class="value">{feed_cache_count}</div>
        </div>
        <div class="stat-card">
            <h3>Entry Hashes</h3>
            <div class="value">{hash_count:,}</div>
        </div>
    </div>

    <div class="card">
        <h3>Webhooks (letzte 20)</h3>
        <table>
            <thead><tr><th>Channel</th><th>Webhook ID</th><th>Name</th><th>Erstellt</th></tr></thead>
            <tbody>{webhooks_rows}</tbody>
        </table>

        <h3>Entry Hashes (letzte 20)</h3>
        <table>
            <thead><tr><th>GUID</th><th>Hash</th><th>Erstellt</th></tr></thead>
            <tbody>{hashes_rows}</tbody>
        </table>
    </div>
    """
    return render_page("Cache", body, "cache")


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_overview() -> HTMLResponse:
    p = await get_pool()

    async with p.acquire() as conn:
        messages = await conn.fetch("""
            SELECT * FROM monitor_messages
            ORDER BY created_at DESC
            LIMIT 50
        """)

    messages_rows = "".join(f"""
        <tr>
            <td>{m['channel_id']}</td>
            <td>{m['message_id']}</td>
            <td>{html.escape(m['monitor_type'])}</td>
            <td>{m['auto_update_interval'] or '—'}</td>
            <td>{format_datetime(m['created_at'])}</td>
        </tr>
    """ for m in messages) or '<tr><td colspan="5">Keine Monitor Messages.</td></tr>'

    body = f"""
    <h1>Monitor Messages</h1>

    <div class="card">
        <table>
            <thead><tr><th>Channel</th><th>Message</th><th>Typ</th><th>Update Interval</th><th>Erstellt</th></tr></thead>
            <tbody>{messages_rows}</tbody>
        </table>
    </div>
    """
    return render_page("Monitor", body, "monitor")


@app.get("/logs", response_class=HTMLResponse)
async def log_viewer(
    file: str = Query("tausendsassa", description="Log file name without .log extension"),
    lines: int = Query(100, ge=10, le=500),
) -> HTMLResponse:
    """View log files."""
    log_dir = BASE_PATH / "logs"
    
    # List available log files
    log_files = sorted([f.stem for f in log_dir.glob("*.log")]) if log_dir.exists() else []
    
    # Sanitize filename to prevent directory traversal
    safe_file = "".join(c for c in file if c.isalnum() or c in "-_")
    log_path = log_dir / f"{safe_file}.log"
    
    log_content = ""
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:]
                
                for line in recent_lines:
                    line = html.escape(line.rstrip())
                    css_class = ""
                    if "ERROR" in line or "CRITICAL" in line:
                        css_class = "error"
                    elif "WARNING" in line:
                        css_class = "warning"
                    elif "INFO" in line:
                        css_class = "info"
                    log_content += f'<div class="log-line {css_class}">{line}</div>'
        except Exception as e:
            log_content = f'<div class="log-line error">Error reading log: {html.escape(str(e))}</div>'
    else:
        log_content = '<div class="log-line">Log file not found.</div>'
    
    # File selector
    file_buttons = " ".join(
        f'<a href="/logs?file={f}&lines={lines}" class="btn {"" if f != safe_file else "btn-secondary"}">{f}</a>'
        for f in log_files
    )

    body = f"""
    <h1>Log Viewer</h1>
    
    <div class="card">
        <h3>Log Files</h3>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;">
            {file_buttons if file_buttons else '<span class="meta">No log files found.</span>'}
        </div>
        
        <h3>{safe_file}.log (letzte {lines} Zeilen)</h3>
        <div class="log-viewer">
            {log_content if log_content else '<div class="log-line">No content.</div>'}
        </div>
    </div>
    """
    return render_page("Logs", body, "logs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
