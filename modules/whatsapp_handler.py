import logging
import threading
import requests
import asyncio
import edge_tts
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)

app = Flask(__name__)
_OWNER = os.getenv("OWNER_NAME", "User")
_announce_pool = ThreadPoolExecutor(max_workers=1)
_speak_func = None
_chain_func = None
_pending_call = None
_notify_func = None
_log_func = None
_ai_func = None
_contacts = {}

def _load_contacts():
    global _contacts
    try:
        import json, os
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contacts.json")
        with open(path, "r") as f:
            _contacts = json.load(f)
    except Exception:
        _contacts = {}

def _resolve_name(number: str, fallback: str) -> str:
    return _contacts.get(number, fallback)

def resolve_contact_by_name(name: str) -> str | None:
    """Return phone number for a contact name (case-insensitive partial match)."""
    name_lower = name.lower()
    for number, contact_name in _contacts.items():
        if name_lower in contact_name.lower():
            return number
    return None

def get_last_message():
    return _last_message

def set_ui_callbacks(notify_fn, log_fn):
    global _notify_func, _log_func
    _notify_func = notify_fn
    _log_func = log_fn

def _notif_whatsapp_enabled() -> bool:
    try:
        import json as _j
        with open("api_keys.json") as _f:
            return bool(_j.load(_f).get("notif_whatsapp", True))
    except Exception:
        return True


def init_whatsapp(speak, chain, ai_func=None):
    global _speak_func, _chain_func, _ai_func
    _speak_func = speak
    _chain_func = chain
    _ai_func = ai_func

    from modules.event_extractor import init as _init_extractor
    _init_extractor(speak_fn=speak)
    
    try:
        import main as _main
        _spotify = _main.spotify_api
    except Exception:
        _spotify = None
    from modules.ui_api import register_ui_api
    register_ui_api(
        app=app,
        chain_fn=chain,
        speak_fn=speak,
        get_response_fn=ai_func,
        spotify_handler=_spotify,
    )

    _load_contacts()
    # threaded=True — without it, Werkzeug's dev server handles one request at a
    # time, so any two concurrent callers (Cortex UI, the phone, N8N, Forge's
    # own status/dashboard polling) can queue behind each other and stall.
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False, threaded=True), daemon=True).start()
    threading.Thread(target=_monitor_connection, daemon=True).start()
    print("[WHATSAPP] Handler Online on port 5050 — bridge lazy-loaded on first WA command.")

_bridge_started = False
_bridge_lock = threading.Lock()


def _bridge_already_healthy() -> bool:
    """True if something on port 3000 is already a live, responding bridge.
    Checked before ever killing that port — a second, unrelated call to
    ensure_bridge_running() (e.g. from another main.py process, or a test
    run exercising WhatsAppAgent) must never collateral-kill an already-
    connected, real bridge session just because it also wants one running."""
    try:
        import requests
        r = requests.get("http://localhost:3000/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _free_bridge_port():
    """Kill any leftover process still holding port 3000 — e.g. a Node bridge
    orphaned by a previous main.py run that didn't shut down cleanly. Without
    this, a stale process causes a hard EADDRINUSE crash on every subsequent
    start. Same psutil-based, cross-platform pattern main.py uses for 5051.
    Skipped entirely if the port already holds a healthy bridge (see
    _bridge_already_healthy) — only genuinely dead/stale processes get killed."""
    if _bridge_already_healthy():
        return
    try:
        import psutil
        for proc in psutil.process_iter(["pid"]):
            try:
                for conn in proc.net_connections(kind="inet"):
                    if conn.laddr and conn.laddr.port == 3000:
                        proc.kill()
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess, PermissionError):
                continue
    except Exception:
        pass


def _start_bridge():
    import subprocess, time
    from modules.platform_utils import IS_WINDOWS
    time.sleep(3)
    if _bridge_already_healthy():
        print("[WHATSAPP] Bridge already running and healthy — reusing it instead of restarting.")
        return
    _free_bridge_port()
    try:
        bridge_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "whatsapp_bridge.js")
        if IS_WINDOWS:
            subprocess.Popen(["node", bridge_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(["node", bridge_path], start_new_session=True)
        print("[WHATSAPP] Bridge started")
    except Exception as e:
        print(f"[WHATSAPP] Could not start bridge: {e}")


def ensure_bridge_running():
    """Lazy-start WhatsApp bridge on first WA command. Safe to call many times.

    In dual-instance Secondary Connector mode, the live bridge only ever runs
    on whichever machine is currently primary — running two independent
    whatsapp-web.js sessions under the same account risks QR/session
    conflicts, and message history/contacts are already shared across
    machines via the Syncthing-synced JSON files instead. A secondary
    instance just never starts its own bridge; it relies on the primary's."""
    from modules.instance_coordinator import get_role
    if get_role() == "secondary":
        print("[WHATSAPP] Skipping bridge start — this machine is a Secondary Connector, "
              "the primary machine's bridge handles WhatsApp.")
        return

    global _bridge_started
    with _bridge_lock:
        if _bridge_started:
            return
        _bridge_started = True
    threading.Thread(target=_start_bridge, daemon=True).start()
    print("[WHATSAPP] Bridge starting — first WhatsApp command triggered launch.")

def _monitor_connection():
    import time, requests as req
    time.sleep(30)  # Give bridge time to start + connect
    while True:
        if not _bridge_started:
            time.sleep(60)
            continue
        try:
            r = req.get("http://localhost:3000/health", timeout=3)
            status = r.json().get("status")
            if status != "connected" and _speak_func:
                _speak_func("WhatsApp is not connected.")
        except Exception:
            pass  # Bridge offline but not our problem to announce — status route handles it
        time.sleep(300)  # Check every 5 minutes

@app.route('/whatsapp/call', methods=['POST'])
def incoming_call():
    global _pending_call
    data = request.json or {}
    raw_caller = data.get('caller', 'Unknown')
    number = data.get('number')
    caller = _resolve_name(number, raw_caller)
    _pending_call = {'caller': caller, 'number': number, 'type': 'call'}

    # ── DND: auto-decline + queue + call log ─────────────────────
    try:
        from modules import dnd_mode as _dnd_call
        if _dnd_call.is_active():
            # Add to DND queue (shows Windows toast notification)
            queue_item = {
                "type":   "phone_call",
                "from":   caller,
                "number": number,
                "text":   "📞 Incoming WhatsApp call",
            }
            _dnd_call.add_to_queue(queue_item)
            # Log to call log (triggers escalation if 3+ calls in 10 min)
            _dnd_call.log_call(number, caller, action="declined")

            # Send call-specific declined message (not the sarcastic WA text-message reply)
            import threading as _t
            def _send_call_declined_msg():
                try:
                    from modules.whatsapp_sender import send_message as _wasm
                    import os as _os
                    owner = _os.getenv("OWNER_NAME", "Vansh")
                    msg = (
                        f"Hey {caller}! 👋 iZACH here — {owner}'s AI assistant.\n"
                        f"{owner} is currently in Do Not Disturb mode and couldn't take your call.\n"
                        f"He'll call you back as soon as he's free! 🙏\n\n"
                        f"💡 If it's urgent, reply starting with *URGENT* and I'll alert him immediately."
                    )
                    _wasm(number, msg, caller)
                except Exception as _ce:
                    import logging as _lg
                    _lg.getLogger(__name__).warning(f"[DND] Call declined msg failed: {_ce}")
            _t.Thread(target=_send_call_declined_msg, daemon=True, name="dnd-call-reply").start()

            return jsonify({'status': 'dnd_decline', 'decline': True})
    except Exception:
        pass

    # ── Busy mode: decline call + log + notify ────────────────────
    try:
        from modules import busy_mode as _busy_call
        if _busy_call.is_active():
            from modules import dnd_mode as _dnd_call2
            _dnd_call2.log_call(number, caller, action="busy_declined")
            # Send a polite busy reply
            import threading as _t2
            def _send_busy_wa():
                try:
                    from modules.whatsapp_sender import send_message as _sm
                    persona = _busy_call.get_persona_context()
                    # get_persona_context() already returns full sentence, don't prepend "Vansh is currently"
                    msg = (
                        f"Hey! iZACH here 👋 {persona} "
                        f"He'll get back to you soon. 🙏"
                    )
                    _sm(number, msg, caller)
                except Exception:
                    pass
            _t2.Thread(target=_send_busy_wa, daemon=True).start()
            return jsonify({'status': 'busy_decline', 'decline': True})
    except Exception:
        pass

    if _speak_func:
        _speak_func(f"{_OWNER}, {caller} is calling you on WhatsApp. Should I pick up, ignore, or reply later?")
    return jsonify({'status': 'notified', 'decline': False})

@app.route('/health', methods=['GET'])
def izach_health():
    return jsonify({'status': 'online', 'agent': 'iZACH'})

@app.route('/remote_command', methods=['POST'])
def remote_command():
    data = request.json or {}
    cmd = data.get('command', '').strip().lstrip('=')
    if not cmd:
        return jsonify({'success': False, 'error': 'No command'})
    try:
        if _chain_func:
            import threading
            threading.Thread(target=_chain_func, args=(cmd,), daemon=True).start()
        if _notify_func:
            _notify_func('MMA Remote', cmd[:60])
        return jsonify({'success': True, 'result': f'iZACH executing: {cmd}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

_wa_state = {"connected": False, "qr": "", "qr_ts": 0}


@app.route('/whatsapp/qr', methods=['POST'])
def whatsapp_qr():
    global _wa_state
    import time as _t
    data = request.json or {}
    qr_string = data.get('qr', '')
    if qr_string:
        # Convert raw QR string → base64 PNG so Cortex UI can render it as <img>
        qr_b64 = _qr_to_base64(qr_string)
        _wa_state["qr"] = qr_b64
        _wa_state["qr_ts"] = int(_t.time())
        _wa_state["connected"] = False
        _print_qr_terminal(qr_string)
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "whatsapp_qr", "qr": qr_b64})
            broadcast({"type": "whatsapp_status", "connected": False, "qr": qr_b64})
        except Exception:
            pass
    return jsonify({'status': 'ok'})


@app.route('/whatsapp/status', methods=['GET'])
def whatsapp_status_get():
    """Cortex/Forge UI polls this to render the WA widget.

    _wa_state["connected"] is normally kept in sync by the bridge itself
    POSTing to /whatsapp/status on connect/disconnect — but that never fires
    if the bridge process dies ungracefully (crash, OOM, killed), leaving the
    widget stuck showing CONNECTED indefinitely. Since this route is already
    polled every 30s, a cheap live reconciliation here self-heals that case
    instead of trusting the cached flag blindly."""
    global _wa_state
    if _wa_state.get("connected"):
        try:
            import requests as _req
            r = _req.get("http://localhost:3000/health", timeout=2)
            if r.status_code != 200 or r.json().get("status") != "connected":
                raise ValueError("bridge reports not connected")
        except Exception:
            _wa_state["connected"] = False
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "whatsapp_status", "connected": False, "qr": _wa_state.get("qr", "")})
            except Exception:
                pass
    return jsonify({
        "ok":         True,
        "connected":  bool(_wa_state.get("connected")),
        "qr":         _wa_state.get("qr", ""),
        "qr_age_sec": int(__import__("time").time()) - int(_wa_state.get("qr_ts", 0)),
    })

def _qr_to_base64(qr_string: str) -> str:
    """Convert raw WhatsApp QR text → base64-encoded PNG (for <img src>)."""
    try:
        import qrcode, io, base64 as _b64
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(qr_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return _b64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning(f"[WA QR] PNG gen failed: {e}")
        return ""  # empty — frontend checks qr.length > 0 before rendering


def _print_qr_terminal(qr_string: str):
    try:
        import qrcode
        import io
        qr = qrcode.QRCode(border=1)
        qr.add_data(qr_string)
        qr.make(fit=True)
        f = io.StringIO()
        qr.print_ascii(out=f, invert=True)
        art = f.getvalue()
        border = "─" * 50
        print(f"\n{border}")
        print("  WhatsApp — Scan QR to connect")
        print(border)
        print(art)
        print(border + "\n")
    except Exception as e:
        print(f"[WHATSAPP QR] Could not render QR: {e}")

@app.route('/whatsapp/status', methods=['POST'])
def whatsapp_status():
    global _wa_state
    data = request.json or {}
    status = data.get('status')
    if status == 'connected':
        _wa_state["connected"] = True
        _wa_state["qr"] = ""  # clear stale QR once connected
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "whatsapp_status", "connected": True, "qr": ""})
        except Exception:
            pass
        if _speak_func:
            _speak_func("WhatsApp connected.")
    elif status == 'disconnected':
        _wa_state["connected"] = False
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "whatsapp_status", "connected": False, "qr": _wa_state.get("qr", "")})
        except Exception:
            pass
        if _speak_func:
            _speak_func(f"{_OWNER}, WhatsApp disconnected.")
    return jsonify({'status': 'ok'})

_last_message = {"sender": None, "text": None, "number": None}

@app.route('/whatsapp/message', methods=['POST'])
def incoming_message():
    global _last_message
    data = request.json or {}
    raw_sender = data.get('sender', 'Unknown')
    text = data.get('text', '')
    number = data.get('number', '')
    # Bridge-provided WA send timestamp (seconds). Used to filter pre-DND replays.
    wa_ts = data.get("timestamp") or data.get("ts") or None
    sender = _resolve_name(number, raw_sender)

    # Backup group suppression (bridge already filters, this is safety net)
    if number and number.endswith('@g.us'):
        return jsonify({'status': 'group_skipped'})

    # Skip empty or media-only messages
    if not text or not text.strip():
        return jsonify({'status': 'empty_skipped'})

    _last_message = {"sender": sender, "text": text, "number": number}

    try:
        from modules.mongo_brain import store_context
        store_context("last_whatsapp_sender", sender)
        store_context("last_whatsapp_text",   text)
        store_context("last_whatsapp_number", number)
    except Exception:
        pass

    # Auto-register WhatsApp number in relationship memory so draft engine
    # can link name → number for future fetch.
    # Skip unknown contacts whose "name" is just digits — prevents raw numbers
    # from appearing as nodes in the relationship graph.
    try:
        from modules.relationship_memory import get_person, add_fact
        if not sender.replace("+", "").replace(" ", "").isdigit():
            person = get_person(sender)
            if not person.get("whatsapp_number"):
                add_fact(sender, "whatsapp_number", number)
    except Exception:
        pass

    from modules.context_memory import get_context_memory
    get_context_memory().record_whatsapp_received(sender, text, number)

    if _notify_func and _notif_whatsapp_enabled():
        _notify_func(f"WhatsApp — {sender}", text[:120])
    try:
        from modules.ws_bridge import broadcast
        import time as _time
        broadcast({
            "type": "notification",
            "source": "whatsapp",
            "text": f"WhatsApp — {sender}: {text[:60]}",
            "ts": _time.strftime("%H:%M")
        })
    except Exception:
        pass
    try:
        from modules.notification_system import push as _notif_push
        _notif_push(f"WhatsApp — {sender}", category="alerts", body=text[:120], source="whatsapp")
    except Exception:
        pass

    # extract calendar events from message (non-blocking)
    try:
        import time as _t
        from modules.event_extractor import process_message as _extract_event
        _extract_event(text=text, sender=sender, msg_id=data.get("id"), timestamp=str(_t.time()))
    except Exception:
        pass

    # DND: if active, queue the message instead of announcing it
    try:
        from modules import dnd_mode as _dnd_wa
        if _dnd_wa.is_active():
            _dnd_wa.add_to_queue({
                "type":   "whatsapp_message",
                "from":   sender,
                "number": number,
                "text":   text,
                "wa_ts":  int(wa_ts) if wa_ts else None,
            })
            return jsonify({'status': 'dnd_queued'})
    except Exception:
        pass

    # Busy mode: still announce vocally, but also trigger auto-reply via N8N or direct AI
    try:
        from modules import busy_mode as _busy_msg
        if _busy_msg.is_active():
            # Log to busy session
            _busy_msg.log_message(sender, number, text, reply="")
            # Fire auto-reply in background (same N8N path as DND)
            import threading as _tbm
            def _busy_auto_reply():
                import requests as _req, os as _os
                try:
                    n8n_url  = _os.getenv("N8N_URL", "http://127.0.0.1:5678")
                    r = _req.post(
                        f"{n8n_url}/webhook/wa-auto-handle",
                        json={"from": sender, "number": number, "text": text,
                              "id": 0, "ts": int(__import__("time").time()), "mode": "busy"},
                        timeout=12,
                    )
                    if r.status_code != 200:
                        raise ValueError(f"N8N HTTP {r.status_code}")
                except Exception:
                    # Fallback: direct AI reply
                    try:
                        r2 = _req.post(
                            "http://127.0.0.1:5050/ai/respond",
                            json={"from": sender, "message": text, "number": number, "lang_hint": "hinglish"},
                            headers={"X-N8N-Token": "izach-n8n-2024", "Content-Type": "application/json"},
                            timeout=25,
                        )
                        reply = r2.json().get("reply", "").strip()
                        if reply:
                            _req.post(
                                "http://127.0.0.1:3000/send-message",
                                json={"number": number, "text": reply},
                                timeout=10,
                            )
                            _busy_msg.log_message(sender, number, text, reply)
                    except Exception:
                        pass
            _tbm.Thread(target=_busy_auto_reply, daemon=True, name="busy-auto-reply").start()
    except Exception:
        pass

    if _speak_func and _ai_func and _notif_whatsapp_enabled():
        _announce_pool.submit(_announce_message, sender, text, number)

    return jsonify({'status': 'notified'})

def _announce_message(sender: str, text: str, number: str = ""):
    """Generate natural announcement — context-aware, always English."""
    try:
        prompt = f"""You are iZACH, a JARVIS-style voice assistant for {_OWNER}.
Someone sent {_OWNER} a WhatsApp message. Announce it in ONE short English sentence.

Sender: {sender}
Message: "{text}"

Rules:
- ALWAYS respond in English only
- Summarize what the message means — never quote it word for word
- Always start with the sender's name
- Max 12 words
- Never say: "you have received", "you've got a message", "{_OWNER},"
- Never add filler like "Good", "Sure", "Alright" at the start

Good examples:
  "Bhai kaisa hai" → "{sender} is checking in on you."
  "Notes bhej de" → "{sender} needs your notes."
  "Kab aayega" → "{sender} wants to know when you're coming."
  "Party tonight?" → "{sender} is asking about the party."
  "Call me" → "{sender} wants you to call back."
  "Kya kar rha hai" → "{sender} is asking what you're up to."

Respond with ONLY the announcement sentence. Nothing else."""

        response = _ai_func(prompt)
        if _speak_func and response:
            clean = response.strip().strip('"')
            # Store for context so reply knows who/what to reply to
            _last_message["sender"] = sender
            _last_message["text"] = text
            _last_message["number"] = number
            _speak_func(clean)
    except Exception:
        if _speak_func:
            _speak_func(f"{sender} sent you a message.")

def handle_whatsapp_command(cmd, speak):
    global _pending_call
    if not _pending_call:
        speak("No pending WhatsApp call or message.")
        return

    number = _pending_call.get('number')
    caller = _pending_call.get('caller')

    if any(w in cmd for w in ["pick up", "accept", "answer"]):
        import pyautogui, time
        from modules.platform_utils import IS_MAC
        pyautogui.hotkey('command', 'tab') if IS_MAC else pyautogui.hotkey('alt', 'tab')
        time.sleep(1)
        speak("Picking up the call.")
        _pending_call = None

    elif any(w in cmd for w in ["ignore", "reject", "decline", "don't want to talk"]):
        reply = f"Hi, {_OWNER} is busy right now and will contact you later."
        ok, status = _send_message(number, reply, caller)
        speak(f"Call ignored. Sent a message to {caller}." if ok else f"Couldn't send message to {caller}.")
        _pending_call = None

    elif any(w in cmd for w in ["contact later", "reply later", "message them"]):
        reply = f"Hey! {_OWNER} saw your message and will get back to you soon."
        ok, status = _send_message(number, reply)
        speak(f"Replied to {caller} saying you'll contact them later." if ok else f"Couldn't send that to {caller} — {status}")
        _pending_call = None

    elif any(w in cmd for w in ["send voice", "voice note"]):
        audio_path = _generate_voice_note(
            f"Hey, this is {_OWNER}'s assistant. He's busy right now but will call you back soon."
        )
        _send_voice(number, audio_path)
        speak(f"Sent a voice note to {caller}.")
        _pending_call = None

def _send_message(number, text, contact_name=""):
    from modules.whatsapp_sender import send_message as _reliable_send
    from modules.context_memory import get_context_memory
    ok, status = _reliable_send(number, text, contact_name)
    if ok:
        get_context_memory().record_whatsapp_sent(
            contact_name or number, text, number
        )
    print(f"[WHATSAPP SEND] {status}")
    return ok, status

def _send_voice(number, audio_path):
    try:
        requests.post('http://localhost:3000/send-voice',
                      json={'number': number, 'audio_path': audio_path}, timeout=10)
    except Exception as e:
        print(f"[WHATSAPP] Voice send error: {e}")

def _generate_voice_note(text):
    path = "whatsapp_voice.mp3"
    async def _gen():
        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
        await communicate.save(path)
    asyncio.run(_gen())
    return os.path.abspath(path)


# =============================================================================
# WhatsApp Media Context Awareness
# =============================================================================

def _extract_text_from_media(media_type: str, b64_data: str, filename: str) -> str:
    """
    Extract readable text from a WA media attachment.
    image → Groq/Gemini vision
    pdf   → PyPDF2 text extraction
    docx  → python-docx paragraph extraction
    Returns extracted text string (may be empty on failure).
    """
    import base64, tempfile, os as _os

    if media_type == "image":
        try:
            from modules.camera_vision import _ask_vision
            prompt = (
                "Describe what this image shows. If it contains text (a document, notice, "
                "assignment, grocery list, etc.), extract and list all the text exactly. "
                "Mention any dates, deadlines, subject names, or important details you see."
            )
            return _ask_vision(b64_data, prompt) or ""
        except Exception as e:
            print(f"[WA MEDIA] Vision error: {e}")
            return ""

    raw_bytes = base64.b64decode(b64_data)

    if media_type == "pdf":
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages_text = []
            for page in reader.pages[:5]:  # limit to first 5 pages
                text = page.extract_text()
                if text:
                    pages_text.append(text.strip())
            return "\n".join(pages_text)
        except ImportError:
            try:
                import PyPDF2, io
                reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
                return "\n".join(
                    p.extract_text() for p in reader.pages[:5] if p.extract_text()
                )
            except Exception as e:
                print(f"[WA MEDIA] PDF extract error: {e}")
                return ""
        except Exception as e:
            print(f"[WA MEDIA] PDF extract error: {e}")
            return ""

    if media_type in ("docx", "doc"):
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(raw_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            print(f"[WA MEDIA] DOCX extract error: {e}")
            return ""

    return ""


def _announce_media_context(sender: str, media_type: str, filename: str, extracted_text: str, number: str):
    """
    Uses AI to summarise extracted media content, detect deadlines,
    announce to user, and trigger calendar event extraction if deadline found.
    """
    if not _speak_func or not _ai_func:
        return

    try:
        label_map = {"image": "an image", "pdf": "a PDF file", "docx": "a Word document", "doc": "a Word document"}
        label = label_map.get(media_type, "a file")

        if not extracted_text.strip():
            _speak_func(f"{sender} sent {label} named {filename}.")
            return

        prompt = f"""You are iZACH. {sender} sent {_OWNER} {label} via WhatsApp.

Extracted content from the file:
\"\"\"
{extracted_text[:1500]}
\"\"\"

Do these two things:
1. Announce in ONE short English sentence what the file is about and why it matters. Max 15 words. Start with the sender's name.
2. On a NEW LINE starting with "DEADLINE:", if you find any submission deadline, exam date, or due date, write it as: DEADLINE: <subject or task> | <date string as found in text>. If no deadline found, write: DEADLINE: none

Example output:
Siddhant sent notes on Time Series Analysis for Unit 3 exam.
DEADLINE: none

or:

College Teacher sent a Mathematics assignment due before 1 June.
DEADLINE: Mathematics Assignment | 1 June"""

        response = _ai_func(prompt)
        if not response:
            _speak_func(f"{sender} sent {label}.")
            return

        lines = response.strip().splitlines()
        announcement = lines[0].strip().strip('"') if lines else f"{sender} sent {label}."
        deadline_line = next((l for l in lines if l.strip().startswith("DEADLINE:")), "DEADLINE: none")

        _speak_func(announcement)

        # Broadcast to UI
        try:
            from modules.ws_bridge import broadcast
            import time as _t
            broadcast({
                "type": "notification",
                "source": "whatsapp_media",
                "text": f"📎 {sender}: {announcement}",
                "ts": _t.strftime("%H:%M"),
            })
        except Exception:
            pass
        try:
            from modules.notification_system import push as _notif_push
            _notif_push(f"WhatsApp — {sender}", category="alerts", body=announcement, source="whatsapp")
        except Exception:
            pass

        # Extract deadline → event_extractor
        if "none" not in deadline_line.lower():
            parts = deadline_line.replace("DEADLINE:", "").strip().split("|")
            if len(parts) == 2:
                task, date_str = parts[0].strip(), parts[1].strip()
                synthetic_text = f"{task} submission deadline is {date_str}."
                try:
                    import time as _t
                    from modules.event_extractor import process_message as _extract_event
                    _extract_event(
                        text=synthetic_text,
                        sender=sender,
                        msg_id=f"media_{_t.time()}",
                        timestamp=str(_t.time())
                    )
                except Exception as exc:
                    print(f"[WA MEDIA] Event extract error: {exc}")

    except Exception as e:
        print(f"[WA MEDIA] Announce error: {e}")
        if _speak_func:
            _speak_func(f"{sender} sent a file.")


@app.route('/whatsapp/media', methods=['POST'])
def incoming_media():
    """
    Receives WhatsApp media attachments from the Node.js bridge.
    Expected JSON payload:
    {
        "sender":     "display name or number",
        "number":     "919XXXXXXXXX",
        "media_type": "image" | "pdf" | "docx" | "doc" | "video" | "audio",
        "filename":   "Assignment.pdf",
        "data":       "<base64 encoded file bytes>"
    }
    """
    data = request.json or {}
    raw_sender  = data.get("sender", "Unknown")
    number      = data.get("number", "")
    media_type  = data.get("media_type", "").lower()
    filename    = data.get("filename", "file")
    b64_data    = data.get("data", "")

    sender = _resolve_name(number, raw_sender)

    # Unsupported types (video, audio) — just announce, no extraction
    if media_type in ("video", "audio"):
        if _speak_func:
            label = "a video" if media_type == "video" else "a voice note"
            _speak_func(f"{sender} sent {label}.")
        try:
            from modules.ws_bridge import broadcast
            import time as _t
            broadcast({
                "type": "notification",
                "source": "whatsapp_media",
                "text": f"📎 {sender} sent {'a video' if media_type == 'video' else 'a voice note'}.",
                "ts": _t.strftime("%H:%M"),
            })
        except Exception:
            pass
        try:
            from modules.notification_system import push as _notif_push
            label = "a video" if media_type == "video" else "a voice note"
            _notif_push(f"WhatsApp — {sender}", category="alerts", body=f"Sent {label}.", source="whatsapp")
        except Exception:
            pass
        return jsonify({"status": "announced"})

    if not b64_data:
        return jsonify({"status": "no_data"}), 400

    # Run media processing in background — don't block the bridge
    _announce_pool.submit(_process_media_async, sender, number, media_type, filename, b64_data)
    return jsonify({"status": "processing"})


def _process_media_async(sender: str, number: str, media_type: str, filename: str, b64_data: str):
    """Background worker: extract text from media, then announce with context."""
    extracted = _extract_text_from_media(media_type, b64_data, filename)
    _announce_media_context(sender, media_type, filename, extracted, number)