import re
import time
import webbrowser
import logging
import json

_vision_in_progress = False
_chain_ref = None  # set by main.py after CommandChain is instantiated; used by ws_bridge

_NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100",
}

def _normalize_numbers(cmd: str) -> str:
    """Convert spoken number words to digits so regex can parse them."""
    for word, digit in _NUM_WORDS.items():
        cmd = re.sub(r'\b' + word + r'\b', digit, cmd)
    return cmd
_vision_last_call = 0
_VISION_COOLDOWN = 5

logger = logging.getLogger(__name__)

from modules.task_engine import TaskEngine, Task
from rapidfuzz import process, fuzz
from modules.automation import open_app, play_specific_youtube
from modules.intent_router import IntentRouter
from modules.state_engine import state
import modules.vision as vision
from modules import system_control


def _last_whatsapp_message_check(cmd: str) -> bool:
    keywords = ["message", "whatsapp", "he say", "she say", "they say",
                "he sent", "she sent", "they sent", "he wrote", "she wrote",
                "what did", "what's he", "what's she", "what are they"]
    return any(k in cmd for k in keywords)

# ──────────────────────────────────────────────
# HELPER: Auto Device Alias Loader
# ──────────────────────────────────────────────

ALIAS_FILE = "device_alias.json"


def _load_device_aliases():
    try:
        with open(ALIAS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def _save_device_alias(spoken_name: str, real_device_name: str):
    """Call this AFTER a successful switch_device() to learn the alias."""
    try:
        aliases = _load_device_aliases()
        aliases[spoken_name.lower()] = real_device_name
        with open(ALIAS_FILE, "w") as f:
            json.dump(aliases, f, indent=2)
        print(f"[ALIAS LEARNED]: '{spoken_name}' → '{real_device_name}'")
    except Exception as e:
        print(f"[ALIAS ERROR]: {e}")


def _resolve_device_alias(target: str) -> str:
    """Resolve a spoken device name to real name using learned aliases."""
    aliases = _load_device_aliases()
    for alias, real in aliases.items():
        if alias in target.lower():
            print(f"[ALIAS RESOLVED]: '{target}' → '{real}'")
            return real
    return target


class CommandChain:

    def __init__(self, context_handler, scheduler_handler, ai_handler, raw_ai_handler, speak_func, orchestrator, context_manager, spotify_handler):
        self.context_handler = context_handler
        self.scheduler = scheduler_handler
        self.ai = ai_handler          # with memory — for conversations
        self._raw_ai = raw_ai_handler # without memory — for JSON parsing only
        self.speak = speak_func
        self.orchestrator = orchestrator
        self.ctx_mgr = context_manager
        self.spotify_handler = spotify_handler
        
        self.task_engine = TaskEngine(self.spotify_handler, self.speak)
        self.router = IntentRouter(self.spotify_handler, self.speak, self.ai, self.task_engine)

        self.awaiting_playlist_selection = False
        self.available_playlists = {}

        self.awaiting_platform_choice = False
        self.pending_song_request = ""

        self.awaiting_disambiguation = None  # {"action": "open"|"delete", "matches": [...], "query": str}

    def _get_crypto_price(self, coin: str) -> str:
        import requests as _req
        _COIN_IDS = {
            "bitcoin": "bitcoin", "btc": "bitcoin",
            "ethereum": "ethereum", "eth": "ethereum",
            "dogecoin": "dogecoin", "doge": "dogecoin",
            "solana": "solana", "sol": "solana",
        }
        coin_id = _COIN_IDS.get(coin.lower(), coin.lower())
        try:
            r = _req.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd,inr"},
                timeout=6
            )
            data = r.json()
            if coin_id in data:
                usd = data[coin_id].get("usd", 0)
                inr = data[coin_id].get("inr", 0)
                name = coin_id.capitalize()
                return f"{name} is ₹{inr:,.0f} rupees, that's {usd:,.0f} US dollars."
            return f"Couldn't find price for {coin}."
        except Exception as e:
            return f"Couldn't fetch crypto price right now."

    def ai_parse(self, cmd):
        if "open chrome" in cmd:
            return {"intent": "open_app", "app": "chrome", "confidence": 1.0}
        cmd_lower = cmd.lower()

        if "open" in cmd_lower:
            # Remove "open" and common filler words
            app = cmd_lower.replace("open", "").strip()
            # Remove filler words
            fillers = ["please", "can you", "could you", "would you", "just", "the"]
            for filler in fillers:
                app = app.replace(filler, "").strip()
            # Clean up multiple spaces
            app = " ".join(app.split())
            if app:
                return {"intent": "open_app", "app": app, "confidence": 1.0}
        prompt = f"""You are an AI command parser.

Convert the user command into JSON.

Command: "{cmd}"

Rules:
- intent can be: open_app, play_music, pause, resume, next, switch_device, search, whatsapp, unknown
- Extract app name if intent is open_app
- Extract song, artist, device, platform if present
- Include confidence (0 to 1)

Output format:
{{"intent":"open_app","app":"...","song":"...","artist":"...","device":"...","platform":"...","confidence":0.0}}
"""

        response = ""
        try:
            response = self._raw_ai(prompt)
            print(f"[AI RAW]: {response}")
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return {"intent": "unknown"}
            data = json.loads(json_match.group())
            print("[PARSED]:", data)
            if "intent" not in data:
                return {"intent": "unknown"}
            return data
        except Exception as e:
            print(f"[AI PARSE ERROR]: {e}")
            print(f"[AI RESPONSE WAS]: {response}")
            return {"intent": "unknown"}
    
    

    def process(self, query):
        query = query.lower().strip()
        # Strip filler words at the start
        import re as _re
        query = _re.sub(r'^(hey|please|hi|okay|ok|yo|uh|um|can you|could you|would you|izach|will you|now)[,\s]+', '', query).strip()
        # "dot txt" / "dot pdf" etc → ".txt" / ".pdf"
        query = _re.sub(r'\s*\bdot\s+([a-z0-9]{1,5})\b', r'.\1', query)
        query = _re.sub(r'\s+\.([a-z0-9]{1,5})\b', r'.\1', query)
        sub_commands = [c.strip() for c in re.split(r'\b(?:and|then)\b', query) if c.strip()]
        for cmd in sub_commands:
            resolved_cmd = self._resolve_pronouns(cmd)

            # Web automation (before system control to intercept "open X")
            _WEB_AUTOMATION_TRIGGERS = [
                "open youtube", "open google", "open github", "open gmail", "open reddit",
                "open website", "go to",
                "search on google", "google search", "look up on google",
                "fill form", "autofill", "fill the form", "fill this form", "fill these details", "fill my details", "fill this for me", "fill details",
                "feel this form", "feel these details", "feel this details", "feel the form", "feel my details",
                "extract emails", "find emails", "scrape emails",
            ]
            if any(t in resolved_cmd for t in _WEB_AUTOMATION_TRIGGERS):
                self._handle_web_automation(resolved_cmd)
                continue

            # These must be handled BEFORE AI parse
            _SYSTEM_CONTROL_TRIGGERS = [
            "volume", "mute", "unmute", "decrease volume", "lower volume", "increase volume", "raise volume", "set volume",
            "wifi", "wi-fi", "internet", "turn on wifi", "turn off wifi", "enable wifi", "disable wifi", "toggle wifi", "can you turn on wifi", "can you turn off wifi",
            "brightness", "set brightness", "brightness to", "change brightness", "lower brightness", "raise brightness",
            "dark mode", "light mode", "switch to dark mode", "switch to light mode", "can you switch to dark mode", "can you switch to light mode", "turn on dark mode", "turn on light mode", "switch to dark", "switch to light",
            "switch to dark", "switch to light",
            "set timer", "start timer", "timer for", "set a timer for", "start a timer for", "timer of", "can you set a timer for", "please set a timer for",
            "set alarm", "alarm for", "alarm at", "set an alarm for", "can you set an alarm for", "please set an alarm for", "wake me up at", "wake me at", "wake me up at",
            "wake me at", "wake me up at", "remind me to", "remind me about", "set a reminder to", "can you remind me to", "please remind me to",
            "list drives", "show drives", "connected drives", "what drives", "eject", "safely remove", "remove drive", "eject drive", "safely remove drive", "eject the device", "safely remove the device", "show connected drives", "what are my drives", "what drives do i have", "what storage devices do i have", "list storage devices", "what pendrives do i have", "eject the drive", "safely remove the drive", "eject the pendrive", "safely remove the pendrive",
            "what can you do", "your features", "your capabilities", "what do you know", "list your features", "what are you capable of", "what commands", "your functions", "what functions do you have", "introduce yourself", "help me",
            "battery", "battery percentage", "battery level", "how much battery", "battery status", "how much battery do i have", "what's my battery level", "what's my battery percentage", "how's my battery", "is my battery healthy", "what's the health of my battery", "health of my battery", "battery condition", "battery info", "how's my battery doing",
            "firewall", "firewall status", "is firewall on", "is firewall off", "check firewall", "firewall status", "is my firewall on", "is my firewall off", "check if firewall is on", "check if firewall is off",
            "windows update", "pending updates", "any updates", "check for updates", "update status", "are there any updates", "do i have updates", "check if there are updates", "check if i have updates", "update status", "what's the update status", "are updates pending", "are there updates pending", 
            "wifi signal", "signal strength", "wifi strength", "how strong is wifi", "network strength",
            "network devices", "who's on my network", "connected devices", "who is on my network", "devices on network",
            "battery health", "battery wear", "cpu temperature", "cpu temp", "ram usage", "memory usage",
            ]
            _FILE_FAST_PATH = [
                "open file", "open my file", "open the file",
                "open assignment", "open notes", "open syllabus", "open homework", "open report", "open lecture",
                "list files", "show files", "what files", "list folder", "show folder",
                "create folder", "make folder", "new folder",
                "find file", "search file", "find my", "search for file",
                "read file", "read the file", "read my file",
                "latest file", "newest file", "most recent file", "find latest",
                "delete file", "delete the file", "remove file", "delete my file",
                "go up", "navigate up", "back folder", "parent folder",
                "where am i", "current folder", "current directory",
                "show file log", "file actions", "file manager status", "file permission",
                "clean my", "clean the", "organize my", "organize the", "clean and", "rearrange",
                "sort my", "sort the", "sort downloads", "sort documents", "sort desktop",
                "rename file", "rename the", "rename my",
                "move file", "move the file", "move my file",
                "copy file", "copy the file", "copy my file",
                "how many files", "folder stats", "folder size", "how much space",
            ]
            if "playlist" in resolved_cmd or resolved_cmd.startswith("open ") or any(t in resolved_cmd for t in _SYSTEM_CONTROL_TRIGGERS) or any(m in resolved_cmd for m in _FILE_FAST_PATH + ["what am i holding", "what's in my hand", "what do you see", "look at this", "what is this", "identify this", "what's this", "how many calories", "what food is this", "scan this", "describe what you see", "what can you see", "look at camera", "work mode", "focus mode", "gym mode", "idle mode", "switch to work", "switch to focus", "switch to gym", "switch to idle", "click on", "click the", "read the screen", "what's on screen", "read screen", "remember that", "remember this", "what do you remember", "forget that", "reply to", "reply her", "reply him", "what did he say", "what did she say", "bitcoin", "ethereum", "crypto", "btc price", "eth price", "dogecoin", "solana", "crypto rate", "enroll my face", "register my face", "add my face", "save my face"]):
                self._classify_and_execute(resolved_cmd)
                continue

            task = self._classify_and_convert_to_task(resolved_cmd)

            if task is True:  # confidence gate blocked — already spoke, skip execute
                continue
            if task:
                self.task_engine.add_task(task)
            else:
                self._classify_and_execute(resolved_cmd)

        self.task_engine.run()

    def _clean_playlist_query(self, query):
        keywords = ["play", "my", "playlist", "on", "spotify", "in", "youtube"]
        pattern = re.compile(r'\b(' + '|'.join(keywords) + r')\b', re.IGNORECASE)
        clean = pattern.sub('', query).strip()
        return clean

    def _resolve_pronouns(self, query):
        resolved = query

        if " it" in query or query.endswith("it"):
            # ctx_mgr: last opened app (has 3-min validity window)
            if self.ctx_mgr.is_context_valid():
                app_ctx = self.ctx_mgr.get_context("last_app_opened")
                if app_ctx:
                    resolved = resolved.replace("it", app_ctx)
                    return resolved

            # context_memory: last adjustable control (no timeout)
            from modules.context_memory import get_context_memory
            action = get_context_memory().get_entity("last_control_action")
            if action:
                _lower_verbs = ["lower", "decrease", "turn down", "reduce"]
                _raise_verbs = ["raise", "increase", "turn up", "boost"]
                q = query.lower()
                if any(v in q for v in _lower_verbs):
                    resolved = f"decrease {action}"
                elif any(v in q for v in _raise_verbs):
                    resolved = f"increase {action}"

        if " that" in query or query.endswith("that"):
            if self.ctx_mgr.is_context_valid():
                last_search = self.ctx_mgr.get_context("last_search_query")
                if last_search:
                    resolved = resolved.replace("that", last_search)

        return resolved

    def _handle_web_automation(self, cmd):
        import threading
        from modules import web_automation

        if any(t in cmd for t in ["search on google", "google search", "look up on google"]):
            query = cmd
            for t in ["search on google", "look up on google", "google search"]:
                query = query.replace(t, "").strip()
            if not query:
                self.speak("What should I search for?")
                return
            self.speak(f"Searching for {query}.")
            def _do_search(q=query):
                ok, msg = web_automation.search_google(q)
                if not ok:
                    self.speak(msg)
            threading.Thread(target=_do_search, daemon=True).start()
            return

        if any(t in cmd for t in ["open youtube", "open google", "open github", "open gmail", "open reddit", "open website", "go to"]):
            target = cmd
            for phrase in sorted(["go to", "open website", "open youtube", "open google",
                                   "open github", "open gmail", "open reddit", "open"], key=len, reverse=True):
                target = target.replace(phrase, "").strip()
            if not target:
                for name in web_automation._SHORTNAMES:
                    if name in cmd:
                        target = name
                        break
            if not target:
                self.speak("Which website?")
                return
            self.speak(f"Opening {target}.")
            def _do_open(t=target):
                ok, msg = web_automation.open_website(t)
                if not ok:
                    self.speak(msg)
            threading.Thread(target=_do_open, daemon=True).start()
            return

        if any(t in cmd for t in ["fill form", "autofill", "fill the form", "fill this form", "fill these details", "fill my details", "fill this for me", "fill details",
                                  "feel this form", "feel these details", "feel this details", "feel the form", "feel my details"]):
            from modules.ws_bridge import broadcast, has_extension_client
            from modules.memory import load_memory
            try:
                raw = load_memory()
                if not raw:
                    self.speak("No details saved in memory. Add them from iZACH settings first.")
                    return
                if not has_extension_client():
                    self.speak("Chrome extension not connected. Open the form page and reload the extension, then try again.")
                    return
                profile = {k: (v["value"] if isinstance(v, dict) else str(v)) for k, v in raw.items()}
                broadcast({"type": "fill_form", "data": profile})
                self.speak("Filling form. I'll tell you how many fields I got.")
            except Exception as e:
                self.speak(f"Could not fill form: {e}")
            return

        if any(t in cmd for t in ["extract emails", "find emails", "scrape emails"]):
            self.speak("Scanning page for emails.")
            def _do_email():
                _, msg = web_automation.extract_emails()
                self.speak(msg)
            threading.Thread(target=_do_email, daemon=True).start()
            return

    def _resolve_disambiguation(self, cmd: str) -> bool:
        """Handle user response after iZACH asked 'which one?'. Returns True if handled."""
        if not self.awaiting_disambiguation:
            return False
        import os as _os
        matches  = self.awaiting_disambiguation["matches"]
        action   = self.awaiting_disambiguation["action"]
        query    = self.awaiting_disambiguation.get("query", "")
        self.awaiting_disambiguation = None

        # User said first/second/third or a number
        _ORD = {"first": 0, "second": 1, "third": 2, "1": 0, "2": 1, "3": 2,
                "one": 0, "two": 1, "three": 2}
        for word, idx in _ORD.items():
            if word in cmd and idx < len(matches):
                chosen = matches[idx]
                break
        else:
            # Try fuzzy name match
            cmd_lower = cmd.lower()
            chosen = None
            for m in matches:
                if _os.path.basename(m).lower().replace("_", " ").replace("-", " ") in cmd_lower:
                    chosen = m
                    break
            if not chosen:
                self.speak("Couldn't match your choice. Please try again.")
                return True

        fname = _os.path.basename(chosen)
        if action == "open":
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            ok, msg = fm.handle_by_type(chosen)
            self.speak(f"Opening {fname}." if ok else f"Couldn't open {fname}: {msg}")
        elif action == "delete":
            # Re-run face auth for deletion on chosen file
            self._delete_with_face_auth(chosen)
        return True

    def _delete_with_face_auth(self, path: str):
        import os as _os
        from modules.file_manager import get_file_manager
        from modules.vision_engine import get_vision_engine
        fm = get_file_manager()
        fm.set_speak(self.speak)
        ve = get_vision_engine()
        if ve is None:
            self.speak("Camera offline. Delete blocked.")
            return
        encodings, _ = ve._face_db.get_all_encodings()
        if not encodings:
            self.speak("No face enrolled. Say 'enroll my face' first.")
            return
        try:
            from modules.ws_bridge import broadcast as _bcast
            _bcast({"type": "face_verify", "state": "scanning"})
        except Exception:
            pass
        self.speak("Admin level authentication required. Stare at the camera for face verification.")
        time.sleep(3)
        verified = ve.verify_face("vansh")
        try:
            from modules.ws_bridge import broadcast as _bcast
            _bcast({"type": "face_verify", "state": "success" if verified else "failed"})
        except Exception:
            pass
        if not verified:
            self.speak("Not matched. Delete blocked.")
            return
        self.speak("Identity confirmed.")
        ok, msg = fm.delete_verified(path)
        self.speak(msg)

    def _handle_file_command(self, cmd: str) -> bool:
        """
        Handle all file manager commands. Returns True if handled, False to fall through.
        Called BEFORE ai_parse to prevent AI fallback from hijacking file commands.
        """
        import os as _os
        import re as _re
        from modules.file_manager import get_file_manager

        fm = get_file_manager()
        fm.set_speak(self.speak)

        _FOLDER_MAP = {
            "desktop":    _os.path.join(_os.path.expanduser("~"), "Desktop"),
            "documents":  _os.path.join(_os.path.expanduser("~"), "Documents"),
            "downloads":  _os.path.join(_os.path.expanduser("~"), "Downloads"),
            "pictures":   _os.path.join(_os.path.expanduser("~"), "Pictures"),
            "music":      _os.path.join(_os.path.expanduser("~"), "Music"),
            "videos":     _os.path.join(_os.path.expanduser("~"), "Videos"),
            "wallpapers": _os.path.join(_os.path.expanduser("~"), "Pictures", "Wallpapers"),
            "onedrive":   _os.path.join(_os.path.expanduser("~"), "OneDrive"),
        }

        # ── CLEAN / ORGANIZE FOLDER ──
        if any(w in cmd for w in ["clean my", "clean the", "organize my", "organize the",
                                   "clean and rearrange", "rearrange"]):
            folder_path = None
            for fname, fpath in _FOLDER_MAP.items():
                if fname in cmd:
                    folder_path = fpath
                    break
            if not folder_path:
                self.speak("Which folder should I organize? Downloads, Desktop, Documents, Pictures, Music, or Videos?")
                return True
            if any(w in cmd for w in ["alphabetically", "by name", "a to z", "sort alphabetically"]):
                ok, msg, items = fm.sort_folder(folder_path, "name")
                if ok:
                    preview = ", ".join(items[:8])
                    self.speak(f"Files in {_os.path.basename(folder_path)} sorted alphabetically. First eight: {preview}{'...' if len(items) > 8 else '.'}")
                else:
                    self.speak(msg)
            else:
                ok, msg = fm.organize_by_type(folder_path)
                self.speak(msg)
            return True

        # ── SORT FOLDER ──
        if any(w in cmd for w in ["sort my", "sort the", "sort downloads", "sort documents",
                                   "sort desktop", "sort pictures", "sort videos"]):
            folder_path = None
            for fname, fpath in _FOLDER_MAP.items():
                if fname in cmd:
                    folder_path = fpath
                    break
            if not folder_path:
                folder_path = fm.current_dir
            sort_by = "name"
            if any(w in cmd for w in ["by date", "date modified", "newest first", "oldest first"]):
                sort_by = "date"
            elif "by size" in cmd or "size" in cmd:
                sort_by = "size"
            elif "by type" in cmd or "by kind" in cmd:
                sort_by = "type"
            ok, msg, items = fm.sort_folder(folder_path, sort_by)
            if ok:
                preview = ", ".join(items[:10])
                self.speak(f"{msg} {preview}{'...' if len(items) > 10 else ''}")
            else:
                self.speak(msg)
            return True

        # ── FOLDER STATS ──
        if any(w in cmd for w in ["how many files", "folder stats", "folder size",
                                   "how much space", "how large is", "folder info"]):
            folder_path = None
            for fname, fpath in _FOLDER_MAP.items():
                if fname in cmd:
                    folder_path = fpath
                    break
            ok, msg = fm.folder_stats(folder_path)
            self.speak(msg)
            return True

        # ── RENAME FILE ──
        if any(w in cmd for w in ["rename file", "rename the", "rename my"]):
            m = _re.search(r'rename\s+(?:file\s+|the\s+|my\s+)?(.+?)\s+(?:to|as)\s+(.+)', cmd)
            if not m:
                self.speak("How should I rename it? Say: rename old name to new name.")
                return True
            old_q, new_name = m.group(1).strip(), m.group(2).strip()
            results = fm.smart_find(old_q, ai_func=self.ai)
            if not results:
                self.speak(f"No file named {old_q} found.")
                return True
            ok, msg = fm.rename_file(results[0], new_name)
            self.speak(msg)
            return True

        # ── MOVE FILE ──
        if any(w in cmd for w in ["move file", "move the file", "move my file", "move it to"]):
            m = _re.search(r'move\s+(?:file\s+|the\s+|my\s+|it\s+)?(.+?)\s+to\s+(\w+)', cmd)
            if not m:
                self.speak("Tell me what to move and where. Say: move filename to folder name.")
                return True
            file_q = m.group(1).strip()
            dest_key = m.group(2).strip().lower()
            dest_folder = _FOLDER_MAP.get(dest_key)
            if not dest_folder:
                self.speak(f"I don't know where {dest_key} is. Try Desktop, Downloads, or Documents.")
                return True
            results = fm.smart_find(file_q, ai_func=self.ai)
            if not results:
                self.speak(f"No file named {file_q} found.")
                return True
            ok, msg = fm.move_file(results[0], dest_folder)
            self.speak(msg)
            return True

        # ── COPY FILE ──
        if any(w in cmd for w in ["copy file", "copy the file", "copy my file", "copy it to"]):
            m = _re.search(r'copy\s+(?:file\s+|the\s+|my\s+|it\s+)?(.+?)\s+to\s+(\w+)', cmd)
            if not m:
                self.speak("Tell me what to copy and where.")
                return True
            file_q = m.group(1).strip()
            dest_key = m.group(2).strip().lower()
            dest_folder = _FOLDER_MAP.get(dest_key)
            if not dest_folder:
                self.speak(f"I don't know where {dest_key} is.")
                return True
            results = fm.smart_find(file_q, ai_func=self.ai)
            if not results:
                self.speak(f"No file named {file_q} found.")
                return True
            ok, msg = fm.copy_file(results[0], dest_folder)
            self.speak(msg)
            return True

        # ── OPEN FILE (with smart subject disambiguation) ──
        _FILE_SUBJECT_HINTS = ["assignment", "notes", "note", "syllabus", "report",
                                "project", "homework", "lecture", "slides"]
        _FILE_OPEN_EXPLICIT = any(w in cmd for w in ["open file", "open my file", "open the file"])
        _FILE_OPEN_SUBJECT  = "open" in cmd and any(h in cmd for h in _FILE_SUBJECT_HINTS)

        if _FILE_OPEN_EXPLICIT or _FILE_OPEN_SUBJECT:
            from modules.response_generator import instant
            name = cmd
            for w in ["open my file", "open the file", "open file", "open"]:
                name = name.replace(w, "").strip()
            instant("open_file")
            results = fm.smart_find(name, ai_func=self.ai)
            if not results:
                # Try find_file as fallback (exact substring)
                results = fm.find_file(name)
            if results:
                if len(results) > 1:
                    self.awaiting_disambiguation = {"action": "open", "matches": results, "query": name}
                    short_names = [_os.path.basename(r) for r in results[:4]]
                    options_list = []
                    for i, n in enumerate(short_names):
                        clean = n
                        for h in _FILE_SUBJECT_HINTS:
                            clean = _re.sub(r'\b' + h + r's?\b', '', clean, flags=_re.IGNORECASE)
                        clean = _re.sub(r'\.[^.]+$', '', clean).strip(" -_.")
                        options_list.append(f"{i+1}. {clean if clean else n}")
                    hint_word = next((h for h in _FILE_SUBJECT_HINTS if h in cmd), "file")
                    self.speak(f"Which {hint_word}? {', '.join(options_list)}")
                    return True
                fname = _os.path.basename(results[0])
                ok, msg = fm.handle_by_type(results[0])
                self.speak(f"Opening {fname}." if ok else f"Couldn't open {fname}: {msg}")
            else:
                # No file found — only return True (blocking app-open) for explicit subject hints
                if _FILE_OPEN_SUBJECT:
                    self.speak(f"No {name} file found.")
                    return True
                # Let "open chrome" etc. fall through
                return False
            return True

        # ── LIST FILES ──
        if any(w in cmd for w in ["list files", "show files", "what files", "list folder", "show folder"]):
            ok, msg, items = fm.list_folder()
            if ok:
                self.speak(msg)
                if items:
                    self.speak(f"Contents: {', '.join(items[:6])}")
            else:
                self.speak(msg)
            return True

        # ── CREATE FOLDER ──
        if any(w in cmd for w in ["create folder", "make folder", "new folder", "create new folder"]):
            name = cmd
            for w in ["create new folder", "create folder", "make folder", "new folder", "called", "named"]:
                name = name.replace(w, "").strip()
            path = _os.path.join(fm.current_dir, name)
            ok, msg = fm.create_folder(path)
            self.speak(msg)
            return True

        # ── NAVIGATE ──
        if any(w in cmd for w in ["go up", "navigate up", "back folder", "parent folder"]):
            ok, msg = fm.navigate("up")
            self.speak(msg)
            return True

        if any(w in cmd for w in ["where am i", "current folder", "current directory", "which folder"]):
            self.speak(f"You are in {fm.where_am_i()}")
            return True

        # ── FIND FILE ──
        if any(w in cmd for w in ["find file", "search file", "find my", "search for file"]):
            name = cmd
            for w in ["search for file", "find file", "search file", "find my", "find", "search"]:
                name = name.replace(w, "").strip()
            results = fm.find_file(name)
            if results:
                self.speak(f"Found {len(results)} file{'s' if len(results) > 1 else ''}. First match: {results[0]}")
            else:
                self.speak(f"No files found matching {name}.")
            return True

        # ── LATEST FILE ──
        if any(w in cmd for w in ["latest file", "newest file", "most recent file", "find latest"]):
            ext = None
            for e in ["pdf", "txt", "py", "docx", "xlsx", "mp3", "mp4"]:
                if e in cmd:
                    ext = e
                    break
            result = fm.get_latest_file(file_type=ext)
            if result:
                self.speak(f"Latest file is {_os.path.basename(result)}")
            else:
                self.speak("No files found in the current folder.")
            return True

        # ── READ FILE ──
        if any(w in cmd for w in ["read file", "read the file", "read my file"]):
            name = cmd
            for w in ["read the file", "read my file", "read file", "read"]:
                name = name.replace(w, "").strip()
            results = fm.find_file(name)
            if results:
                ok, content = fm.read_text_file(results[0])
                self.speak(content[:300] if ok else content)
            else:
                self.speak(f"No file named {name} found.")
            return True

        # ── DELETE FILE ──
        _DEL_EXPLICIT = any(w in cmd for w in ["delete file", "delete the file", "remove file", "delete my file"])
        _DEL_BARE = cmd.startswith("delete ") or cmd.startswith("remove ")
        _NON_FILE_WORDS = ["memory", "reminder", "alarm", "timer", "history", "log", "account"]
        if _DEL_EXPLICIT or (_DEL_BARE and not any(w in cmd for w in _NON_FILE_WORDS)):
            name = cmd
            for w in ["delete the file", "delete my file", "delete file", "remove file", "delete", "remove"]:
                name = name.replace(w, "").strip()

            search_dir = None
            loc_m = _re.search(r'\bfrom\s+(desktop|documents|downloads|pictures|music|videos)\b', name)
            if loc_m:
                search_dir = _FOLDER_MAP.get(loc_m.group(1))
                name = name[:loc_m.start()].strip()

            results = []
            if search_dir and name:
                direct = _os.path.join(search_dir, name)
                if _os.path.exists(direct):
                    results = [direct]
            if not results:
                orig_dir = fm.current_dir
                if search_dir:
                    fm.current_dir = search_dir
                results = fm.smart_find(name, ai_func=self.ai)
                if not results:
                    results = fm.find_file(name, search_dir=search_dir)
                if search_dir:
                    fm.current_dir = orig_dir

            if not results:
                if _DEL_EXPLICIT:
                    self.speak(f"No file found matching {name}.")
                    return True
                return False  # bare "delete X" with no file found — fall through

            if len(results) > 1:
                self.awaiting_disambiguation = {"action": "delete", "matches": results, "query": name}
                short_names = [_os.path.basename(r) for r in results[:4]]
                options = ", ".join(f"{i+1}. {n}" for i, n in enumerate(short_names))
                self.speak(f"Found {len(results)} matches. Which one to delete? {options}")
                return True

            self.speak(f"Found {_os.path.basename(results[0])}. Deleting it permanently.")
            self._delete_with_face_auth(results[0])
            return True

        # ── FILE LOG / STATUS ──
        if any(w in cmd for w in ["show file log", "file actions", "recent file actions"]):
            actions = fm.get_recent_actions(5)
            if actions:
                self.speak(f"Last {len(actions)} file actions:")
                for a in actions:
                    parts = a.split("|")
                    if len(parts) >= 3:
                        self.speak(f"{parts[1].strip()} — {parts[2].strip()}")
            else:
                self.speak("No file actions logged yet.")
            return True

        if any(w in cmd for w in ["file manager status", "file permission", "what permission"]):
            s = fm.get_status()
            self.speak(f"Permission level is {s['permission']}. Sandbox is {'on' if s['sandbox'] else 'off'}. Current folder is {s['current_dir']}.")
            return True

        return False

    def _classify_and_execute(self, cmd):
        cmd = cmd.lower().strip()
        from modules.response_generator import instant, smart

        # ── DISAMBIGUATION — must be checked before everything else ──
        if self._resolve_disambiguation(cmd):
            return

        # ── CAMERA VISION — must be FIRST before ai_parse burns keys ──
        vision_triggers = [
            "what am i holding", "what's in my hand", "what do you see",
            "look at this", "what is this", "identify this", "what's this",
            "how many calories", "what food is this", "scan this",
            "describe what you see", "what can you see", "look at camera",
            "see this", "analyze this", "what's around me", "what's in front of you",
            "what's in the room", "what's on the table", "what's on the floor",
            "what's on the desk", "what's on the counter", "what's on the bed",
            "what's on the chair", "what's on the couch", "what's on the shelf",
            "look around", "what's nearby", "what's in the vicinity", "what's in the area",
            "can you see anything", "do you see anything", "what's in your view", "what's in your sight",
            "can you identify this", "what's in this picture", "analyze the camera", "describe the camera view",
            "how's the view", "what's in the frame", "what's in front of you", "what's around you",
            "rate this food", "calorie estimate", "how many calories", "what food is this",
            "what drink is this", "identify the food", "identify the drink",
            "brand of this", "what brand is this", "what object is this", "what item is this",
            "see if this is", "is this a", "is this an", "what type of", "what kind of", "describe the scene"
        ]
        if any(t in cmd for t in vision_triggers):
            global _vision_in_progress, _vision_last_call
            now = time.time()
            if _vision_in_progress or (now - _vision_last_call < _VISION_COOLDOWN):
                self.speak("Vision is busy, try again in a moment.")
                return
            _vision_in_progress = True
            _vision_last_call = now
            print("VISION TRIGGERED ONCE")
            try:
                from modules.camera_vision import capture_and_ask
                answer = capture_and_ask(cmd)
                self.speak(answer)
            finally:
                _vision_in_progress = False
            return

        # Time and date — fast local answers
        from modules.automation import get_current_time, get_current_date
        if any(w in cmd for w in ["what time", "current time", "time now", "kitne baje"]):
            self.speak(get_current_time())
            return
        if any(w in cmd for w in ["what date", "today's date", "current date", "aaj kya date"]):
            self.speak(get_current_date())
            return

        # Playlist must be handled before AI parse
        if "playlist" in cmd:
            clean_name = self._clean_playlist_query(cmd)
            self.available_playlists = self.spotify_handler.get_playlist_map()
            uri, actual_name = self.spotify_handler.find_best_playlist(clean_name, self.available_playlists)
            if uri:
                self.speak(f"Playing {actual_name}.")
                self.spotify_handler.play_specific_playlist_uri(uri)
            else:
                self.speak(f"I couldn't find a playlist matching {clean_name}.")
            return
        
        # ---------------- CAPABILITIES ----------------
        if any(w in cmd for w in ["what can you do", "your features", "your capabilities", "what do you know", "list your features", "what are you capable of", "help me", "what commands"]):
            self.speak(
                "Here's what I can do. "
                "System control: set volume, mute, unmute, adjust brightness, toggle WiFi, switch dark or light mode, set a timer, set an alarm. "
                "System status: check battery, firewall status, and Windows update status. "
                "Network: check WiFi signal strength, list devices currently on your network. "
                "Device awareness: I announce when Bluetooth devices or USB drives connect or disconnect. I can also list drives and eject them by name or letter. "
                "Music: play, pause, resume, skip, go back, switch Spotify device, play playlists. "
                "Apps: open any app by name. "
                "Vision: identify objects, estimate calories, read the screen, click on screen elements. "
                "Memory: remember facts, recall them later. "
                "Modes: switch between work, focus, gym, and idle mode. "
                "Real-time info: weather, news, and general questions. "
                "File management: open, find, delete files with face auth. Clean and organize folders by type. Sort by name, date, or size. Rename, move, copy files. Smart open — say open assignment and I ask which subject. "
                "Communication: read and reply to WhatsApp messages."
            )
            return

        if any(w in cmd for w in ["battery health", "battery wear"]):
            _, msg = system_control.get_battery_health()
            self.speak(msg)
            return

        if any(w in cmd for w in ["cpu temperature", "cpu temp"]):
            _, msg = system_control.get_cpu_temperature()
            self.speak(msg)
            return

        if any(w in cmd for w in ["ram usage", "memory usage"]):
            _, msg = system_control.get_ram_usage()
            self.speak(msg)
            return

        # real-time data check — runs before AI parse
        from modules.realtime_data import handle_realtime_query
        realtime_result = handle_realtime_query(cmd)
        if realtime_result:
            self.speak(realtime_result)
            return

        # ---------------- SYSTEM CONTROL ----------------

        if any(w in cmd for w in ["wifi on", "turn on wifi", "enable wifi", "wifi off", "turn off wifi", "disable wifi", "toggle wifi"]):
            if "off" in cmd or "disable" in cmd:
                _, msg = system_control.set_wifi(False)
            elif "on" in cmd or "enable" in cmd:
                _, msg = system_control.set_wifi(True)
            else:
                _, msg = system_control.toggle_wifi()
            self.speak(msg)
            return

        if "unmute" in cmd:
            _, msg = system_control.unmute()
            self.speak(msg)
            return

        if any(w in cmd for w in ["mute volume", "mute it", "silence", "go mute", "mute"]):
            _, msg = system_control.mute()
            self.speak(msg)
            return

        if any(w in cmd for w in ["decrease volume", "lower volume", "turn down volume", "reduce volume"]):
            _, msg = system_control.adjust_volume(-10)
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "volume")
            return

        if any(w in cmd for w in ["increase volume", "raise volume", "turn up volume", "boost volume"]):
            _, msg = system_control.adjust_volume(10)
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "volume")
            return

        if any(w in cmd for w in ["set volume", "volume to", "volume at", "turn volume", "change volume"]):
            match = re.search(r'\b(\d{1,3})\b', _normalize_numbers(cmd))
            if match:
                _, msg = system_control.set_volume(int(match.group(1)))
            else:
                msg = "Please specify a volume level between 0 and 100."
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "volume")
            return

        if any(w in cmd for w in ["lower brightness", "decrease brightness", "reduce brightness", "turn down brightness"]):
            _, msg = system_control.adjust_brightness(-10)
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "brightness")
            return

        if any(w in cmd for w in ["raise brightness", "increase brightness", "boost brightness", "turn up brightness"]):
            _, msg = system_control.adjust_brightness(10)
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "brightness")
            return

        if any(w in cmd for w in ["set brightness", "brightness to", "brightness at", "change brightness"]):
            match = re.search(r'\b(\d{1,3})\b', _normalize_numbers(cmd))
            if match:
                _, msg = system_control.set_brightness(int(match.group(1)))
            else:
                msg = "Please specify a brightness level between 0 and 100."
            self.speak(msg)
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_control_action", "brightness")
            return

        if any(w in cmd for w in ["dark mode", "light mode", "switch to dark", "switch to light"]):
            mode = "dark" if "dark" in cmd else "light"
            _, msg = system_control.set_theme(mode)
            self.speak(msg)
            return

        if any(w in cmd for w in ["set timer", "start timer", "timer for"]):
            def _notify(m): self.speak(m)
            seconds = 0
            _nc = _normalize_numbers(cmd)
            m = re.search(r'(\d+)\s*hour', _nc)
            if m: seconds += int(m.group(1)) * 3600
            m = re.search(r'(\d+)\s*min', _nc)
            if m: seconds += int(m.group(1)) * 60
            m = re.search(r'(\d+)\s*sec', _nc)
            if m: seconds += int(m.group(1))
            _, msg = system_control.set_timer(seconds, _notify)
            self.speak(msg)
            return

        if any(w in cmd for w in ["set alarm", "alarm for", "alarm at", "wake me at", "wake me up at"]):
            def _notify(m): self.speak(m)
            hour, minute = None, None
            m = re.search(r'(\d{1,2}):(\d{2})', cmd)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
            else:
                m = re.search(r'(\d{1,2})\s*(am|pm)', cmd)
                if m:
                    hour = int(m.group(1))
                    if m.group(2) == "pm" and hour != 12:
                        hour += 12
                    if m.group(2) == "am" and hour == 12:
                        hour = 0
                    minute = 0
            if hour is not None:
                _, msg = system_control.set_alarm(hour, minute, _notify)
            else:
                msg = "Please specify a time for the alarm, like 7:30 AM."
            self.speak(msg)
            return

        if any(w in cmd for w in ["list drives", "show drives", "connected drives", "what drives"]):
            _, msg = system_control.list_drives()
            self.speak(msg)
            return

        if any(w in cmd for w in ["eject", "safely remove", "remove drive"]):
            identifier = cmd
            for phrase in ["safely remove", "remove drive", "eject drive", "eject the", "eject"]:
                identifier = identifier.replace(phrase, "").strip()
            for filler in ["pendrive", "pen drive", "usb drive", "usb", "the drive", "the", "drive"]:
                identifier = identifier.replace(filler, "").strip()
            identifier = identifier.strip()
            if not identifier:
                msg = "Please specify a drive name or letter, like 'eject Sandisk' or 'eject D'."
            else:
                _, msg = system_control.eject_drive(identifier)
            self.speak(msg)
            return

        if any(w in cmd for w in ["battery", "battery percentage", "battery level", "how much battery", "battery status"]):
            _, msg = system_control.get_battery()
            self.speak(msg)
            return

        if any(w in cmd for w in ["firewall", "firewall status", "is firewall on", "is firewall off", "check firewall"]):
            _, msg = system_control.get_firewall_status()
            self.speak(msg)
            return

        if any(w in cmd for w in ["windows update", "pending updates", "any updates", "update status"]):
            _, msg = system_control.get_update_status()
            self.speak(msg)
            return

        if any(w in cmd for w in ["wifi signal", "signal strength", "wifi strength", "how strong is wifi", "network strength"]):
            _, msg = system_control.get_wifi_signal()
            self.speak(msg)
            return

        if any(w in cmd for w in ["network devices", "who's on my network", "connected devices", "who is on my network", "devices on network"]):
            _, msg = system_control.get_network_devices()
            self.speak(msg)
            return

        # ── FILE MANAGER — handled before AI parse to prevent AI fallback hijack ──
        if self._handle_file_command(cmd):
            return

        # 🧠 LOAD MEMORY (FIXED)
        user_music = None
        last_person = None

        try:
            from modules.mongo_brain import get_preference, retrieve_context

            user_music = get_preference("music")
            # last_person = retrieve_context("last_person")

            print(f"[MEMORY] music={user_music}, last_person={last_person}")
        except Exception as e:
            print("[ERROR]", e)

        parsed = self.ai_parse(cmd)

        if parsed.get("intent") != "unknown" and parsed.get("confidence", 1.0) < 0.7:
            _conf = parsed.get("confidence", 1.0)
            if _conf < 0.4:
                self.speak("Say that again?")
            else:
                _clarify = {
                    "play_music": "Play what? Give me a song or artist.",
                    "open_app": "Open what app?",
                    "switch_device": "Switch to which device?",
                    "search": "Search for what?",
                }
                self.speak(_clarify.get(parsed.get("intent"), "Say that again?"))
            return

        # 🧠 MEMORY-DRIVEN MODIFICATION
        if parsed.get("intent") == "play_music" and not parsed.get("platform"):
            if user_music:
                parsed["platform"] = user_music if isinstance(user_music, str) else "spotify"

        # Route known intents, skip unknown ones to fallback AI
        result = self.router.route(parsed)

        # 🧠 STORE CONTEXT (AFTER EXECUTION)
        try:
            from modules.mongo_brain import store_context

            if parsed.get("intent") == "open_app":
                store_context("last_app", parsed.get("app"))

            if parsed.get("intent") == "play_music":
                store_context("last_song", parsed.get("song"))
        except Exception as e:
            print("[ERROR]", e)      

        # 🧠 AUTO-LEARN PREFERENCES
        try:
            from modules.mongo_brain import store_preference

            if parsed.get("intent") == "play_music" and parsed.get("platform"):
                store_preference("music", parsed.get("platform"))

            if parsed.get("intent") == "open_app":
                store_preference("apps", parsed.get("app"))
        except Exception as e:
            print("[ERROR]", e)

        

        if result:
            if not isinstance(result, str):
                result = "Done." if result is True else "Something went wrong."

            # 🧠 SAVE INSIGHT
            try:
                from modules.obsidian_brain import log_smart_insight
                log_smart_insight(parsed.get("intent"), cmd, result)
            except Exception as e:
                print("[ERROR]", e)

            self.speak(result)
            
            # 🧠 LOG TO MONGO
            try:
                from modules.mongo_brain import log_important_command
                log_important_command(cmd, result, parsed.get("intent", ""))
            except Exception as e:
                print("[MONGO ERROR]", e)
            
            return

        cmd = cmd.lower().strip()

        # ---------------- DEVICE COMMANDS ----------------
        device_commands = [
            "show devices", "show all devices", "list all devices",
            "devices list", "my devices", "list the devices",
            "spotify devices"
        ]

        if any(p in cmd for p in device_commands):
            status = self.spotify_handler.list_devices()
            self.speak(status)
            return

        # ---------------- CANCEL ----------------
        if cmd in ["cancel", "nevermind", "stop", "forget it"]:
            self.awaiting_playlist_selection = False
            self.awaiting_platform_choice = False
            self.available_playlists = {}
            self.pending_song_request = ""
            self.speak("Request cancelled.")
            return

        # ---------------- CURRENT SONG ----------------
        if any(w in cmd for w in [
            "what song is playing",
            "what's playing",
            "what's this song",
            "name of this song"
        ]):
            status = self.spotify_handler.get_current_track()
            self.speak(status)
            return

        # ---- CONTEXT-AWARE MUSIC COMMANDS (Build 8.0) ----
        context_keywords = ["similar songs", "play similar", "queue this", "play next"]

        if any(kw in cmd for kw in context_keywords):
            ctx = self.spotify_handler.get_music_context()
            last_track = ctx.get("track")
            last_artist = ctx.get("artist")

            query = None
            for kw in context_keywords:
                if cmd.strip() == kw:
                    query = f"{last_track} {last_artist}" if last_track else None
                    break

            if not query and cmd.strip() in context_keywords and not last_track:
                self.speak("I don't know which song you're referring to. Try playing a song first.")
                return

            if any(w in cmd for w in ["similar songs", "play similar"]):
                search_query = query if query else cmd.replace("play similar songs", "").replace("similar songs", "").strip()
                status = self.spotify_handler.play_similar_tracks(search_query)
                self.speak(status)
                return

            if "queue this" in cmd or "play next" in cmd:
                if not last_track:
                    self.speak("There is no song in my memory to queue.")
                    return
                results = self.spotify_handler.sp.search(q=f"{last_track} {last_artist}", limit=1, type='track')
                items = results.get('tracks', {}).get('items', [])
                if items:
                    uri = items[0]['uri']
                    self.spotify_handler.sp.add_to_queue(uri)
                    self.speak(f"Added {last_track} to your queue.")
                else:
                    self.speak("I couldn't find that song in the Spotify catalog.")
                return

        # ---------------- RADIO / SIMILAR ----------------
        radio_keywords = ["similar to", "songs like", "radio for"]

        if any(kw in cmd for kw in radio_keywords):
            clean_query = cmd
            strip_patterns = [
                r"play\s+songs?\s+like",
                r"play\s+similar\s+songs?\s+to",
                r"similar\s+to",
                r"songs?\s+like",
                r"radio\s+for",
                r"on\s+spotify",
                r"in\s+spotify"
            ]
            for pattern in strip_patterns:
                clean_query = re.sub(pattern, "", clean_query).strip()

            if clean_query:
                status = self.spotify_handler.play_similar_tracks(clean_query)
                self.speak(status)
            else:
                self.speak("Tell me which song to base it on.")
            return

        # ---------------- QUEUE ----------------
        if any(w in cmd for w in ["queue", "add to queue", "play next"]):
            song_query = re.sub(r"(queue|add|to|next|play)", "", cmd).strip()
            if song_query:
                results = self.spotify_handler.sp.search(q=song_query, limit=1, type='track')
                tracks = results.get('tracks', {}).get('items', [])
                if tracks:
                    uri = tracks[0]['uri']
                    name = tracks[0]['name']
                    self.spotify_handler.sp.add_to_queue(uri)
                    self.speak(f"Added {name} to queue.")
                else:
                    self.speak("Song not found.")
            return

        # ---------------- PLATFORM CHOICE ----------------
        if self.awaiting_platform_choice:
            self.awaiting_platform_choice = False
            if "spotify" in cmd:
                status = self.spotify_handler.play_track(self.pending_song_request)
                self.speak(status)
            elif "youtube" in cmd:
                play_specific_youtube(self.pending_song_request)
            else:
                self.speak("Invalid platform.")
            self.pending_song_request = ""
            return

        # ---- DEVICE-AWARE PLAY LOGIC (Build 8.4) ----
        play_triggers = ["play", "please play", "start", "put on"]

        if any(cmd.startswith(p) for p in play_triggers):
            for trigger in play_triggers:
                if cmd.startswith(trigger):
                    full_query = cmd.replace(trigger, "", 1).strip()
                    break

            target_device = None
            device_match = re.search(r"\s+(?:on|in)\s+(?:my\s+)?([a-zA-Z0-9\s]+)$", full_query, re.IGNORECASE)
            if device_match:
                possible_device = device_match.group(1).strip().lower()
                if possible_device not in ["spotify", "youtube"]:
                    target_device = possible_device
                    full_query = full_query[:device_match.start()].strip()

            platform = None
            if "spotify" in full_query:
                platform = "spotify"
                full_query = full_query.replace("on spotify", "").strip()
            elif "youtube" in full_query:
                platform = "youtube"
                full_query = full_query.replace("on youtube", "").strip()

            if target_device:
                resolved_device = _resolve_device_alias(target_device)
                device_status = self.spotify_handler.switch_device(resolved_device)
                if "couldn't find" in device_status.lower():
                    self.speak(device_status)
                    return
                _save_device_alias(target_device, resolved_device)

            if not full_query:
                self.speak("What should I play?")
                return

            if platform == "spotify":
                # Speak immediately — TTS generates while Spotify API runs
                self.speak(f"Playing {full_query}.")
                status = self.spotify_handler.play_track(full_query)
                if any(w in status.lower() for w in ["couldn't", "error", "not found", "failed", "no active"]):
                    self.speak(status)
                return
            elif platform == "youtube":
                play_specific_youtube(full_query)
                return

            self.pending_song_request = full_query
            self.awaiting_platform_choice = True
            self.speak(f"Play {full_query} on Spotify or YouTube?")
            return

        

        # ---- PLAYLIST SELECTION STATE ----
        if self.awaiting_playlist_selection:
            if len(cmd.split()) == 1 and len(cmd) < 5:
                self.speak("Please say more of the playlist name.")
                return

            uri, actual_name = self.spotify_handler.find_best_playlist(cmd, self.available_playlists)

            if uri:
                self.awaiting_playlist_selection = False
                self.available_playlists = {}
                status = self.spotify_handler.play_specific_playlist_uri(uri)
                self.speak(status)
            else:
                names = ". ".join(list(self.available_playlists.keys())[:5])
                self.speak(f"I couldn't match that playlist. Please choose one of these: {names}.")
            return

        
        if any(w in cmd for w in ["work mode", "focus mode", "gym mode", "idle mode"]):
            for mode in ["work", "focus", "gym", "idle"]:
                if mode in cmd:
                    result = state.transition(mode)
                    self.speak(result)
                    return
            return
        

        if any(w in cmd for w in ["click on", "click the"]):
            target = cmd.replace("click on", "").replace("click the", "").strip()
            import google.generativeai as genai
            vision_client = genai.GenerativeModel("gemini-2.0-flash")
            result = vision.smart_locate_and_click(target, vision_client)
            if result is True:
                self.speak(f"Clicked {target}.")
            elif isinstance(result, str) and result.startswith("COOLDOWN"):
                secs = result.split("_")[1]
                self.speak(f"Vision is on cooldown. Try again in {secs} seconds.")
            else:
                self.speak(f"I couldn't find {target} on screen.")
            return

        

        if any(w in cmd for w in ["read the screen", "what's on screen", "read screen"]):
            from PIL import ImageGrab
            import pytesseract
            img = ImageGrab.grab()
            text = pytesseract.image_to_string(img).strip()
            if text:
                self.speak(f"I can see: {text[:300]}")
            else:
                self.speak("I couldn't read anything on the screen.")
            return

        if any(w in cmd for w in ["bitcoin", "ethereum", "crypto price", "btc price", "eth price", "dogecoin", "solana", "crypto rate"]):
            coin = "bitcoin"
            for c in ["bitcoin", "btc", "ethereum", "eth", "dogecoin", "doge", "solana", "sol"]:
                if c in cmd:
                    coin = c
                    break
            self.speak(self._get_crypto_price(coin))
            return

        if any(w in cmd for w in ["enroll my face", "register my face", "add my face", "save my face"]):
            from modules.vision_engine import get_vision_engine
            ve = get_vision_engine()
            if ve:
                try:
                    from modules.ws_bridge import broadcast as _bcast
                    _bcast({"type": "face_verify", "state": "enrolling"})
                except Exception:
                    pass
                self.speak("Look directly at the camera. Capturing your face now.")
                time.sleep(2)
                ok, msg = ve.enroll_face("vansh")
                try:
                    from modules.ws_bridge import broadcast as _bcast
                    _bcast({"type": "face_verify", "state": "success" if ok else "failed"})
                except Exception:
                    pass
                self.speak(msg)
            else:
                self.speak("Camera not available for face enrollment.")
            return

        if any(w in cmd for w in ["show log report", "command report", "log analysis", "how many commands"]):
            from modules.log_analyzer import analyze_logs
            analyze_logs()
            self.speak("Log report printed in terminal.")
            return

        if any(w in cmd for w in ["system stats", "cpu usage", "ram usage", "system status", "how's the system", "battery"]):
            from modules.performance_guard import PerformanceGuard
            guard = PerformanceGuard(self.speak)
            self.speak(guard.get_system_vitals())
            return

        # ---------------- MEDIA CONTROLS ----------------
        if any(w in cmd for w in ["pause music", "pause spotify", "stop music"]):
            from modules.response_generator import instant, smart, get_response_generator
            rg = get_response_generator()
            if rg: rg.instant("pause")
            result = self.spotify_handler.pause_music()
            if rg: rg.smart({"task": "pause", "target": "", "status": "success"}, cmd)
            return

        if any(w in cmd for w in ["resume music", "resume spotify", "continue music", "drop the needle"]):
            from modules.response_generator import instant, smart, get_response_generator
            rg = get_response_generator()
            if rg: rg.instant("resume")
            result = self.spotify_handler.resume_music()
            if rg: rg.smart({"task": "resume", "target": "", "status": "success"}, cmd)
            return

        if any(w in cmd for w in ["next song", "skip song", "next track"]):
            from modules.response_generator import instant, get_response_generator
            rg = get_response_generator()
            if rg: rg.instant("next")
            self.spotify_handler.next_track()
            return

        if any(w in cmd for w in ["previous song", "go back", "last song", "prev song", "previous track"]):
            from modules.response_generator import instant, get_response_generator
            rg = get_response_generator()
            if rg: rg.instant("previous")
            self.spotify_handler.previous_track()
            return

        if any(w in cmd for w in ["remember that", "remember this", "add to memory", "note that"]):
            from modules.memory import add_memory
            content = cmd
            for w in ["remember that", "remember this", "add to memory", "note that"]:
                content = content.replace(w, "").strip()
            if content:
                key = content[:30]
                add_memory(key, content)
                self.speak(f"Got it. I'll remember that.")
            else:
                self.speak("What should I remember?")
            return

        if any(w in cmd for w in ["what do you remember", "show memory", "list memory", "what you know about me"]):
            from modules.memory import list_memory
            items = list_memory()
            if not items:
                self.speak("I don't have anything stored in memory yet.")
            else:
                self.speak(f"I remember {len(items)} things about you.")
                for key, val, _ in items[:5]:
                    self.speak(val)
            return

        if any(w in cmd for w in ["forget that", "remove from memory", "delete memory"]):
            from modules.memory import list_memory, remove_memory
            content = cmd
            for w in ["forget that", "remove from memory", "delete memory"]:
                content = content.replace(w, "").strip()
            items = list_memory()
            for key, val, _ in items:
                if content.lower() in val.lower() or content.lower() in key.lower():
                    remove_memory(key)
                    self.speak(f"Removed from memory.")
                    return
            self.speak("I couldn't find that in my memory.")
            return

        if _last_whatsapp_message_check(cmd):
            from modules.whatsapp_handler import get_last_message
            last = get_last_message()
            if last and last.get("text"):
                sender = last.get("sender", "They")
                text = last.get("text", "")
                prompt = f"""The user said: "{cmd}"
A WhatsApp message exists from {sender}: "{text}"
Decide: does the user want to (A) hear the exact message or (B) get a summary/elaboration?
Reply with only "exact" or "elaborate"."""
                decision = self._raw_ai(prompt).strip().lower()
                if "exact" in decision:
                    self.speak(f"{sender} said: {text}")
                else:
                    prompt2 = f"""WhatsApp message from {sender}: "{text}"
Explain in one sentence what they want. Start with their name. Sound like JARVIS."""
                    self.speak(self._raw_ai(prompt2))
            else:
                self.speak("No recent WhatsApp message.")
            return

        # File manager commands are handled earlier via _handle_file_command()

        #Scheduler and Reminder Commands
        if any(w in cmd for w in ["remind me", "set a reminder", "add reminder"]):
            try:
                at_index = cmd.index(" at ")
                task_text = cmd[:at_index].replace("remind me to", "").replace("remind me", "").replace("set a reminder for", "").replace("add reminder", "").strip()
                time_str = cmd[at_index + 4:].strip()
                result = self.scheduler.add_reminder(task_text, time_str)
                self.speak(result)
            except ValueError:
                self.speak("Please say a time. For example, remind me to drink water at 5pm.")
            return
        
        #Whsatsapp Bridge Commands
        if any(w in cmd for w in ["whatsapp status", "is whatsapp connected", "whatsapp connected"]):
            try:
                import requests as req
                r = req.get("http://localhost:3000/health", timeout=3)
                status = r.json().get("status")
                if status == "connected":
                    self.speak("WhatsApp is connected and running.")
                else:
                    self.speak("WhatsApp is connecting. Please wait.")
            except Exception:
                self.speak("WhatsApp bridge is offline.")
            return

        if any(w in cmd for w in ["logout whatsapp", "disconnect whatsapp"]):
            try:
                import requests as req
                req.post("http://localhost:3000/logout", timeout=5)
                self.speak("WhatsApp session logged out.")
            except Exception:
                self.speak("Could not reach WhatsApp bridge.")
            return
        
        if any(w in cmd for w in ["what did he say", "what did she say", "what did they say",
                                   "what he said", "what she said", "what's the message",
                                   "read the message", "what did he send", "read it",
                                   "what did he write", "what was the message",
                                   "what it is", "what is it", "what did they send"]):
            from modules.whatsapp_handler import get_last_message
            last = get_last_message()
            if last and last.get("text"):
                sender = last.get("sender", "They")
                text = last.get("text", "")
                self.speak(f"{sender} said: {text}")
            else:
                self.speak("No recent WhatsApp message to read.")
            return

        if any(w in cmd for w in ["what he's saying", "what she's saying", "elaborate",
                                   "elaborate the message", "what does it mean",
                                   "explain the message", "what they want",
                                   "summarize the message"]):
            from modules.whatsapp_handler import get_last_message
            last = get_last_message()
            if last and last.get("text"):
                sender = last.get("sender", "They")
                text = last.get("text", "")
                import os as _os_cc
                owner = _os_cc.getenv("OWNER_NAME", "User")
                prompt = f"""A WhatsApp message was received from {sender}: "{text}"
Explain in one short sentence what they want or are saying, as if you're JARVIS briefing {owner}.
Start with the sender's name. Do not quote the message directly."""
                response = self._raw_ai(prompt)
                self.speak(response)
            else:
                self.speak("No recent WhatsApp message to elaborate.")
            return

        # Disable instant feedback for WhatsApp commands
        from modules.response_generator import get_response_generator
        _rg = get_response_generator()
        _orig_instant = None
        if _rg:
            _orig_instant = _rg.instant
            _rg.instant = lambda *a, **k: None

        if any(w in cmd for w in ["reply to", "reply her", "reply him", "reply them",
                                   "send a reply", "message back", "tell her", "tell him"]):
            from modules.whatsapp_handler import get_last_message, _send_message
            from modules.whatsapp_handler import _ai_func
            last = get_last_message()
            if not last or not last.get("number"):
                self.speak("No recent WhatsApp message to reply to.")
                return
            sender = last.get("sender", "them")
            original = last.get("text", "")
            number = last.get("number")
            context = cmd
            for w in ["reply to", "reply her", "reply him", "reply them", "tell them", 
                      "send a reply", "message back", "tell her", "tell him"]:
                context = context.replace(w, "").strip()
            if _ai_func and context:
                import os as _os_cc
                owner = _os_cc.getenv("OWNER_NAME", "User")
                prompt = f"""Write a WhatsApp reply message.
Original message from {sender}: "{original}"
{owner}'s instruction: "{context}"

Rules:
- Write ONLY the message text, nothing else — no explanations, no quotes
- Detect the language of the original message:
  * If original is in Hinglish/Hindi → reply in Hinglish (Roman Hindi, casual)
  * If original is in English → reply in English
- Match the tone of the original message (casual if casual, formal if formal)
- Keep it short, natural, conversational
- Write from {owner}'s perspective

Examples:
  Original: "Bhai kaisa hai" + instruction: "say i'm fine doing project"
  Reply: "Bhai sab theek hai, project kar rha hu"

  Original: "Hey what's up" + instruction: "say i'm busy"
  Reply: "Hey, bit busy rn, will catch up later"

  Original: "Notes bhej de" + instruction: "say will send later"
  Reply: "thodi der mein bhejta hu"
- Match the tone {owner} wants based on his instruction"""
                reply_text = _ai_func(prompt)
                _send_message(number, reply_text)
                self.speak(f"Replied to {sender}.")
            else:
                self.speak("What should I say in the reply?")
                # Restore instant feedback
        if _rg and _orig_instant:
            _rg.instant = _orig_instant
            return

        if any(w in cmd for w in ["pick up", "accept", "ignore", "reject", "contact later", "reply later", "send voice", "don't want to talk"]):
            from modules.whatsapp_handler import handle_whatsapp_command
            handle_whatsapp_command(cmd, self.speak)
            return

        if any(w in cmd for w in ["list reminders", "my reminders", "show reminders", "what are my reminders"]):
            self.speak(self.scheduler.list_reminders())
            return


        # ---------------- GOOGLE SEARCH ----------------
        if cmd.startswith("search "):
            query = cmd.split("search ", 1)[1].strip()
            clean_query = re.sub(r"\b(on|in)\s+(chrome|google)\b", "", query).strip()
            search_url = f"https://www.google.com/search?q={clean_query.replace(' ', '+')}"
            webbrowser.open(search_url)
            self.speak(f"Searching for {clean_query}.")
            return

        # ---------------- OPEN APP ----------------
        if cmd.startswith("open "):
            full = cmd.split("open ", 1)[1].strip()
            position = None
            for pos in ["left", "right", "top", "bottom", "maximize"]:
                if f"on the {pos}" in full or f"to the {pos}" in full or full.endswith(pos):
                    position = pos
                    full = full.replace(f"on the {pos}", "").replace(f"to the {pos}", "").replace(pos, "").strip()
                    break
            from modules.context_engine import handle_open_with_position
            open_result = handle_open_with_position(full, position)
            if "opened" in open_result.lower():
                self.speak(f"{full.title()} is open.")
            else:
                self.speak(f"Couldn't open {full}.")
            return

        # ---- AI GUARD ----
        if self.awaiting_playlist_selection or self.awaiting_platform_choice:
            return

        if "that" in cmd:
            ctx = self.spotify_handler.get_music_context()
            if ctx.get("track"):
                cmd = cmd.replace("that", ctx["track"])
        
        # ---- FINAL FALLBACK (NO RE-PARSE) ----
        
        from modules.context_memory import get_context_memory
        cm = get_context_memory()

        resolved = cmd   # ✅ ALWAYS DEFINE FIRST

        try:
            resolved = cm.resolve_followup(cmd)
            print("[CONTEXT RESOLVED]:", resolved)

            # STEP 6
            entity_person = cm.get_entity("last_person")
            if "his" in cmd.lower() and entity_person:
                resolved = resolved.replace("his", entity_person)
                print(f"[CONTEXT RESOLVED EXTRA]: {resolved}")

        except Exception as e:
            print("[ERROR]", e)

        try:
            response = self.ai(resolved)
        except Exception as e:
            print(f"[AI ERROR] {e}")
            response = None
        if response and not response.strip().startswith("{"):
            cm.add_turn(cmd, response)
            cm.update_entities_from_input(cmd)

            person_match = re.search(r"(Childish Gambino|Donald Glover)", response or "")
            if person_match:
                cm.set_entity("last_person", person_match.group(0))

            self.speak(response)
        else:
            # Direct fallback — bypass memory/personality overhead
            try:
                from modules.personality import PERSONALITY_PROMPT
                direct = self._raw_ai(f"{PERSONALITY_PROMPT}\n\nUser: {cmd}")
                if direct and not direct.strip().startswith("{"):
                    self.speak(direct)
                else:
                    self.speak("Say that again?")
            except Exception:
                self.speak("Say that again?")


    def _classify_and_convert_to_task(self, cmd):

        # 🧠 LOAD MEMORY
        user_music = None
        last_person = None
        try:
            from modules.mongo_brain import get_preference, retrieve_context
            user_music = get_preference("music")
            last_person = retrieve_context("last_person")
            print(f"[MEMORY] music={user_music}, last_person={last_person}")
        except Exception:
            pass

        parsed = self.ai_parse(cmd)

        if parsed.get("intent") != "unknown" and parsed.get("confidence", 1.0) < 0.7:
            _conf = parsed.get("confidence", 1.0)
            if _conf < 0.4:
                self.speak("Say that again?")
            else:
                _clarify = {
                    "play_music": "Play what? Give me a song or artist.",
                    "open_app": "Open what app?",
                    "switch_device": "Switch to which device?",
                    "search": "Search for what?",
                }
                self.speak(_clarify.get(parsed.get("intent"), "Say that again?"))
            return True  # sentinel: gate blocked, skip _classify_and_execute

        if parsed.get("intent") == "play_music":
            song = (parsed.get("song") or "").strip()
            artist = (parsed.get("artist") or "").strip()
            query = song or artist or ""
            if not query:
                return None
            return Task("play_music", {"song": query})

        if parsed.get("intent") == "pause":
            return Task("pause")

        if parsed.get("intent") == "next":
            return Task("next")

        if parsed.get("intent") == "switch_device":
            return Task("switch_device", {"device": parsed.get("device")})

        return None