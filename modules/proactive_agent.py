"""
proactive_agent.py
Phase 4: Daemon thread that checks system state every 5 minutes and speaks
proactively without being asked. iZACH becomes aware instead of just reactive.

Checks every loop:
  1. Upcoming calendar events (announce at T-60min, T-15min)
  2. Weather vs outdoor events (rain warning)
  3. Morning briefing (once per day at configured time)
  4. Idle nudge (user hasn't spoken in N hours)
"""

import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

INTERVAL_SECS = 300  # 5 minutes

_speak_func = None
_running    = False

# ── Dedup state (in-memory, resets on restart) ────────────────
_announced_events: dict[str, set] = {}   # event_id → {"60min", "15min"}
_morning_briefing_done_date: str  = ""
_weather_warned_events: set       = set()
_last_interaction_time: float     = time.time()


def init(speak_fn):
    global _speak_func
    _speak_func = speak_fn


def start():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, daemon=True).start()
    logger.info("[ProactiveAgent] Started.")


def stop():
    global _running
    _running = False


def record_interaction():
    """Call from main voice loop each time user speaks."""
    global _last_interaction_time
    _last_interaction_time = time.time()


# ── Main loop ─────────────────────────────────────────────────

def _loop():
    time.sleep(30)  # wait for system to fully init
    while _running:
        try:
            if _get_setting("proactive_enabled", True):
                _check_morning_briefing()
                _check_upcoming_events()
                _check_weather_outdoor_clash()
                _check_pattern_suggestion()
        except Exception as e:
            logger.error(f"[ProactiveAgent] Loop error: {e}")
        time.sleep(INTERVAL_SECS)


# ── Check 1: Morning briefing ─────────────────────────────────

def _check_morning_briefing():
    global _morning_briefing_done_date

    briefing_time = _get_setting("morning_briefing_time", "08:00")
    now = datetime.now(tz=IST)
    today_str = now.strftime("%Y-%m-%d")

    if _morning_briefing_done_date == today_str:
        return

    try:
        target_h, target_m = map(int, briefing_time.split(":"))
    except Exception:
        return

    if now.hour != target_h or now.minute > target_m + 9:
        return

    # Fire briefing
    _morning_briefing_done_date = today_str
    threading.Thread(target=_deliver_morning_briefing, daemon=True).start()


def _deliver_morning_briefing():
    if not _speak_func:
        return
    try:
        import psutil
        now = datetime.now(tz=IST)
        greeting = _time_greeting(now.hour)

        parts = [greeting]

        # Calendar events — check briefing_calendar (UI key); fall back to briefing_events
        _cal_default = _get_setting("briefing_events", True)
        if _get_setting("briefing_calendar", _cal_default):
            try:
                from modules.calendar_agent import get_today_events, format_event_for_speech
                events = get_today_events() or []
                if not events:
                    parts.append("No events on your calendar today")
                elif len(events) == 1:
                    parts.append(f"One event today: {format_event_for_speech(events[0])}")
                else:
                    ev_parts = [format_event_for_speech(e) for e in events[:4]]
                    parts.append(f"{len(events)} events today: {', then '.join(ev_parts)}")
            except Exception as ce:
                logger.warning(f"[ProactiveAgent] Calendar unavailable for briefing: {ce}")

        # Battery status — briefing_system (UI key) or briefing_battery_status
        _sys_default = _get_setting("briefing_battery_status", False)
        if _get_setting("briefing_system", _sys_default):
            battery = psutil.sensors_battery()
            if battery:
                parts.append(f"Battery at {int(battery.percent)}%")

        # RAM — briefing_system (UI key) or briefing_ram
        _ram_default = _get_setting("briefing_ram", False)
        if _get_setting("briefing_system", _ram_default):
            vm = psutil.virtual_memory()
            parts.append(f"Memory at {vm.percent:.0f}%")

        if len(parts) == 1:
            # Only greeting — no items enabled, skip
            logger.info("[ProactiveAgent] Morning briefing skipped — no items enabled.")
            return

        msg = ". ".join(parts) + "."
        _speak_func(msg)
        logger.info("[ProactiveAgent] Morning briefing delivered.")
    except Exception as e:
        logger.error(f"[ProactiveAgent] Morning briefing error: {e}")


# ── Check 2: Upcoming events ─────────────────────────────────

def _check_upcoming_events():
    try:
        from modules.calendar_agent import get_upcoming_events, format_event_for_speech
        events = get_upcoming_events(hours=2)  # only look 2h ahead
    except Exception:
        return

    now = datetime.now(tz=IST)
    for event in events:
        eid  = event.get("id", "")
        start_raw = event.get("start", {}).get("dateTime", "")
        if not start_raw or not eid:
            continue

        try:
            event_dt = datetime.fromisoformat(start_raw).astimezone(IST)
        except Exception:
            continue

        mins_until = (event_dt - now).total_seconds() / 60
        announced = _announced_events.setdefault(eid, set())

        if 55 <= mins_until <= 65 and "60min" not in announced:
            announced.add("60min")
            title = event.get("summary", "Event")
            time_str = event_dt.strftime("%I:%M %p").lstrip("0")
            _speak_func and _speak_func(f"{title} in about an hour, at {time_str}.")
            _push_calendar_notification(title, f"In about an hour, at {time_str}.")

        elif 10 <= mins_until <= 20 and "15min" not in announced:
            announced.add("15min")
            title = event.get("summary", "Event")
            desc = event.get("description", "")
            has_link = "http" in desc
            msg = f"{title} in 15 minutes."
            if has_link:
                msg += " Link is ready."
            _speak_func and _speak_func(msg)
            _push_calendar_notification(title, msg)


def _push_calendar_notification(title: str, body: str):
    # Calendar reminders used to be voice-only — nothing queryable was ever
    # left behind, so /notifications/history (and the unified feed) never
    # showed them. Now also recorded like every other notification source.
    try:
        from modules.notification_system import push
        push(title, category="alerts", body=body, source="calendar")
    except Exception:
        pass


# ── Check 3: Weather vs outdoor events ────────────────────────

_OUTDOOR_KEYWORDS = [
    "golf", "gym", "cricket", "football", "basketball", "tennis",
    "run", "jog", "walk", "hike", "trek", "cycling", "swimming",
    "outdoor", "park", "ground", "field", "pitch",
]

def _check_weather_outdoor_clash():
    try:
        from modules.calendar_agent import get_upcoming_events
        events = get_upcoming_events(hours=24)
    except Exception:
        return

    outdoor = [
        e for e in events
        if any(kw in e.get("summary", "").lower() for kw in _OUTDOOR_KEYWORDS)
        and e.get("id") not in _weather_warned_events
    ]

    if not outdoor:
        return

    rain_pct = _get_rain_chance()
    if rain_pct is None or rain_pct < 60:
        return

    for e in outdoor:
        eid   = e.get("id", "")
        title = e.get("summary", "your outdoor event")
        start_raw = e.get("start", {}).get("dateTime", "")
        time_str  = ""
        if start_raw:
            try:
                dt = datetime.fromisoformat(start_raw).astimezone(IST)
                time_str = f" at {dt.strftime('%I:%M %p').lstrip('0')}"
            except Exception:
                pass

        _weather_warned_events.add(eid)
        _speak_func and _speak_func(
            f"Heads up — {rain_pct}% chance of rain today. "
            f"You have {title}{time_str} on your calendar. Might want to reschedule."
        )


def _get_rain_chance() -> int | None:
    """Returns rain probability % from wttr.in or None on failure."""
    city = _get_setting("weather_city", "New Delhi").replace(" ", "+")
    try:
        r = requests.get(
            f"https://wttr.in/{city}?format=j1",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=8,
        )
        data = r.json()
        hourly = data["weather"][0]["hourly"]
        if hourly:
            chances = [int(h.get("chanceofrain", 0)) for h in hourly]
            return max(chances)
    except Exception as e:
        logger.debug(f"[ProactiveAgent] Rain check failed: {e}")
    return None


# ── Helpers ───────────────────────────────────────────────────

def _get_setting(key: str, default):
    try:
        with open("api_keys.json") as f:
            return json.load(f).get(key, default)
    except Exception:
        return default


# ── Check 4: Pattern suggestion ───────────────────────────────

_last_pattern_offer_ts: float = 0.0

def _check_pattern_suggestion():
    global _last_pattern_offer_ts
    if not _get_setting("pattern_automation_suggestions_enabled", True):
        return
    if time.time() - _last_pattern_offer_ts < 3600:  # offer at most once per hour
        return
    try:
        from modules.pattern_learner import offer_next_pattern
        pattern = offer_next_pattern()
        if not pattern or not _speak_func:
            return

        _last_pattern_offer_ts = time.time()
        cmd   = pattern.get("example_cmd", "")
        day_type = pattern.get("day_type", "")
        hb    = pattern.get("hour_bucket", 0)
        count = pattern.get("count", 0)
        time_str = f"{hb:02d}:00"
        day_desc  = "every weekday" if day_type == "weekday" else "every weekend"
        _speak_func(
            f"I noticed you {cmd} {day_desc} around {time_str}, "
            f"{count} times in the last month. "
            f"Want me to automate this? Say 'yes automate it' or 'no skip'."
        )
        logger.info(f"[ProactiveAgent] Offered pattern: {pattern['id']}")
    except Exception as e:
        logger.debug(f"[ProactiveAgent] Pattern check error: {e}")


def _time_greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"
