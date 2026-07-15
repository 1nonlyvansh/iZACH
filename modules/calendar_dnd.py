"""
modules/calendar_dnd.py
Calendar-driven auto-DND — enables Do Not Disturb a configurable number of
minutes before a calendar event starts, and disables it once the event ends.

Runs as a periodic poll against modules.calendar_agent (not per-event timers,
unlike modules/smart_alarm.py) so it covers every event on the calendar —
not just ones iZACH itself scheduled through conversation — and self-heals
if a poll is missed (e.g. the machine was asleep): the next poll just
re-evaluates "is a meeting window active right now" from scratch.
"""
import json
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger("iZACH.CalendarDND")

_SETTINGS_FILE = "api_keys.json"
_POLL_INTERVAL_SECONDS = 60

_thread = None
_stop_event = threading.Event()
_active_event_id = None  # calendar event currently driving an auto-DND session


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _parse_dt(dt_str: str):
    """Google returns e.g. '2026-07-16T14:00:00+05:30' for timed events, or a
    bare date ('2026-07-16') for all-day events. All-day events have no
    sensible "meeting time" to auto-DND around, so they're skipped."""
    if not dt_str or "T" not in dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except Exception:
        return None


def _poll():
    global _active_event_id
    from modules import dnd_mode
    from modules.calendar_agent import get_upcoming_events

    settings = _load_settings()
    if not settings.get("auto_dnd_before_meetings", False):
        # Setting turned off mid-session — release any session we're holding.
        if _active_event_id and dnd_mode.get_status().get("reason") == "calendar":
            dnd_mode.turn_off()
        _active_event_id = None
        return

    try:
        lead_minutes = int(settings.get("auto_dnd_lead_minutes", 5) or 5)
    except (TypeError, ValueError):
        lead_minutes = 5

    now_ts = datetime.now().astimezone().timestamp()

    try:
        events = get_upcoming_events(hours=6) or []
    except Exception as e:
        logger.warning(f"Calendar fetch failed: {e}")
        return

    current_event = None
    for e in events:
        start = _parse_dt((e.get("start") or {}).get("dateTime"))
        end = _parse_dt((e.get("end") or {}).get("dateTime"))
        if not start or not end:
            continue
        window_start_ts = start.timestamp() - lead_minutes * 60
        if window_start_ts <= now_ts < end.timestamp():
            current_event = (e.get("id"), e.get("summary", "meeting"))
            break  # events are ordered by start time — first match is enough

    status = dnd_mode.get_status()

    if current_event:
        event_id, title = current_event
        _active_event_id = event_id
        if not status.get("active"):
            dnd_mode.turn_on("calendar")
            logger.info(f'[Calendar DND] Auto-enabled for "{title}".')
        # If DND is already active for any other reason (manual, or an
        # app-detected zoom/teams/meet session), leave it exactly as-is —
        # never override an existing session, just track that a calendar
        # window is also currently open so we know not to clear it below.
    else:
        if _active_event_id and status.get("active") and status.get("reason") == "calendar":
            dnd_mode.turn_off()
            logger.info("[Calendar DND] Meeting window ended — auto-disabled.")
        _active_event_id = None


def _loop():
    while not _stop_event.is_set():
        try:
            _poll()
        except Exception as e:
            logger.warning(f"Poll error: {e}")
        _stop_event.wait(_POLL_INTERVAL_SECONDS)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    logger.info("Calendar-driven auto-DND poller started.")


def stop():
    _stop_event.set()
