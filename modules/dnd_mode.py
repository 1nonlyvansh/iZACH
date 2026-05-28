"""
modules/dnd_mode.py
Do Not Disturb state manager for iZACH.

When DND is active:
  - speak() calls are suppressed (no audio)
  - Mic voice loop is paused
  - Alerts/messages → Windows toast + WS overlay
  - Text commands still work but AI replies ultra-concise
  - Meeting auto-detect (Google Meet, Zoom, Teams)

Public API:
  init(speak_fn, broadcast_fn)
  is_active() -> bool
  turn_on(reason="manual")
  turn_off()
  get_status() -> dict
  get_queue() -> list
  add_to_queue(item: dict)
  mark_handle(idx) -> bool
  mark_busy(idx) -> bool
  concise_system_prefix() -> str
"""

import json
import logging
import os
import threading
import time
import random

logger = logging.getLogger(__name__)

_QUEUE_FILE = "dnd_queue.json"

# ── State ──────────────────────────────────────────────────────
_lock          = threading.Lock()
_active        = False
_reason        = "manual"      # "manual" | "meet" | "zoom" | "teams"
_queue: list   = []
_speak_fn      = None
_broadcast_fn  = None
_auto_triggered = False        # True if DND was auto-enabled by meeting detector

_POLL_INTERVAL = 15            # seconds between meeting checks
_dnd_start_ts: float = 0.0    # Unix ts when DND was last turned on

# ── Per-session tracking ───────────────────────────────────────
_busy_replied: dict   = {}    # number → count of busy replies sent this DND session
_grouped_senders: dict = {}   # number → queue index of latest unactioned alert
_sender_msg_times: dict = {}  # number → list of timestamps (for escalation)
_handle_reminders: dict = {}  # item_id → calendar event_id (for auto-cancel)
_MAX_BUSY_REPLIES = 2

# ── Call log (Phase 3) ─────────────────────────────────────────
_call_log: list   = []         # list of call event dicts (persistent across DND)
_call_log_file    = "dnd_call_log.json"
_call_times: dict = {}         # number → list of timestamps (call escalation, 10min window)
_MAX_CALL_LOG     = 200

# ── Priority contacts ──────────────────────────────────────────
def _load_priority_contacts() -> set:
    try:
        with open("api_keys.json") as f:
            return set(json.load(f).get("dnd_priority_contacts", []))
    except Exception:
        return set()

# ── Ack filter ─────────────────────────────────────────────────
_ACK_WORDS = {
    "okay","okayy","okayyy","ok","k","kk","kkk","fine","acha","achha","accha",
    "theek hai","theek","haan","han","ha","hmm","hm","haan ji","ji",
    "👍","🙏","alright","sure","got it","noted","ohh","oh","ohhh",
    "lol","haha","hahaha","ha ha","lmao","nice","cool","hn","hmm okay",
    "okk","okkk","oki","okie","roger","noted","seen","dekha","sahi",
    "bas","thik","thik hai","accha thik hai","okay thik hai","achha thik"
}

def _is_ack(text: str) -> bool:
    """Return True if message is just an acknowledgment (no action needed)."""
    t = text.strip().lower().rstrip("!.,? 🙏👍")
    if len(t) <= 2:
        return True
    return t in _ACK_WORDS

# ── Sarcastic busy replies ─────────────────────────────────────
_BUSY_REPLIES = [
    "Hey there! This is iZACH — Vansh's AI assistant (the one who actually shows up). Vansh is currently in a meeting, probably pretending to take notes. He'll reply soon! 🤖",
    "Oh hello! iZACH here. Vansh is unavailable right now — he's in a meeting trying to look busy (ironic, I know). I'll make sure he gets your message! 🙏",
    "Greetings! iZACH speaking, the AI that keeps Vansh organized. He's currently 'occupied' (read: in a meeting he couldn't escape). He'll get back to you ASAP! 😄",
    "Hey! iZACH — Vansh's digital assistant here. He's currently in a meeting, which means he's either solving world problems or zoning out. Either way, he'll reply later! 🚀",
    "Hello! iZACH at your service. Vansh is currently unavailable — he's in a meeting where somebody could've just sent an email. Will relay your message! 😅",
    "Yo! This is iZACH, the AI keeping Vansh's life together. He's in a meeting right now (don't worry, he'll survive). Your message is noted — he'll respond soon! 💪",
]

_URGENT_HINT = (
    "💡 *If it's urgent*, reply starting with *URGENT*\n"
    "Example: `URGENT Bhai call me, it's important`\n"
    "iZACH will alert Vansh immediately! 🚨"
)


# ── Register izach:// custom protocol (no Chrome on toast clicks) ──
def _register_toast_protocol():
    """Register izach:// URI scheme so toast buttons run dnd_action.pyw silently."""
    try:
        import winreg, sys as _sys
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "dnd_action.pyw"
        )
        pythonw = os.path.join(os.path.dirname(_sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = _sys.executable
        cmd = f'"{pythonw}" "{script}" "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\izach") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, "URL:iZACH DND Handler")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Classes\izach\shell\open\command") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, cmd)
        logger.debug("[DND] izach:// protocol registered — toast buttons run silently")
    except Exception as e:
        logger.debug(f"[DND] Protocol registration skipped: {e}")


# ── Init ──────────────────────────────────────────────────────
def init(speak_fn=None, broadcast_fn=None):
    global _speak_fn, _broadcast_fn
    _speak_fn     = speak_fn
    _broadcast_fn = broadcast_fn
    _load_queue()
    _load_call_log()
    _register_toast_protocol()   # izach:// URI → silent toast button handler
    t = threading.Thread(target=_meeting_detector_loop, daemon=True, name="DND-MeetDetector")
    t.start()
    logger.info("[DND] Initialized.")


# ── Public API ─────────────────────────────────────────────────
def is_active() -> bool:
    with _lock:
        return _active


def turn_on(reason: str = "manual"):
    global _active, _reason, _auto_triggered, _dnd_start_ts
    with _lock:
        if _active:
            return
        _active         = True
        _reason         = reason
        _auto_triggered = (reason != "manual")
        _dnd_start_ts   = time.time()   # record exactly when DND started
    logger.info(f"[DND] ON — reason: {reason}")
    _broadcast_state()
    if _speak_fn and reason == "manual":
        _speak_fn("Do Not Disturb mode activated. Mic paused. Alerts will be held silently.")


def turn_off():
    global _active, _reason, _auto_triggered, _busy_replied, _grouped_senders, _sender_msg_times
    with _lock:
        if not _active:
            return
        _active            = False
        _reason            = "manual"
        _auto_triggered    = False
        _busy_replied      = {}
        _grouped_senders   = {}
        _sender_msg_times  = {}
    logger.info("[DND] OFF")
    _broadcast_state()
    _deliver_briefing()


def get_status() -> dict:
    with _lock:
        return {
            "active":      _active,
            "reason":      _reason,
            "queue_count": len(_queue),
        }


def get_queue() -> list:
    with _lock:
        return list(_queue)


def clear_queue():
    global _queue
    with _lock:
        _queue = []
    _save_queue()


def add_to_queue(item: dict):
    """Smart queue: ack filter, grouping, priority escalation, auto-escalation."""
    number = item.get("number", "")
    text   = item.get("text", "")
    typ    = item.get("type", "alert")

    # ── Pre-DND filter — drop messages sent BEFORE DND was turned on ──
    # wa_ts is the actual WA send timestamp from the bridge (not arrival time).
    # Bridge replays buffered messages when iZACH reconnects; those are pre-DND.
    wa_ts = item.get("wa_ts")
    if wa_ts:
        with _lock:
            start = _dnd_start_ts
        if float(wa_ts) < start - 2:   # 2s grace for clock skew
            logger.info(f"[DND] Dropped pre-DND message (wa_ts={wa_ts:.0f} < dnd_start={start:.0f}) from {item.get('from','?')}")
            return

    # ── Group message suppression ──────────────────────────────
    if number and number.endswith("@g.us"):
        logger.debug(f"[DND] Skipped group message from {number}")
        return

    # ── Ack filter — skip trivial acknowledgments ──────────────
    if typ == "whatsapp_message" and _is_ack(text):
        logger.info(f"[DND] Ack filtered: '{text}' from {item.get('from','?')}")
        return

    # ── URGENT keyword detection ────────────────────────────────
    if typ == "whatsapp_message" and text.upper().lstrip().startswith("URGENT"):
        urgent_body = text[6:].strip().lstrip(":<>").strip()
        _show_urgent_notification(item.get("from", "Unknown"), urgent_body)
        return   # don't queue as normal DND alert

    now = int(time.time())

    # ── Priority contacts — always show, skip grouping ─────────
    priority = _load_priority_contacts()
    is_priority = number in priority or item.get("from", "") in priority

    # ── Message grouping — update existing unactioned alert ────
    with _lock:
        item.setdefault("ts",     now)
        item.setdefault("action", None)

        grouped_idx = _grouped_senders.get(number)
        if (not is_priority
                and grouped_idx is not None
                and grouped_idx < len(_queue)
                and _queue[grouped_idx].get("action") is None
                and typ == "whatsapp_message"):
            # Append new text to existing alert instead of new entry
            existing = _queue[grouped_idx]
            prev_text = existing.get("text", "")
            existing["text"] = f"{prev_text}\n+ {text}"
            existing["ts"]   = now
            existing["grouped"] = True
            item = dict(existing)
            logger.info(f"[DND] Grouped msg from {item.get('from','?')}")
        else:
            item["id"] = len(_queue)
            item["reminder_status"] = "none"   # none | pending | done | cancelled
            item["reminder_event_id"] = None
            _queue.append(item)
            _grouped_senders[number] = item["id"]

        # ── Auto-escalation tracking ───────────────────────────
        times = _sender_msg_times.get(number, [])
        times = [t for t in times if now - t < 600]   # keep last 10 min
        times.append(now)
        _sender_msg_times[number] = times
        escalate = len(times) >= 3 and not is_priority

    _save_queue()

    # ── Toast & broadcast ──────────────────────────────────────
    if escalate:
        item["escalated"] = True
        _show_toast(item, escalated=True)
        if _speak_fn:
            try:
                _speak_fn(f"Heads up — {item.get('from','Someone')} has sent multiple messages during DND.")
            except Exception:
                pass
    else:
        _show_toast(item)

    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "dnd_alert", **item})
        except Exception:
            pass
    logger.info(f"[DND] Queued alert: {item.get('type')} from {item.get('from','?')}{' [PRIORITY]' if is_priority else ''}{' [ESCALATED]' if escalate else ''}")


def mark_handle(idx: int) -> bool:
    with _lock:
        if idx < 0 or idx >= len(_queue):
            return False
        _queue[idx]["action"] = "handle"
        item = dict(_queue[idx])
    _save_queue()
    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "dnd_queue_update", **item})
        except Exception:
            pass
    # Trigger N8N auto-reply pipeline for WhatsApp messages
    if item.get("type") == "whatsapp_message" and item.get("number"):
        threading.Thread(
            target=_trigger_n8n_auto_reply,
            args=(item,),
            daemon=True,
            name="dnd-n8n-handle",
        ).start()
    # Create calendar reminder to follow up + start reply-watcher
    threading.Thread(
        target=_create_handle_reminder,
        args=(item,),
        daemon=True,
        name="dnd-cal-reminder",
    ).start()
    return True


_HANDLE_REPLIES = [
    "Hey {name}! Vansh saw your message and will personally get back to you soon. He's on it! 👍",
    "Hi {name}! Vansh received your message and is going to reply shortly. Hang tight! ⏳",
    "Hey! Vansh has been notified about your message, {name}. He'll respond when he's free. 🙏",
    "Got it, {name}! Vansh is aware and will handle your message soon. Stay tuned! ✅",
    "Hey {name}, Vansh has seen your message. He's handling it — reply coming soon! 💬",
]


def _trigger_n8n_auto_reply(item: dict):
    """
    Send a 'Handle It' reply: use direct AI first (reliable), ping N8N as side-effect.

    N8N bug: it returns HTTP 200 for ANY webhook hit ("Workflow started") even if the
    workflow doesn't exist or fails — so we can't trust HTTP 200 as a success signal.
    Always send via whatsapp_sender directly. N8N notified in background for logging.
    """
    number = item.get("number", "")
    sender = item.get("from", "Unknown")
    text   = item.get("text", "")

    if not number:
        logger.warning("[DND] Handle reply skipped — no number in item")
        return

    # ── Step 1: generate reply (try AI, fall back to template) ───
    reply = _ai_handle_reply(sender, text)

    # ── Step 2: send via whatsapp_sender (proven reliable) ───────
    try:
        from modules.whatsapp_sender import send_message as _wasm
        ok, status = _wasm(number, reply, sender)
        if ok:
            logger.info(f"[DND] Handle reply sent → {sender} ✓")
        else:
            logger.warning(f"[DND] Handle reply FAILED → {sender}: {status}")
    except Exception as e:
        logger.error(f"[DND] Handle reply exception: {e}")

    # ── Step 3: notify N8N as optional side-effect (fire & forget) ─
    try:
        import requests as _req
        n8n_url = os.getenv("N8N_URL", "http://127.0.0.1:5678")
        _req.post(
            f"{n8n_url}/webhook/wa-handle-notify",
            json={"from": sender, "number": number, "text": text, "id": item.get("id", 0)},
            timeout=3,
        )
    except Exception:
        pass  # N8N notification is fully optional


def _ai_handle_reply(sender: str, text: str) -> str:
    """Try /ai/respond for context-aware reply; fall back to template on any failure."""
    import requests as _req
    try:
        r = _req.post(
            "http://127.0.0.1:5050/ai/respond",
            json={"from": sender, "message": text, "number": "", "lang_hint": "hinglish"},
            headers={"X-N8N-Token": "izach-n8n-2024", "Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code == 200:
            ai_reply = r.json().get("reply", "").strip()
            if ai_reply:
                logger.info(f"[DND] AI handle reply generated for {sender}")
                return ai_reply
    except Exception as e:
        logger.debug(f"[DND] AI handle reply fallback: {e}")
    # Template fallback
    tmpl = random.choice(_HANDLE_REPLIES)
    return tmpl.format(name=sender)




def mark_busy(idx: int) -> bool:
    with _lock:
        if idx < 0 or idx >= len(_queue):
            return False
        _queue[idx]["action"] = "busy"
        item = dict(_queue[idx])
    _save_queue()
    # Send auto "busy" reply if WhatsApp message — max _MAX_BUSY_REPLIES per contact
    if item.get("type") in ("whatsapp_message", "phone_call") and item.get("number"):
        number = item["number"]
        with _lock:
            count = _busy_replied.get(number, 0)
        if count < _MAX_BUSY_REPLIES:
            with _lock:
                _busy_replied[number] = count + 1
            threading.Thread(
                target=_send_busy_reply,
                args=(number, item.get("from", "")),
                daemon=True,
            ).start()
        else:
            logger.info(f"[DND] Busy reply limit reached for {number} — skip")
    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "dnd_queue_update", **item})
        except Exception:
            pass
    return True


def concise_system_prefix() -> str:
    """Inject into AI prompt when DND is active. Forces 1-2 sentence replies."""
    return (
        "[DND MODE] User is in Do Not Disturb / meeting mode. "
        "Reply in MAXIMUM 1-2 short sentences. Be direct. No filler. No markdown. "
        "Speed > completeness. If answer needs detail, give the key fact only.\n\n"
    )


# ── Meeting Detector ───────────────────────────────────────────
def _meeting_detector_loop():
    while True:
        time.sleep(_POLL_INTERVAL)
        try:
            _check_meetings()
        except Exception as e:
            logger.debug(f"[DND] Meeting check error: {e}")


def _check_meetings():
    try:
        import psutil
    except ImportError:
        return

    in_meeting, detected_reason = _detect_meeting(psutil)

    with _lock:
        currently_active = _active
        is_auto          = _auto_triggered

    if in_meeting and not currently_active:
        logger.info(f"[DND] Meeting detected ({detected_reason}) — auto-enabling DND.")
        turn_on(detected_reason)
        # Announce via speak — will NOT be suppressed because we call _speak_fn
        # directly (turn_on already called it for manual; for auto we do it here)
        if _speak_fn:
            label = {"meet": "Google Meet", "zoom": "Zoom", "teams": "Teams"}.get(detected_reason, detected_reason)
            _speak_fn(f"{label} meeting detected. Enabling Do Not Disturb mode.")

    elif not in_meeting and currently_active and is_auto:
        logger.info("[DND] Meeting ended — auto-disabling DND.")
        turn_off()
        if _speak_fn:
            _speak_fn("Meeting ended. Do Not Disturb disabled.")


def _detect_meeting(psutil_mod) -> tuple:
    """Returns (in_meeting: bool, reason: str)."""
    try:
        proc_names = {p.info["name"].lower() for p in psutil_mod.process_iter(["name"]) if p.info["name"]}
    except Exception:
        proc_names = set()

    # Zoom — only if meeting window is open (not just background app)
    if "zoom.exe" in proc_names:
        if _window_title_contains(["zoom meeting", "zoom webinar", "zoom video"]):
            return True, "zoom"

    # Microsoft Teams
    if any(n in proc_names for n in ("ms-teams.exe", "teams.exe", "msteams.exe")):
        if _window_title_contains(["| microsoft teams", "teams meeting", "call with"]):
            return True, "teams"

    # Google Meet — Chrome/Edge with meet.google.com in title
    if _window_title_contains(["meet.google.com", "google meet"]):
        return True, "meet"

    return False, ""


def _window_title_contains(keywords: list) -> bool:
    try:
        import win32gui
        found = []
        def _enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if any(k in title for k in keywords):
                    found.append(True)
        win32gui.EnumWindows(_enum_cb, None)
        return bool(found)
    except Exception:
        return False


# ── Windows Toast ──────────────────────────────────────────────
def _show_toast(item: dict, escalated: bool = False):
    try:
        from winotify import Notification, audio as _wa
        sender = item.get("from", "Unknown")
        typ    = item.get("type", "alert")
        text   = item.get("text", "")

        if escalated:
            title = f"🚨 DND ESCALATION — {sender}"
            body  = f"Multiple messages! Latest: {(text[:60] + '…') if len(text) > 60 else text}"
        elif typ == "whatsapp_message":
            title = f"📱 WhatsApp — {sender}"
            body  = (text[:72] + "…") if len(text) > 72 else text
        elif typ == "phone_call":
            title = f"📞 WhatsApp Call from {sender} — Handled by iZACH"
            body  = f"iZACH auto-declined the call and sent {sender} a message."
        else:
            title = "⛔ iZACH — DND Alert"
            body  = (text[:72] + "…") if len(text) > 72 else text

        item_id = item.get("id", 0)
        toast = Notification(
            app_id   = "iZACH",
            title    = title,
            msg      = body,
            duration = "long",
        )
        toast.set_audio(_wa.Default, loop=False)
        try:
            # izach:// protocol → runs dnd_action.pyw silently (no browser window)
            toast.add_actions(
                label  = "✅ Handle",
                launch = f"izach://dnd/action/handle/{item_id}",
            )
            toast.add_actions(
                label  = "🔕 I'm Busy",
                launch = f"izach://dnd/action/busy/{item_id}",
            )
        except Exception:
            pass  # winotify version may not support add_actions
        toast.show()
        logger.debug(f"[DND] Toast shown: {title}")
    except Exception as e:
        logger.debug(f"[DND] Toast failed: {e}")


# ── Auto-reply "I'm Busy" — sarcastic rotation + URGENT hint ──
def _send_busy_reply(number: str, name: str):
    try:
        from modules.whatsapp_sender import send_message
        msg1 = random.choice(_BUSY_REPLIES)
        send_message(number, msg1, name)
        time.sleep(1.2)   # small delay so messages arrive in order
        send_message(number, _URGENT_HINT, name)
        logger.info(f"[DND] Busy reply (2 msgs) sent → {name} ({number})")
    except Exception as e:
        logger.warning(f"[DND] Busy reply failed: {e}")


# ── URGENT notification (loud Windows toast, no queue) ─────────
def _show_urgent_notification(sender: str, text: str):
    logger.info(f"[DND] URGENT from {sender}: {text[:60]}")
    try:
        from winotify import Notification, audio as _wa
        toast = Notification(
            app_id   = "iZACH",
            title    = f"🚨 URGENT — {sender}",
            msg      = text if text else "(no message body)",
            duration = "long",
        )
        toast.set_audio(_wa.Reminder, loop=False)   # louder reminder sound
        toast.show()
    except Exception as e:
        logger.debug(f"[DND] Urgent toast failed: {e}")
    # Broadcast to UI (shows red urgent popup)
    if _broadcast_fn:
        try:
            _broadcast_fn({
                "type":   "urgent_alert",
                "from":   sender,
                "text":   text,
                "ts":     int(time.time()),
            })
        except Exception:
            pass
    # Also speak if possible
    if _speak_fn:
        try:
            short = text[:60] + ("…" if len(text) > 60 else "")
            _speak_fn(f"Urgent message from {sender}: {short}")
        except Exception:
            pass


# ── Smart calendar reminder on Handle ─────────────────────────
def _create_handle_reminder(item: dict):
    """Create a Google Calendar reminder to follow up, then watch for auto-cancel."""
    item_id = item.get("id", 0)
    sender  = item.get("from", "Unknown")
    number  = item.get("number", "")

    try:
        # Figure out when to remind — 5 min after meeting ends, or 35 min from now
        remind_at = _get_reminder_time()

        from modules.calendar_engine import get_service as _gcal_svc
        service = _gcal_svc()
        import datetime as _dt
        start = _dt.datetime.fromtimestamp(remind_at).isoformat()
        end   = _dt.datetime.fromtimestamp(remind_at + 300).isoformat()
        tz    = "Asia/Kolkata"

        event = service.events().insert(
            calendarId="primary",
            body={
                "summary":     f"📱 Reply to {sender} (WhatsApp — iZACH DND)",
                "description": f"Message: {item.get('text', '')[:200]}\nNumber: {number}",
                "start":       {"dateTime": start, "timeZone": tz},
                "end":         {"dateTime": end,   "timeZone": tz},
                "reminders":   {"useDefault": False, "overrides": [{"method": "popup", "minutes": 1}]},
            }
        ).execute()

        event_id = event.get("id")
        with _lock:
            _handle_reminders[item_id] = event_id
            # update queue item
            if item_id < len(_queue):
                _queue[item_id]["reminder_status"]   = "pending"
                _queue[item_id]["reminder_event_id"] = event_id
        _save_queue()
        logger.info(f"[DND] Calendar reminder created for {sender}: event {event_id}")

        # Watch WhatsApp history — cancel reminder if replied
        threading.Thread(
            target=_watch_for_reply,
            args=(item_id, number, event_id, remind_at),
            daemon=True,
            name=f"dnd-reply-watch-{item_id}",
        ).start()

    except Exception as e:
        logger.warning(f"[DND] Calendar reminder failed: {e}")


def _get_reminder_time() -> int:
    """Return Unix timestamp for when to remind — 5 min after meeting end, or now+35min."""
    try:
        from modules.calendar_engine import get_service as _gcal_svc
        import datetime as _dt
        service = _gcal_svc()
        now_iso = _dt.datetime.utcnow().isoformat() + "Z"
        events  = service.events().list(
            calendarId="primary",
            timeMin=now_iso,
            maxResults=3,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        # Find event currently in progress
        now_ts = time.time()
        for ev in events:
            end_str = ev.get("end", {}).get("dateTime", "")
            if end_str:
                import dateutil.parser as _dp
                end_ts = _dp.parse(end_str).timestamp()
                if end_ts > now_ts:
                    return int(end_ts) + 300   # 5 min after meeting ends
    except Exception:
        pass
    return int(time.time()) + 35 * 60   # fallback: 35 min from now


def _watch_for_reply(item_id: int, number: str, event_id: str, deadline_ts: int):
    """Poll WhatsApp every 2 min — if we replied, delete calendar event."""
    import requests as _req
    poll_until = deadline_ts + 120
    mark_ts    = time.time()

    while time.time() < poll_until:
        time.sleep(120)
        try:
            r = _req.get(
                f"http://127.0.0.1:3000/messages/chat?number={number}&limit=10",
                timeout=5
            )
            msgs = r.json().get("messages", [])
            for m in msgs:
                if m.get("fromMe") and m.get("timestamp", 0) > mark_ts:
                    # We replied! Cancel the calendar reminder
                    _cancel_reminder(item_id, event_id)
                    return
        except Exception:
            pass

    logger.debug(f"[DND] Reply watcher expired for item {item_id}")


def _cancel_reminder(item_id: int, event_id: str):
    """Delete calendar event and update queue item status."""
    try:
        from modules.calendar_engine import get_service as _gcal_svc
        _gcal_svc().events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"[DND] Reminder auto-cancelled (replied) for item {item_id}")
    except Exception as e:
        logger.debug(f"[DND] Reminder cancel failed: {e}")
    with _lock:
        if item_id < len(_queue):
            _queue[item_id]["reminder_status"]   = "cancelled"
            _queue[item_id]["reminder_event_id"] = None
    _save_queue()
    if _broadcast_fn:
        try:
            with _lock:
                item = dict(_queue[item_id]) if item_id < len(_queue) else {}
            _broadcast_fn({"type": "dnd_queue_update", **item})
        except Exception:
            pass


# ── Post-DND Briefing ──────────────────────────────────────────
def _deliver_briefing():
    with _lock:
        total      = len(_queue)
        unattended = [i for i in _queue if i.get("action") is None]
        handled    = [i for i in _queue if i.get("action") == "handle"]
        busy       = [i for i in _queue if i.get("action") == "busy"]

        # Mark unattended items in queue so UI can show the badge
        for item in _queue:
            if item.get("action") is None:
                item["action"] = "unattended"

        queue_snap = list(_queue)
    _save_queue()

    if not total:
        if _speak_fn:
            _speak_fn("Do Not Disturb disabled. No missed alerts while you were away.")
        if _broadcast_fn:
            try:
                _broadcast_fn({"type": "dnd_off", "queue": []})
            except Exception:
                pass
        return

    parts = []

    # Unattended — speak each sender by name (up to 3 names)
    if unattended:
        senders = list(dict.fromkeys(i.get("from", "someone") for i in unattended))
        if len(senders) == 1:
            parts.append(f"1 unattended message from {senders[0]}")
        elif len(senders) == 2:
            parts.append(f"unattended messages from {senders[0]} and {senders[1]}")
        else:
            named = ", ".join(senders[:2])
            rest  = len(senders) - 2
            parts.append(f"unattended messages from {named} and {rest} other{'s' if rest > 1 else ''}")

    if handled:
        parts.append(f"{len(handled)} message{'s' if len(handled) > 1 else ''} handled by iZACH")
    if busy:
        parts.append(f"{len(busy)} auto-replied as busy")

    briefing = ". ".join(parts)
    if _speak_fn:
        _speak_fn(f"Do Not Disturb off. While you were away — {briefing}. Check iZACH for details.")

    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "dnd_off", "queue": queue_snap})
        except Exception:
            pass


# ── Call Log (Phase 3) ────────────────────────────────────────
def log_call(number: str, caller: str, action: str = "declined", callback_event_id: str = None):
    """
    Add a call entry to the persistent call log.
    action: "declined" | "ignored" | "callback_scheduled" | "escalated"
    Triggers escalation check (3 calls in 10 min → urgent alert).
    """
    global _call_log, _call_times

    # Resolve name from contacts.json if not already resolved
    if not caller or caller == number:
        caller = _resolve_caller_name(number)

    known = caller != number and not caller.startswith("Unknown")

    now = int(time.time())
    entry = {
        "id":                len(_call_log),
        "ts":                now,
        "number":            number,
        "caller":            caller,
        "known":             known,
        "action":            action,
        "callback_event_id": callback_event_id,
        "escalated":         False,
    }

    with _lock:
        # Call escalation: 3 calls in 10 min from same number → urgent
        times = _call_times.get(number, [])
        times = [t for t in times if now - t < 600]
        times.append(now)
        _call_times[number] = times
        escalate = len(times) >= 3

        if escalate:
            entry["escalated"] = True
            entry["action"]    = "escalated"

        _call_log.append(entry)
        if len(_call_log) > _MAX_CALL_LOG:
            _call_log = _call_log[-_MAX_CALL_LOG:]

    _save_call_log()

    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "call_log_update", **entry})
        except Exception:
            pass

    if escalate:
        logger.warning(f"[DND] Call ESCALATION — {caller} called {len(times)}x in 10 min")
        _show_urgent_notification(caller, f"Called {len(times)} times in under 10 minutes!")
        if _speak_fn:
            try:
                _speak_fn(f"Urgent — {caller} has called you {len(times)} times in the last 10 minutes!")
            except Exception:
                pass

    return entry


def get_call_log() -> list:
    with _lock:
        return list(reversed(_call_log))


def _resolve_caller_name(number: str) -> str:
    """Lookup number in contacts.json. Returns name or 'Unknown'."""
    try:
        with open("contacts.json", encoding="utf-8") as f:
            contacts = json.load(f)
        # Try exact match first (number may already have @c.us)
        if number in contacts:
            return contacts[number]
        # Try with @c.us suffix
        if not number.endswith("@c.us") and f"{number}@c.us" in contacts:
            return contacts[f"{number}@c.us"]
        # Try stripping country code leading zero variations
        for key, name in contacts.items():
            if key.replace("@c.us", "").endswith(number.lstrip("91+0")[-9:]):
                return name
    except Exception:
        pass
    return "Unknown"


def schedule_call_callback(number: str, caller: str, callback_time_str: str = None) -> str | None:
    """
    Create a Google Calendar event to call back.
    Returns event_id or None.
    """
    try:
        import datetime as _dt
        from modules.calendar_engine import get_service as _gcal_svc

        tz = "Asia/Kolkata"
        if callback_time_str:
            # Parse HH:MM or "4:30 PM"
            now = _dt.datetime.now()
            for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
                try:
                    parsed = _dt.datetime.strptime(callback_time_str.upper().strip(), fmt)
                    callback_dt = now.replace(
                        hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                    )
                    if callback_dt < now:
                        callback_dt += _dt.timedelta(days=1)
                    break
                except ValueError:
                    callback_dt = None
        else:
            callback_dt = _dt.datetime.now() + _dt.timedelta(hours=1)

        if not callback_dt:
            callback_dt = _dt.datetime.now() + _dt.timedelta(hours=1)

        start = callback_dt.isoformat()
        end   = (callback_dt + _dt.timedelta(minutes=15)).isoformat()

        svc   = _gcal_svc()
        event = svc.events().insert(calendarId="primary", body={
            "summary":     f"📞 Call back {caller} (iZACH)",
            "description": f"Number: {number}\nMissed WhatsApp call — iZACH created this callback reminder.",
            "start":       {"dateTime": start, "timeZone": tz},
            "end":         {"dateTime": end,   "timeZone": tz},
            "reminders":   {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
        }).execute()
        logger.info(f"[DND] Callback scheduled for {caller}: event {event.get('id')}")
        return event.get("id")
    except Exception as e:
        logger.debug(f"[DND] Callback schedule failed: {e}")
        return None


def _load_call_log():
    global _call_log
    try:
        if os.path.exists(_call_log_file):
            with open(_call_log_file, encoding="utf-8") as f:
                _call_log = json.load(f)
            logger.info(f"[DND] Loaded {len(_call_log)} call log entries.")
    except Exception:
        _call_log = []


def _save_call_log():
    try:
        with _lock:
            data = list(_call_log)
        with open(_call_log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[DND] Call log save error: {e}")


# ── Persistence ────────────────────────────────────────────────
def _save_queue():
    try:
        with _lock:
            data = list(_queue)
        with open(_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[DND] Queue save error: {e}")


def _load_queue():
    global _queue
    try:
        if os.path.exists(_QUEUE_FILE):
            with open(_QUEUE_FILE, encoding="utf-8") as f:
                _queue = json.load(f)
            logger.info(f"[DND] Loaded {len(_queue)} queued alerts from disk.")
    except Exception:
        _queue = []


def _broadcast_state():
    if _broadcast_fn:
        try:
            _broadcast_fn({"type": "dnd_status", **get_status()})
        except Exception:
            pass
