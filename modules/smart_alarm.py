"""
smart_alarm.py
Schedules T-30min reminder + T-0 auto-action for calendar events with links.
Persists jobs across restarts — reschedules on startup for any future events.
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

JOBS_FILE = "calendar_alarm_jobs.json"
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

_speak_func = None
_active_timers: dict[str, list[threading.Timer]] = {}  # event_id → [Timer, ...]


def init(speak_fn):
    global _speak_func
    _speak_func = speak_fn
    threading.Thread(target=_load_and_reschedule, daemon=True).start()


def schedule_event_alarms(calendar_event_id: str, title: str,
                          datetime_iso: str, link: str = None, link_type: str = None):
    """
    Called after add_event(). Schedules:
      - T-30min: speak reminder
      - T-0:     auto-open Chrome if link present
    """
    try:
        event_dt = datetime.fromisoformat(datetime_iso).astimezone(IST)
    except Exception as e:
        logger.error(f"[SmartAlarm] Bad datetime_iso '{datetime_iso}': {e}")
        return

    now = datetime.now(tz=IST)
    secs_until = (event_dt - now).total_seconds()

    # Cancel any old alarms for this event first
    cancel_event_alarms(calendar_event_id, persist=False)

    timers = []

    # T-30 reminder
    remind_secs = secs_until - 1800
    if remind_secs > 10:
        t = threading.Timer(remind_secs, _fire_reminder, args=[title, event_dt, link])
        t.daemon = True
        t.start()
        timers.append(t)
        logger.info(f"[SmartAlarm] T-30 reminder in {remind_secs:.0f}s for '{title}'")

    # T-0 action
    if secs_until > 0:
        t = threading.Timer(secs_until, _fire_action, args=[calendar_event_id, title, link, link_type])
        t.daemon = True
        t.start()
        timers.append(t)
        logger.info(f"[SmartAlarm] T-0 action in {secs_until:.0f}s for '{title}'")

    if timers:
        _active_timers[calendar_event_id] = timers

    # Persist job
    _save_job(calendar_event_id, title, datetime_iso, link, link_type)


def cancel_event_alarms(calendar_event_id: str, persist: bool = True):
    """Cancel all timers for an event."""
    for t in _active_timers.pop(calendar_event_id, []):
        t.cancel()
    if persist:
        _remove_job(calendar_event_id)
    logger.info(f"[SmartAlarm] Alarms cancelled for {calendar_event_id}")


def _fire_reminder(title: str, event_dt: datetime, link: str = None):
    if not _speak_func:
        return
    time_str = event_dt.strftime("%I:%M %p").lstrip("0")
    msg = f"{title} in 30 minutes at {time_str}."
    if link:
        msg += " Link is ready."
    _speak_func(msg)


def _fire_action(calendar_event_id: str, title: str, link: str = None, link_type: str = None):
    if link and link_type in ("meet", "zoom", "teams", "other"):
        _open_link_in_chrome(link)
        if _speak_func:
            _speak_func(f"Opening {title} now.")
    else:
        if _speak_func:
            _speak_func(f"{title} is starting now.")

    # Mark job complete
    _remove_job(calendar_event_id)
    _active_timers.pop(calendar_event_id, None)


def _open_link_in_chrome(url: str):
    chrome = None
    for path in CHROME_PATHS:
        if os.path.exists(path):
            chrome = path
            break
    try:
        if chrome:
            subprocess.Popen([chrome, url])
        else:
            # fallback to default browser
            import webbrowser
            webbrowser.open(url)
        logger.info(f"[SmartAlarm] Opened link: {url}")
    except Exception as e:
        logger.error(f"[SmartAlarm] Failed to open link: {e}")


def _load_and_reschedule():
    """
    On startup: load persisted jobs, reschedule future ones.
    For missed events (past but within 30min window): execute action now.
    """
    time.sleep(5)  # give main system time to init
    jobs = _load_jobs()
    now = datetime.now(tz=IST)

    for job in jobs:
        eid     = job.get("calendar_event_id")
        title   = job.get("title", "Event")
        dt_iso  = job.get("datetime_iso", "")
        link    = job.get("link")
        ltype   = job.get("link_type")

        try:
            event_dt = datetime.fromisoformat(dt_iso).astimezone(IST)
        except Exception:
            continue

        secs_until = (event_dt - now).total_seconds()

        if secs_until > 0:
            # Future event — reschedule normally
            schedule_event_alarms(eid, title, dt_iso, link, ltype)
            logger.info(f"[SmartAlarm] Rescheduled on startup: '{title}' in {secs_until:.0f}s")

        elif -1800 < secs_until <= 0:
            # Event was in the past 30 min — missed while system was off
            # Execute action immediately if link exists
            logger.info(f"[SmartAlarm] Missed event '{title}' — executing now (was {abs(secs_until):.0f}s ago)")
            if _speak_func:
                _speak_func(f"I was offline when {title} started. Opening now.")
            _fire_action(eid, title, link, ltype)

        else:
            # Too old — clean up
            _remove_job(eid)


# ── Persistence ───────────────────────────────────────────────

def _load_jobs() -> list[dict]:
    if not os.path.exists(JOBS_FILE):
        return []
    try:
        with open(JOBS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_job(event_id, title, datetime_iso, link, link_type):
    jobs = _load_jobs()
    jobs = [j for j in jobs if j.get("calendar_event_id") != event_id]
    jobs.append({
        "calendar_event_id": event_id,
        "title": title,
        "datetime_iso": datetime_iso,
        "link": link,
        "link_type": link_type,
    })
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def _remove_job(event_id: str):
    jobs = [j for j in _load_jobs() if j.get("calendar_event_id") != event_id]
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)
