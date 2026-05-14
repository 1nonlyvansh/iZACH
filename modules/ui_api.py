"""
modules/ui_api.py
REST API for the iZACH React/Electron UI.
Registered onto the same Flask app as whatsapp_handler (port 5050).
"""

import os
import time
import threading
import uuid as _uuid
import hashlib as _hashlib
import psutil
from flask import Blueprint, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ── Safe mode — commands requiring explicit confirmation ──────
_DANGEROUS_CMDS = [
    "shutdown pc", "shut down pc", "shutdown computer", "shut down computer",
    "turn off pc", "turn off my pc", "turn off computer", "turn off my computer",
    "restart pc", "restart my pc", "restart computer", "restart my computer",
    "force restart", "force shutdown", "reboot",
    "log off", "logoff", "sign out of windows",
    "kill process", "force quit", "end task",
]
_pending_confirmations: dict[str, dict] = {}


def _is_dangerous(text: str) -> bool:
    lc = text.lower().strip()
    return any(cmd in lc for cmd in _DANGEROUS_CMDS)

def _safe_mode_on() -> bool:
    try:
        import json as _j
        with open("api_keys.json") as _f:
            return bool(_j.load(_f).get("safe_mode_enabled", True))
    except Exception:
        return True

SHARED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "shared")
os.makedirs(SHARED_DIR, exist_ok=True)

ui_bp = Blueprint("ui_api", __name__)

# ── injected at startup ───────────────────────────────────────
_chain_fn    = None
_speak_fn    = None
_get_resp    = None
_spotify_api = None     # SpotifyController instance

# ── in-process message log ────────────────────────────────────
_message_log: list[dict] = []
MAX_LOG = 200

# ── psutil CPU primer (first call always returns 0 — call once at import) ──
psutil.cpu_percent(interval=None)


def register_ui_api(app, chain_fn, speak_fn, get_response_fn, spotify_handler=None):
    """
    Call once during startup from whatsapp_handler.init_whatsapp().
    spotify_handler — SpotifyController instance (optional but needed for /spotify)
    """
    global _chain_fn, _speak_fn, _get_resp, _spotify_api
    _chain_fn    = chain_fn
    _speak_fn    = speak_fn
    _get_resp    = get_response_fn
    _spotify_api = spotify_handler

    # Start clipboard monitor once at startup
    try:
        from modules.clipboard_sync import start as _start_clipboard
        _start_clipboard()
    except Exception as _e:
        print(f"[UI API] Clipboard monitor failed: {_e}")

    # Start download monitor
    try:
        from modules.download_monitor import start as _start_downloads
        _start_downloads()
    except Exception as _e:
        print(f"[UI API] Download monitor failed: {_e}")

    CORS(app, resources={r"/*": {"origins": [
        "http://localhost:5173",
        "http://localhost:4173",
        "app://*",
    ]}})

    app.register_blueprint(ui_bp)
    print("[UI API] Registered on Flask app. CORS enabled for React/Electron.")


def _log_message(sender: str, text: str):
    global _message_log
    _message_log.append({
        "sender": sender,
        "text":   text,
        "ts":     time.strftime("%H:%M"),
        "epoch":  time.time(),
    })
    if len(_message_log) > MAX_LOG:
        _message_log = _message_log[-MAX_LOG:]


# ─────────────────────────────────────────────────────────────
# POST /command
# Body:    { "text": "play kanye" }
# Returns: { "ok": true, "response": "Playing Kanye West.", "ts": "14:32" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/command", methods=["POST", "OPTIONS"])
def ui_command():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or data.get("command") or "").strip()

    if not text:
        return jsonify({"ok": False, "error": "Empty command"}), 400

    _log_message("YOU", text)
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "chat", "sender": "YOU", "text": text, "ts": time.strftime("%H:%M")})
    except Exception:
        pass

    # File-related voice command shortcuts — handled before chain
    _lc = text.lower()
    # Screenshot voice commands
    if any(k in _lc for k in ("screenshot", "capture screen", "show my desktop",
                               "capture current", "take a screenshot", "screen capture")):
        try:
            from modules.screenshot_engine import capture_sync
            from modules.task_events import start as _ts, complete as _tc
            tid = _ts("Screenshot capture")
            filename = capture_sync()
            if filename:
                _tc(tid, f"Screenshot ready: {filename}")
                reply = f"Screenshot captured. Check your phone — file: {filename}"
                try:
                    from modules.ws_bridge import broadcast
                    broadcast({"type": "screenshot_ready", "filename": filename, "ts": time.strftime("%H:%M")})
                except Exception:
                    pass
            else:
                reply = "Screenshot failed. Check pyautogui is installed."
        except Exception as _e:
            reply = f"Screenshot error: {_e}"
        _log_message("iZACH", reply)
        return jsonify({"ok": True, "response": reply, "ts": time.strftime("%H:%M")})

    # PC context voice commands
    if any(k in _lc for k in ("ram", "memory usage", "cpu", "battery", "disk space",
                               "storage left", "internet status", "wifi status",
                               "what's running", "running apps", "where is my",
                               "find my", "recent files", "how much storage")):
        try:
            from modules.pc_context import answer as _pc_answer
            result = _pc_answer(text)
            reply = result.get("text") or "Could not determine answer."
        except Exception as _e:
            reply = f"PC context error: {_e}"
        _log_message("iZACH", reply)
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "chat", "sender": "iZACH", "text": reply, "ts": time.strftime("%H:%M")})
        except Exception:
            pass
        return jsonify({"ok": True, "response": reply, "ts": time.strftime("%H:%M")})

    if any(k in _lc for k in ("send file", "transfer file", "send to phone", "send me file",
                                "send report", "send pdf", "send document")):
        reply = "Which file? Type / in chat to browse your PC files."
        _log_message("iZACH", reply)
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "chat", "sender": "iZACH", "text": reply,
                       "ts": time.strftime("%H:%M"), "action": "open_file_picker"})
        except Exception:
            pass
        return jsonify({"ok": True, "response": reply, "action": "open_file_picker",
                        "ts": time.strftime("%H:%M")})

    if any(k in _lc for k in ("shared files", "files on phone", "what files", "list files", "send to phone")):
        try:
            fnames = [f for f in sorted(os.listdir(SHARED_DIR)) if os.path.isfile(os.path.join(SHARED_DIR, f))]
            reply = f"Shared folder: {len(fnames)} file(s) — {', '.join(fnames[-5:])}" if fnames else "Shared folder is empty. Upload files from your phone."
        except Exception:
            reply = "Cannot read shared folder."
        _log_message("iZACH", reply)
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "chat", "sender": "iZACH", "text": reply, "ts": time.strftime("%H:%M")})
        except Exception:
            pass
        return jsonify({"ok": True, "response": reply, "ts": time.strftime("%H:%M")})

    # Safe mode — dangerous commands require confirmation
    if _safe_mode_on() and _is_dangerous(text):
        token = _uuid.uuid4().hex[:8]
        _pending_confirmations[token] = {"text": text, "expires": time.time() + 30}
        # Expire old tokens
        now = time.time()
        for k in list(_pending_confirmations.keys()):
            if _pending_confirmations[k]["expires"] < now:
                del _pending_confirmations[k]
        return jsonify({
            "ok": True,
            "requires_confirmation": True,
            "confirmation_token": token,
            "message": f"Confirm: {text}?",
            "ts": time.strftime("%H:%M"),
        })

    try:
        if _chain_fn is None:
            return jsonify({"ok": False, "error": "Backend not initialized"}), 503

        captured = []

        def _capture_speak(msg, **kwargs):
            if msg and msg.strip():
                import re as _re
                clean = _re.sub(r'<[^>]+>', '', msg).strip()
                clean = _re.sub(r'^\[TONE:[^\]]+\]', '', clean).strip()
                if clean:
                    captured.append(clean)
            # Text commands: NO TTS — text reply only

        # Patch speak on the chain object for this request
        chain_obj     = getattr(_chain_fn, '__self__', None)
        original_speak = None
        if chain_obj and hasattr(chain_obj, 'speak'):
            original_speak    = chain_obj.speak
            chain_obj.speak   = _capture_speak

        _chain_fn(text)

        if chain_obj and original_speak is not None:
            chain_obj.speak = original_speak

        # If chain didn't speak, fall back to direct AI
        if not captured and _get_resp:
            resp = _get_resp(text)
            if resp:
                captured.append(resp)

        response_text = " ".join(captured).strip() or "Done."
        _log_message("iZACH", response_text)
        try:
            broadcast({"type": "chat", "sender": "iZACH", "text": response_text, "ts": time.strftime("%H:%M")})
        except Exception:
            pass

        return jsonify({
            "ok":       True,
            "response": response_text,
            "ts":       time.strftime("%H:%M"),
        })

    except Exception as e:
        err = f"Backend error: {type(e).__name__}: {e}"
        print(f"[UI API] /command error: {err}")
        return jsonify({"ok": False, "error": err}), 500


# ─────────────────────────────────────────────────────────────
# GET /status
# FIX: use interval=0.1 so CPU is never 0
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/status", methods=["GET"])
def ui_status():
    try:
        # interval=0.1 gives a real reading every call (never 0)
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()

        # iZACH process own stats
        proc_cpu = 0.0
        proc_mem = 0.0
        try:
            import os as _os
            p = psutil.Process(_os.getpid())
            proc_cpu = round(p.cpu_percent(interval=0.1), 1)
            proc_mem = round(p.memory_percent(), 1)
        except Exception:
            pass

        # Check WhatsApp bridge
        wa_online = False
        try:
            import requests as _req
            r = _req.get("http://localhost:3000/health", timeout=2)
            wa_online = r.json().get("status") == "connected"
        except Exception:
            pass

        # Check MMA agent
        mma_online = False
        try:
            import requests as _req
            r = _req.get("http://localhost:6060/health", timeout=2)
            mma_online = r.status_code == 200
        except Exception:
            pass

        gpu = 0.0
        try:
            import subprocess as _sp
            out = _sp.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                stderr=_sp.DEVNULL, timeout=2
            ).decode().strip()
            gpu = round(float(out.split("\n")[0]), 1)
        except Exception:
            pass

        android_devices = []
        try:
            from modules.ws_bridge import get_android_devices
            android_devices = get_android_devices()
        except Exception:
            pass

        return jsonify({
            "ok":              True,
            "cpu":             round(cpu, 1),
            "ram":             round(ram.percent, 1),
            "ram_used_gb":     round(ram.used  / 1e9, 2),
            "ram_total_gb":    round(ram.total / 1e9, 2),
            "proc_cpu":        proc_cpu,
            "proc_mem":        proc_mem,
            "gpu":             gpu,
            "ts":              time.strftime("%H:%M:%S"),
            "whatsapp":        wa_online,
            "mma":             mma_online,
            "android_devices": android_devices,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# POST /spotify/control  — direct playback control (no chat pipeline)
# body: { "action": "playpause" | "next" | "prev" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/spotify/control", methods=["POST"])
def spotify_control():
    try:
        if _spotify_api is None:
            return jsonify({"ok": False, "error": "Spotify not initialised"}), 503
        data   = request.get_json(silent=True) or {}
        action = data.get("action", "")
        if action == "playpause":
            pb = _spotify_api.sp.current_playback() if _spotify_api.sp else None
            if pb and pb.get("is_playing"):
                msg = _spotify_api.pause_music()
            else:
                msg = _spotify_api.resume_music()
        elif action == "next":
            msg = _spotify_api.next_track()
        elif action == "prev":
            msg = _spotify_api.previous_track()
        else:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400
        return jsonify({"ok": True, "msg": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# POST /spotify/volume  — set playback volume (0–100)
# body: { "volume": 75 }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/spotify/volume", methods=["POST"])
def spotify_volume():
    try:
        if _spotify_api is None:
            return jsonify({"ok": False, "error": "Spotify not initialised"}), 503
        data = request.get_json(silent=True) or {}
        vol  = max(0, min(100, int(data.get("volume", 50))))
        _spotify_api.sp.volume(vol)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /spotify
# Returns current track info from SpotifyController
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/spotify", methods=["GET"])
def ui_spotify():
    try:
        if _spotify_api is None:
            return jsonify({"ok": False, "error": "Spotify not initialised"}), 503

        pb = _spotify_api.sp.current_playback() if _spotify_api.sp else None

        if pb is None or not pb.get("is_playing"):
            return jsonify({
                "ok":        True,
                "playing":   False,
                "title":     "—",
                "artist":    "—",
                "device":    "—",
                "album_art": "",
                "progress":  0,
                "duration":  0,
                "volume":    0,
            })

        item   = pb.get("item", {}) or {}
        title  = item.get("name", "—")
        artist = ", ".join(a["name"] for a in item.get("artists", []))
        album  = item.get("album", {}) or {}
        images = album.get("images", [])
        art    = images[0]["url"] if images else ""
        device = pb.get("device", {}) or {}

        return jsonify({
            "ok":        True,
            "playing":   True,
            "title":     title,
            "artist":    artist,
            "device":    device.get("name", "—"),
            "album_art": art,
            "progress":  pb.get("progress_ms", 0),
            "duration":  item.get("duration_ms", 0),
            "volume":    device.get("volume_percent", 0),
            "shuffle":   pb.get("shuffle_state", False),
            "repeat":    pb.get("repeat_state", "off"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /memory          — list all memory entries
# POST /memory          — add entry  { "key": "x", "value": "y" }
# DELETE /memory/<key>  — remove entry
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/memory", methods=["GET"])
def memory_list():
    try:
        from modules.memory import list_memory
        entries = list_memory()   # [(key, value, added), ...]
        return jsonify({
            "ok":   True,
            "data": [{"key": k, "value": v, "added": a} for k, v, a in entries],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/memory", methods=["POST"])
def memory_add():
    try:
        data  = request.get_json(silent=True) or {}
        key   = data.get("key", "").strip()
        value = data.get("value", "").strip()
        if not key or not value:
            return jsonify({"ok": False, "error": "key and value required"}), 400
        from modules.memory import add_memory
        add_memory(key, value)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/memory/<path:key>", methods=["DELETE"])
def memory_delete(key):
    try:
        from modules.memory import remove_memory
        removed = remove_memory(key)
        return jsonify({"ok": removed, "error": None if removed else "Key not found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /settings          — read api_keys.json
# POST /settings          — write api_keys.json
# ─────────────────────────────────────────────────────────────

import json as _json
SETTINGS_FILE = "api_keys.json"

@ui_bp.route("/settings", methods=["GET"])
def settings_get():
    try:
        with open(SETTINGS_FILE) as f:
            data = _json.load(f)
        # Never expose raw API keys to the frontend — send masked versions
        safe = {}
        for k, v in data.items():
            if "key" in k.lower() and isinstance(v, str) and len(v) > 8:
                safe[k] = v[:6] + "•" * (len(v) - 6)
            else:
                safe[k] = v
        return jsonify({"ok": True, "settings": safe})
    except FileNotFoundError:
        return jsonify({"ok": True, "settings": {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/settings", methods=["POST"])
def settings_post():
    try:
        incoming = request.get_json(silent=True) or {}
        # Load existing so we don't overwrite keys that weren't sent
        try:
            with open(SETTINGS_FILE) as f:
                existing = _json.load(f)
        except Exception:
            existing = {}

        # Only update non-key fields (never accept raw key overwrites from UI)
        allowed = {
            "wake_word_enabled", "voice", "tts_speed",
            "response_style", "response_verbosity", "safe_mode_enabled",
            "notif_performance", "notif_whatsapp", "notif_downloads",
            "command_history_enabled", "log_retention_days",
            "theme", "language",
        }
        for k, v in incoming.items():
            if k in allowed:
                existing[k] = v

        with open(SETTINGS_FILE, "w") as f:
            _json.dump(existing, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/history", methods=["GET"])
def ui_history():
    try:
        n = min(int(request.args.get("n", 50)), MAX_LOG)
    except (ValueError, TypeError):
        n = 50
    return jsonify({"ok": True, "messages": _message_log[-n:]})


# ─────────────────────────────────────────────────────────────
# POST /stop  — stop TTS mid-speech
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/shutdown", methods=["POST"])
def ui_shutdown():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    import threading
    def _do_shutdown():
        import time
        time.sleep(0.5)
        import os
        os.kill(os.getpid(), 9)
    threading.Thread(target=_do_shutdown, daemon=True).start()
    return jsonify({"ok": True})

_mic_active = True

@ui_bp.route("/mic", methods=["GET", "POST"])
def ui_mic():
    global _mic_active
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        _mic_active = bool(data.get("active", True))
        return jsonify({"ok": True, "mic_active": _mic_active})
    return jsonify({"ok": True, "mic_active": _mic_active})

def is_mic_active():
    return _mic_active

@ui_bp.route("/mongo/profile", methods=["GET"])
def mongo_profile():
    try:
        from modules.mongo_brain import get_db
        db = get_db()
        if not db:
            return jsonify({"ok": False, "error": "MongoDB offline"}), 503
        doc = db.profile.find_one({"_id": "vansh"}, {"_id": 0})
        return jsonify({"ok": True, "profile": doc or {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/mongo/history", methods=["GET"])
def mongo_history():
    try:
        from modules.mongo_brain import get_recent_history
        return jsonify({"ok": True, "history": get_recent_history(20)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/cache/sizes", methods=["GET"])
def cache_sizes():
    from pathlib import Path as _Path

    root = _Path(__file__).parent.parent

    def _dir_bytes(p):
        total, count = 0, 0
        try:
            for f in (p.rglob("*") if p.is_dir() else []):
                if f.is_file():
                    total += f.stat().st_size
                    count += 1
        except Exception:
            pass
        return total, count

    def _fmt(b):
        if b >= 1_000_000:
            return f"{b / 1_000_000:.1f} MB"
        if b >= 1_000:
            return f"{b / 1_000:.1f} KB"
        return f"{b} B"

    sizes = {}

    sz, cnt = _dir_bytes(root / "temp")
    sizes["temp"] = f"{_fmt(sz)}  ·  {cnt} files" if cnt else "empty"

    sc_dir = root / "screenshots"
    sc_files = list(sc_dir.glob("*.jpg")) if sc_dir.exists() else []
    sc_sz = sum(f.stat().st_size for f in sc_files)
    sizes["screenshots"] = f"{_fmt(sc_sz)}  ·  {len(sc_files)} files" if sc_files else "empty"

    try:
        from modules import realtime_data as _rd
        sizes["realtime"] = f"{len(_rd._cache)} entries cached"
    except Exception:
        sizes["realtime"] = "unknown"

    sizes["msglog"] = f"{len(_message_log)} messages"

    try:
        from modules.context_memory import get_context_memory
        cm = get_context_memory()
        sizes["context"] = f"{len(cm._history) + len(cm._entities)} entries"
    except Exception:
        sizes["context"] = "unknown"

    sz, cnt = _dir_bytes(root / ".wwebjs_cache")
    sizes["wwebjs_cache"] = f"{_fmt(sz)}  ·  {cnt} files" if cnt else "empty"

    sp_dir = root / ".cache"
    sp_files = [f for f in sp_dir.iterdir() if f.is_file()] if sp_dir.exists() else []
    sp_sz = sum(f.stat().st_size for f in sp_files)
    sizes["spotify_cache"] = f"{_fmt(sp_sz)}" if sp_files else "empty"

    # speech_files — speech_*.mp3 in root
    speech_files = list(root.glob("speech_*.mp3"))
    speech_sz = sum(f.stat().st_size for f in speech_files)
    sizes["speech_files"] = f"{_fmt(speech_sz)}  ·  {len(speech_files)} files" if speech_files else "empty"

    # logs directory
    sz, cnt = _dir_bytes(root / "logs")
    sizes["logs"] = f"{_fmt(sz)}  ·  {cnt} files" if cnt else "empty"

    # command_log.csv
    cl = root / "command_log.csv"
    sizes["command_log"] = _fmt(cl.stat().st_size) if cl.exists() else "empty"

    # wa_processed_msgs.json
    wa = root / "wa_processed_msgs.json"
    sizes["wa_processed"] = _fmt(wa.stat().st_size) if wa.exists() else "empty"

    # __pycache__ dirs
    pc_total, pc_count = 0, 0
    for pc in root.rglob("__pycache__"):
        if pc.is_dir():
            s, c = _dir_bytes(pc)
            pc_total += s
            pc_count += c
    sizes["pycache"] = f"{_fmt(pc_total)}  ·  {pc_count} files" if pc_count else "empty"

    return jsonify({"ok": True, "sizes": sizes})


@ui_bp.route("/cache/clear", methods=["POST"])
def cache_clear():
    from pathlib import Path as _Path

    data = request.get_json(silent=True) or {}
    targets = set(data.get("targets", []))
    if not targets:
        return jsonify({"ok": False, "error": "No targets selected"}), 400

    root = _Path(__file__).parent.parent
    cleared = []
    errors = []

    if "temp" in targets:
        try:
            count = sum(
                1 for f in (root / "temp").iterdir()
                if f.is_file() and not f.unlink(missing_ok=True)
            )
            cleared.append(f"temp ({count} files)")
        except Exception as e:
            errors.append(f"temp: {e}")

    if "screenshots" in targets:
        try:
            count = sum(
                1 for f in (root / "screenshots").glob("*")
                if f.is_file() and not f.unlink(missing_ok=True)
            )
            cleared.append(f"screenshots ({count} files)")
        except Exception as e:
            errors.append(f"screenshots: {e}")

    if "realtime" in targets:
        try:
            from modules import realtime_data as _rd
            _rd._cache.clear()
            cleared.append("realtime data cache")
        except Exception as e:
            errors.append(f"realtime: {e}")

    if "msglog" in targets:
        global _message_log
        _message_log.clear()
        cleared.append("message log")

    if "context" in targets:
        try:
            from modules.context_memory import get_context_memory
            cm = get_context_memory()
            cm._history.clear()
            cm._entities.clear()
            cleared.append("context history")
        except Exception as e:
            errors.append(f"context: {e}")

    if "wwebjs_cache" in targets:
        try:
            import shutil as _shutil
            ww = root / ".wwebjs_cache"
            if ww.exists():
                _shutil.rmtree(ww)
                ww.mkdir()
            cleared.append("WhatsApp browser cache")
        except Exception as e:
            errors.append(f"wwebjs_cache: {e}")

    if "spotify_cache" in targets:
        try:
            sc = root / ".cache"
            if sc.exists():
                for f in sc.iterdir():
                    if f.is_file():
                        f.unlink(missing_ok=True)
            cleared.append("Spotify OAuth token")
        except Exception as e:
            errors.append(f"spotify_cache: {e}")

    if "speech_files" in targets:
        try:
            count = 0
            for f in root.glob("speech_*.mp3"):
                f.unlink(missing_ok=True)
                count += 1
            cleared.append(f"speech files ({count} files)")
        except Exception as e:
            errors.append(f"speech_files: {e}")

    if "logs" in targets:
        try:
            count = sum(
                1 for f in (root / "logs").iterdir()
                if f.is_file() and not f.unlink(missing_ok=True)
            )
            cleared.append(f"logs ({count} files)")
        except Exception as e:
            errors.append(f"logs: {e}")

    if "command_log" in targets:
        try:
            cl = root / "command_log.csv"
            if cl.exists():
                cl.write_text("timestamp,source,command,result,duration\n", encoding="utf-8")
            cleared.append("command history CSV")
        except Exception as e:
            errors.append(f"command_log: {e}")

    if "wa_processed" in targets:
        try:
            wa = root / "wa_processed_msgs.json"
            if wa.exists():
                wa.write_text("[]", encoding="utf-8")
            cleared.append("WhatsApp processed IDs")
        except Exception as e:
            errors.append(f"wa_processed: {e}")

    if "pycache" in targets:
        try:
            import shutil as _shutil
            count = 0
            for pc in root.rglob("__pycache__"):
                if pc.is_dir():
                    _shutil.rmtree(pc, ignore_errors=True)
                    count += 1
            cleared.append(f"Python bytecode cache ({count} dirs)")
        except Exception as e:
            errors.append(f"pycache: {e}")

    return jsonify({"ok": True, "cleared": cleared, "errors": errors})


@ui_bp.route("/obsidian/sync", methods=["POST"])
def obsidian_sync():
    try:
        from modules.obsidian_brain import generate_insights
        generate_insights()
        return jsonify({"ok": True, "message": "Obsidian vault updated."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/analyze", methods=["POST"])
def ui_analyze():
    try:
        from modules.performance_analyzer import run_analysis
        mode = request.args.get("mode", "overwrite")
        ok, result = run_analysis(mode=mode)
        return jsonify({"ok": ok, "message": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/stop", methods=["POST"])
def ui_stop():
    try:
        import pygame as _pg
        _pg.mixer.music.stop()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    
# ─────────────────────────────────────────────────────────────
# POST /vision/ask
# Body:    { "question": "what am i holding?" }
# Returns: { "ok": true, "answer": "You are holding..." }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/vision/ask", methods=["POST"])
def vision_ask():
    try:
        data = request.get_json(silent=True) or {}
        question = data.get("question", "What do you see?").strip()
        from modules.camera_vision import capture_and_ask
        answer = capture_and_ask(question)
        return jsonify({"ok": True, "answer": answer})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /vision/stream  — MJPEG live camera feed for UI
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/vision/stream")
def vision_stream():
    import cv2 as _cv2
    from flask import Response as _Response
    from modules.camera_vision import _start_stream_cam, _stop_stream_cam, _read_stream_frame

    def _generate():
        _start_stream_cam()
        try:
            while True:
                frame = _read_stream_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue
                ret, buf = _cv2.imencode('.jpg', frame, [_cv2.IMWRITE_JPEG_QUALITY, 65])
                if not ret:
                    continue
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')
                time.sleep(0.067)  # ~15 fps
        except GeneratorExit:
            pass
        finally:
            _stop_stream_cam()

    return _Response(_generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ─────────────────────────────────────────────────────────────
# GET /mic/devices   — list audio input devices
# POST /mic/select   — { "index": N } switch active mic
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/mic/devices")
def mic_devices():
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append({"index": i, "name": info["name"]})
        p.terminate()
        import main as _main
        active = getattr(_main, "_mic_device_index", None)
        return jsonify({"ok": True, "devices": devices, "active": active})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/mic/select", methods=["POST"])
def mic_select():
    try:
        data = request.get_json(silent=True) or {}
        idx = data.get("index", None)
        if idx is not None:
            idx = int(idx)
        import main as _main
        _main.set_mic_device(idx)
        return jsonify({"ok": True, "active": idx})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# File transfer — shared folder at /shared/
# POST /upload           — multipart file upload
# GET  /files            — list shared files
# GET  /download/<name>  — download file
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/upload", methods=["POST", "OPTIONS"])
def ui_upload():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    filename = secure_filename(f.filename)
    dest = os.path.join(SHARED_DIR, filename)
    f.save(dest)
    size = os.path.getsize(dest)
    return jsonify({"ok": True, "filename": filename, "size": size})


@ui_bp.route("/files", methods=["GET"])
def ui_files():
    try:
        files = []
        for name in sorted(os.listdir(SHARED_DIR)):
            p = os.path.join(SHARED_DIR, name)
            if os.path.isfile(p):
                files.append({
                    "name": name,
                    "size": os.path.getsize(p),
                    "modified": os.path.getmtime(p),
                })
        return jsonify({"ok": True, "files": files})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/download/<path:filename>", methods=["GET"])
def ui_download(filename):
    try:
        return send_from_directory(SHARED_DIR, filename, as_attachment=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 404


# ─────────────────────────────────────────────────────────────
# Smart File Selector — browser for PC filesystem
# GET /list_dirs              — predefined roots; ?path= for subdirs
# GET /list_files?path=       — files in given directory
# GET /fetch_file?path=       — stream file by validated absolute path
# ─────────────────────────────────────────────────────────────

_ALLOWED_ROOTS: dict | None = None

def _build_roots() -> dict:
    home = os.path.expanduser("~")
    roots = {}
    for label, rel in [
        ("Desktop", "Desktop"),
        ("Downloads", "Downloads"),
        ("Documents", "Documents"),
        ("Pictures", "Pictures"),
        ("Videos", "Videos"),
        ("Music", "Music"),
    ]:
        p = os.path.join(home, rel)
        if os.path.isdir(p):
            roots[label] = p
    # OneDrive Desktop / Documents (common on Windows 11)
    for od in ["OneDrive", "OneDrive - Personal"]:
        od_path = os.path.join(home, od)
        if os.path.isdir(od_path):
            for label, rel in [("OneDrive Desktop", "Desktop"), ("OneDrive Documents", "Documents")]:
                p = os.path.join(od_path, rel)
                if os.path.isdir(p):
                    roots[label] = p
    roots["Shared (iZACH)"] = SHARED_DIR
    return roots

def _get_roots() -> dict:
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is None:
        _ALLOWED_ROOTS = _build_roots()
    return _ALLOWED_ROOTS

def _validate_path(path: str) -> str | None:
    """Return realpath if within allowed roots, else None."""
    try:
        real = os.path.realpath(path)
        for root in _get_roots().values():
            if real.startswith(os.path.realpath(root)):
                return real
    except Exception:
        pass
    return None


@ui_bp.route("/list_dirs", methods=["GET"])
def ui_list_dirs():
    path = request.args.get("path", "").strip()
    if not path:
        roots = _get_roots()
        return jsonify({"ok": True, "entries": [
            {"name": k, "path": v, "is_dir": True}
            for k, v in roots.items() if os.path.isdir(v)
        ]})
    safe = _validate_path(path)
    if not safe:
        return jsonify({"ok": False, "error": "Access denied"}), 403
    try:
        entries = []
        for name in sorted(os.listdir(safe)):
            if name.startswith("."):
                continue
            full = os.path.join(safe, name)
            if os.path.isdir(full):
                entries.append({"name": name, "path": full, "is_dir": True})
        return jsonify({"ok": True, "entries": entries})
    except PermissionError:
        return jsonify({"ok": False, "error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/list_files", methods=["GET"])
def ui_list_files():
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"ok": False, "error": "path required"}), 400
    safe = _validate_path(path)
    if not safe:
        return jsonify({"ok": False, "error": "Access denied"}), 403
    try:
        entries = []
        for name in sorted(os.listdir(safe)):
            if name.startswith("."):
                continue
            full = os.path.join(safe, name)
            if os.path.isfile(full):
                entries.append({
                    "name": name,
                    "path": full,
                    "is_dir": False,
                    "size": os.path.getsize(full),
                })
        return jsonify({"ok": True, "entries": entries})
    except PermissionError:
        return jsonify({"ok": False, "error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/fetch_file", methods=["GET"])
def ui_fetch_file():
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"ok": False, "error": "path required"}), 400
    safe = _validate_path(path)
    if not safe or not os.path.isfile(safe):
        return jsonify({"ok": False, "error": "Access denied or not found"}), 403
    return send_from_directory(os.path.dirname(safe), os.path.basename(safe), as_attachment=True)


# ─────────────────────────────────────────────────────────────
# Screenshot
# POST /screenshot/capture   — take screenshot now
# GET  /screenshot/latest    — latest screenshot metadata
# GET  /screenshot/image/<f> — serve screenshot JPEG
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/screenshot/capture", methods=["POST", "OPTIONS"])
def screenshot_capture():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        from modules.screenshot_engine import capture_sync
        filename = capture_sync()
        if not filename:
            return jsonify({"ok": False, "error": "Capture failed"}), 500
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "screenshot_ready", "filename": filename, "ts": time.strftime("%H:%M")})
        except Exception:
            pass
        return jsonify({"ok": True, "filename": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/screenshot/latest", methods=["GET"])
def screenshot_latest():
    try:
        from modules.screenshot_engine import latest
        f = latest()
        if not f:
            return jsonify({"ok": False, "error": "No screenshots"}), 404
        return jsonify({"ok": True, "filename": f})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/screenshot/image/<path:filename>", methods=["GET"])
def screenshot_image(filename):
    try:
        from modules.screenshot_engine import get_dir
        return send_from_directory(str(get_dir()), filename)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 404


# ─────────────────────────────────────────────────────────────
# PC Context
# GET /pc/info?q=<query>  — answer natural language PC questions
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/pc/info", methods=["GET"])
def pc_info():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "error": "q required"}), 400
    try:
        from modules.pc_context import answer
        result = answer(q)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Clipboard
# GET  /clipboard         — get current PC clipboard
# POST /clipboard         — set PC clipboard from phone
# GET  /clipboard/history — last 10 entries
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/clipboard", methods=["GET"])
def clipboard_get():
    try:
        from modules.clipboard_sync import get
        return jsonify({"ok": True, "text": get()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/clipboard", methods=["POST"])
def clipboard_set():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"ok": False, "error": "text required"}), 400
    try:
        from modules.clipboard_sync import set_from_phone
        set_from_phone(text)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/clipboard/history", methods=["GET"])
def clipboard_history():
    try:
        from modules.clipboard_sync import history
        return jsonify({"ok": True, "entries": history()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Task Events
# GET /tasks  — current task list
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/tasks", methods=["GET"])
def get_tasks():
    try:
        from modules.task_events import all_tasks
        return jsonify({"ok": True, "tasks": all_tasks()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# POST /quick_action  — instant PC control, no AI parsing
# body: { "action": "lock_pc|screenshot|volume_up|volume_down|
#                    mute|play_pause|next_track|prev_track" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/quick_action", methods=["POST"])
def quick_action():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip()
    if not action:
        return jsonify({"ok": False, "error": "action required"}), 400
    try:
        if action == "lock_pc":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return jsonify({"ok": True, "msg": "PC locked"})

        if action == "screenshot":
            from modules.screenshot_engine import capture_sync
            from modules.ws_bridge import broadcast
            filename = capture_sync()
            if filename:
                broadcast({"type": "screenshot_ready", "filename": filename, "ts": time.strftime("%H:%M")})
                return jsonify({"ok": True, "msg": f"Screenshot: {filename}", "filename": filename})
            return jsonify({"ok": False, "error": "Capture failed"}), 500

        # Media / volume keys via pynput
        from pynput.keyboard import Key, Controller as _KC
        _kb = _KC()
        _KEY_MAP = {
            "volume_up":    Key.media_volume_up,
            "volume_down":  Key.media_volume_down,
            "mute":         Key.media_volume_mute,
            "play_pause":   Key.media_play_pause,
            "next_track":   Key.media_next,
            "prev_track":   Key.media_previous,
        }
        if action in _KEY_MAP:
            k = _KEY_MAP[action]
            _kb.press(k)
            _kb.release(k)
            return jsonify({"ok": True, "msg": action.replace("_", " ").title()})

        return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /file_preview?path=  — lightweight file metadata + thumbnail
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/file_preview", methods=["GET"])
def file_preview():
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"ok": False, "error": "path required"}), 400
    safe = _validate_path(path)
    if not safe or not os.path.isfile(safe):
        return jsonify({"ok": False, "error": "Access denied or not found"}), 403
    try:
        st = os.stat(safe)
        name = os.path.basename(safe)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        size = st.st_size
        modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))

        if size >= 1_000_000_000:
            size_str = f"{size / 1_000_000_000:.1f} GB"
        elif size >= 1_000_000:
            size_str = f"{size / 1_000_000:.1f} MB"
        elif size >= 1_000:
            size_str = f"{size / 1_000:.1f} KB"
        else:
            size_str = f"{size} B"

        IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
        is_image = ext in IMAGE_EXTS
        thumbnail = None

        if is_image and size < 50_000_000:
            try:
                from PIL import Image
                import io, base64 as _b64
                with Image.open(safe) as img:
                    img.thumbnail((200, 200), Image.LANCZOS)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    thumbnail = _b64.b64encode(buf.getvalue()).decode()
            except Exception:
                pass

        return jsonify({
            "ok": True,
            "name": name,
            "ext": ext,
            "size": size,
            "size_str": size_str,
            "modified": modified,
            "is_image": is_image,
            "thumbnail": thumbnail,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /downloads/active  — currently tracked downloads
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/downloads/active", methods=["GET"])
def downloads_active():
    try:
        from modules.download_monitor import active
        return jsonify({"ok": True, "downloads": active()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# POST /confirm_command  — execute a safe-mode pending command
# body: { "token": "abc12345" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/confirm_command", methods=["POST"])
def confirm_command():
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    pending = _pending_confirmations.pop(token, None)
    if not pending:
        return jsonify({"ok": False, "error": "Invalid or expired token"}), 400
    if time.time() > pending["expires"]:
        return jsonify({"ok": False, "error": "Token expired"}), 400

    text = pending["text"]
    _log_message("YOU", f"[CONFIRMED] {text}")

    try:
        captured = []

        def _capture_speak(msg, **kwargs):
            if msg and msg.strip():
                import re as _re
                clean = _re.sub(r'<[^>]+>', '', msg).strip()
                clean = _re.sub(r'^\[TONE:[^\]]+\]', '', clean).strip()
                if clean:
                    captured.append(clean)

        chain_obj = getattr(_chain_fn, '__self__', None)
        original_speak = None
        if chain_obj and hasattr(chain_obj, 'speak'):
            original_speak = chain_obj.speak
            chain_obj.speak = _capture_speak

        if _chain_fn:
            _chain_fn(text)

        if chain_obj and original_speak is not None:
            chain_obj.speak = original_speak

        response_text = " ".join(captured).strip() or "Done."
        _log_message("iZACH", response_text)

        from modules.ws_bridge import broadcast
        broadcast({"type": "chat", "sender": "iZACH", "text": response_text, "ts": time.strftime("%H:%M")})

        return jsonify({"ok": True, "response": response_text, "ts": time.strftime("%H:%M")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /connect/qr  — QR code encoding backend URL + WS host for Android app
# Optional ?mode=tailscale  → encodes Tailscale IP instead of LAN IP
# ─────────────────────────────────────────────────────────────

def _get_tailscale_ip():
    """Return Tailscale IP (100.x.x.x) or None if not installed/connected."""
    import subprocess as _sp
    try:
        flags = _sp.CREATE_NO_WINDOW if hasattr(_sp, 'CREATE_NO_WINDOW') else 0
        r = _sp.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=3,
            creationflags=flags
        )
        ip = r.stdout.strip().split('\n')[0]
        if ip and ip.startswith("100."):
            return ip
    except Exception:
        pass
    return None


@ui_bp.route("/connect/qr", methods=["GET"])
def connect_qr():
    import socket as _socket, json as _json2, io as _io, base64 as _b64
    import qrcode as _qr

    mode = request.args.get("mode", "lan")

    try:
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        _s.connect(("8.8.8.8", 80))
        lan_ip = _s.getsockname()[0]
        _s.close()
    except Exception:
        lan_ip = "127.0.0.1"

    tailscale_ip = _get_tailscale_ip()
    ip = tailscale_ip if (mode == "tailscale" and tailscale_ip) else lan_ip

    payload = _json2.dumps({"backend_url": f"http://{ip}:5050", "ws_host": ip})
    _qr_img = _qr.QRCode(version=1, box_size=8, border=3)
    _qr_img.add_data(payload)
    _qr_img.make(fit=True)
    img = _qr_img.make_image(fill_color="black", back_color="white")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    b64 = _b64.b64encode(buf.getvalue()).decode()
    return jsonify({
        "ok":           True,
        "qr_base64":    b64,
        "backend_url":  f"http://{ip}:5050",
        "ws_host":      ip,
        "tailscale_ip": tailscale_ip,
        "mode":         mode,
    })


# ─────────────────────────────────────────────────────────────
# GET /notifications/history  — recent push notifications
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/notifications/history", methods=["GET"])
def notifications_history():
    try:
        from modules.notification_system import history
        return jsonify({"ok": True, "notifications": history()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Calendar API ──────────────────────────────────────────────

@ui_bp.route("/calendar/events", methods=["GET"])
def calendar_events():
    try:
        from modules.calendar_agent import get_3day_events
        events = get_3day_events()
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/calendar/events/<event_id>", methods=["PUT"])
def calendar_update_event(event_id):
    data = request.json or {}
    try:
        from modules.calendar_agent import update_event
        ok = update_event(
            calendar_event_id=event_id,
            title=data.get("title"),
            date_str=data.get("date"),
            time_str=data.get("time"),
            link=data.get("link"),
        )
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/calendar/events/<event_id>", methods=["DELETE"])
def calendar_delete_event(event_id):
    try:
        from modules.calendar_agent import cancel_event
        ok = cancel_event(event_id)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Face Auth ─────────────────────────────────────────────────

@ui_bp.route("/face/status", methods=["GET"])
def face_status():
    try:
        from modules.face_auth import is_enrolled
        return jsonify({"enrolled": is_enrolled()})
    except Exception as e:
        return jsonify({"enrolled": False, "error": str(e)}), 500


@ui_bp.route("/face/enroll", methods=["POST"])
def face_enroll():
    try:
        from modules import face_auth
        if not face_auth._speak_func:
            return jsonify({"ok": False, "error": "face_auth not initialized"}), 500
        face_auth.enroll_owner()
        return jsonify({"ok": True, "message": "Enrollment started. Look at the camera."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/face/delete", methods=["DELETE"])
def face_delete():
    try:
        from modules.face_auth import delete_face_data
        ok = delete_face_data()
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── SHELL EXECUTOR ────────────────────────────────────────────────────────────

@ui_bp.route("/shell/run", methods=["POST"])
def shell_run():
    """Run a PowerShell command directly (UI-initiated, already confirmed by user)."""
    data = request.get_json(force=True, silent=True) or {}
    cmd  = (data.get("command") or "").strip()
    if not cmd:
        return jsonify({"ok": False, "error": "No command provided"}), 400
    try:
        from modules import shell_executor
        ok, msg = shell_executor.run_direct(cmd)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/shell/confirm", methods=["POST"])
def shell_confirm():
    """Confirm a pending shell command (from voice confirmation flow)."""
    data    = request.get_json(force=True, silent=True) or {}
    exec_id = (data.get("id") or "").strip()
    if not exec_id:
        return jsonify({"ok": False, "error": "No id provided"}), 400
    try:
        from modules import shell_executor
        ok, msg = shell_executor.run_confirmed(exec_id)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/shell/cancel", methods=["POST"])
def shell_cancel():
    data    = request.get_json(force=True, silent=True) or {}
    exec_id = (data.get("id") or "").strip()
    try:
        from modules import shell_executor
        shell_executor.cancel_pending(exec_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500