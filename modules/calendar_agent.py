import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# get_upcoming_events() is polled every 5 minutes by proactive_agent's
# background loop (2 calls/cycle) as well as called directly from voice
# commands. When Calendar simply isn't configured (no token.json), that
# background polling logged the identical error forever, every 5 minutes —
# this rate-limits the "not configured" log line to once per cooldown window
# while still returning [] immediately every time so callers behave the same.
_UNCONFIGURED_LOG_COOLDOWN = 3600  # seconds
_last_unconfigured_log_ts = 0.0


def _log_upcoming_events_error(e: Exception):
    global _last_unconfigured_log_ts
    msg = str(e)
    if "token.json missing or invalid" in msg:
        now = time.time()
        if now - _last_unconfigured_log_ts < _UNCONFIGURED_LOG_COOLDOWN:
            return
        _last_unconfigured_log_ts = now
        logger.error(
            "Calendar get_upcoming_events failed: %s "
            "(this message repeats at most once an hour — connect Calendar in "
            "Settings to stop seeing it)", msg
        )
    else:
        logger.error(f"Calendar get_upcoming_events failed: {e}")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = "token.json"
CREDS_PATH = "credentials.json"
TIMEZONE = "Asia/Kolkata"
IST = ZoneInfo(TIMEZONE)

# ── One-click reconnect (Settings → Google Calendar) ───────────────────────
_reconnect_lock  = threading.Lock()
_reconnect_state = {"status": "idle", "error": "", "user": None}


def _get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
            except Exception as _refresh_err:
                # Token revoked or expired beyond refresh — delete stale file
                logger.warning(
                    f"[CALENDAR] Token refresh failed ({_refresh_err}). "
                    "Deleting token.json — re-run OAuth flow to restore Calendar access."
                )
                try:
                    os.remove(TOKEN_PATH)
                except OSError:
                    pass
                raise RuntimeError(
                    "Google Calendar token revoked. Open iZACH Settings → "
                    "re-authenticate Calendar to restore access."
                ) from _refresh_err
        else:
            raise RuntimeError("token.json missing or invalid. Re-run OAuth flow.")
    return build("calendar", "v3", credentials=creds)


def get_auth_status() -> dict:
    """Report current connection state — used by the Settings UI."""
    if _reconnect_state["status"] in ("connecting", "waiting_for_browser"):
        return {"connected": False, **_reconnect_state}
    try:
        service = _get_service()
        cal = service.calendars().get(calendarId="primary").execute()
        return {
            "connected": True, "status": "connected", "error": "",
            "user": cal.get("id") or cal.get("summary"),
        }
    except Exception as e:
        return {"connected": False, "status": "idle", "error": str(e), "user": None}


def _run_reconnect():
    """Runs in a background thread — opens the browser, waits for the user
    to log in/authorize via Google's local-server OAuth flow, then writes
    the new token.json. Blocking, so must never run on a Flask request thread."""
    global _reconnect_state
    try:
        _reconnect_state = {"status": "waiting_for_browser", "error": "", "user": None}

        if not os.path.exists(CREDS_PATH):
            raise RuntimeError(f"{CREDS_PATH} not found — download it from Google Cloud Console first.")

        # Drop any stale token so the browser flow can't silently reuse it.
        try:
            if os.path.exists(TOKEN_PATH):
                os.remove(TOKEN_PATH)
        except Exception as e:
            logger.warning(f"[CALENDAR] Could not remove old token: {e}")

        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

        service = build("calendar", "v3", credentials=creds)
        cal = service.calendars().get(calendarId="primary").execute()
        user = cal.get("id") or cal.get("summary")

        _reconnect_state = {"status": "connected", "error": "", "user": user}
        logger.info(f"[CALENDAR] Reconnected as {user}.")
    except Exception as e:
        logger.error(f"[CALENDAR] Reconnect failed: {e}")
        _reconnect_state = {"status": "error", "error": str(e), "user": None}


def start_reconnect() -> dict:
    """Kick off the one-click (re)connect flow. Non-blocking — returns
    immediately; poll get_auth_status() for progress."""
    with _reconnect_lock:
        if _reconnect_state["status"] == "waiting_for_browser":
            return {"ok": False, "error": "A connect attempt is already in progress."}
        threading.Thread(target=_run_reconnect, daemon=True).start()
        return {"ok": True, "status": "waiting_for_browser"}


def disconnect() -> dict:
    """Clear the connected account so the Settings UI can connect a
    different one."""
    global _reconnect_state
    try:
        if os.path.exists(TOKEN_PATH):
            os.remove(TOKEN_PATH)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _reconnect_state = {"status": "idle", "error": "", "user": None}
    logger.info("[CALENDAR] Disconnected.")
    return {"ok": True}


def add_event(title: str, date_str: str, time_str: str, description: str = "",
              link: str = None, source_msg_id: str = None) -> dict | None:
    """
    Add event to Google Calendar.
    date_str: YYYY-MM-DD
    time_str: HH:MM (24h)
    Returns created event dict or None on failure.
    """
    try:
        # Sanitize time_str — extractor may pass "null" / "unknown" / None
        _bad = {"null", "unknown", "none", "", "n/a", "tbd"}
        if not time_str or str(time_str).strip().lower() in _bad:
            time_str = "09:00"
        time_str = str(time_str).strip()

        service = _get_service()
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        start_dt = start_dt.replace(tzinfo=IST)
        end_dt = start_dt + timedelta(hours=1)

        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        }
        if link:
            body["description"] = f"{description}\nLink: {link}".strip()

        event = service.events().insert(calendarId="primary", body=body).execute()
        logger.info(f"Calendar event created: {event['id']} — {title}")

        # store mapping for cancellation lookups
        _save_event_mapping(
            wa_msg_id=source_msg_id,
            calendar_event_id=event["id"],
            title=title,
            datetime_iso=start_dt.isoformat(),
            link=link,
        )
        return event
    except Exception as e:
        logger.error(f"Calendar add_event failed: {e}")
        return None


def cancel_event(calendar_event_id: str) -> bool:
    """Delete event by Google Calendar event ID. Returns True on success."""
    try:
        service = _get_service()
        service.events().delete(calendarId="primary", eventId=calendar_event_id).execute()
        _remove_event_mapping(calendar_event_id)
        logger.info(f"Calendar event deleted: {calendar_event_id}")
        return True
    except Exception as e:
        logger.error(f"Calendar cancel_event failed: {e}")
        return False


def find_event_by_title_time(title_hint: str, date_str: str = None) -> dict | None:
    """
    Find stored event mapping by partial title match + optional date.
    Returns mapping dict or None.
    """
    mappings = _load_event_mappings()
    title_lower = title_hint.lower()
    candidates = [
        m for m in mappings
        if title_lower in m.get("title", "").lower()
        and (date_str is None or m.get("datetime_iso", "").startswith(date_str))
    ]
    if not candidates:
        return None
    # Return the closest UPCOMING match — `now` was computed but never
    # actually used to filter, so a title match on a past event could win
    # over the real next occurrence just by sorting first alphabetically
    # by ISO timestamp (i.e. by being earlier, not by being soonest-future).
    now = datetime.now(tz=IST).isoformat()
    candidates.sort(key=lambda x: x.get("datetime_iso", ""))
    upcoming = [c for c in candidates if c.get("datetime_iso", "") >= now]
    return upcoming[0] if upcoming else candidates[-1]


def get_today_events(date_str: str | None = None) -> list[dict]:
    """Return the given date's Google Calendar events sorted by start time.
    Defaults to today when date_str (YYYY-MM-DD) is omitted."""
    try:
        service = _get_service()
        if date_str:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=IST)
        else:
            day_start = datetime.now(tz=IST).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=0)

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])
    except Exception as e:
        logger.error(f"Calendar get_today_events failed: {e}")
        return []


def get_upcoming_events(hours: int = 24) -> list[dict]:
    """Return events in next N hours."""
    try:
        service = _get_service()
        now = datetime.now(tz=IST)
        until = now + timedelta(hours=hours)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=until.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])
    except Exception as e:
        _log_upcoming_events_error(e)
        return []


def get_next_event() -> dict | None:
    """Return the single next upcoming event or None."""
    events = get_upcoming_events(hours=24)
    return events[0] if events else None


def get_3day_events() -> list[dict]:
    """Return events for today + next 2 days (72h), enriched with local mapping data."""
    try:
        service = _get_service()
        now = datetime.now(tz=IST)
        until = now + timedelta(hours=72)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=until.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        mappings = {m["calendar_event_id"]: m for m in _load_event_mappings()}
        enriched = []
        for e in events:
            eid = e.get("id", "")
            m = mappings.get(eid, {})
            desc = e.get("description", "")
            link = m.get("link") or _extract_link_from_desc(desc)
            event_type = _infer_event_type(e.get("summary", ""), desc)
            enriched.append({
                "id": eid,
                "title": e.get("summary", "Untitled"),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
                "link": link,
                "event_type": event_type,
                "description": desc,
                "htmlLink": e.get("htmlLink", ""),
            })
        return enriched
    except Exception as e:
        logger.error(f"Calendar get_3day_events failed: {e}")
        return []


def update_event(calendar_event_id: str, title: str = None, date_str: str = None,
                 time_str: str = None, link: str = None) -> bool:
    """
    Update an existing calendar event. Pass only fields to change.
    Returns True on success.
    """
    try:
        service = _get_service()
        event = service.events().get(calendarId="primary", eventId=calendar_event_id).execute()

        if title:
            event["summary"] = title

        if date_str or time_str:
            old_start = event.get("start", {}).get("dateTime", "")
            if old_start:
                old_dt = datetime.fromisoformat(old_start).astimezone(IST)
            else:
                old_dt = datetime.now(tz=IST)

            new_date = date_str or old_dt.strftime("%Y-%m-%d")
            new_time = time_str or old_dt.strftime("%H:%M")
            new_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=IST)
            end_dt = new_dt + timedelta(hours=1)
            event["start"] = {"dateTime": new_dt.isoformat(), "timeZone": TIMEZONE}
            event["end"]   = {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE}

        if link is not None:
            desc = event.get("description", "")
            # replace old link line or append
            import re as _re
            desc = _re.sub(r"\nLink:.*", "", desc).strip()
            if link:
                desc = f"{desc}\nLink: {link}".strip()
            event["description"] = desc

        updated = service.events().update(calendarId="primary", eventId=calendar_event_id, body=event).execute()

        # sync mapping
        mappings = _load_event_mappings()
        for m in mappings:
            if m.get("calendar_event_id") == calendar_event_id:
                if title:
                    m["title"] = title
                if date_str or time_str:
                    m["datetime_iso"] = updated["start"]["dateTime"]
                if link is not None:
                    m["link"] = link
        with open(MAPPING_FILE, "w") as f:
            json.dump(mappings, f, indent=2)

        logger.info(f"Calendar event updated: {calendar_event_id}")
        return True
    except Exception as e:
        logger.error(f"Calendar update_event failed: {e}")
        return False


def find_event_by_voice_cmd(title_hint: str, date_hint: str = None) -> dict | None:
    """
    Find a calendar event matching voice command hint.
    Searches both local mapping AND live Google Calendar (next 7 days).
    Returns enriched dict with calendar_event_id or None.
    """
    # first try local mapping
    local = find_event_by_title_time(title_hint, date_hint)
    if local:
        return local

    # fallback: search live calendar
    try:
        service = _get_service()
        now = datetime.now(tz=IST)
        until = now + timedelta(days=7)
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=until.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            q=title_hint,
        ).execute()
        items = result.get("items", [])
        if items:
            e = items[0]
            start_iso = e.get("start", {}).get("dateTime", "")
            return {
                "calendar_event_id": e["id"],
                "title": e.get("summary", ""),
                "datetime_iso": start_iso,
                "link": _extract_link_from_desc(e.get("description", "")),
            }
    except Exception as ex:
        logger.error(f"find_event_by_voice_cmd live search failed: {ex}")
    return None


def _extract_link_from_desc(desc: str) -> str | None:
    import re as _re
    m = _re.search(r"Link:\s*(https?://\S+)", desc)
    return m.group(1) if m else None


def _infer_event_type(title: str, desc: str) -> str:
    combined = (title + " " + desc).lower()
    if any(w in combined for w in ["class", "lecture", "course", "tutorial", "lab"]):
        return "class"
    if any(w in combined for w in ["meeting", "meet", "call", "zoom", "teams", "conference"]):
        return "meeting"
    if any(w in combined for w in ["gym", "workout", "exercise", "fitness", "yoga", "run"]):
        return "social"
    if any(w in combined for w in ["appointment", "doctor", "dentist", "clinic"]):
        return "appointment"
    return "other"


def format_event_for_speech(event: dict) -> str:
    """Convert Calendar event dict to readable string for TTS."""
    title = event.get("summary", "Untitled")
    start = event.get("start", {}).get("dateTime", "")
    if start:
        dt = datetime.fromisoformat(start).astimezone(IST)
        time_str = dt.strftime("%I:%M %p")
        return f"{title} at {time_str}"
    return title


# --- Local event mapping store (JSON file, no MongoDB dependency) ---

MAPPING_FILE = "calendar_event_map.json"


def _load_event_mappings() -> list[dict]:
    if not os.path.exists(MAPPING_FILE):
        return []
    with open(MAPPING_FILE, "r") as f:
        return json.load(f)


def _save_event_mapping(wa_msg_id, calendar_event_id, title, datetime_iso, link):
    mappings = _load_event_mappings()
    mappings.append({
        "wa_msg_id": wa_msg_id,
        "calendar_event_id": calendar_event_id,
        "title": title,
        "datetime_iso": datetime_iso,
        "link": link,
        "status": "active",
    })
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f, indent=2)


def _remove_event_mapping(calendar_event_id: str):
    mappings = _load_event_mappings()
    mappings = [m for m in mappings if m.get("calendar_event_id") != calendar_event_id]
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f, indent=2)
