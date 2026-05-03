import threading
import requests
import asyncio
import edge_tts
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
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

def get_last_message():
    return _last_message

def set_ui_callbacks(notify_fn, log_fn):
    global _notify_func, _log_func
    _notify_func = notify_fn
    _log_func = log_fn

def init_whatsapp(speak, chain, ai_func=None):
    global _speak_func, _chain_func, _ai_func
    _speak_func = speak
    _chain_func = chain
    _ai_func = ai_func
    
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
    threading.Thread(target=lambda: app.run(port=5050, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=_monitor_connection, daemon=True).start()
    threading.Thread(target=_start_bridge, daemon=True).start()
    print("[WHATSAPP] Handler Online on port 5050")

def _start_bridge():
    import subprocess, time
    time.sleep(3)  # Wait for Flask to start first
    try:
        bridge_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "whatsapp_bridge.js")
        subprocess.Popen(["node", bridge_path],
                        creationflags=subprocess.CREATE_NEW_CONSOLE)
        print("[WHATSAPP] Bridge started automatically")
    except Exception as e:
        print(f"[WHATSAPP] Could not auto-start bridge: {e}")

def _monitor_connection():
    import time, requests as req
    time.sleep(15)  # Give bridge time to connect
    while True:
        try:
            r = req.get("http://localhost:3000/health", timeout=3)
            status = r.json().get("status")
            if status != "connected" and _speak_func:
                _speak_func("WhatsApp is not connected.")
        except Exception:
            if _speak_func:
                _speak_func("WhatsApp bridge is offline.")
        time.sleep(300)  # Check every 5 minutes

@app.route('/whatsapp/call', methods=['POST'])
def incoming_call():
    global _pending_call
    data = request.json
    raw_caller = data.get('caller', 'Unknown')
    number = data.get('number')
    caller = _resolve_name(number, raw_caller)
    _pending_call = {'caller': caller, 'number': number, 'type': 'call'}
    if _speak_func:
        _speak_func(f"Vansh, {caller} is calling you on WhatsApp. Should I pick up, ignore, or reply later?")
    return jsonify({'status': 'notified'})

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

@app.route('/whatsapp/status', methods=['POST'])
def whatsapp_status():
    data = request.json
    status = data.get('status')
    if status == 'connected':
        if _speak_func:
            _speak_func("WhatsApp connected.")
    elif status == 'disconnected':
        if _speak_func:
            _speak_func("Vansh, WhatsApp disconnected.")
    return jsonify({'status': 'ok'})

_last_message = {"sender": None, "text": None, "number": None}

@app.route('/whatsapp/message', methods=['POST'])
def incoming_message():
    global _last_message
    data = request.json
    raw_sender = data.get('sender', 'Unknown')
    text = data.get('text', '')
    number = data.get('number')
    sender = _resolve_name(number, raw_sender)

    _last_message = {"sender": sender, "text": text, "number": number}

    try:
        from modules.mongo_brain import store_context
        store_context("last_whatsapp_sender", sender)
        store_context("last_whatsapp_text",   text)
        store_context("last_whatsapp_number", number)
    except Exception:
        pass

    from modules.context_memory import get_context_memory
    get_context_memory().record_whatsapp_received(sender, text, number)

    if _notify_func:
        _notify_func(f"WhatsApp — {sender}", text[:120])
    try:
        from modules.ws_bridge import broadcast
        import time as _time
        broadcast({
            "type": "notification",
            "text": f"WhatsApp — {sender}: {text[:60]}",
            "ts": _time.strftime("%H:%M")
        })
    except Exception:
        pass

    if _speak_func and _ai_func:
        threading.Thread(
            target=_announce_message,
            args=(sender, text, number),
            daemon=True
        ).start()

    return jsonify({'status': 'notified'})

def _announce_message(sender: str, text: str, number: str = ""):
    """Generate natural announcement — context-aware, always English."""
    try:
        prompt = f"""You are iZACH, a JARVIS-style voice assistant for Vansh.
Someone sent Vansh a WhatsApp message. Announce it in ONE short English sentence.

Sender: {sender}
Message: "{text}"

Rules:
- ALWAYS respond in English only
- Summarize what the message means — never quote it word for word
- Always start with the sender's name
- Max 12 words
- Never say: "you have received", "you've got a message", "Vansh,"
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
        pyautogui.hotkey('alt', 'tab')
        time.sleep(1)
        speak("Picking up the call.")
        _pending_call = None

    elif any(w in cmd for w in ["ignore", "reject", "decline", "don't want to talk"]):
        reply = f"Hi, Vansh is busy right now and will contact you later."
        ok, status = _send_message(number, reply, caller)
        speak(f"Call ignored. Sent a message to {caller}." if ok else f"Couldn't send message to {caller}.")
        _pending_call = None

    elif any(w in cmd for w in ["contact later", "reply later", "message them"]):
        reply = f"Hey! Vansh saw your message and will get back to you soon."
        _send_message(number, reply)
        speak(f"Replied to {caller} saying you'll contact them later.")
        _pending_call = None

    elif any(w in cmd for w in ["send voice", "voice note"]):
        audio_path = _generate_voice_note(
            f"Hey, this is Vansh's assistant. He's busy right now but will call you back soon."
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