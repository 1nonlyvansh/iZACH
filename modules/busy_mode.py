"""
modules/busy_mode.py
Busy Mode — iZACH handles WhatsApp while user is occupied (gym, studying, etc.)
NOT the same as DND (mic stays active, iZACH still responds to voice).

Public API:
  init(speak_fn, broadcast_fn)
  is_active() -> bool
  turn_on(reason="manual", duration_min=None)   # duration_min → auto-off timer
  turn_off()
  get_status() -> dict
  concise_system_prefix() -> str
  get_log() -> list                              # busy session log
  get_persona_context() -> str                  # reason-aware persona string
"""

import json
import logging
import os
import threading
import time
import re

logger = logging.getLogger(__name__)

_LOG_FILE      = os.path.join(os.path.dirname(os.path.dirname(__file__)), "busy_session.jsonl")
# Was hardcoded to a Windows path (C:\iZACH\iZACH-brain) — silently never
# worked on macOS since os.makedirs() there just creates a literal folder
# named that string rather than failing. Now matches modules/obsidian_brain.py's
# VAULT_PATH default (same vault, same override convention).
_OBSIDIAN_DIR  = os.environ.get(
    "OBSIDIAN_VAULT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iZACH-Brain"),
)

# ── State ──────────────────────────────────────────────────────
_lock          = threading.Lock()
_active        = False
_reason        = "manual"       # "gym" | "studying" | "sleeping" | "eating" | "manual" | …
_started_at    = 0.0
_duration_min  = None           # None = no auto-off; int = auto-off after N min
_session_msgs  = []             # messages handled this busy session
_speak_fn      = None
_broadcast_fn  = None

# ── Reason → Persona mapping ───────────────────────────────────
_REASON_PERSONAS = {
    "gym": {
        "label":     "at the gym",
        "hint":      "Vansh is crushing a workout right now.",
        "eta":       "He usually wraps up in about 1–1.5 hours.",
        "emoji":     "💪",
    },
    "studying": {
        "label":     "studying / deep work",
        "hint":      "Vansh is in deep study mode — no interruptions!",
        "eta":       "He'll check messages in a couple of hours.",
        "emoji":     "📚",
    },
    "sleeping": {
        "label":     "sleeping / resting",
        "hint":      "Vansh is getting some rest — he'll reply when he wakes up.",
        "eta":       "Usually checks messages in the morning.",
        "emoji":     "😴",
    },
    "eating": {
        "label":     "having a meal",
        "hint":      "Vansh stepped away for a meal break.",
        "eta":       "Should be back in 20–30 minutes.",
        "emoji":     "🍽️",
    },
    "driving": {
        "label":     "driving / commuting",
        "hint":      "Vansh is on the road right now — can't text.",
        "eta":       "Should be reachable in 30–60 minutes.",
        "emoji":     "🚗",
    },
    "meeting": {
        "label":     "in a meeting",
        "hint":      "Vansh is in a meeting and can't check messages.",
        "eta":       "He'll reply once the meeting wraps up.",
        "emoji":     "🤝",
    },
    "manual": {
        "label":     "temporarily unavailable",
        "hint":      "Vansh is unavailable at the moment.",
        "eta":       "He'll get back to you shortly.",
        "emoji":     "🤖",
    },
}

def _get_persona(reason: str) -> dict:
    r = reason.lower().strip()
    # partial match (e.g. "gym session" → "gym")
    for key in _REASON_PERSONAS:
        if key in r:
            return _REASON_PERSONAS[key]
    return _REASON_PERSONAS["manual"]


# ── Init ──────────────────────────────────────────────────────
def init(speak_fn=None, broadcast_fn=None):
    global _speak_fn, _broadcast_fn
    _speak_fn     = speak_fn
    _broadcast_fn = broadcast_fn
    logger.info("[BUSY] Initialized.")


# ── Public API ─────────────────────────────────────────────────
def is_active() -> bool:
    with _lock:
        return _active


def turn_on(reason: str = "manual", duration_min=None):
    global _active, _reason, _started_at, _duration_min, _session_msgs
    with _lock:
        if _active:
            return   # already busy
        _active       = True
        _reason       = reason or "manual"
        _started_at   = time.time()
        _duration_min = int(duration_min) if duration_min else None
        _session_msgs = []

    logger.info(f"[BUSY] ON — reason: {_reason}, timer: {_duration_min}min")
    _broadcast_state()

    # Auto-off timer thread
    if _duration_min:
        threading.Thread(
            target=_auto_off_timer,
            args=(_duration_min, _started_at),
            daemon=True,
            name="busy-auto-off",
        ).start()

    if _speak_fn:
        persona = _get_persona(_reason)
        try:
            _speak_fn(
                f"Busy mode on. Reason: {persona['label']}. "
                + (f"Auto-off in {_duration_min} minutes. " if _duration_min else "")
                + "I'll handle WhatsApp for you."
            )
        except Exception:
            pass


def turn_off():
    global _active, _reason, _started_at, _duration_min
    with _lock:
        if not _active:
            return
        was_reason  = _reason
        session_dur = time.time() - _started_at
        msgs_snap   = list(_session_msgs)
        _active       = False
        _reason       = "manual"
        _duration_min = None

    logger.info(f"[BUSY] OFF — session: {int(session_dur//60)}min, {len(msgs_snap)} msgs handled")

    _save_session_log(was_reason, session_dur, msgs_snap)
    _save_to_obsidian(was_reason, session_dur, msgs_snap)
    _broadcast_state()
    _deliver_briefing(msgs_snap, session_dur)


def get_status() -> dict:
    with _lock:
        elapsed = int(time.time() - _started_at) if _active else 0
        remaining = None
        if _active and _duration_min:
            remaining = max(0, _duration_min * 60 - elapsed)
        return {
            "active":        _active,
            "reason":        _reason,
            "started_at":    _started_at,
            "elapsed_sec":   elapsed,
            "duration_min":  _duration_min,
            "remaining_sec": remaining,
            "msg_count":     len(_session_msgs),
        }


def get_log() -> list:
    """Return recent busy session entries from log file."""
    try:
        if not os.path.exists(_LOG_FILE):
            return []
        entries = []
        with open(_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        return list(reversed(entries[-20:]))   # latest 20
    except Exception:
        return []


def get_persona_context() -> str:
    """Return persona hint string for AI prompt injection."""
    with _lock:
        if not _active:
            return ""
        reason = _reason
    p = _get_persona(reason)
    return f"{p['hint']} {p['eta']}"


def concise_system_prefix() -> str:
    """Inject into AI prompt when busy. Reason-aware persona."""
    with _lock:
        if not _active:
            return ""
        reason = _reason
        started = _started_at

    p = _get_persona(reason)
    elapsed = int((time.time() - started) // 60)

    return (
        f"[BUSY MODE] User is {p['label']} {p['emoji']}. "
        f"{p['hint']} {p['eta']} "
        f"(has been busy for ~{elapsed} min). "
        "Reply as iZACH — warm, helpful, natural. "
        "Ask what they need. Offer to take a note or relay the message. "
        "Do NOT pretend to be human; be upfront that you're an AI assistant. "
        "Keep reply under 3 sentences.\n\n"
    )


def log_message(sender: str, number: str, text: str, reply: str):
    """Record a handled message to the session log (called by N8N/direct reply)."""
    entry = {
        "ts":     int(time.time()),
        "sender": sender,
        "number": number,
        "text":   text,
        "reply":  reply,
    }
    with _lock:
        _session_msgs.append(entry)


def extract_callback_time(ai_reply: str) -> str | None:
    """
    Parse callback time from AI reply or sender message.
    Returns HH:MM string or None.
    e.g. "I'll be free at 4:30 PM" → "4:30 PM"
         "call at 5 baje" → "5:00 PM" (heuristic)
    """
    # Standard time patterns: 4:30 PM / 16:30 / 4 PM / 5 baje
    patterns = [
        r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b',
        r'\b(\d{1,2}\s*(?:AM|PM|am|pm))\b',
        r'\b(\d{1,2}:\d{2})\b',
        r'\b(\d{1,2})\s*baje\b',
    ]
    for pat in patterns:
        m = re.search(pat, ai_reply, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def create_callback_event(sender: str, number: str, callback_time_str: str):
    """Create a Google Calendar callback reminder from extracted time."""
    try:
        import datetime as _dt
        from modules.calendar_engine import get_service as _gcal_svc

        # Parse time (simple: today at that hour)
        now = _dt.datetime.now()
        t = callback_time_str.strip()
        # Try parsing  "4:30 PM" style
        for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
            try:
                parsed = _dt.datetime.strptime(t.upper(), fmt)
                callback_dt = now.replace(
                    hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                )
                if callback_dt < now:
                    callback_dt += _dt.timedelta(days=1)
                break
            except ValueError:
                callback_dt = None

        if not callback_dt:
            logger.debug(f"[BUSY] Could not parse callback time: {t}")
            return

        svc   = _gcal_svc()
        start = callback_dt.isoformat()
        end   = (callback_dt + _dt.timedelta(minutes=15)).isoformat()
        tz    = "Asia/Kolkata"

        svc.events().insert(calendarId="primary", body={
            "summary":     f"📞 Call back {sender} (iZACH Busy)",
            "description": f"Number: {number}\nCallback time extracted by iZACH busy mode.",
            "start":       {"dateTime": start, "timeZone": tz},
            "end":         {"dateTime": end,   "timeZone": tz},
            "reminders":   {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]},
        }).execute()
        logger.info(f"[BUSY] Callback event created: {sender} at {callback_time_str}")
    except Exception as e:
        logger.debug(f"[BUSY] Callback event failed: {e}")


# ── Internal helpers ───────────────────────────────────────────
def _auto_off_timer(duration_min: int, started_at: float):
    """Sleep until timer expires, then auto-turn-off busy mode."""
    target = started_at + duration_min * 60
    while True:
        now = time.time()
        if now >= target:
            break
        time.sleep(min(30, target - now))

    with _lock:
        still_active = _active and abs(_started_at - started_at) < 1
    if still_active:
        logger.info(f"[BUSY] Auto-off after {duration_min}min")
        turn_off()


def _broadcast_state():
    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "busy_status", **get_status()})
        except Exception:
            pass


def _deliver_briefing(msgs: list, duration_sec: float):
    """Voice + WS briefing when busy mode ends."""
    dur_min = int(duration_sec // 60)
    count   = len(msgs)

    if _speak_fn:
        try:
            if count:
                senders = list({m["sender"] for m in msgs})[:3]
                s = ", ".join(senders)
                _speak_fn(
                    f"Busy mode off. {count} message{'s' if count > 1 else ''} handled "
                    f"from {s} over {dur_min} minutes. Check the busy log for details."
                )
            else:
                _speak_fn(f"Busy mode off. No messages came in while you were busy.")
        except Exception:
            pass

    if _broadcast_fn:
        try:
            _broadcast_fn({
                "type":       "busy_briefing",
                "duration_min": dur_min,
                "msg_count":  count,
                "messages":   msgs,
            })
        except Exception:
            pass


def _save_session_log(reason: str, duration_sec: float, msgs: list):
    """Append session summary to JSONL log."""
    try:
        entry = {
            "ts":           int(time.time()),
            "reason":       reason,
            "duration_min": round(duration_sec / 60, 1),
            "msg_count":    len(msgs),
            "messages":     msgs,
        }
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[BUSY] Log save failed: {e}")


def _save_to_obsidian(reason: str, duration_sec: float, msgs: list):
    """Append session to Obsidian daily note."""
    try:
        import datetime as _dt
        date_str = _dt.date.today().strftime("%Y-%m-%d")
        note_dir = os.path.join(_OBSIDIAN_DIR, "Daily Notes")
        os.makedirs(note_dir, exist_ok=True)
        note_path = os.path.join(note_dir, f"{date_str}.md")

        dur_min = round(duration_sec / 60, 1)
        persona = _get_persona(reason)
        lines   = [
            f"\n## 🤖 iZACH Busy Session — {time.strftime('%H:%M')}",
            f"**Reason:** {persona['label']} {persona['emoji']}",
            f"**Duration:** {dur_min} min",
            f"**Messages handled:** {len(msgs)}",
        ]
        for m in msgs[:10]:
            ts  = time.strftime("%H:%M", time.localtime(m.get("ts", 0)))
            lines.append(f"- [{ts}] **{m.get('sender','?')}**: {m.get('text','')[:80]}")

        with open(note_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"[BUSY] Obsidian session saved: {note_path}")
    except Exception as e:
        logger.debug(f"[BUSY] Obsidian save failed: {e}")
