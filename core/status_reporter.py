# core/status_reporter.py
"""
Status/health snapshot for Tausendsassa's live bot process.

The db-browser's /api/dashboard endpoint has no access to the running
discord.py client (separate container, DB-only access), so gateway
connection status and loaded cogs can't be derived there. This module
writes a small data/status.json from the bot process itself — the
dashboard reads it directly (read-only volume mount), mirroring the
pattern already used by RoaringBot (including rolling-window counters
and event logs, e.g. for the log-error graph).
"""
import json
import logging
import os
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict

log = logging.getLogger("tausendsassa.status")

STATUS_FILE = os.path.join("data", "status.json")
WRITE_INTERVAL_SECONDS = 15

# How long counter events are kept around before they age out of every window.
_COUNTER_RETENTION_SECONDS = 24 * 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StatusReporter:
    """Thread-unsafe by design — only ever touched from the bot's asyncio loop."""

    def __init__(self):
        self._sections: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._counters: Dict[str, Dict[str, Deque[float]]] = defaultdict(lambda: defaultdict(deque))
        self._started_at = time.time()
        self._task = None

    # ─── Writers used by cogs/core modules ─────────────────────────────────
    def record(self, section: str, **fields):
        """Merge fields into a named section (e.g. record('feeds', last_error=None))."""
        self._sections[section].update(fields)
        self._sections[section]["updated_at"] = _now_iso()

    def record_event(self, section: str, list_key: str, entry: Any, max_len: int = 20):
        """Append a timestamped entry to a rolling list within a section (e.g. recent errors)."""
        events = self._sections[section].setdefault(list_key, [])
        events.append({"at": _now_iso(), **entry} if isinstance(entry, dict) else {"at": _now_iso(), "value": entry})
        del events[:-max_len]
        self._sections[section]["updated_at"] = _now_iso()

    def bump_counter(self, section: str, counter: str):
        """Record one occurrence of an event for rolling-window rate counting (15m/1h/24h)."""
        self._counters[section][counter].append(time.time())

    def load(self):
        """Restore sections (rolling event logs, last-known fields) from a previous run's
        status.json, so a bot restart doesn't wipe the dashboard's history. Counters are
        intentionally dropped — they're rebuilt from live events, and we have no reliable
        timestamps to replay them with. Call before cogs load, so fresh cog_load() values
        still win."""
        if not os.path.exists(STATUS_FILE):
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            log.warning("Failed to load previous status.json, starting fresh")
            return

        restored = []
        for section, fields in data.items():
            if section in ("generated_at", "uptime_seconds") or not isinstance(fields, dict):
                continue
            fields = dict(fields)
            fields.pop("counters", None)
            self._sections[section].update(fields)
            restored.append(section)
        if restored:
            log.info(f"Restored status sections from previous run: {', '.join(restored)}")

    # ─── Snapshot assembly ──────────────────────────────────────────────────
    def _counter_windows(self, timestamps: Deque[float], now: float) -> Dict[str, int]:
        while timestamps and now - timestamps[0] > _COUNTER_RETENTION_SECONDS:
            timestamps.popleft()
        return {
            "15m": sum(1 for t in timestamps if now - t <= 900),
            "1h": sum(1 for t in timestamps if now - t <= 3600),
            "24h": len(timestamps),
        }

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        sections = {name: dict(fields) for name, fields in self._sections.items()}
        for section, counters in self._counters.items():
            target = sections.setdefault(section, {})
            target["counters"] = {name: self._counter_windows(ts, now) for name, ts in counters.items()}
        return {
            "generated_at": _now_iso(),
            "uptime_seconds": int(now - self._started_at),
            **sections,
        }

    def write(self):
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        data = self.snapshot()
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATUS_FILE), prefix=".status-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp_path, STATUS_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ─── Lifecycle ───────────────────────────────────────────────────────────
    async def start(self, asyncio_module):
        if self._task and not self._task.done():
            return
        self._task = asyncio_module.create_task(self._writer_loop(asyncio_module))
        log.info("Started status reporter writer task")

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

    async def _writer_loop(self, asyncio_module):
        while True:
            try:
                self.write()
            except Exception as e:
                log.error(f"Error writing status snapshot: {e}")
            await asyncio_module.sleep(WRITE_INTERVAL_SECONDS)


status_reporter = StatusReporter()
