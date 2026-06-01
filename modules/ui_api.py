"""
modules/ui_api.py
REST API for the iZACH React/Electron UI.
Registered onto the same Flask app as whatsapp_handler (port 5050).
"""

import os
import re
import time
import threading
import uuid as _uuid
import psutil
from flask import Blueprint, request, jsonify, send_from_directory, Response, stream_with_context
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


def _friendly_error(exc: Exception) -> str:
    """
    Convert raw provider errors (Groq/Gemini/OpenRouter) into short, human
    messages so the chat UI doesn't dump 2 KB of JSON at the user.
    """
    s = str(exc)
    s_low = s.lower()
    # Gemini quota
    if "resource_exhausted" in s_low or ("429" in s and ("gemini" in s_low or "generativelanguage" in s_low)):
        return "All Gemini keys are exhausted. Add a new key in Settings → Keys & IDs."
    # Groq quota
    if "429" in s and "groq" in s_low:
        return "Groq key is exhausted. Add a new key in Settings → Keys & IDs."
    if "429" in s and ("rate_limit_exceeded" in s_low or "tokens per minute" in s_low or "requests per minute" in s_low):
        return "API rate-limit hit. Wait a minute or add a fresh Groq/Gemini key."
    if "401" in s and ("groq" in s_low or "gemini" in s_low):
        return "API key invalid or expired. Update it in Settings → Keys & IDs."
    if "openrouter" in s_low and "401" in s:
        return "OpenRouter key invalid. Update it in Settings → Keys & IDs."
    # Network failures
    if any(t in s_low for t in ("connection refused", "max retries", "timeout", "timed out")):
        return "Cannot reach AI provider — check your internet."
    if "ssl" in s_low and "error" in s_low:
        return "SSL error reaching AI provider. Check system clock / network."
    # Default — short type + first sentence only
    msg = s.split("\n")[0].split(". ")[0]
    return f"{type(exc).__name__}: {msg[:160]}"


# ── injected at startup ───────────────────────────────────────
_chain_fn    = None
_speak_fn    = None
_get_resp    = None
_spotify_api = None     # SpotifyController instance

# ── WhatsApp DND dedicated Groq client ────────────────────────
_wa_groq_client = None   # Groq(api_key=GROQ_WA_KEY) — built lazily

def _get_wa_groq_client():
    """Return dedicated WA Groq client if GROQ_WA_KEY is set, else None."""
    global _wa_groq_client
    if _wa_groq_client:
        return _wa_groq_client
    key = os.getenv("GROQ_WA_KEY", "").strip()
    if not key:
        # Try reading from api_keys.json directly (hot-saved keys)
        try:
            with open("api_keys.json") as _f:
                import json as _j
                key = _j.load(_f).get("GROQ_WA_KEY", "").strip()
        except Exception:
            pass
    if key:
        try:
            from groq import Groq as _Groq
            _wa_groq_client = _Groq(api_key=key)
            print("[UI API] WhatsApp Groq client ready (dedicated key)")
        except Exception as e:
            print(f"[UI API] WA Groq client init failed: {e}")
    return _wa_groq_client


def _wa_ai_call(prompt: str) -> str:
    """Call AI using WA-dedicated key if available, else fall back to main _get_resp."""
    client = _get_wa_groq_client()
    if client:
        try:
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            # Key exhausted or error — fall through to main key
            print(f"[UI API] WA Groq key failed: {e} — falling back to main key")
    # Fall back to main response generator
    if _get_resp:
        return _get_resp(prompt) or ""
    return ""

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

    CORS(app, resources={r"/*": {"origins": "*"}})

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
    source = str(data.get("source", "")).lower().strip()

    if not text:
        return jsonify({"ok": False, "error": "Empty command"}), 400

    _log_message("YOU", text)

    # DND: if active, tag text so command_chain injects concise AI prefix
    # We pass the flag via a thread-local or just let command_chain check dnd_mode directly.
    # Also allow DND toggle commands to pass through normally.
    _dnd_active = False
    try:
        from modules import dnd_mode as _dnd_ui
        _dnd_active = _dnd_ui.is_active()
    except Exception:
        pass

    # If command came from the Android app, auto-mark phone connected and
    # push to the phone command history ring for the PHONE widget.
    if source == "phone":
        try:
            _record_phone_command(text, device_name=str(data.get("device_name", "")))
        except Exception as _pe:
            print(f"[UI API] phone command record failed: {_pe}")
    # UI already adds the YOU message locally — no WS echo needed

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
    # Use word-boundary regex for short ambiguous keywords (ram, cpu) to avoid
    # matching them as substrings inside other words ("ram" in "instagram"!).
    import re as _re_pc
    _pc_word_kw = ("ram", "cpu", "battery")
    _pc_phrase_kw = ("memory usage", "disk space", "storage left", "internet status",
                     "wifi status", "what's running", "running apps", "where is my",
                     "find my", "recent files", "how much storage")
    _pc_match = (
        any(_re_pc.search(rf"\b{k}\b", _lc) for k in _pc_word_kw) or
        any(k in _lc for k in _pc_phrase_kw)
    )
    if _pc_match:
        try:
            from modules.pc_context import answer as _pc_answer
            result = _pc_answer(text)
            if isinstance(result, dict):
                reply = result.get("text") or "Could not determine answer."
            else:
                reply = str(result) if result else "Could not determine answer."
        except Exception as _e:
            reply = f"PC context error: {_e}"
        _log_message("iZACH", reply)
        return jsonify({"ok": True, "response": reply, "ts": time.strftime("%H:%M")})

    if any(k in _lc for k in ("send file", "transfer file", "send to phone", "send me file",
                                "send report", "send pdf", "send document")):
        reply = "Which file? Type / in chat to browse your PC files."
        _log_message("iZACH", reply)
        return jsonify({"ok": True, "response": reply, "action": "open_file_picker",
                        "ts": time.strftime("%H:%M")})

    if any(k in _lc for k in ("shared files", "files on phone", "what files", "list files", "send to phone")):
        try:
            fnames = [f for f in sorted(os.listdir(SHARED_DIR)) if os.path.isfile(os.path.join(SHARED_DIR, f))]
            reply = f"Shared folder: {len(fnames)} file(s) — {', '.join(fnames[-5:])}" if fnames else "Shared folder is empty. Upload files from your phone."
        except Exception:
            reply = "Cannot read shared folder."
        _log_message("iZACH", reply)
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

    # ── Skill shortcut — #skill-id prefix bypasses command chain ──────────────
    # Must happen BEFORE _chain_fn() so the orchestrator never sees it.
    if text.startswith('#'):
        try:
            from modules.skill_engine import detect_skills
            skill_ids, _ = detect_skills(text)
            if skill_ids:
                # Route directly to get_ai_response which has skill injection
                if _get_resp:
                    resp = _get_resp(text)
                    if resp:
                        _log_message("iZACH", resp)
                        if source == "phone":
                            try:
                                from modules.ws_bridge import _broadcast_to_non_android
                                _broadcast_to_non_android({"type": "chat", "sender": "iZACH", "text": resp, "ts": time.strftime("%H:%M")})
                            except Exception:
                                pass
                        return jsonify({"ok": True, "response": resp, "ts": time.strftime("%H:%M")})
        except Exception as _se:
            print(f"[UI API] Skill intercept error: {_se}")

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

        # For phone commands: broadcast both the user command and iZACH response
        # to cortex-ui's chat feed so PC chatbox reflects the phone conversation.
        if source == "phone":
            try:
                from modules.ws_bridge import _broadcast_to_non_android
                _broadcast_to_non_android({
                    "type": "chat",
                    "sender": "iZACH",
                    "text": response_text,
                    "ts": time.strftime("%H:%M"),
                })
            except Exception:
                pass

        return jsonify({
            "ok":       True,
            "response": response_text,
            "ts":       time.strftime("%H:%M"),
        })

    except Exception as e:
        err = _friendly_error(e)
        print(f"[UI API] /command error: {type(e).__name__}: {str(e)[:200]}")
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

        # current_playback() can block indefinitely on slow network.
        # Run with 5 s timeout to prevent hanging a Flask worker thread.
        import concurrent.futures as _cf_sp
        pb = None
        if _spotify_api.sp:
            try:
                with _cf_sp.ThreadPoolExecutor(max_workers=1) as _spex:
                    pb = _spex.submit(_spotify_api.sp.current_playback).result(timeout=5)
            except _cf_sp.TimeoutError:
                return jsonify({"ok": False, "error": "Spotify timeout"}), 504
            except Exception as _spe:
                return jsonify({"ok": False, "error": str(_spe)}), 500

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
# SMART MEMORY — /smart-memory
#   GET    /smart-memory            list (category=, search=, include_disabled=)
#   POST   /smart-memory            add  {category, content, [raw_input]}
#   PATCH  /smart-memory/<id>       edit {content?, enabled?}
#   DELETE /smart-memory/<id>       delete
#   POST   /smart-memory/import     import text from ChatGPT/Claude
#   GET    /smart-memory/export     export all as text
#   POST   /smart-memory/obsidian-sync  sync all to Obsidian vault
#   GET    /smart-memory/jobs       list APScheduler jobs
# ─────────────────────────────────────────────────────────────

# ── API Usage routes ───────────────────────────────────────────────────────
@ui_bp.route("/api-usage", methods=["GET"])
def api_usage():
    try:
        from modules.api_usage_tracker import get_stats
        return jsonify({"ok": True, "stats": get_stats()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/api-usage/reset/<key_name>", methods=["POST"])
def api_usage_reset(key_name):
    try:
        from modules.api_usage_tracker import reset_key
        reset_key(key_name)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Skills routes ──────────────────────────────────────────────────────────
#   GET    /skills                  list all installed skills
#   POST   /skills/import           import .md from path or raw content
#   DELETE /skills/<id>             delete skill
#   PATCH  /skills/<id>/model       update model preference
#   GET    /skills/projects         list generated projects
#   POST   /skills/projects/open    open project folder in Explorer
# ──────────────────────────────────────────────────────────────────────────

@ui_bp.route("/skills", methods=["GET"])
def skills_list():
    try:
        from modules.skill_engine import list_skills
        return jsonify({"ok": True, "skills": list_skills()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/skills/import", methods=["POST"])
def skills_import():
    try:
        from modules.skill_engine import import_skill, import_skill_from_text
        data = request.get_json(silent=True) or {}
        if "path" in data:
            meta = import_skill(data["path"])
            if meta and "error" not in meta:
                return jsonify({"ok": True, "skill": meta})
            return jsonify({"ok": False, "error": meta.get("error", "Import failed")}), 400
        elif "name" in data and "content" in data:
            ok = import_skill_from_text(data["name"], data["content"])
            return jsonify({"ok": ok})
        return jsonify({"ok": False, "error": "Provide 'path' or 'name'+'content'"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/skills/<skill_id>", methods=["DELETE"])
def skills_delete(skill_id):
    try:
        from modules.skill_engine import delete_skill
        ok = delete_skill(skill_id)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/skills/<skill_id>/model", methods=["PATCH"])
def skills_update_model(skill_id):
    try:
        from modules.skill_engine import update_skill_model
        data  = request.get_json(silent=True) or {}
        model = data.get("model", "auto")
        ok    = update_skill_model(skill_id, model)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/skills/projects", methods=["GET"])
def skills_projects():
    try:
        from modules.skill_engine import list_projects
        return jsonify({"ok": True, "projects": list_projects()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/skills/projects/open", methods=["POST"])
def skills_project_open():
    try:
        from modules.skill_engine import open_project_folder
        data = request.get_json(silent=True) or {}
        ok   = open_project_folder(data.get("name", ""))
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@ui_bp.route("/smart-memory", methods=["GET"])
def smart_memory_list():
    try:
        from modules.smart_memory import list_smart_memories
        cat     = request.args.get("category", "")
        search  = request.args.get("search", "")
        inc_dis = request.args.get("include_disabled", "false").lower() == "true"
        items   = list_smart_memories(
            category=cat or None,
            include_disabled=inc_dis,
            search=search,
        )
        return jsonify({"ok": True, "data": items, "total": len(items)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory", methods=["POST"])
def smart_memory_add():
    try:
        from modules.smart_memory import add_smart_memory, _classify_memory, _parse_schedule_from_text
        data     = request.get_json(silent=True) or {}
        content  = (data.get("content") or "").strip()
        category = (data.get("category") or "").strip()
        raw_in   = (data.get("raw_input") or content).strip()

        if not content:
            return jsonify({"ok": False, "error": "content required"}), 400
        if not category:
            category = _classify_memory(content)

        auto_sched = None
        if category == "automation":
            auto_sched = _parse_schedule_from_text(content)

        entry = add_smart_memory(category, content, raw_input=raw_in, auto_schedule=auto_sched)
        return jsonify({"ok": True, "data": entry})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/import", methods=["POST"])
def smart_memory_import():
    try:
        from modules.smart_memory import import_from_text
        data    = request.get_json(silent=True) or {}
        raw     = (data.get("text") or "").strip()
        if not raw:
            return jsonify({"ok": False, "error": "text required"}), 400
        imported = import_from_text(raw)
        return jsonify({"ok": True, "imported": len(imported), "data": imported})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/export", methods=["GET"])
def smart_memory_export():
    try:
        from modules.smart_memory import export_to_text
        inc_dis = request.args.get("include_disabled", "false").lower() == "true"
        text    = export_to_text(include_disabled=inc_dis)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/obsidian-sync", methods=["POST"])
def smart_memory_obsidian_sync():
    try:
        from modules.smart_memory import sync_all_to_obsidian
        count = sync_all_to_obsidian()
        return jsonify({"ok": True, "synced": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/jobs", methods=["GET"])
def smart_memory_jobs():
    try:
        from modules.automation_scheduler import list_jobs
        return jsonify({"ok": True, "jobs": list_jobs()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/<string:mid>", methods=["PATCH"])
def smart_memory_update(mid):
    try:
        from modules.smart_memory import update_smart_memory
        data    = request.get_json(silent=True) or {}
        content = data.get("content")
        enabled = data.get("enabled")
        if content is not None:
            content = content.strip()
        ok = update_smart_memory(mid, content=content, enabled=enabled)
        return jsonify({"ok": ok, "error": None if ok else "Not found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/smart-memory/<string:mid>", methods=["DELETE"])
def smart_memory_delete(mid):
    try:
        from modules.smart_memory import delete_smart_memory
        ok = delete_smart_memory(mid)
        return jsonify({"ok": ok, "error": None if ok else "Not found"})
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
            "theme", "language", "ui", "screensaver_timeout",
            "ask_ui_on_boot", "command_only",
            "hotkey_bar", "hotkey_mic",
            "morning_briefing_time", "weather_city",
            "briefing_enabled", "briefing_greeting", "briefing_news",
            "briefing_gold_rate", "briefing_silver_rate", "briefing_weather",
            "briefing_battery_status", "briefing_battery_health",
            "briefing_ram", "briefing_events", "briefing_whatsapp",
            "briefing_calendar", "briefing_reminders", "briefing_tasks",
            "briefing_stocks", "briefing_sports", "briefing_commute", "briefing_system",
            # ── Notification settings ──
            "meeting_join_alert_enabled", "meeting_join_alert_mins",
            "meeting_dnd_toast_enabled",
            "installer_download_path",
            # ── New settings (Feature 7 / 10 / 11 / 12) ──
            "toast_enabled", "toast_bg_only",
            "font_size",
            "battery_auto_switch", "lid_close_trigger",
            "push_to_talk",
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
# GET  /api-keys   — return masked status of mutable API keys
# POST /api-keys   — write new values to .env, hot-reload module vars
# ─────────────────────────────────────────────────────────────

_MUTABLE_KEYS = [
    # Chat / commands
    "GROQ_API_KEY",
    "GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3",
    # Vision / camera / screen analysis (separate quota pool)
    "GROQ_VISION_KEY",
    "GEMINI_VISION_KEY_1", "GEMINI_VISION_KEY_2", "GEMINI_VISION_KEY_3",
    # WhatsApp DND automation (separate quota pool — N8N AI replies)
    "GROQ_WA_KEY",
    # Other services
    "SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI",
    "OPENROUTER_API_KEY",
    "EDAMAM_APP_ID", "EDAMAM_APP_KEY",
]
_ENV_FILE = ".env"


def _read_env() -> dict:
    """Parse .env into a dict (key=value, strips quotes)."""
    env = {}
    try:
        with open(_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def _write_env(updates: dict):
    """Write updated keys back to .env, preserving order and comments."""
    try:
        with open(_ENV_FILE) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k in updates:
            new_lines.append(f"{k}={updates[k]}\n")
            written.add(k)
        else:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in written:
            new_lines.append(f"{k}={v}\n")

    with open(_ENV_FILE, "w") as f:
        f.writelines(new_lines)


@ui_bp.route("/api-keys", methods=["GET"])
def api_keys_get():
    env = _read_env()
    result = {}
    for k in _MUTABLE_KEYS:
        v = env.get(k, "")
        if v and len(v) > 6:
            result[k] = v[:4] + "•" * (len(v) - 4)
        elif v:
            result[k] = "•" * len(v)
        else:
            result[k] = ""
    return jsonify({"ok": True, "keys": result})


@ui_bp.route("/api-keys", methods=["POST"])
def api_keys_post():
    try:
        incoming = request.get_json(silent=True) or {}
        updates = {k: v for k, v in incoming.items() if k in _MUTABLE_KEYS and isinstance(v, str)}
        if not updates:
            return jsonify({"ok": False, "error": "No valid keys provided"}), 400

        _write_env(updates)

        # Hot-reload module-level vars where possible
        try:
            import modules.camera_vision as _cv
            import os as _os_hr
            for k, v in updates.items():
                # Vision-specific keys take precedence; chat keys are only
                # used by vision as a fallback when vision keys are unset.
                if k == "GROQ_VISION_KEY":
                    _cv.GROQ_KEY = v or _os_hr.getenv("GROQ_API_KEY", "")
                elif k == "GROQ_API_KEY":
                    # Only update vision Groq key if no dedicated vision key set
                    if not _os_hr.getenv("GROQ_VISION_KEY", "").strip():
                        _cv.GROQ_KEY = v
                elif k == "GEMINI_VISION_KEY_1":
                    _cv.GEMINI_KEYS[0] = v or _os_hr.getenv("GEMINI_KEY_1", "")
                elif k == "GEMINI_VISION_KEY_2":
                    _cv.GEMINI_KEYS[1] = v or _os_hr.getenv("GEMINI_KEY_2", "")
                elif k == "GEMINI_VISION_KEY_3":
                    _cv.GEMINI_KEYS[2] = v or _os_hr.getenv("GEMINI_KEY_3", "")
                elif k == "GEMINI_KEY_1" and not _os_hr.getenv("GEMINI_VISION_KEY_1", "").strip():
                    _cv.GEMINI_KEYS[0] = v
                elif k == "GEMINI_KEY_2" and not _os_hr.getenv("GEMINI_VISION_KEY_2", "").strip():
                    _cv.GEMINI_KEYS[1] = v
                elif k == "GEMINI_KEY_3" and not _os_hr.getenv("GEMINI_VISION_KEY_3", "").strip():
                    _cv.GEMINI_KEYS[2] = v
                elif k == "OPENROUTER_API_KEY":
                    _cv.OPENROUTER_KEY = v
                elif k == "EDAMAM_APP_ID":
                    _cv.EDAMAM_APP_ID = v
                elif k == "EDAMAM_APP_KEY":
                    _cv.EDAMAM_APP_KEY = v
        except Exception:
            pass
        # Hot-reload WA Groq client when GROQ_WA_KEY is updated
        if "GROQ_WA_KEY" in updates:
            global _wa_groq_client
            _wa_groq_client = None   # force rebuild on next _get_wa_groq_client() call
            os.environ["GROQ_WA_KEY"] = updates["GROQ_WA_KEY"]

        # Groq + Gemini keys cached inside live AIProvider / OrchestratorAgent
        # instances built at startup — must rebuild their underlying HTTP clients.
        if any(k in updates for k in ("GROQ_API_KEY", "GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3")):
            try:
                import os as _os
                from dotenv import load_dotenv as _ld
                _ld(override=True)  # refresh process env from disk

                # Collect the new key values (prefer just-saved updates, fall back to env)
                _new_groq = updates.get("GROQ_API_KEY") or _os.getenv("GROQ_API_KEY", "")
                _new_gem  = [
                    updates.get("GEMINI_KEY_1") or _os.getenv("GEMINI_KEY_1", ""),
                    updates.get("GEMINI_KEY_2") or _os.getenv("GEMINI_KEY_2", ""),
                    updates.get("GEMINI_KEY_3") or _os.getenv("GEMINI_KEY_3", ""),
                ]

                import sys as _sys
                _main = _sys.modules.get("__main__")

                # Update module-level constants in main.py
                if _main is not None:
                    if "GROQ_API_KEY" in updates:
                        setattr(_main, "GROQ_KEY", _new_groq)
                    if any(k in updates for k in ("GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3")):
                        setattr(_main, "GEMINI_KEYS", _new_gem)

                # Hot-swap inside the live AIProvider singleton
                _ai_mgr = getattr(_main, "ai_manager", None) if _main is not None else None
                if _ai_mgr is not None and hasattr(_ai_mgr, "reload_keys"):
                    _ai_mgr.reload_keys(
                        groq_key=_new_groq if "GROQ_API_KEY" in updates else None,
                        gemini_keys=_new_gem if any(k in updates for k in ("GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3")) else None,
                    )

                # Hot-swap inside the OrchestratorAgent singleton
                if "GROQ_API_KEY" in updates:
                    _orch = getattr(_main, "agent_orch", None) if _main is not None else None
                    if _orch is not None and hasattr(_orch, "reload_key"):
                        _orch.reload_key(_new_groq)

                # Other modules cache Groq clients at module level
                # (event_extractor, realtime_data, research_agent). Rebuild them.
                if "GROQ_API_KEY" in updates and _new_groq:
                    try:
                        from groq import Groq as _Groq
                        for _mod_name in ("modules.event_extractor",
                                          "modules.realtime_data",
                                          "modules.research_agent"):
                            _m = _sys.modules.get(_mod_name)
                            if _m is not None and hasattr(_m, "_groq_client"):
                                try:
                                    _m._groq_client = _Groq(api_key=_new_groq)
                                    print(f"[api-keys] Rebuilt Groq client in {_mod_name}.")
                                except Exception as _me:
                                    print(f"[api-keys] {_mod_name} client rebuild failed: {_me}")
                    except Exception:
                        pass
            except Exception as _hot_err:
                print(f"[api-keys] Hot-reload partial failure: {_hot_err}")
                import traceback as _tb
                _tb.print_exc()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# DND — Do Not Disturb endpoints
# GET  /dnd              → { active, reason, queue_count }
# POST /dnd              → { action: "on"|"off", reason?: str }
# GET  /dnd/queue        → { ok, queue: [...] }
# POST /dnd/handle       → { index: N }
# POST /dnd/busy         → { index: N }
# POST /dnd/clear        → clears queue
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/dnd", methods=["GET"])
def dnd_status():
    try:
        from modules import dnd_mode as _dnd
        return jsonify({"ok": True, **_dnd.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd", methods=["POST"])
def dnd_toggle():
    try:
        from modules import dnd_mode as _dnd
        data   = request.get_json(silent=True) or {}
        action = data.get("action", "").lower()
        reason = data.get("reason", "manual")
        if action == "on":
            _dnd.turn_on(reason)
        elif action == "off":
            _dnd.turn_off()
        else:
            return jsonify({"ok": False, "error": "action must be 'on' or 'off'"}), 400
        return jsonify({"ok": True, **_dnd.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/queue", methods=["GET"])
def dnd_queue():
    try:
        from modules import dnd_mode as _dnd
        return jsonify({"ok": True, "queue": _dnd.get_queue()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/handle", methods=["POST"])
def dnd_handle():
    try:
        from modules import dnd_mode as _dnd
        idx = int((request.get_json(silent=True) or {}).get("index", -1))
        ok  = _dnd.mark_handle(idx)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/busy", methods=["POST"])
def dnd_busy():
    try:
        from modules import dnd_mode as _dnd
        idx = int((request.get_json(silent=True) or {}).get("index", -1))
        ok  = _dnd.mark_busy(idx)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/clear", methods=["POST"])
def dnd_clear():
    try:
        from modules import dnd_mode as _dnd
        _dnd.clear_queue()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


_DND_ACTION_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>iZACH</title>
<style>body{{background:#050d1a;color:#00e5ff;font-family:monospace;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;font-size:14px;}}</style>
</head><body><p>{msg}</p>
<script>setTimeout(()=>window.close(),1200);</script></body></html>"""


@ui_bp.route("/dnd/config", methods=["GET"])
def dnd_config_get():
    """Return DND config (priority contacts list)."""
    try:
        with open("api_keys.json") as f:
            import json as _j
            cfg = _j.load(f)
        return jsonify({"ok": True, "priority_contacts": cfg.get("dnd_priority_contacts", [])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/config", methods=["POST"])
def dnd_config_set():
    """Update DND config (priority contacts list)."""
    try:
        data = request.get_json(silent=True) or {}
        contacts = data.get("priority_contacts", [])
        import json as _j
        try:
            with open("api_keys.json") as f:
                cfg = _j.load(f)
        except Exception:
            cfg = {}
        cfg["dnd_priority_contacts"] = contacts
        with open("api_keys.json", "w") as f:
            _j.dump(cfg, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/action/handle/<int:item_id>", methods=["GET"])
def dnd_action_handle(item_id):
    """Browser-openable endpoint triggered by Windows toast 'Handle' button."""
    try:
        from modules import dnd_mode as _dnd
        ok = _dnd.mark_handle(item_id)
        msg = "✅ Marked to handle — N8N agent will follow up." if ok else "⚠ Alert not found."
    except Exception as e:
        msg = f"Error: {e}"
    from flask import make_response
    r = make_response(_DND_ACTION_HTML.format(msg=msg))
    r.headers["Content-Type"] = "text/html"
    return r


@ui_bp.route("/dnd/action/busy/<int:item_id>", methods=["GET"])
def dnd_action_busy(item_id):
    """Browser-openable endpoint triggered by Windows toast 'I'm Busy' button."""
    try:
        from modules import dnd_mode as _dnd
        ok = _dnd.mark_busy(item_id)
        msg = "🔕 Auto-replied as busy." if ok else "⚠ Alert not found."
    except Exception as e:
        msg = f"Error: {e}"
    from flask import make_response
    r = make_response(_DND_ACTION_HTML.format(msg=msg))
    r.headers["Content-Type"] = "text/html"
    return r


# ─────────────────────────────────────────────────────────────
# BUSY MODE ENDPOINTS  (Phase 2)
# GET  /busy              → status
# POST /busy              → { action: "on"|"off", reason: "gym", duration_min: 90 }
# GET  /busy/log          → list of recent busy sessions
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/busy", methods=["GET"])
def busy_status():
    try:
        from modules import busy_mode as _busy
        return jsonify({"ok": True, **_busy.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/busy", methods=["POST"])
def busy_toggle():
    try:
        from modules import busy_mode as _busy
        data     = request.get_json(silent=True) or {}
        action   = data.get("action", "").lower()
        reason   = data.get("reason", "manual")
        duration = data.get("duration_min")

        if action == "on":
            # Smart overlap: if DND active, just note busy reason but don't conflict
            _busy.turn_on(reason=reason, duration_min=duration)
        elif action == "off":
            _busy.turn_off()
        else:
            return jsonify({"ok": False, "error": "action must be 'on' or 'off'"}), 400

        return jsonify({"ok": True, **_busy.get_status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/busy/log", methods=["GET"])
def busy_log():
    try:
        from modules import busy_mode as _busy
        return jsonify({"ok": True, "log": _busy.get_log()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# WA CALL LOG ENDPOINTS (WhatsApp calls, kept separate)
# GET  /calls             → WA call log entries
# POST /calls/callback    → { index: N, time: "4:30 PM" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/calls", methods=["GET"])
def call_log():
    try:
        from modules import dnd_mode as _dnd
        return jsonify({"ok": True, "calls": _dnd.get_call_log()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/calls/callback", methods=["POST"])
def call_schedule_callback():
    """Schedule a Google Calendar callback event for a WA missed call."""
    try:
        from modules import dnd_mode as _dnd
        data  = request.get_json(silent=True) or {}
        calls = _dnd.get_call_log()
        idx   = int(data.get("index", -1))
        t_str = data.get("time", "").strip()

        if idx < 0 or idx >= len(calls):
            return jsonify({"ok": False, "error": "Invalid call index"}), 400

        call_id = calls[idx].get("id")
        raw = [c for c in _dnd.get_call_log() if c.get("id") == call_id]
        if not raw:
            return jsonify({"ok": False, "error": "Call not found"}), 404

        entry = raw[0]
        ev_id = _dnd.schedule_call_callback(
            entry.get("number", ""),
            entry.get("caller", "Unknown"),
            t_str or None,
        )
        return jsonify({"ok": bool(ev_id), "event_id": ev_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# N8N-FACING ENDPOINTS
# POST /ai/respond     — N8N → iZACH AI generates reply (DND agent persona)
# POST /notes/save     — N8N → append transcript line to Obsidian call log
# POST /whatsapp/send  — N8N → send WA message via bridge
# ─────────────────────────────────────────────────────────────

_N8N_TOKEN = os.getenv("N8N_SHARED_TOKEN", "izach-n8n-2024")


def _check_n8n_token() -> bool:
    auth = request.headers.get("X-N8N-Token", "")
    return auth == _N8N_TOKEN


@ui_bp.route("/ai/respond", methods=["POST"])
def n8n_ai_respond():
    """
    N8N calls this to generate a DND auto-reply.
    Body: { "from": "Arjun", "number": "91XXXXXXXXXX",
            "message": "bhai kab milega", "lang_hint": "hinglish" }
    Returns: { "ok": true, "reply": "...", "lang": "hinglish" }
    """
    if not _check_n8n_token():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data    = request.get_json(silent=True) or {}
    sender  = data.get("from", "Someone")
    message = data.get("message", "").strip()
    lang    = data.get("lang_hint", "hinglish").lower()

    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400

    if not _get_resp and not _get_wa_groq_client():
        return jsonify({"ok": False, "error": "AI not ready"}), 503

    owner = os.getenv("OWNER_NAME", "Vansh")

    # DND persona prompt — Hinglish-aware
    lang_instruction = (
        "Reply in Hinglish (mix of Hindi and English, Roman script). Match the sender's language style."
        if "hindi" in lang or "hinglish" in lang
        else "Reply in English."
    )

    # Try to get meeting end time from calendar for context-aware reply
    meeting_context = ""
    try:
        from modules.calendar_engine import get_service as _gcal
        import datetime as _dt
        _svc  = _gcal()
        _now  = _dt.datetime.utcnow().isoformat() + "Z"
        _evts = _svc.events().list(
            calendarId="primary", timeMin=_now,
            maxResults=3, singleEvents=True, orderBy="startTime"
        ).execute().get("items", [])
        import dateutil.parser as _dp
        _now_ts = time.time()
        for _ev in _evts:
            _end_str = _ev.get("end", {}).get("dateTime", "")
            if _end_str:
                _end_ts = _dp.parse(_end_str).timestamp()
                if _end_ts > _now_ts:
                    _end_local = _dt.datetime.fromtimestamp(_end_ts).strftime("%I:%M %p")
                    meeting_context = f"{owner}'s current commitment ends at approximately {_end_local}."
                    break
    except Exception:
        pass

    # Also check busy mode for richer context
    busy_context = ""
    try:
        from modules import busy_mode as _busy_ai
        if _busy_ai.is_active():
            busy_context = _busy_ai.get_persona_context()
    except Exception:
        pass

    effective_context = meeting_context or busy_context

    persona_prompt = f"""You are iZACH, the AI assistant of {owner}.
{owner} is currently busy (Do Not Disturb mode — in a meeting or unavailable).
You are handling messages on {owner}'s behalf like JARVIS did for Tony Stark.
{f"Context: {effective_context}" if effective_context else ""}

Your goal: gather what the person needs so {owner} can act on it later.
{lang_instruction}

Rules:
- Be polite, warm, and natural. Not robotic.
- Tell the person {owner} is busy but you're here to help note their message.
- If you have the meeting end time, mention it naturally (e.g. "Vansh should be free around 4:30 PM").
- Ask for the key detail: what do they need, or is there a message to pass on?
- Keep it SHORT — max 2 sentences.
- Never reveal internal system details.
- Never pretend to be {owner}. Be iZACH.

Message from {sender}: "{message}"

Generate your reply:"""

    try:
        reply = _wa_ai_call(persona_prompt)   # uses WA key → falls back to main key
        if not reply:
            reply = f"Hey! {owner} is currently busy. I'm iZACH, his assistant — what can I note down for him?"
        return jsonify({"ok": True, "reply": reply.strip(), "lang": lang})
    except Exception as e:
        return jsonify({"ok": False, "error": _friendly_error(e)}), 500


@ui_bp.route("/notes/save", methods=["POST"])
def n8n_notes_save():
    """
    N8N calls this to append a transcript line to Obsidian call log.
    Body: { "contact": "Arjun", "role": "caller"|"izach",
            "text": "bhai kab milega", "ts": 1716800000 }
    Returns: { "ok": true, "path": "iZACH-Brain/Calls/Arjun_2026-05-27.md" }
    """
    if not _check_n8n_token():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data    = request.get_json(silent=True) or {}
    contact = data.get("contact", "Unknown").strip()
    role    = data.get("role", "caller").lower()
    text    = data.get("text", "").strip()
    ts      = data.get("ts", int(time.time()))

    if not text:
        return jsonify({"ok": False, "error": "text required"}), 400

    try:
        import datetime, pathlib
        date_str  = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        time_str  = datetime.datetime.fromtimestamp(ts).strftime("%H:%M")

        # Resolve Obsidian vault root
        vault_root = os.getenv("OBSIDIAN_VAULT", os.path.join(os.path.dirname(os.path.dirname(__file__)), "iZACH-Brain"))
        calls_dir  = pathlib.Path(vault_root) / "Calls"
        calls_dir.mkdir(parents=True, exist_ok=True)

        filename   = f"{contact}_{date_str}.md"
        filepath   = calls_dir / filename
        rel_path   = f"iZACH-Brain/Calls/{filename}"

        # Role label
        label = "📱 Caller" if role == "caller" else "🤖 iZACH"
        line  = f"**[{time_str}] {label}:** {text}\n"

        # Create file with header if new
        if not filepath.exists():
            header = (
                f"# 📞 Call/Message Log — {contact}\n"
                f"**Date:** {date_str}  \n"
                f"**Handled by:** iZACH (DND auto-reply)\n\n"
                f"---\n\n"
            )
            filepath.write_text(header, encoding="utf-8")

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)

        return jsonify({"ok": True, "path": rel_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/whatsapp/send", methods=["POST"])
def n8n_whatsapp_send():
    """
    N8N calls this to send a WhatsApp message.
    Body: { "number": "91XXXXXXXXXX", "text": "...", "name": "Arjun" }
    Returns: { "ok": true, "status": "Message sent to Arjun." }
    """
    if not _check_n8n_token():
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data   = request.get_json(silent=True) or {}
    number = data.get("number", "").strip()
    text   = data.get("text", "").strip()
    name   = data.get("name", "")

    if not number or not text:
        return jsonify({"ok": False, "error": "number and text required"}), 400

    try:
        from modules.whatsapp_sender import send_message as _wa_send
        ok, status = _wa_send(number, text, name)
        return jsonify({"ok": ok, "status": status})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /websites         — list custom websites
# POST /websites         — add {name, url}
# DELETE /websites/<key> — remove by key (lowercased name)
# ─────────────────────────────────────────────────────────────
_WEBSITES_FILE = "custom_websites.json"


def _read_websites() -> list:
    try:
        with open(_WEBSITES_FILE) as f:
            return _json.load(f)
    except Exception:
        return []


def _write_websites(sites: list):
    with open(_WEBSITES_FILE, "w") as f:
        _json.dump(sites, f, indent=2)
    # Sync into web_automation._SHORTNAMES live
    try:
        from modules import web_automation as _wa
        for s in sites:
            _wa._SHORTNAMES[s["key"]] = s["url"]
    except Exception:
        pass


@ui_bp.route("/websites", methods=["GET"])
def websites_get():
    return jsonify({"ok": True, "websites": _read_websites()})


@ui_bp.route("/websites", methods=["POST"])
def websites_post():
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        url  = (data.get("url")  or "").strip()
        if not name or not url:
            return jsonify({"ok": False, "error": "name and url required"}), 400
        if not url.startswith("http"):
            url = "https://" + url
        key = name.lower()
        sites = _read_websites()
        if any(s["key"] == key for s in sites):
            return jsonify({"ok": False, "error": "Already exists"}), 409
        sites.append({"name": name, "key": key, "url": url})
        _write_websites(sites)
        return jsonify({"ok": True, "name": name, "key": key, "url": url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/websites/<path:key>", methods=["DELETE"])
def websites_delete(key):
    try:
        sites = _read_websites()
        before = len(sites)
        sites = [s for s in sites if s["key"] != key]
        if len(sites) == before:
            return jsonify({"ok": False, "error": "Not found"}), 404
        _write_websites(sites)
        # Remove from live shortnames
        try:
            from modules import web_automation as _wa
            _wa._SHORTNAMES.pop(key, None)
        except Exception:
            pass
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# CUSTOM LINKS  (used by Cortex UI settings tab)
# GET  /api/custom_links   → [{title, url}, ...]
# POST /api/custom_links   → save full list (replaces)
# ─────────────────────────────────────────────────────────────
_CUSTOM_LINKS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "custom_links.json")


def _read_custom_links() -> list:
    try:
        with open(_CUSTOM_LINKS_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return []


def _write_custom_links(links: list):
    with open(_CUSTOM_LINKS_FILE, "w", encoding="utf-8") as f:
        _json.dump(links, f, indent=2, ensure_ascii=False)
    # Live-sync into web_automation shortnames so voice commands work immediately
    try:
        from modules import web_automation as _wa
        for lk in links:
            title = lk.get("title", "").strip().lower()
            url   = lk.get("url", "").strip()
            if title and url:
                _wa._SHORTNAMES[title] = url
    except Exception:
        pass


@ui_bp.route("/api/custom_links", methods=["GET"])
def custom_links_get():
    return jsonify(_read_custom_links())


@ui_bp.route("/api/custom_links", methods=["POST"])
def custom_links_post():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, list):
            return jsonify({"ok": False, "error": "Expected JSON array"}), 400
        # Validate each entry
        cleaned = []
        for item in data:
            title = (item.get("title") or "").strip()
            url   = (item.get("url")   or "").strip()
            if title and url:
                cleaned.append({"title": title, "url": url})
        _write_custom_links(cleaned)
        return jsonify({"ok": True, "count": len(cleaned)})
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
# GET  /aliases              → list all voice aliases
# POST /aliases              → add alias {trigger, command}
# DELETE /aliases/<b64>      → delete alias by base64-encoded trigger
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/aliases", methods=["GET"])
def aliases_list():
    try:
        from modules.alias_engine import list_aliases as _list_al
        return jsonify({"ok": True, "aliases": _list_al()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/aliases", methods=["POST"])
def aliases_add():
    try:
        data    = request.get_json(silent=True) or {}
        trigger = data.get("trigger", "").strip()
        command = data.get("command", "").strip()
        if not trigger or not command:
            return jsonify({"ok": False, "error": "trigger and command required"}), 400
        from modules.alias_engine import add_alias as _add_al
        _add_al(trigger, command)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/aliases/<trigger_b64>", methods=["DELETE"])
def aliases_delete(trigger_b64):
    try:
        import base64 as _b64
        trigger = _b64.b64decode(trigger_b64.encode()).decode("utf-8")
        from modules.alias_engine import delete_alias as _del_al
        _del_al(trigger)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /export-chat?format=txt|pdf — download conversation log
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/export-chat", methods=["GET"])
def export_chat():
    fmt = request.args.get("format", "txt").lower()
    try:
        messages = _message_log[-200:]
        lines = []
        for m in messages:
            sender = m.get("sender", "?")
            text   = m.get("text", "")
            ts     = m.get("ts", "")
            lines.append(f"[{ts}] {sender}: {text}")
        plain = "\n".join(lines)

        if fmt == "pdf":
            try:
                from fpdf import FPDF  # type: ignore
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Helvetica", size=10)
                pdf.set_auto_page_break(auto=True, margin=15)
                for line in lines:
                    safe = line.encode("latin-1", errors="replace").decode("latin-1")
                    pdf.multi_cell(0, 6, safe)
                from io import BytesIO
                buf = BytesIO()
                pdf_bytes = pdf.output()
                buf.write(pdf_bytes)
                buf.seek(0)
                from flask import send_file
                return send_file(
                    buf,
                    mimetype="application/pdf",
                    as_attachment=True,
                    download_name="iZACH-chat-export.pdf",
                )
            except Exception:
                fmt = "txt"  # fallback to txt

        from flask import Response
        return Response(
            plain,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=iZACH-chat-export.txt"},
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


@ui_bp.route("/background-mode", methods=["POST"])
def background_mode():
    """Switch the running instance to Background Mode: persist ui=background and
    start the system-tray icon. The caller (UI) then closes its Electron window;
    Electron's window-all-closed handler sees ui=background and keeps the Python
    backend alive instead of killing it."""
    try:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            data = {}
        data["ui"] = "background"
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2)
        from modules import tray_icon
        tray_icon.start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/diagnostics/voice", methods=["GET"])
def diagnostics_voice():
    """Surface why iZACH might not be listening — flags blocking voice_loop."""
    info = {"mic_active": _mic_active}
    try:
        from modules import voice_id as _vid
        info["voice_enrolling"] = getattr(_vid, "_enrolling", False)
        info["voice_enrolled"]  = _vid.is_enrolled()
    except Exception:
        pass
    try:
        from modules import face_auth as _fa
        info["face_enrolling"] = getattr(_fa, "_enrolling", False)
    except Exception:
        pass
    try:
        from modules.speaker_diarization import list_enrolled, MIN_ENERGY_RMS
        info["diarization_profiles"] = list_enrolled()
        info["diarization_min_rms"]  = MIN_ENERGY_RMS
    except Exception:
        pass
    return jsonify({"ok": True, **info})


@ui_bp.route("/diagnostics/voice/reset", methods=["POST"])
def diagnostics_voice_reset():
    """Force-reset stuck enrollment flags so voice_loop resumes."""
    cleared = []
    try:
        from modules import voice_id as _vid
        if getattr(_vid, "_enrolling", False):
            _vid._enrolling = False
            cleared.append("voice_id._enrolling")
    except Exception:
        pass
    try:
        from modules import face_auth as _fa
        if getattr(_fa, "_enrolling", False):
            _fa._enrolling = False
            cleared.append("face_auth._enrolling")
    except Exception:
        pass
    return jsonify({"ok": True, "cleared": cleared})

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
    sp_files = [f for f in sp_dir.iterdir() if f.is_file()] if sp_dir.is_dir() else []
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


# ─────────────────────────────────────────────────────────────
# GET /phone/status  — Android app connection status
# GET /phone/qr      — QR code for pairing (base64 PNG)
# These are stubs; a future Android companion app will push
# real status via WebSocket broadcast({"type":"phone_status",...}).
# ─────────────────────────────────────────────────────────────

_phone_connected = False
_phone_device_name = ""
_phone_qr_b64 = None
_phone_commands: list[dict] = []
_phone_last_seen_ts: float = 0.0
_PHONE_HEARTBEAT_WINDOW = 60.0  # seconds — auto-mark disconnected after silence


def _phone_is_live() -> bool:
    """True if either explicit POST set connected OR a phone command arrived recently."""
    if _phone_connected:
        return True
    return (time.time() - _phone_last_seen_ts) < _PHONE_HEARTBEAT_WINDOW


def _record_phone_command(text: str, device_name: str = ""):
    """Record a command that came from the Android app + broadcast to UI."""
    global _phone_commands, _phone_last_seen_ts, _phone_device_name, _phone_connected
    _phone_last_seen_ts = time.time()
    _phone_connected = True
    if device_name:
        _phone_device_name = device_name
    entry = {
        "text":   text[:200],
        "ts":     time.strftime("%H:%M:%S"),
        "epoch":  _phone_last_seen_ts,
    }
    _phone_commands.append(entry)
    if len(_phone_commands) > 30:
        _phone_commands = _phone_commands[-30:]
    try:
        from modules.ws_bridge import broadcast
        broadcast({
            "type":        "phone_command",
            "text":        entry["text"],
            "ts":          entry["ts"],
            "device_name": _phone_device_name,
        })
        # Also broadcast updated status so widget flips to CONNECTED instantly
        broadcast({
            "type":        "phone_status",
            "connected":   True,
            "device_name": _phone_device_name,
            "qr":          _phone_qr_b64,
        })
    except Exception:
        pass


@ui_bp.route("/phone/commands", methods=["GET"])
def phone_commands_get():
    return jsonify({"ok": True, "commands": _phone_commands[-30:]})


@ui_bp.route("/phone/status", methods=["GET"])
def phone_status_get():
    return jsonify({
        "ok":          True,
        "connected":   _phone_is_live(),
        "device_name": _phone_device_name,
        "qr":          _phone_qr_b64,
    })


@ui_bp.route("/phone/status", methods=["POST"])
def phone_status_post():
    """Android app calls this to report its connection state."""
    global _phone_connected, _phone_device_name
    data = request.get_json(silent=True) or {}
    _phone_connected   = bool(data.get("connected", False))
    _phone_device_name = str(data.get("device_name", ""))
    try:
        from modules.ws_bridge import broadcast
        broadcast({
            "type":        "phone_status",
            "connected":   _phone_connected,
            "device_name": _phone_device_name,
            "qr":          _phone_qr_b64,
        })
    except Exception:
        pass
    return jsonify({"ok": True})


@ui_bp.route("/phone/qr", methods=["GET"])
def phone_qr():
    return jsonify({"ok": True, "qr": _phone_qr_b64})


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
# GET  /vision/cameras — list available camera indices
# POST /vision/camera  — { "index": N } switch active camera
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/vision/cameras")
def vision_cameras():
    try:
        from modules.camera_vision import list_cameras, _cam_device_index
        force = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        cameras = list_cameras(force_refresh=force)
        return jsonify({"ok": True, "cameras": cameras, "active": _cam_device_index})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/vision/camera", methods=["POST"])
def vision_set_camera():
    try:
        data = request.get_json(silent=True) or {}
        idx = int(data.get("index", 0))
        from modules.camera_vision import set_camera_device
        set_camera_device(idx)
        return jsonify({"ok": True, "active": idx})
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
        seen_names = set()

        # Noise patterns to skip — virtual mappers, loopback, Steam, empty names
        _SKIP_PATTERNS = [
            "microsoft sound mapper",
            "primary sound capture driver",
            "stereo mix",
            "pc speaker",
            "wave out",
            "steam streaming",
            "loopback",
            "what u hear",
        ]

        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) <= 0:
                continue

            raw_name = info.get("name", "")
            # PyAudio on some Windows builds returns bytes; always coerce to str
            if isinstance(raw_name, bytes):
                name = raw_name.decode("utf-8", errors="replace").strip()
            else:
                name = str(raw_name).strip()

            # Skip empty / placeholder names like "Input ()"
            if not name or name in ("Input ()", "Microphone ()"):
                continue

            # Skip known virtual / loopback / streaming devices
            name_lower = name.lower()
            if any(p_ in name_lower for p_ in _SKIP_PATTERNS):
                continue

            # De-duplicate — pyaudio lists same physical mic under multiple
            # Windows audio API layers (MME, DirectSound, WASAPI).
            # Keep first occurrence only.
            norm = re.sub(r'\s*\(.*?\)\s*$', '', name).strip().lower()
            if norm in seen_names:
                continue
            seen_names.add(norm)

            devices.append({"index": i, "name": name})

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
    return jsonify({"ok": True, "filename": filename, "path": dest, "size": size})


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
# Document Generation
# POST /document/generate
# body: { "content": "...", "format": "pdf"|"docx",
#          "title": "...", "template": "custom"|"activity_report"|"weekly_summary" }
# GET  /document/list  — files in shared/ folder
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/document/generate", methods=["POST"])
def document_generate():
    data     = request.get_json(silent=True) or {}
    content  = data.get("content", "")
    fmt      = data.get("format", "pdf")
    title    = data.get("title", "iZACH Document")
    template = data.get("template", "custom")
    try:
        from modules.document_engine import generate
        ok, msg, path = generate(content, fmt, title, template)
        return jsonify({"ok": ok, "message": msg,
                        "filename": os.path.basename(path) if path else ""})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Network Monitor
# GET /network/devices      — LAN devices from latest scan
# GET /network/connections  — active TCP connections per process
# GET /network/alerts       — alert history
# POST /network/trust       — { "mac": "aa:bb:...", "label": "TV" }
# POST /network/scan        — force rescan now
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/network/devices", methods=["GET"])
def network_devices():
    try:
        from modules.network_monitor import get_devices
        return jsonify({"ok": True, "devices": get_devices()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/network/connections", methods=["GET"])
def network_connections():
    try:
        from modules.network_monitor import get_connections
        return jsonify({"ok": True, "connections": get_connections()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/network/alerts", methods=["GET"])
def network_alerts():
    try:
        from modules.network_monitor import get_alerts
        return jsonify({"ok": True, "alerts": get_alerts()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/network/trust", methods=["POST"])
def network_trust():
    data  = request.get_json(silent=True) or {}
    mac   = data.get("mac", "").strip().lower()
    label = data.get("label", "").strip()
    if not mac:
        return jsonify({"ok": False, "error": "mac required"}), 400
    try:
        from modules.network_monitor import trust_device
        trust_device(mac, label)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/network/scan", methods=["POST"])
def network_scan():
    try:
        from modules.network_monitor import scan_now
        import threading
        threading.Thread(target=scan_now, daemon=True).start()
        return jsonify({"ok": True, "message": "Scan started."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET /window  — active foreground window info
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/window", methods=["GET"])
def active_window():
    try:
        from modules.window_watcher import get_active_window
        return jsonify({"ok": True, **get_active_window()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# GET  /location          — current location (SSID + city + coords)
# POST /location/label    — { "ssid": "HomeWifi", "label": "Home" }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/location", methods=["GET"])
def get_location_api():
    try:
        from modules.location_engine import get_location
        return jsonify({"ok": True, **get_location()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/location/label", methods=["POST"])
def label_location():
    data  = request.get_json(silent=True) or {}
    ssid  = data.get("ssid", "").strip()
    label = data.get("label", "").strip()
    if not ssid or not label:
        return jsonify({"ok": False, "error": "ssid and label required"}), 400
    try:
        from modules.location_engine import label_ssid
        label_ssid(ssid, label)
        return jsonify({"ok": True})
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


# ── Voice Auth ────────────────────────────────────────────────

@ui_bp.route("/voice/status", methods=["GET"])
def voice_status():
    try:
        from modules.voice_id import is_enrolled, get_meta
        return jsonify({"ok": True, "enrolled": is_enrolled(), "meta": get_meta()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/voice/phrases", methods=["GET"])
def voice_phrases():
    """Return the list of guided enrollment phrases."""
    try:
        from modules.voice_id import ENROLLMENT_PHRASES, PHRASE_SECONDS, PREP_SECONDS
        return jsonify({
            "ok": True,
            "phrases": ENROLLMENT_PHRASES,
            "phrase_seconds": PHRASE_SECONDS,
            "prep_seconds": PREP_SECONDS,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/voice/enroll", methods=["POST"])
def voice_enroll():
    try:
        from modules.voice_id import enroll_voice_async
        data  = request.get_json(silent=True) or {}
        label = data.get("label", "owner").strip() or "owner"
        enroll_voice_async(label)
        return jsonify({"ok": True, "message": "Guided enrollment started."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/voice/delete", methods=["DELETE"])
def voice_delete():
    try:
        from modules.voice_id import delete_voice_data
        ok = delete_voice_data()
        return jsonify({"ok": ok, "error": None if ok else "No voice data found"})
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
        # Auto-init if main.py forgot to bind speak handler
        if not face_auth._speak_func:
            face_auth.init(lambda _msg: None)
        # Verify face_recognition is installed before spawning subprocess
        try:
            import importlib
            if importlib.util.find_spec("face_recognition") is None:
                return jsonify({
                    "ok": False,
                    "error": "face_recognition package not installed. Run: pip install face-recognition"
                }), 500
        except Exception:
            pass
        face_auth.enroll_owner()
        return jsonify({"ok": True, "message": "Enrollment started. Look at the camera."})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/face/delete", methods=["DELETE"])
def face_delete():
    try:
        from modules.face_auth import delete_face_data
        ok = delete_face_data()
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Contacts — contacts.json CRUD + CSV/VCF import
# GET  /contacts               — list all contacts
# POST /contacts               — add { number, name }
# DELETE /contacts/<number>    — remove by WA number
# POST /contacts/import        — multipart file (.csv or .vcf)
# ─────────────────────────────────────────────────────────────

_CONTACTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contacts.json")

def _load_contacts_file():
    try:
        with open(_CONTACTS_FILE) as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_contacts_file(data):
    with open(_CONTACTS_FILE, "w") as f:
        _json.dump(data, f, indent=2)

def _reload_wa_contacts():
    try:
        from modules.whatsapp_handler import _load_contacts
        _load_contacts()
    except Exception:
        pass

def _normalize_wa_number(raw: str) -> str:
    digits = re.sub(r'\D', '', raw)
    return digits + "@c.us"


@ui_bp.route("/contacts", methods=["GET"])
def contacts_get():
    try:
        data = _load_contacts_file()
        contacts = [{"number": k, "name": v} for k, v in data.items()]
        return jsonify({"ok": True, "contacts": contacts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/contacts", methods=["POST"])
def contacts_add():
    try:
        body = request.get_json(silent=True) or {}
        number = body.get("number", "").strip()
        name   = body.get("name",   "").strip()
        if not number or not name:
            return jsonify({"ok": False, "error": "number and name required"}), 400
        wa_number = _normalize_wa_number(number)
        data = _load_contacts_file()
        data[wa_number] = name
        _save_contacts_file(data)
        _reload_wa_contacts()
        return jsonify({"ok": True, "number": wa_number, "name": name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/contacts/<path:number>", methods=["DELETE"])
def contacts_delete(number):
    try:
        data = _load_contacts_file()
        if number not in data:
            return jsonify({"ok": False, "error": "Not found"}), 404
        del data[number]
        _save_contacts_file(data)
        _reload_wa_contacts()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/contacts/import", methods=["POST"])
def contacts_import():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files["file"]
    filename = (f.filename or "").lower()
    content = f.read().decode("utf-8", errors="ignore")
    imported = {}

    if filename.endswith(".vcf"):
        current_name = None
        current_tel  = None
        for line in content.splitlines():
            line = line.strip()
            if line.upper().startswith("FN:"):
                current_name = line[3:].strip()
            elif line.upper().startswith("TEL") and ":" in line:
                tel    = line.split(":", 1)[1].strip()
                digits = re.sub(r'\D', '', tel)
                if digits:
                    current_tel = digits
            elif line.upper() == "END:VCARD":
                if current_name and current_tel:
                    imported[current_tel + "@c.us"] = current_name
                current_name = None
                current_tel  = None

    elif filename.endswith(".csv"):
        import csv, io
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            name = (row.get("Name") or "").strip()
            if not name:
                first = (row.get("First Name") or "").strip()
                last  = (row.get("Last Name")  or "").strip()
                name  = f"{first} {last}".strip()
            if not name:
                continue
            phone = ""
            for key, val in row.items():
                if any(k in key.lower() for k in ("phone", "tel", "mobile")):
                    val = (val or "").strip()
                    if val:
                        phone = val
                        break
            if not phone:
                continue
            digits = re.sub(r'\D', '', phone)
            if digits:
                imported[digits + "@c.us"] = name
    else:
        return jsonify({"ok": False, "error": "Only .csv and .vcf files supported"}), 400

    if not imported:
        return jsonify({"ok": False, "error": "No valid contacts found in file"}), 400

    data = _load_contacts_file()
    data.update(imported)
    _save_contacts_file(data)
    _reload_wa_contacts()
    return jsonify({"ok": True, "imported": len(imported), "total": len(data)})


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


# ── WhatsApp Logout ───────────────────────────────────────────

@ui_bp.route("/whatsapp/logout", methods=["POST"])
def whatsapp_logout():
    try:
        import requests as _req
        r = _req.post("http://localhost:3000/logout", timeout=10)
        data = r.json()
        if data.get("status") == "logged_out":
            # Tell the UI to show the QR widget in 'pending' state. The Node
            # bridge will POST a fresh QR to /whatsapp/qr within a few seconds
            # once it re-initialises its WA client.
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "whatsapp_status", "connected": False, "pending_qr": True})
                broadcast({"type": "whatsapp_qr", "qr": "", "pending": True})
            except Exception:
                pass
            # Best-effort: poke the bridge to restart its WA client so a new QR
            # is generated immediately. Some bridge versions expose /restart.
            def _trigger_restart():
                import time as _t
                _t.sleep(0.3)
                for path in ("/restart", "/start", "/init"):
                    try:
                        _req.post(f"http://localhost:3000{path}", timeout=5)
                        return
                    except Exception:
                        continue
            import threading as _thr
            _thr.Thread(target=_trigger_restart, daemon=True).start()
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": data.get("message", "Logout failed")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Relationships ─────────────────────────────────────────────

@ui_bp.route("/relationships", methods=["GET"])
def get_relationships():
    """
    Returns all people in relationship memory with their facts.
    Used by RelationshipGraph.jsx D3 force graph.
    """
    try:
        from modules.relationship_memory import list_people, get_person
        names = list_people()
        people = []
        for name in names:
            if name.replace("+", "").replace(" ", "").isdigit():
                continue
            facts = get_person(name)
            people.append({"name": name, "facts": facts})
        return jsonify({"ok": True, "people": people, "count": len(people)})
    except Exception as e:
        return jsonify({"ok": False, "people": [], "error": str(e)})


# ─────────────────────────────────────────────────────────────
# Remote Node API — Devices widget
# GET  /nodes/vitals?node=alliednode+2
# POST /nodes/control  { node, action, value }
# ─────────────────────────────────────────────────────────────

@ui_bp.route("/nodes/vitals", methods=["GET"])
def nodes_vitals():
    node = request.args.get("node", "").strip()
    if not node:
        return jsonify({"ok": False, "error": "node required"}), 400
    try:
        from modules.remote_node import get_vitals
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
        # Hard 4s wall-clock timeout — prevents Flask thread hanging on offline
        # remote nodes where OS-level TCP SYN ignores requests.timeout on Windows.
        with ThreadPoolExecutor(max_workers=1) as _ex:
            try:
                v = _ex.submit(get_vitals, node).result(timeout=4)
            except _FutTimeout:
                return jsonify({"ok": False, "error": f"Node '{node}' unreachable (timeout)"}), 504
        if "error" in v:
            return jsonify({"ok": False, "error": v["error"]}), 503
        return jsonify({"ok": True, "vitals": v})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/nodes/control", methods=["POST"])
def nodes_control():
    data   = request.get_json(silent=True) or {}
    node   = data.get("node", "").strip()
    action = data.get("action", "").strip()
    value  = data.get("value", None)
    if not node or not action:
        return jsonify({"ok": False, "error": "node and action required"}), 400
    try:
        from modules import remote_node as _rn

        # Power actions
        if action in ("shutdown", "restart", "sleep", "lock"):
            r = _rn.system_control(node, action)
            return jsonify({"ok": "error" not in r, **r})

        # Kill process
        if action == "kill_process":
            proc = data.get("process", "")
            r = _rn.system_control(node, "kill_process", process=proc)
            return jsonify({"ok": "error" not in r, **r})

        # Volume — Windows Core Audio IAudioEndpointVolume (works on Win10/11; waveOutSetVolume is legacy)
        if action == "volume" and value is not None:
            import base64
            pct = max(0, min(100, int(value)))
            lines = [
                f"$vol=[float]({pct}/100.0)",
                'Add-Type -TypeDefinition @"',
                "using System;",
                "using System.Runtime.InteropServices;",
                '[ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]',
                "class MMDE {}",
                '[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]',
                "interface IMMDE {",
                "  int _a();",
                "  [PreserveSig] int GetDefaultAudioEndpoint(int d,int r,out IMMD p);",
                "}",
                '[Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]',
                "interface IMMD {",
                "  [PreserveSig] int Activate(ref Guid id,int ctx,IntPtr ap,[MarshalAs(UnmanagedType.IUnknown)]out object pp);",
                "}",
                '[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]',
                "interface IAEV {",
                "  int _a();int _b();int _c();int _d();",
                "  [PreserveSig] int SetMasterVolumeLevelScalar(float f,Guid g);",
                "}",
                "public class VA {",
                "  public static void Set(float v){",
                "    var e=(IMMDE)new MMDE();",
                "    IMMD d;e.GetDefaultAudioEndpoint(0,1,out d);",
                "    var id=typeof(IAEV).GUID;object o;",
                "    d.Activate(ref id,23,IntPtr.Zero,out o);",
                "    ((IAEV)o).SetMasterVolumeLevelScalar(v,Guid.Empty);",
                "  }",
                "}",
                '"@',
                "[VA]::Set($vol)",
            ]
            script = "\n".join(lines)
            enc = base64.b64encode(script.encode('utf-16-le')).decode()
            r = _rn.execute(node, f'powershell -EncodedCommand {enc}')
            return jsonify({"ok": True, "action": action, "value": pct, "node_result": r})

        # Brightness — base64-encoded PS via WMI
        if action == "brightness" and value is not None:
            import base64
            pct = max(0, min(100, int(value)))
            script = (
                f'(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)'
                f'.WmiSetBrightness(1,{pct})'
            )
            enc = base64.b64encode(script.encode('utf-16-le')).decode()
            r = _rn.execute(node, f'powershell -EncodedCommand {enc}')
            return jsonify({"ok": True, "action": action, "value": pct, "node_result": r})

        # Media keys via PowerShell SendKeys
        _MEDIA_MAP = {
            "media_play_pause": "{MEDIA_PLAY_PAUSE}",
            "media_next":       "{MEDIA_NEXT_TRACK}",
            "media_prev":       "{MEDIA_PREV_TRACK}",
        }
        if action in _MEDIA_MAP:
            key = _MEDIA_MAP[action]
            ps_cmd = (
                f'Add-Type -AssemblyName System.Windows.Forms;'
                f'[System.Windows.Forms.SendKeys]::SendWait("{key}")'
            )
            r = _rn.execute(node, f'powershell -c "{ps_cmd}"')
            return jsonify({"ok": True, "action": action})

        return jsonify({"ok": False, "error": f"unknown action: {action}"}), 400

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# GET /nodes/processes?node=&top=20
@ui_bp.route("/nodes/processes", methods=["GET"])
def nodes_processes():
    node = request.args.get("node", "").strip()
    top  = min(int(request.args.get("top", 20)), 50)
    if not node:
        return jsonify({"ok": False, "error": "node required"}), 400
    try:
        from modules import remote_node as _rn
        r = _rn.get_processes(node, top=top)
        if "error" in r:
            return jsonify({"ok": False, "error": r["error"]}), 502
        return jsonify({"ok": True, "processes": r.get("processes", [])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# GET /nodes/screenshot?node=
@ui_bp.route("/nodes/screenshot", methods=["GET"])
def nodes_screenshot():
    node = request.args.get("node", "").strip()
    if not node:
        return jsonify({"ok": False, "error": "node required"}), 400
    try:
        from modules import remote_node as _rn
        r = _rn.take_screenshot(node)
        if "error" in r:
            return jsonify({"ok": False, "error": r["error"]}), 502
        return jsonify({"ok": True, "screenshot": r.get("screenshot"),
                        "width": r.get("width"), "height": r.get("height")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# POST /nodes/execute  { node, command }
@ui_bp.route("/nodes/execute", methods=["POST"])
def nodes_execute():
    data    = request.get_json(silent=True) or {}
    node    = data.get("node", "").strip()
    command = data.get("command", "").strip()
    if not node or not command:
        return jsonify({"ok": False, "error": "node and command required"}), 400
    try:
        from modules import remote_node as _rn
        r = _rn.execute(node, command)
        if "error" in r:
            return jsonify({"ok": False, "error": r["error"]}), 502
        return jsonify({"ok": True, "stdout": r.get("stdout", ""),
                        "stderr": r.get("stderr", ""), "returncode": r.get("returncode")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# POST /nodes/file  { node, dest, content }   (base64 content)
@ui_bp.route("/nodes/file", methods=["POST"])
def nodes_file():
    data    = request.get_json(silent=True) or {}
    node    = data.get("node", "").strip()
    dest    = data.get("dest", "").strip()
    content = data.get("content", "")
    if not node or not dest or not content:
        return jsonify({"ok": False, "error": "node, dest, content required"}), 400
    try:
        import base64 as _b64
        from modules import remote_node as _rn
        r = _rn.upload_bytes(node, dest, _b64.b64decode(content))
        if "error" in r:
            return jsonify({"ok": False, "error": r["error"]}), 502
        return jsonify({"ok": True, **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# POST /nodes/wol  { node }
@ui_bp.route("/nodes/wol", methods=["POST"])
def nodes_wol():
    data = request.get_json(silent=True) or {}
    node = data.get("node", "").strip()
    if not node:
        return jsonify({"ok": False, "error": "node required"}), 400
    try:
        from modules import remote_node as _rn
        r = _rn.wake_on_lan(node)
        return jsonify({"ok": "error" not in r, **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# =============================================================================
# PRINT ENGINE — Phase 2
# =============================================================================

@ui_bp.route("/print/printers", methods=["GET"])
def print_list_printers():
    """List all available printers."""
    try:
        from modules.print_engine import list_printers
        return jsonify({"ok": True, "printers": list_printers()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/status", methods=["GET"])
def print_status():
    """Get status + queue for the configured/default printer."""
    try:
        from modules.print_engine import get_printer_status, get_prefs
        prefs = get_prefs()
        printer = request.args.get("printer") or prefs.get("default_printer") or ""
        status = get_printer_status(printer)
        return jsonify({"ok": True, **status})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/settings", methods=["GET"])
def print_get_settings():
    """Return current default print preferences."""
    try:
        from modules.print_engine import get_prefs
        return jsonify({"ok": True, "settings": get_prefs()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/settings", methods=["POST"])
def print_update_settings():
    """Update default print preferences."""
    try:
        from modules.print_engine import update_prefs
        data = request.json or {}
        updated = update_prefs(data)
        return jsonify({"ok": True, "settings": updated})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/open-browser", methods=["POST"])
def print_open_browser():
    """
    Open a file in the user's default browser (Chrome) so they can use
    Chrome's built-in PDF preview + print dialog. PDFs render in-place;
    other types may download. Replaces the IPP/CUPS print path.
    Body: { "path": "/abs/path/to/file.pdf" }
    """
    try:
        data = request.json or {}
        path = (data.get("path") or "").strip()
        if not path or not os.path.isfile(path):
            return jsonify({"ok": False, "error": "File not found"}), 404
        import webbrowser as _wb
        abs_path = os.path.abspath(path).replace("\\", "/")
        url = "file:///" + abs_path
        ok = _wb.open(url, new=2)
        return jsonify({"ok": bool(ok), "url": url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/job", methods=["POST"])
def print_job():
    """
    Send one or more files to the printer.
    Body: {files: ["/abs/path/to/file.pdf", ...], overrides: {color_mode, dpi, ...}}
    Or: {file_paths: [...], overrides: {...}}
    """
    try:
        from modules.print_engine import print_files_batch
        data = request.json or {}
        paths = data.get("files") or data.get("file_paths") or []
        overrides = data.get("overrides") or {}
        per_file_pages = data.get("per_file_pages") or {}  # {path: "page_spec"}
        if not paths:
            return jsonify({"ok": False, "error": "No files specified"}), 400
        results = print_files_batch(paths, overrides, per_file_pages)
        success = all(r["success"] for r in results)
        return jsonify({"ok": success, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/upload-and-print", methods=["POST"])
def print_upload_and_print():
    """
    Upload file(s) then print them.
    multipart/form-data: files[] + optional JSON overrides field.
    """
    try:
        from modules.print_engine import print_file, get_prefs
        files = request.files.getlist("files[]") or request.files.getlist("file")
        if not files:
            return jsonify({"ok": False, "error": "No files uploaded"}), 400

        overrides_raw = request.form.get("overrides", "{}")
        try:
            import json as _j
            overrides = _j.loads(overrides_raw)
        except Exception:
            overrides = {}

        saved_paths = []
        for f in files:
            if not f.filename:
                continue
            safe_name = secure_filename(f.filename)
            dest = os.path.join(SHARED_DIR, f"print_{int(time.time())}_{safe_name}")
            f.save(dest)
            saved_paths.append(dest)

        results = []
        for path in saved_paths:
            ok, msg = print_file(path, overrides)
            results.append({"file": os.path.basename(path), "success": ok, "message": msg})
        success = all(r["success"] for r in results)
        return jsonify({"ok": success, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/preview", methods=["POST"])
def print_preview():
    """
    Generate a preview thumbnail for a file.
    Body: {path: "/abs/path/to/file.pdf"}
    Returns: {ok, preview: "base64png" | "pdf:N" | "docx:N" | null}
    """
    try:
        from modules.print_engine import generate_preview
        data = request.json or {}
        path = data.get("path", "").strip()
        if not path or not os.path.exists(path):
            return jsonify({"ok": False, "error": "File not found"}), 404
        preview = generate_preview(path)
        # Also include page count in response
        page_count = 0
        if preview and isinstance(preview, str) and preview.startswith("pdf:"):
            try: page_count = int(preview.split(":")[1])
            except Exception: pass
        return jsonify({"ok": True, "preview": preview, "page_count": page_count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/print/page-count", methods=["POST"])
def print_page_count():
    """Return page count for a PDF. Body: {path: "..."}"""
    try:
        from modules.print_engine import get_pdf_page_count
        data = request.json or {}
        path = data.get("path", "").strip()
        if not path or not os.path.exists(path):
            return jsonify({"ok": False, "count": 0}), 404
        count = get_pdf_page_count(path)
        return jsonify({"ok": True, "count": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# =============================================================================
# OCR ENGINE — Phase 2 (camera-based document scanning)
# =============================================================================

_ocr_state = {
    "enabled": False,
    "last_text": "",
    "last_ts": 0,
    "mode": "idle",  # idle | scanning | done
}


@ui_bp.route("/ocr/status", methods=["GET"])
def ocr_status():
    """Return current OCR state."""
    return jsonify({
        "ok": True,
        "enabled": _ocr_state["enabled"],
        "mode": _ocr_state["mode"],
        "last_text": _ocr_state["last_text"],
        "last_ts": _ocr_state["last_ts"],
    })


@ui_bp.route("/ocr/toggle", methods=["POST"])
def ocr_toggle():
    """Enable or disable live OCR scanning mode."""
    try:
        data = request.json or {}
        enabled = data.get("enabled", not _ocr_state["enabled"])
        _ocr_state["enabled"] = bool(enabled)
        _ocr_state["mode"] = "scanning" if enabled else "idle"

        if enabled:
            # Announce via speak
            if _speak_fn:
                _speak_fn("Camera OCR activated. Show me the document.")
            # Start background OCR scan
            threading.Thread(target=_run_ocr_scan, daemon=True).start()
        else:
            if _speak_fn:
                _speak_fn("OCR scanning disabled.")

        return jsonify({"ok": True, "enabled": enabled})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/ocr/scan-image", methods=["POST"])
def ocr_scan_image():
    """
    Scan a base64 image for text (for manual image uploads).
    Body: {image: "base64...", mime: "image/png"}
    """
    try:
        data = request.json or {}
        b64 = data.get("image", "")
        if not b64:
            return jsonify({"ok": False, "error": "No image data"}), 400

        text = _extract_text_from_b64(b64)
        _ocr_state["last_text"] = text
        _ocr_state["last_ts"] = int(time.time())
        _ocr_state["mode"] = "done"

        # Broadcast to UI
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "ocr_result", "text": text, "ts": _ocr_state["last_ts"]})
        except Exception:
            pass

        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/ocr/save", methods=["POST"])
def ocr_save():
    """Save last OCR result to a notepad/text file on Desktop."""
    try:
        data = request.json or {}
        text = data.get("text") or _ocr_state.get("last_text", "")
        if not text.strip():
            return jsonify({"ok": False, "error": "No text to save"}), 400

        filename = f"iZACH_OCR_{int(time.time())}.txt"
        dest = os.path.join(os.path.expanduser("~"), "Desktop", filename)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)

        if _speak_fn:
            _speak_fn(f"Saved OCR text to Desktop as {filename}.")
        return jsonify({"ok": True, "saved_to": dest})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _extract_text_from_b64(b64: str) -> str:
    """Run vision OCR on base64 image. Returns extracted text."""
    try:
        from modules.camera_vision import _ask_vision
        prompt = (
            "This is a document/page shown to a camera. Extract ALL the text from it exactly as written. "
            "Preserve formatting — use line breaks between lines. "
            "Also note any dates, names, subject headings, or deadlines you see."
        )
        return _ask_vision(b64, prompt) or ""
    except Exception as e:
        return f"[OCR error: {e}]"


def _run_ocr_scan():
    """Background: capture a camera frame and run OCR on it."""
    try:
        import time as _t
        _t.sleep(3)  # give user time to hold document steady
        from modules.camera_vision import _capture_frame, _frame_to_b64
        # OCR needs the raw (un-mirrored) frame so text is not flipped backward
        frame = _capture_frame(flip_h=False)
        if frame is None:
            _ocr_state["mode"] = "idle"
            _ocr_state["enabled"] = False
            return

        b64 = _frame_to_b64(frame)
        if not b64:
            _ocr_state["mode"] = "idle"
            _ocr_state["enabled"] = False
            return

        text = _extract_text_from_b64(b64)
        _ocr_state["last_text"] = text
        _ocr_state["last_ts"] = int(_t.time())
        _ocr_state["mode"] = "done"
        _ocr_state["enabled"] = False

        if _speak_fn:
            preview = text[:80].replace("\n", " ") if text else "no text found"
            _speak_fn(f"Document scanned. I extracted: {preview}…")

        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "ocr_result", "text": text, "ts": _ocr_state["last_ts"]})
        except Exception:
            pass
    except Exception as e:
        _ocr_state["mode"] = "idle"
        _ocr_state["enabled"] = False


# =============================================================================
# ── WEATHER WIDGET ENDPOINT (structured JSON for Cortex/Forge UI) ────────────
# =============================================================================

@ui_bp.route("/weather", methods=["GET"])
def ui_weather():
    """Return current weather as structured JSON for the weather widget."""
    try:
        import requests as _req
        # Read user's configured city from settings
        try:
            with open("api_keys.json") as _f:
                _cfg = _json.load(_f)
            city = _cfg.get("weather_city", "New Delhi").strip() or "New Delhi"
        except Exception:
            city = "New Delhi"

        # wttr.in JSON format — free, no key
        url = f"https://wttr.in/{city.replace(' ', '+')}?format=j1"
        r = _req.get(url, timeout=8)
        if r.status_code != 200:
            return jsonify({"ok": False, "error": f"wttr {r.status_code}"}), 502
        data = r.json() or {}
        cur = (data.get("current_condition") or [{}])[0]

        return jsonify({
            "ok":         True,
            "city":       city.upper(),
            "country":    (data.get("nearest_area", [{}])[0].get("country", [{}])[0].get("value", "") or "").upper(),
            "temp_c":     int(cur.get("temp_C", 0) or 0),
            "feels_c":    int(cur.get("FeelsLikeC", 0) or 0),
            "desc":       (cur.get("weatherDesc", [{}])[0].get("value", "") or "Unknown").strip(),
            "humidity":   int(cur.get("humidity", 0) or 0),
            "uv_index":   int(cur.get("uvIndex", 0) or 0),
            "wind_kmh":   int(cur.get("windspeedKmph", 0) or 0),
            "wind_dir":   cur.get("winddir16Point", "") or "",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# =============================================================================
# ── PHASE 3: GOOGLE FIT / FITNESS ENDPOINTS ──────────────────────────────────
# =============================================================================

@ui_bp.route("/fitness/status", methods=["GET"])
def fitness_status():
    try:
        from modules.fitness_engine import get_auth_status
        return jsonify(get_auth_status())
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@ui_bp.route("/fitness/summary", methods=["GET"])
def fitness_summary():
    try:
        from modules.fitness_engine import get_summary
        return jsonify(get_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/fitness/auth/start", methods=["GET"])
def fitness_auth_start():
    try:
        from modules.fitness_engine import start_auth_flow
        return jsonify(start_auth_flow())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/fitness/auth/complete", methods=["POST"])
def fitness_auth_complete():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "code required"}), 400
    try:
        from modules.fitness_engine import complete_auth
        return jsonify(complete_auth(code))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/fitness/disconnect", methods=["POST"])
def fitness_disconnect():
    try:
        from modules.fitness_engine import disconnect
        return jsonify(disconnect())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── PHASE 3: LOCATION / PHONE GPS ENDPOINTS ──────────────────────────────────
# =============================================================================

@ui_bp.route("/location/status", methods=["GET"])
def location_status():
    try:
        from modules.location_engine import get_full_location, is_running
        data = get_full_location()
        data["engine_running"] = is_running()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/location/toggle", methods=["POST"])
def location_toggle():
    """Start or stop background location engine. Body: {enabled: bool}"""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    try:
        if enabled:
            from modules.location_engine import start, is_running
            if not is_running():
                start()
            return jsonify({"ok": True, "running": True})
        else:
            from modules.location_engine import stop, is_running
            stop()
            return jsonify({"ok": True, "running": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/location/phone-ping", methods=["POST"])
def location_phone_ping():
    """
    Receives GPS ping from mobile companion (location_companion.html).
    Body: {lat, lon, accuracy, timestamp}
    """
    data = request.get_json(silent=True) or {}
    lat  = float(data.get("lat", 0.0))
    lon  = float(data.get("lon", 0.0))
    acc  = float(data.get("accuracy", 0.0))
    if lat == 0.0 and lon == 0.0:
        return jsonify({"error": "invalid coordinates"}), 400
    try:
        from modules.location_engine import update_phone_location, get_phone_location
        update_phone_location(lat, lon, acc)
        return jsonify({"received": True, **get_phone_location()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/location/label-ssid", methods=["POST"])
def location_label_ssid():
    """Label a WiFi SSID with a human-readable name (Home, College, Gym…)"""
    data = request.get_json(silent=True) or {}
    ssid  = data.get("ssid", "").strip()
    label = data.get("label", "").strip()
    if not ssid or not label:
        return jsonify({"error": "ssid and label required"}), 400
    try:
        from modules.location_engine import label_ssid
        label_ssid(ssid, label)
        return jsonify({"success": True, "ssid": ssid, "label": label})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/companion", methods=["GET"])
def location_companion():
    """Serve the mobile location companion page over HTTP."""
    base = os.path.dirname(os.path.dirname(__file__))
    return send_from_directory(base, "location_companion.html")


@ui_bp.route("/location/my-ip", methods=["GET"])
def location_my_ip():
    """Return PC's local IP so companion page can auto-fill server URL."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    return jsonify({"ip": ip, "url": f"http://{ip}:5050"})


# =============================================================================
# ── PHASE 4: SMART HOME ENDPOINTS ────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/smarthome/status", methods=["GET"])
def smarthome_status():
    try:
        from modules.smart_home_engine import get_all_status
        return jsonify(get_all_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/auth/start", methods=["GET"])
def smarthome_auth_start():
    try:
        from modules.smart_home_engine import start_auth_flow
        return jsonify(start_auth_flow())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/auth/complete", methods=["POST"])
def smarthome_auth_complete():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "code required"}), 400
    try:
        from modules.smart_home_engine import complete_auth
        return jsonify(complete_auth(code))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/auth/disconnect", methods=["POST"])
def smarthome_auth_disconnect():
    try:
        from modules.smart_home_engine import disconnect
        return jsonify(disconnect())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/devices", methods=["GET"])
def smarthome_devices():
    force = request.args.get("force", "false").lower() == "true"
    try:
        from modules.smart_home_engine import list_sdm_devices, list_cast_devices
        return jsonify({
            "nest_devices": list_sdm_devices(force=force),
            "cast_devices": list_cast_devices(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/settings", methods=["GET", "POST"])
def smarthome_settings():
    try:
        from modules.smart_home_engine import get_settings, update_settings
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            return jsonify(update_settings(data))
        return jsonify(get_settings())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/ac/temperature", methods=["POST"])
def smarthome_ac_temperature():
    """Body: {device_id, temp_c, mode}  — mode: COOL or HEAT"""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    temp_c    = data.get("temp_c", data.get("temp", 24))
    mode      = data.get("mode", "COOL").upper()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import set_temperature
        return jsonify(set_temperature(device_id, float(temp_c), mode))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/ac/mode", methods=["POST"])
def smarthome_ac_mode():
    """Body: {device_id, mode}  — mode: COOL | HEAT | HEATCOOL | OFF"""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    mode      = data.get("mode", "COOL").upper()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import set_thermostat_mode
        return jsonify(set_thermostat_mode(device_id, mode))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/ac/fan", methods=["POST"])
def smarthome_ac_fan():
    """Body: {device_id, duration_sec, action}  — action: start | stop"""
    data = request.get_json(silent=True) or {}
    device_id    = data.get("device_id", "")
    action       = data.get("action", "start").lower()
    duration_sec = int(data.get("duration_sec", 900))
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import set_fan_timer, stop_fan
        if action == "stop":
            return jsonify(stop_fan(device_id))
        return jsonify(set_fan_timer(device_id, duration_sec))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/cast/devices", methods=["GET"])
def smarthome_cast_devices():
    try:
        from modules.smart_home_engine import list_cast_devices
        return jsonify({"devices": list_cast_devices()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/cast/control", methods=["POST"])
def smarthome_cast_control():
    """
    Body: {action, value, friendly_name}
    action: play_pause | stop | mute | volume | volume_up | volume_down | cast_url
    value: (volume 0-100) | (url for cast_url)
    """
    data          = request.get_json(silent=True) or {}
    action        = data.get("action", "")
    value         = data.get("value")
    friendly_name = data.get("friendly_name", "")
    try:
        from modules.smart_home_engine import (
            cast_play_pause, cast_stop, cast_mute_toggle,
            cast_volume, cast_volume_up, cast_volume_down, cast_media_url,
        )
        fn = friendly_name
        if action == "play_pause":
            return jsonify(cast_play_pause(fn))
        elif action == "stop":
            return jsonify(cast_stop(fn))
        elif action == "mute":
            return jsonify(cast_mute_toggle(fn))
        elif action == "volume":
            return jsonify(cast_volume(float(value or 50) / 100.0, fn))
        elif action == "volume_up":
            return jsonify(cast_volume_up(friendly_name=fn))
        elif action == "volume_down":
            return jsonify(cast_volume_down(friendly_name=fn))
        elif action == "cast_url":
            url   = str(value or "")
            title = data.get("title", "")
            ctype = data.get("content_type", "video/mp4")
            return jsonify(cast_media_url(url, title, ctype, fn))
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/command", methods=["POST"])
def smarthome_command():
    """Natural-language smart home command. Body: {command, device_id, cast_name}"""
    data    = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "command required"}), 400
    context = {k: v for k, v in data.items() if k != "command"}
    try:
        from modules.smart_home_engine import execute_voice_command
        return jsonify(execute_voice_command(command, context))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── SAMSUNG TV (local WebSocket) ─────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/smarthome/samsung/tv/info", methods=["GET"])
def samsung_tv_info():
    ip = request.args.get("ip", "")
    try:
        from modules.smart_home_engine import samsung_tv_get_info
        return jsonify(samsung_tv_get_info(ip))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/samsung/tv/key", methods=["POST"])
def samsung_tv_key():
    """Body: {key, ip}  — e.g. KEY_VOLUMEUP, KEY_MUTE, KEY_POWER"""
    data = request.get_json(silent=True) or {}
    key  = data.get("key", "").strip().upper()
    ip   = data.get("ip", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    try:
        from modules.smart_home_engine import samsung_tv_send_key
        return jsonify(samsung_tv_send_key(key, ip))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/samsung/tv/control", methods=["POST"])
def samsung_tv_control():
    """
    Body: {action, value, ip}
    action: power | volume_up | volume_down | mute | channel_up | channel_down |
            set_channel | key
    value:  channel number (for set_channel) | key name (for key)
    """
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "")
    value  = data.get("value")
    ip     = data.get("ip", "")
    try:
        from modules.smart_home_engine import (
            samsung_tv_power, samsung_tv_volume_up, samsung_tv_volume_down,
            samsung_tv_mute, samsung_tv_channel_up, samsung_tv_channel_down,
            samsung_tv_set_channel, samsung_tv_send_key,
        )
        if action == "power":          return jsonify(samsung_tv_power(ip))
        elif action == "volume_up":    return jsonify(samsung_tv_volume_up(ip))
        elif action == "volume_down":  return jsonify(samsung_tv_volume_down(ip))
        elif action == "mute":         return jsonify(samsung_tv_mute(ip))
        elif action == "channel_up":   return jsonify(samsung_tv_channel_up(ip))
        elif action == "channel_down": return jsonify(samsung_tv_channel_down(ip))
        elif action == "set_channel":  return jsonify(samsung_tv_set_channel(int(value or 1), ip))
        elif action == "key":          return jsonify(samsung_tv_send_key(str(value or ""), ip))
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── SAMSUNG SMARTTHINGS ───────────────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/smarthome/smartthings/devices", methods=["GET"])
def st_devices():
    try:
        from modules.smart_home_engine import list_smartthings_devices
        return jsonify({"devices": list_smartthings_devices()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/devices/<device_id>/status", methods=["GET"])
def st_device_status(device_id):
    try:
        from modules.smart_home_engine import get_smartthings_device_status
        return jsonify(get_smartthings_device_status(device_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/devices/<device_id>/command", methods=["POST"])
def st_device_command(device_id):
    """Body: {capability, command, args, component}"""
    data = request.get_json(silent=True) or {}
    capability = data.get("capability", "")
    command    = data.get("command", "")
    args       = data.get("args", [])
    component  = data.get("component", "main")
    if not capability or not command:
        return jsonify({"error": "capability and command required"}), 400
    try:
        from modules.smart_home_engine import smartthings_command
        return jsonify(smartthings_command(device_id, capability, command, args, component))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/ac/onoff", methods=["POST"])
def st_ac_onoff():
    """Body: {device_id, on: bool}"""
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    on        = bool(data.get("on", True))
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import st_ac_on, st_ac_off
        return jsonify(st_ac_on(device_id) if on else st_ac_off(device_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/ac/temperature", methods=["POST"])
def st_ac_temperature():
    """Body: {device_id, temp_c, mode}  mode: cool | heat"""
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    temp_c    = float(data.get("temp_c", data.get("temp", 24)))
    mode      = data.get("mode", "cool").lower()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import st_ac_set_temp
        return jsonify(st_ac_set_temp(device_id, temp_c, mode))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/ac/mode", methods=["POST"])
def st_ac_mode():
    """Body: {device_id, mode}  cool|heat|auto|dry|wind|fanOnly"""
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    mode      = data.get("mode", "cool").lower()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import st_ac_set_mode
        return jsonify(st_ac_set_mode(device_id, mode))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/ac/fan", methods=["POST"])
def st_ac_fan():
    """Body: {device_id, speed}  auto|low|medium|high|turbo"""
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    speed     = data.get("speed", "auto").lower()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import st_ac_set_fan_speed
        return jsonify(st_ac_set_fan_speed(device_id, speed))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── SMARTTHINGS TV ENDPOINTS ──────────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/smarthome/smartthings/tv/control", methods=["POST"])
def st_tv_control():
    """
    Body: {device_id, action, value}
    action: on | off | volume_up | volume_down | set_volume | mute |
            channel_up | channel_down | set_channel | play | pause | stop | app
    value:  volume level (0-100) for set_volume | channel for set_channel | app name for app
    """
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "")
    action    = data.get("action", "")
    value     = data.get("value")

    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    try:
        from modules.smart_home_engine import (
            st_tv_on, st_tv_off, st_tv_volume_up, st_tv_volume_down,
            st_tv_set_volume, st_tv_mute_toggle, st_tv_mute, st_tv_unmute,
            st_tv_channel_up, st_tv_channel_down, st_tv_set_channel,
            st_tv_play, st_tv_pause, st_tv_stop, st_tv_launch_app_by_name,
        )
        if action == "on":             return jsonify(st_tv_on(device_id))
        elif action == "off":          return jsonify(st_tv_off(device_id))
        elif action == "volume_up":    return jsonify(st_tv_volume_up(device_id))
        elif action == "volume_down":  return jsonify(st_tv_volume_down(device_id))
        elif action == "set_volume":   return jsonify(st_tv_set_volume(device_id, int(value or 30)))
        elif action == "mute":         return jsonify(st_tv_mute_toggle(device_id))
        elif action == "mute_on":      return jsonify(st_tv_mute(device_id))
        elif action == "mute_off":     return jsonify(st_tv_unmute(device_id))
        elif action == "channel_up":   return jsonify(st_tv_channel_up(device_id))
        elif action == "channel_down": return jsonify(st_tv_channel_down(device_id))
        elif action == "set_channel":  return jsonify(st_tv_set_channel(device_id, str(value or 1)))
        elif action == "play":         return jsonify(st_tv_play(device_id))
        elif action == "pause":        return jsonify(st_tv_pause(device_id))
        elif action == "stop":         return jsonify(st_tv_stop(device_id))
        elif action == "app":          return jsonify(st_tv_launch_app_by_name(device_id, str(value or "")))
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/smarthome/smartthings/tv/status", methods=["GET"])
def st_tv_status_ep():
    device_id = request.args.get("device_id", "")
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    try:
        from modules.smart_home_engine import get_smartthings_device_status
        return jsonify(get_smartthings_device_status(device_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── SUBCONSCIOUSNESS (Phase 5A) ───────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/subconsciousness/status", methods=["GET"])
def sc_status():
    """System health snapshot + running state."""
    try:
        from modules import subconsciousness as _sc
        import psutil as _ps
        bat  = _ps.sensors_battery()
        vm   = _ps.virtual_memory()
        disk = _ps.disk_usage("C:\\")
        return jsonify({
            "running":       True,
            "pending_count": len(_sc.get_pending()),
            "battery": {
                "percent": bat.percent if bat else None,
                "plugged": bat.power_plugged if bat else None,
            },
            "ram": {
                "percent":  vm.percent,
                "used_gb":  round(vm.used  / (1024**3), 1),
                "total_gb": round(vm.total / (1024**3), 1),
            },
            "disk_c": {
                "free_gb":      round(disk.free / (1024**3), 1),
                "percent_used": disk.percent,
            },
        })
    except Exception as e:
        return jsonify({"running": False, "error": str(e)}), 500


@ui_bp.route("/subconsciousness/pending", methods=["GET"])
def sc_pending():
    """List all pending permission requests."""
    try:
        from modules import subconsciousness as _sc
        return jsonify({"pending": _sc.get_pending()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/subconsciousness/permit/<action_id>", methods=["POST"])
def sc_permit(action_id: str):
    """Grant a pending permission (UI button click)."""
    try:
        from modules import subconsciousness as _sc
        ok = _sc.grant(action_id)
        return jsonify({"granted": ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/subconsciousness/deny/<action_id>", methods=["POST"])
def sc_deny(action_id: str):
    """Deny a pending permission (UI button click)."""
    try:
        from modules import subconsciousness as _sc
        ok = _sc.deny(action_id, "Okay, cancelled.")
        return jsonify({"denied": ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/subconsciousness/history", methods=["GET"])
def sc_history():
    """All permission entries including resolved."""
    try:
        from modules import subconsciousness as _sc
        return jsonify({"history": _sc.get_all()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/subconsciousness/clear", methods=["POST"])
def sc_clear():
    """Prune resolved entries."""
    try:
        from modules import subconsciousness as _sc
        _sc.clear_resolved()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── INSTAGRAM (Phase 5B) ──────────────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/instagram/status", methods=["GET"])
def ig_status():
    try:
        from modules.instagram_engine import auth_status, rate_status
        s = auth_status()
        s["rate"] = rate_status()
        return jsonify(s)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/auth/start", methods=["GET"])
def ig_auth_start():
    try:
        from modules.instagram_engine import start_auth_flow
        return jsonify(start_auth_flow())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/auth/complete", methods=["POST"])
def ig_auth_complete():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "code required"}), 400
    try:
        from modules.instagram_engine import complete_auth
        return jsonify(complete_auth(code))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/auth/disconnect", methods=["POST"])
def ig_auth_disconnect():
    try:
        from modules.instagram_engine import disconnect
        return jsonify(disconnect())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/profile", methods=["GET"])
def ig_profile():
    try:
        from modules.instagram_engine import get_profile
        return jsonify(get_profile())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/settings", methods=["GET"])
def ig_settings_get():
    try:
        from modules.instagram_engine import get_settings
        return jsonify(get_settings())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/settings", methods=["POST"])
def ig_settings_post():
    data = request.get_json(silent=True) or {}
    try:
        from modules.instagram_engine import update_settings
        return jsonify(update_settings(data))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/inbox", methods=["GET"])
def ig_inbox():
    limit = int(request.args.get("limit", 20))
    try:
        from modules.instagram_engine import get_inbox
        return jsonify(get_inbox(limit=limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/thread/<thread_id>", methods=["GET"])
def ig_thread(thread_id: str):
    try:
        from modules.instagram_engine import get_thread_messages
        return jsonify(get_thread_messages(thread_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/reply", methods=["POST"])
def ig_reply():
    """Body: {thread_id, message}"""
    data      = request.get_json(silent=True) or {}
    thread_id = data.get("thread_id", "")
    message   = data.get("message", "").strip()
    if not thread_id or not message:
        return jsonify({"error": "thread_id and message required"}), 400
    try:
        from modules.instagram_engine import send_dm
        return jsonify(send_dm(thread_id, message))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/auto_reply", methods=["POST"])
def ig_auto_reply_toggle():
    """Body: {enabled: bool}"""
    data    = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    try:
        from modules.instagram_engine import update_settings, _ensure_bg_services
        update_settings({"auto_reply_enabled": enabled})
        if enabled:
            _ensure_bg_services()
        return jsonify({"ok": True, "auto_reply_enabled": enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/posts", methods=["GET"])
def ig_posts():
    limit = int(request.args.get("limit", 12))
    try:
        from modules.instagram_engine import get_recent_posts
        return jsonify(get_recent_posts(limit=limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/post/insights/<media_id>", methods=["GET"])
def ig_post_insights(media_id: str):
    try:
        from modules.instagram_engine import get_post_insights
        return jsonify(get_post_insights(media_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/post/photo", methods=["POST"])
def ig_post_photo():
    """Body: {image_url, caption}"""
    data      = request.get_json(silent=True) or {}
    image_url = data.get("image_url", "").strip()
    caption   = data.get("caption", "").strip()
    if not image_url:
        return jsonify({"error": "image_url required (must be public URL)"}), 400
    try:
        from modules.instagram_engine import post_photo
        return jsonify(post_photo(image_url, caption))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/post/reel", methods=["POST"])
def ig_post_reel():
    """Body: {video_url, caption, cover_url, share_to_feed}"""
    data          = request.get_json(silent=True) or {}
    video_url     = data.get("video_url", "").strip()
    caption       = data.get("caption", "").strip()
    cover_url     = data.get("cover_url", "").strip()
    share_to_feed = bool(data.get("share_to_feed", True))
    if not video_url:
        return jsonify({"error": "video_url required (must be public URL)"}), 400
    try:
        from modules.instagram_engine import post_reel
        return jsonify(post_reel(video_url, caption, cover_url, share_to_feed))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/post/video", methods=["POST"])
def ig_post_video():
    """Body: {video_url, caption}"""
    data      = request.get_json(silent=True) or {}
    video_url = data.get("video_url", "").strip()
    caption   = data.get("caption", "").strip()
    if not video_url:
        return jsonify({"error": "video_url required"}), 400
    try:
        from modules.instagram_engine import post_video
        return jsonify(post_video(video_url, caption))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/caption/generate", methods=["POST"])
def ig_caption_gen():
    """Body: {context, style, hashtag_count}"""
    data          = request.get_json(silent=True) or {}
    context       = data.get("context", "").strip()
    style         = data.get("style", "casual")
    hashtag_count = int(data.get("hashtag_count", 10))
    if not context:
        return jsonify({"error": "context required"}), 400
    try:
        from modules.instagram_engine import generate_caption
        caption = generate_caption(context, style, hashtag_count)
        return jsonify({"caption": caption})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/followers/check", methods=["GET"])
def ig_followers_check():
    try:
        from modules.instagram_engine import check_follower_change
        return jsonify(check_follower_change())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/comments/<media_id>", methods=["GET"])
def ig_comments(media_id: str):
    try:
        from modules.instagram_engine import get_comments
        return jsonify(get_comments(media_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/comments/reply", methods=["POST"])
def ig_comment_reply():
    """Body: {comment_id, message}"""
    data       = request.get_json(silent=True) or {}
    comment_id = data.get("comment_id", "")
    message    = data.get("message", "").strip()
    if not comment_id or not message:
        return jsonify({"error": "comment_id and message required"}), 400
    try:
        from modules.instagram_engine import reply_to_comment
        return jsonify(reply_to_comment(comment_id, message))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/instagram/insights", methods=["GET"])
def ig_insights():
    try:
        from modules.instagram_engine import get_insights
        return jsonify(get_insights())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ── NEWS ENGINE (Phase 6) ─────────────────────────────────────────────────────
# =============================================================================

@ui_bp.route("/news/headlines", methods=["GET"])
def news_headlines():
    """?topic=india&count=6"""
    topic = request.args.get("topic", "india")
    count = int(request.args.get("count", 6))
    try:
        from modules.news_engine import get_headline_items
        return jsonify({"topic": topic, "items": get_headline_items(topic, count)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/market", methods=["GET"])
def news_market():
    """Full market snapshot: indices, crypto, gold, petrol."""
    try:
        from modules.news_engine import get_market_snapshot
        return jsonify(get_market_snapshot())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/ticker", methods=["GET"])
def news_ticker():
    """Single-line ticker string."""
    try:
        from modules.news_engine import build_ticker_text
        return jsonify({"ticker": build_ticker_text()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/channels", methods=["GET"])
def news_channels():
    """All YouTube channel configs."""
    try:
        from modules.news_engine import YOUTUBE_CHANNELS, get_channel_embed_url
        result = {}
        for key, ch in YOUTUBE_CHANNELS.items():
            result[key] = {**ch, "embed_url": get_channel_embed_url(key)}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/narrate", methods=["POST"])
def news_narrate():
    """Body: {topic, count}  — narrate headlines via TTS."""
    data  = request.get_json(silent=True) or {}
    topic = data.get("topic", "india")
    count = int(data.get("count", 5))
    try:
        from modules.news_engine import narrate_headlines
        text = narrate_headlines(topic, count, speak_immediately=True)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/narrate/<int:index>", methods=["POST"])
def news_narrate_single(index: int):
    """Speak more detail about headline at 1-based index."""
    data  = request.get_json(silent=True) or {}
    topic = data.get("topic", "india")
    try:
        from modules.news_engine import narrate_single
        text = narrate_single(index, topic)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/settings", methods=["GET"])
def news_settings_get():
    try:
        from modules.news_engine import load_settings
        return jsonify(load_settings())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ui_bp.route("/news/settings", methods=["POST"])
def news_settings_post():
    data = request.get_json(silent=True) or {}
    try:
        from modules.news_engine import save_settings
        return jsonify(save_settings(data))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── PC Audio Stream ───────────────────────────────────────────────────────────

@ui_bp.route("/audio/info", methods=["GET"])
def audio_stream_info():
    try:
        from modules.audio_streamer import get_stream_info
        return jsonify({"ok": True, **get_stream_info()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/audio/stream", methods=["GET"])
def audio_stream():
    """
    Streams raw PCM audio from PC speakers to the Android client.
    Format: s16le, 22050Hz, mono — ready for Android AudioTrack.
    Client disconnects to stop streaming.
    """
    try:
        from modules.audio_streamer import stream_generator
        return Response(
            stream_with_context(stream_generator()),
            mimetype="application/octet-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Audio-SampleRate": "22050",
                "X-Audio-Channels": "1",
                "X-Audio-Encoding": "pcm_s16le",
            },
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/audio/stop", methods=["POST"])
def audio_stream_stop():
    try:
        from modules.audio_streamer import stop_stream
        stop_stream()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── VIP / Priority DND Contacts ───────────────────────────────────────────────

@ui_bp.route("/dnd/vip", methods=["GET"])
def dnd_vip_get():
    try:
        with open("api_keys.json") as f:
            data = _json.load(f)
        return jsonify({"ok": True, "vip": data.get("dnd_priority_contacts", [])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ui_bp.route("/dnd/vip", methods=["POST"])
def dnd_vip_post():
    """Body: {"vip": ["number_or_name", ...]} — replaces full list."""
    try:
        incoming = (request.get_json(silent=True) or {}).get("vip", [])
        if not isinstance(incoming, list):
            return jsonify({"ok": False, "error": "vip must be a list"}), 400
        with open("api_keys.json") as f:
            data = _json.load(f)
        data["dnd_priority_contacts"] = [str(v).strip() for v in incoming if v]
        with open("api_keys.json", "w") as f:
            _json.dump(data, f, indent=2)
        return jsonify({"ok": True, "vip": data["dnd_priority_contacts"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
