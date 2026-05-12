import os
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = "token.json"
CREDS_PATH = "credentials.json"
TIMEZONE = "Asia/Kolkata"
IST = ZoneInfo(TIMEZONE)


def _get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("token.json missing or invalid. Re-run OAuth flow.")
    return build("calendar", "v3", credentials=creds)


def add_event(title: str, date_str: str, time_str: str, description: str = "",
              link: str = None, source_msg_id: str = None) -> dict | None:
    """
    Add event to Google Calendar.
    date_str: YYYY-MM-DD
    time_str: HH:MM (24h)
    Returns created event dict or None on failure.
    """
    try:
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
    except HttpError as e:
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
    except HttpError as e:
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
    # return closest upcoming
    now = datetime.now(tz=IST).isoformat()
    candidates.sort(key=lambda x: x.get("datetime_iso", ""))
    return candidates[0]


def get_today_events() -> list[dict]:
    """Return today's Google Calendar events sorted by start time."""
    try:
        service = _get_service()
        now = datetime.now(tz=IST)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])
    except HttpError as e:
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
    except HttpError as e:
        logger.error(f"Calendar get_upcoming_events failed: {e}")
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
    except HttpError as e:
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
    except HttpError as e:
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
    except HttpError as ex:
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
