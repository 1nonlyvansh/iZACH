"""
event_extractor.py
Hinglish-aware NLP pipeline: WhatsApp message → structured event dict.
Uses Groq for extraction, then calls calendar_agent to act on results.
"""

import json
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from groq import Groq

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_groq_client: Groq | None = None
_speak_func = None
_pending_events: list = []
_pending_lock = threading.Lock()


def init(speak_fn=None):
    global _groq_client, _speak_func
    _speak_func = speak_fn
    import os
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        # fallback: some setups store in .env file
        try:
            from dotenv import dotenv_values
            groq_key = dotenv_values(".env").get("GROQ_API_KEY", "")
        except Exception:
            pass
    if groq_key:
        _groq_client = Groq(api_key=groq_key)
        logger.info("[EventExtractor] Groq client ready.")
    else:
        logger.warning("[EventExtractor] No GROQ_API_KEY in environment.")


def process_message(text: str, sender: str, msg_id: str = None, timestamp: str = None):
    """
    Entry point. Call from incoming_message() in whatsapp_handler.
    Runs in background thread — non-blocking.
    """
    threading.Thread(
        target=_process,
        args=(text, sender, msg_id, timestamp),
        daemon=True
    ).start()


def _process(text: str, sender: str, msg_id: str, timestamp: str):
    if not _groq_client:
        return

    extracted = _extract(text, sender, timestamp)
    if not extracted:
        return

    confidence = extracted.get("confidence", 0)
    if confidence < 0.80:
        logger.info(f"[EventExtractor] Low confidence ({confidence:.2f}), skipping: {text[:60]}")
        return

    is_event = extracted.get("is_event", False)
    is_cancellation = extracted.get("is_cancellation", False)
    is_reschedule = extracted.get("is_reschedule", False)

    if is_cancellation:
        _handle_cancellation(extracted, sender)
    elif is_reschedule:
        _handle_reschedule(extracted, sender)
    elif is_event:
        _queue_for_confirmation(extracted, sender, msg_id)


def _extract(text: str, sender: str, timestamp: str) -> dict | None:
    now = datetime.now(tz=IST)
    today_str = now.strftime("%Y-%m-%d")
    today_name = now.strftime("%A, %d %B %Y")

    prompt = f"""You are an event parser for a personal AI assistant.
Extract event information from this WhatsApp message.
The message may be in English, Hindi, or Hinglish (mix of both).

Today is: {today_name} ({today_str})
Sender: {sender}
Message: "{text}"

Return ONLY a valid JSON object with these fields:
{{
  "is_event": true or false,
  "is_cancellation": true or false,
  "is_reschedule": true or false,
  "event_type": "class|meeting|social|appointment|reminder|other",
  "title": "short event title in English",
  "date": "YYYY-MM-DD or null",
  "time": "HH:MM in 24h format or null",
  "new_time": "HH:MM in 24h format or null (only for reschedule, the NEW time)",
  "new_date": "YYYY-MM-DD or null (only for reschedule, the NEW date)",
  "link": "full URL if present or null",
  "link_type": "meet|zoom|teams|other|null",
  "cancels_what": "description of what is being cancelled or rescheduled, or null",
  "confidence": 0.0 to 1.0
}}

Rules:
- "aaj" or "today" = {today_str}
- "kal" = tomorrow
- "baje" after a number = that hour (e.g. "3 baje" = 03:00 or 15:00, use context)
- If time is ambiguous, prefer PM for afternoon/evening context
- "cancel", "nahi hogi", "nahi hai" = is_cancellation true
- "instead of", "moved to", "ab X baje", "postponed to", "rescheduled to" = is_reschedule true
- For reschedule: date/time = ORIGINAL time, new_date/new_time = NEW time
- Only set is_event true if there is a clear future event with at least a time or date
- confidence should reflect how certain you are about the extraction
- For social messages ("bhai kaisa hai", "kya kar rha"), is_event = false, confidence = 0.1

Return ONLY the JSON. No explanation, no markdown, no code blocks."""

    try:
        resp = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        # strip markdown if model wraps in ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.warning(f"[EventExtractor] JSON parse failed: {e} | raw: {raw[:100]}")
        return None
    except Exception as e:
        logger.error(f"[EventExtractor] Groq call failed: {e}")
        return None


def _queue_for_confirmation(extracted: dict, sender: str, msg_id: str):
    with _pending_lock:
        was_empty = len(_pending_events) == 0
        _pending_events.append((extracted, sender, msg_id))
    if was_empty:
        _ask_about_pending()


def _ask_about_pending():
    with _pending_lock:
        if not _pending_events:
            return
        extracted, sender, _ = _pending_events[0]

    title = extracted.get("title") or "Untitled Event"
    date_str = extracted.get("date")
    time_str = extracted.get("time")

    date_readable = ""
    if date_str:
        try:
            date_readable = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B")
        except Exception:
            date_readable = date_str

    time_readable = ""
    if time_str:
        try:
            time_readable = f" at {datetime.strptime(time_str, '%H:%M').strftime('%I:%M %p').lstrip('0')}"
        except Exception:
            time_readable = f" at {time_str}"

    question = f"Should I add {title}"
    if date_readable:
        question += f" on {date_readable}"
    question += f"{time_readable} to your calendar?"

    if _speak_func:
        _speak_func(question)


def has_pending_event() -> bool:
    with _pending_lock:
        return bool(_pending_events)


def confirm_pending_event() -> bool:
    with _pending_lock:
        if not _pending_events:
            return False
        extracted, sender, msg_id = _pending_events.pop(0)
        remaining = len(_pending_events)

    threading.Thread(target=_handle_new_event, args=(extracted, sender, msg_id), daemon=True).start()

    if remaining:
        threading.Timer(2.0, _ask_about_pending).start()
    return True


def reject_pending_event() -> bool:
    with _pending_lock:
        if not _pending_events:
            return False
        extracted, _, _ = _pending_events.pop(0)
        remaining = len(_pending_events)

    title = extracted.get("title", "that event")
    if _speak_func:
        _speak_func(f"Okay, skipping {title}.")

    if remaining:
        threading.Timer(1.5, _ask_about_pending).start()
    return True


def _handle_new_event(extracted: dict, sender: str, msg_id: str):
    from modules.calendar_agent import add_event, format_event_for_speech

    title = extracted.get("title") or "Untitled Event"
    date_str = extracted.get("date")
    time_str = extracted.get("time") or "09:00"
    link = extracted.get("link")
    event_type = extracted.get("event_type", "other")

    if not date_str:
        logger.info(f"[EventExtractor] Incomplete event (no date): {extracted}")
        return

    description = f"From WhatsApp message by {sender}"
    event = add_event(
        title=title,
        date_str=date_str,
        time_str=time_str,
        description=description,
        link=link,
        source_msg_id=msg_id,
    )

    if event and _speak_func:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        time_readable = dt.strftime("%I:%M %p").lstrip("0")
        date_readable = dt.strftime("%d %B")
        speech = f"{sender} mentioned {title} at {time_readable} on {date_readable}. Added to your calendar."
        if link:
            speech += " Link saved."
        _speak_func(speech)
        logger.info(f"[EventExtractor] Event added: {title} on {date_str} at {time_str}")

    # schedule alarms if event has a link or is a class/meeting
    if event:
        try:
            from modules.smart_alarm import schedule_event_alarms
            schedule_event_alarms(
                calendar_event_id=event["id"],
                title=title,
                datetime_iso=event["start"]["dateTime"],
                link=link,
                link_type=extracted.get("link_type") if isinstance(extracted, dict) else None,
            )
        except Exception as _se:
            logger.warning(f"[EventExtractor] SmartAlarm schedule failed: {_se}")


def _handle_reschedule(extracted: dict, sender: str):
    from modules.calendar_agent import find_event_by_title_time, update_event

    cancels_what = extracted.get("cancels_what") or extracted.get("title") or ""
    date_str = extracted.get("date")
    new_time = extracted.get("new_time")
    new_date = extracted.get("new_date")

    if not cancels_what or not (new_time or new_date):
        logger.info("[EventExtractor] Reschedule detected but missing target or new time.")
        return

    mapping = find_event_by_title_time(cancels_what, date_str)
    if not mapping:
        logger.info(f"[EventExtractor] No matching event found to reschedule: {cancels_what}")
        return

    ok = update_event(
        calendar_event_id=mapping["calendar_event_id"],
        time_str=new_time,
        date_str=new_date,
    )
    if ok:
        # reschedule alarms with new time
        try:
            from modules.smart_alarm import cancel_event_alarms, schedule_event_alarms
            from modules.calendar_agent import _load_event_mappings
            cancel_event_alarms(mapping["calendar_event_id"], persist=False)
            # find updated datetime from mappings
            for m in _load_event_mappings():
                if m.get("calendar_event_id") == mapping["calendar_event_id"]:
                    schedule_event_alarms(
                        m["calendar_event_id"], m.get("title", ""),
                        m.get("datetime_iso", ""), m.get("link")
                    )
                    break
        except Exception as _se:
            logger.warning(f"[EventExtractor] SmartAlarm reschedule failed: {_se}")
    if ok and _speak_func:
        title = mapping.get("title", "event")
        new_t = new_time or ""
        if new_t:
            from datetime import datetime as _dt
            try:
                t = _dt.strptime(new_t, "%H:%M").strftime("%I:%M %p").lstrip("0")
                new_t = f" to {t}"
            except Exception:
                new_t = f" to {new_t}"
        _speak_func(f"{sender} rescheduled {title}{new_t}. Calendar updated.")
        logger.info(f"[EventExtractor] Rescheduled: {title} -> {new_time or new_date}")


def _handle_cancellation(extracted: dict, sender: str):
    from modules.calendar_agent import find_event_by_title_time, cancel_event

    cancels_what = extracted.get("cancels_what") or extracted.get("title") or ""
    date_str = extracted.get("date")

    if not cancels_what:
        logger.info("[EventExtractor] Cancellation detected but no target identified.")
        return

    mapping = find_event_by_title_time(cancels_what, date_str)
    if not mapping:
        logger.info(f"[EventExtractor] No matching event found to cancel: {cancels_what}")
        return

    ok = cancel_event(mapping["calendar_event_id"])
    if ok:
        try:
            from modules.smart_alarm import cancel_event_alarms
            cancel_event_alarms(mapping["calendar_event_id"])
        except Exception:
            pass
    if ok and _speak_func:
        title = mapping.get("title", "event")
        dt_iso = mapping.get("datetime_iso", "")
        time_str = ""
        if dt_iso:
            try:
                dt = datetime.fromisoformat(dt_iso)
                time_str = f" at {dt.strftime('%I:%M %p').lstrip('0')}"
            except Exception:
                pass
        _speak_func(f"{sender} cancelled {title}{time_str}. Removed from your calendar.")
        logger.info(f"[EventExtractor] Cancelled event: {title}")
