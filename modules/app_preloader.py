"""
modules/app_preloader.py
Predictive app pre-loading — watches command_log.csv for app open patterns,
pre-launches apps 2 minutes before their predicted time window.

Example: User opens VS Code + Chrome every weekday at 9am.
At 8:58am iZACH launches them silently. By 9:00 they're ready.
"""

import csv
import json
import logging
import os
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
LOG_FILE = "command_log.csv"
PRELOAD_STATE_FILE = "preload_state.json"

MIN_OCCURRENCES = 3
MIN_DAY_SPAN = 5
PRE_LAUNCH_MINUTES = 2
CHECK_INTERVAL = 60  # check every minute

_speak_fn = None
_running = False
_preloaded_today: set = set()  # "app:date" keys to avoid double-launch

# Known app launch commands for Windows
_APP_LAUNCH_MAP = {
    "chrome":       "start chrome",
    "google chrome": "start chrome",
    "vscode":       "code",
    "vs code":      "code",
    "visual studio code": "code",
    "notepad":      "notepad",
    "notepad++":    "notepad++",
    "slack":        "start slack",
    "discord":      "start discord",
    "spotify":      "start spotify",
    "whatsapp":     "start whatsapp",
    "telegram":     "start telegram",
    "obs":          "start obs64",
    "figma":        "start figma",
    "postman":      "start postman",
    "terminal":     "start wt",
    "powershell":   "start powershell",
    "cmd":          "start cmd",
    "explorer":     "explorer",
    "file explorer": "explorer",
}


def init(speak_fn):
    global _speak_fn
    _speak_fn = speak_fn


def start():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_preload_loop, daemon=True, name="app-preloader").start()
    logger.info("[Preloader] Started.")


def stop():
    global _running
    _running = False


# ── Pattern extraction ────────────────────────────────────────

def _load_app_open_rows(days: int = 45) -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rows = []
    try:
        with open(LOG_FILE, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                    cmd = row.get("command", "").lower()
                    if ts >= cutoff and row.get("status") == "success":
                        if cmd.startswith("open ") or "open" in cmd[:10]:
                            rows.append({"ts": ts, "cmd": cmd})
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"[Preloader] CSV read error: {e}")
    return rows


def _extract_app_name(cmd: str) -> str | None:
    cmd = cmd.lower().strip()
    for prefix in ("open ", "start ", "launch "):
        if cmd.startswith(prefix):
            return cmd[len(prefix):].strip().split()[0] if cmd[len(prefix):].strip() else None
    return None


def _detect_patterns() -> list[dict]:
    """
    Returns list of {app, hour_bucket, day_type, count} patterns
    that meet the minimum occurrence + day span threshold.
    """
    rows = _load_app_open_rows()
    if not rows:
        return []

    # Group by app + time bucket
    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        app = _extract_app_name(r["cmd"])
        if not app or len(app) < 2:
            continue
        ts = r["ts"]
        hour_bucket = (ts.hour // 2) * 2
        day_type = "weekend" if ts.weekday() >= 5 else "weekday"
        buckets[(app, hour_bucket, day_type)].append(ts)

    patterns = []
    for (app, hour_bucket, day_type), timestamps in buckets.items():
        if len(timestamps) < MIN_OCCURRENCES:
            continue
        dates = sorted(set(t.date() for t in timestamps))
        if (dates[-1] - dates[0]).days < MIN_DAY_SPAN:
            continue
        patterns.append({
            "app": app,
            "hour_bucket": hour_bucket,
            "day_type": day_type,
            "count": len(timestamps),
        })

    return patterns


# ── Pre-launch ────────────────────────────────────────────────

def _resolve_launch_cmd(app: str) -> str | None:
    for key, cmd in _APP_LAUNCH_MAP.items():
        if key in app or app in key:
            return cmd
    return None


def _launch_silently(app: str):
    cmd = _resolve_launch_cmd(app)
    if not cmd:
        logger.info(f"[Preloader] No launch command known for '{app}', skipping.")
        return
    try:
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"[Preloader] Pre-launched: {app} ({cmd})")
    except Exception as e:
        logger.warning(f"[Preloader] Launch failed for {app}: {e}")


# ── Main loop ─────────────────────────────────────────────────

def _preload_loop():
    time.sleep(120)  # wait for full boot
    _refresh_patterns()

    while _running:
        try:
            _check_and_preload()
        except Exception as e:
            logger.error(f"[Preloader] Loop error: {e}")
        time.sleep(CHECK_INTERVAL)


_cached_patterns: list[dict] = []
_last_pattern_refresh = 0.0
PATTERN_REFRESH_INTERVAL = 6 * 3600  # re-analyze every 6h


def _refresh_patterns():
    global _cached_patterns, _last_pattern_refresh
    _cached_patterns = _detect_patterns()
    _last_pattern_refresh = time.time()
    logger.info(f"[Preloader] {len(_cached_patterns)} app patterns loaded.")


def _check_and_preload():
    global _cached_patterns, _last_pattern_refresh

    if time.time() - _last_pattern_refresh > PATTERN_REFRESH_INTERVAL:
        _refresh_patterns()

    now = datetime.now(tz=IST)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    today_str = now.date().isoformat()

    # Look ahead 2 minutes
    future = now + timedelta(minutes=PRE_LAUNCH_MINUTES)
    target_bucket = (future.hour // 2) * 2

    for pat in _cached_patterns:
        if pat["day_type"] != day_type:
            continue
        if pat["hour_bucket"] != target_bucket:
            continue
        # Only fire in the first 2 minutes of the pre-launch window
        if now.minute > PRE_LAUNCH_MINUTES + 1:
            continue

        key = f"{pat['app']}:{today_str}"
        if key in _preloaded_today:
            continue

        _preloaded_today.add(key)
        app = pat["app"]
        logger.info(f"[Preloader] Pre-launching {app} (pattern: {pat['count']}x {day_type})")

        if _speak_fn:
            _speak_fn(f"Pre-loading {app} — you usually open it around now.")

        _launch_silently(app)


# ── Public query ──────────────────────────────────────────────

def list_predicted_apps() -> list[dict]:
    """Return apps predicted to open in the next 30 minutes."""
    now = datetime.now(tz=IST)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    result = []
    for pat in _cached_patterns:
        if pat["day_type"] != day_type:
            continue
        bucket_start = pat["hour_bucket"]
        bucket_end = bucket_start + 2
        if bucket_start <= now.hour < bucket_end:
            result.append(pat)
    return result
