#!/usr/bin/env python3
"""Usage limits (Claude, Codex, MiniMax, Kimi) for the park's views.

Agent Park never talks to a provider and never touches a token or cookie. It
only reads, read-only, the history database that AI Limit Monitor keeps:
~/.config/ai-limit-monitor/history.db on Linux, %APPDATA%\\ai-limit-monitor on
Windows. Without that app, or without a database yet, there is simply nothing
to show. Standard library only.

Every percentage here is the share of the limit already *used*.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import time

from platform_support import config_base

USAGE_POLL = 30  # seconds between reads; the monitor itself polls about every minute
STALE_AFTER = 15 * 60  # older samples are shown, but marked as old

# Providers in display order: key in the database, short name in the views.
PROVIDERS = (("claude", "claude"), ("codex", "codex"), ("minimax", "minimax"), ("kimi", "kimi"))


def default_db():
    """AI Limit Monitor's database; AGENT_PARK_USAGE_DB points elsewhere."""
    override = os.environ.get("AGENT_PARK_USAGE_DB")
    if override:
        return override
    return os.path.join(config_base(), "ai-limit-monitor", "history.db")


def parse_reset(value):
    """Unix seconds of an ISO timestamp such as the monitor stores, or None."""
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def claude_limit(db):
    row = db.execute("SELECT ts, five_hour, seven_day, raw_json FROM snapshots "
                     "ORDER BY ts DESC LIMIT 1").fetchone()
    if row is None:
        return None
    ts, five_hour, seven_day, raw = row
    try:
        body = json.loads(raw or "{}")
    except ValueError:
        body = {}
    resets = {}
    for name in ("five_hour", "seven_day"):
        window = body.get(name)
        resets[name] = parse_reset(window.get("resets_at")) if isinstance(window, dict) else None
    return {"updated_at": ts / 1000, "windows": [
        {"name": "5h", "pct": five_hour, "resets_at": resets["five_hour"]},
        {"name": "7d", "pct": seven_day, "resets_at": resets["seven_day"]},
    ]}


def window_name(seconds, fallback):
    """"5h" and "7d" from a window length in seconds; `fallback` for any other length."""
    if seconds == 18000:
        return "5h"
    if seconds == 604800:
        return "7d"
    return fallback


def codex_limit(db):
    """Codex's 5h and weekly windows. Only the two windows are read from the raw reply:
    it also holds account details that have no business here."""
    row = db.execute("SELECT ts, primary_pct, secondary_pct, raw_json FROM codex_snapshots "
                     "ORDER BY ts DESC LIMIT 1").fetchone()
    if row is None:
        return None
    ts, primary, secondary, raw = row
    try:
        rate = json.loads(raw or "{}").get("rate_limit") or {}
    except (ValueError, AttributeError):
        rate = {}
    windows = []
    for pct, key, fallback in ((primary, "primary_window", "5h"), (secondary, "secondary_window", "7d")):
        window = rate.get(key) if isinstance(rate.get(key), dict) else {}
        resets = window.get("reset_at")
        windows.append({"name": window_name(window.get("limit_window_seconds"), fallback), "pct": pct,
                        "resets_at": resets if isinstance(resets, (int, float)) else None})
    return {"updated_at": ts / 1000, "windows": windows}


def sample_limit(db, provider, name):
    """Providers that record one headline percentage per poll, shown as one window `name`."""
    row = db.execute("SELECT ts, pct FROM provider_snapshots WHERE provider = ? "
                     "AND pct IS NOT NULL ORDER BY ts DESC LIMIT 1", (provider,)).fetchone()
    if row is None:
        return None
    return {"updated_at": row[0] / 1000, "windows": [{"name": name, "pct": row[1], "resets_at": None}]}


def stored_windows(db, provider):
    """Every window AI Limit Monitor kept from the provider's latest poll (newer versions)."""
    rows = db.execute("SELECT name, pct, resets_at, ts FROM provider_windows WHERE provider = ? "
                      "ORDER BY rowid", (provider,)).fetchall()
    if not rows:
        return None
    return {"updated_at": max(row[3] for row in rows) / 1000,
            "windows": [{"name": name, "pct": pct, "resets_at": resets} for name, pct, resets, _ in rows]}


def read_provider(db, key):
    if key == "claude":
        return claude_limit(db)
    if key == "codex":
        return codex_limit(db)
    # MiniMax and Kimi: all windows when the monitor stores them. Older versions only kept one
    # headline percentage (MiniMax's worst interval window, Kimi's 5h window), so fall back to
    # that, and use whichever reading is newer.
    try:
        full = stored_windows(db, key)
    except sqlite3.Error:  # no such table yet
        full = None
    headline = sample_limit(db, key, {"minimax": "interval", "kimi": "5h"}[key])
    if full and (not headline or full["updated_at"] >= headline["updated_at"]):
        return full
    return headline


class UsageMonitor:
    """The latest usage of each provider, read at most every USAGE_POLL seconds."""

    def __init__(self, path=None, clock=time.time):
        self.path = path or default_db()
        self.clock = clock
        self.last = []
        self.next_read = 0.0

    def poll(self):
        now = self.clock()
        if now < self.next_read:
            return self.last
        self.next_read = now + USAGE_POLL
        self.last = self.read(now)
        return self.last

    def read(self, now):
        if not os.path.exists(self.path):
            return []
        try:
            db = sqlite3.connect(f"{Path(self.path).absolute().as_uri()}?mode=ro", uri=True, timeout=1)
        except sqlite3.Error:
            return []
        limits = []
        try:
            for key, label in PROVIDERS:
                try:
                    found = read_provider(db, key)
                except sqlite3.Error:
                    continue  # another version of the schema: skip this provider
                if found:
                    found.update(provider=key, label=label,
                                 stale=now - found["updated_at"] > STALE_AFTER)
                    limits.append(found)
        finally:
            db.close()
        return limits


def until(when, now):
    """"1h08m", "2d20h", "45m", "now": the time left until `when`; "" when it is unknown."""
    if when is None:
        return ""
    left = int(when - now)
    if left <= 0:
        return "now"
    if left < 3600:
        return f"{max(1, left // 60)}m"
    if left < 86400:
        return f"{left // 3600}h{left % 3600 // 60:02d}m"
    return f"{left // 86400}d{left % 86400 // 3600:02d}h"


def mood_face(pct):
    """A little cat that worries as a limit fills up; the 3D view uses the same thresholds."""
    for limit, face in ((50, "(=^.^=)"), (80, "(=o.o=)"), (95, "(=O.O=)")):
        if pct < limit:
            return face
    return "(=x.x=)"
