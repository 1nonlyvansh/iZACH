import re

import webbrowser
import logging
import json

logger = logging.getLogger(__name__)

from modules.task_engine import TaskEngine, Task
from rapidfuzz import process, fuzz
from modules.automation import open_app, play_specific_youtube
from modules.intent_router import IntentRouter
from modules.state_engine import state
import modules.vision as vision


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
        sub_commands = [c.strip() for c in re.split(r'\b(?:and|then)\b', query) if c.strip()]
        for cmd in sub_commands:
            resolved_cmd = self._resolve_pronouns(cmd)

            # These must be handled BEFORE AI parse
            if "playlist" in resolved_cmd or resolved_cmd.startswith("open ") or any(m in resolved_cmd for m in ["what am i holding", "what's in my hand", "what do you see", "look at this", "what is this", "identify this", "what's this", "how many calories", "what food is this", "scan this", "describe what you see", "what can you see", "look at camera", "work mode", "focus mode", "gym mode", "idle mode", "switch to work", "switch to focus", "switch to gym", "switch to idle", "click on", "click the", "read the screen", "what's on screen", "read screen", "remember that", "remember this", "what do you remember", "forget that", "reply to", "reply her", "reply him", "what did he say", "what did she say", "open file", "list files", "create folder", "find file", "read file", "latest file", "where am i", "go up"]):
                self._classify_and_execute(resolved_cmd)
                continue

            task = self._classify_and_convert_to_task(resolved_cmd)

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
        if not self.ctx_mgr.is_context_valid():
            return query

        resolved = query

        if " it" in query or query.endswith("it"):
            app_ctx = self.ctx_mgr.get_context("last_app_opened")
            if app_ctx:
                resolved = resolved.replace("it", app_ctx)

        if " that" in query or query.endswith("that"):
            last_search = self.ctx_mgr.get_context("last_search_query")
            if last_search:
                resolved = resolved.replace("that", last_search)

        return resolved

    def _classify_and_execute(self, cmd):
        print("🔥 ENTERED CLASSIFY")
        cmd = cmd.lower().strip()
        print(f"[DEBUG CMD]: {cmd}")
        from modules.response_generator import instant, smart

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
            from modules.camera_vision import capture_and_ask
            answer = capture_and_ask(cmd)
            self.speak(answer)
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
        
        # real-time data check — runs before AI parse
        from modules.realtime_data import handle_realtime_query
        realtime_result = handle_realtime_query(cmd)
        if realtime_result:
            self.speak(realtime_result)
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

        # 🧠 MEMORY-DRIVEN MODIFICATION
        if parsed.get("intent") == "play_music" and not parsed.get("platform"):
            if user_music:
                parsed["platform"] = user_music if isinstance(user_music, str) else "spotify"

        print("🔥 PARSED OUTPUT:", parsed)

        # Route known intents, skip unknown ones to fallback AI
        result = self.router.route(parsed)

        

        print("🔥 ROUTER RESULT:", result)

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
        from modules.context_memory import get_context_memory

        cm = get_context_memory()
        resolved = cmd   # ✅ ALWAYS DEFINE FIRST

        try:
            resolved = cm.resolve_followup(cmd)
            print("[CONTEXT RESOLVED]:", resolved)

            entity_person = cm.get_entity("last_person")
            if "his" in cmd.lower() and entity_person:
                resolved = resolved.replace("his", entity_person)
                print(f"[CONTEXT RESOLVED EXTRA]: {resolved}")

        except Exception as e:
            print("[ERROR]", e)

        print("[CONTEXT RESOLVED]:", resolved)

        try:
            response = self.ai(resolved)
            

            if response and not response.strip().startswith("{"):
                cm.add_turn(cmd, response)
                cm.update_entities_from_input(cmd)
                self.speak(response)
                
                # 🧠 LOG TO MONGO
                try:
                    from modules.mongo_brain import log_important_command
                    log_important_command(cmd, response, "conversation")
                except Exception as e:
                    print("[MONGO ERROR]", e)
            else:
                self.speak("I didn't understand that.")
        except Exception as e:
            print("[FALLBACK ERROR]:", e)
            self.speak("I didn't understand that.")

        cmd = cmd.lower().strip()
        print(f"[DEBUG CMD]: {cmd}")

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
                instant("play_music")
                status = self.spotify_handler.play_track(full_query)
                smart({"task": "play_music", "target": full_query, "status": "success" if "Playing" in status else "failure", "detail": status}, cmd)
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
                decision = self.ai(prompt).strip().lower()
                if "exact" in decision:
                    self.speak(f"{sender} said: {text}")
                else:
                    prompt2 = f"""WhatsApp message from {sender}: "{text}"
Explain in one sentence what they want. Start with their name. Sound like JARVIS."""
                    self.speak(self.ai(prompt2))
            else:
                self.speak("No recent WhatsApp message.")
            return

        # ── FILE MANAGER COMMANDS ──
        if any(w in cmd for w in ["open file", "open my file", "open the file"]):
            from modules.file_manager import get_file_manager
            from modules.response_generator import instant, smart
            fm = get_file_manager()
            fm.set_speak(self.speak)
            name = cmd
            for w in ["open file", "open my file", "open the file", "open"]:
                name = name.replace(w, "").strip()
            instant("open_file")
            results = fm.smart_find(name, ai_func=self.ai)
            if results:
                import os
                fname = os.path.basename(results[0])
                ok, msg = fm.handle_by_type(results[0])
                if msg.startswith("PASSWORD_REQUIRED"):
                    self.speak("Password required. Type it in the password box.")
                else:
                    smart({"task": "open_file", "target": fname, "status": "success" if ok else "failure"}, cmd)
            else:
                smart({"task": "open_file", "target": name, "status": "failure", "detail": "not found"}, cmd)
            return

        if any(w in cmd for w in ["list files", "show files", "what files", "list folder", "show folder"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            ok, msg, items = fm.list_folder()
            if ok:
                self.speak(msg)
                if items:
                    preview = ", ".join(items[:6])
                    self.speak(f"Contents: {preview}")
            else:
                self.speak(msg)
            return

        if any(w in cmd for w in ["create folder", "make folder", "new folder", "create new folder"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            name = cmd
            for w in ["create folder", "make folder", "new folder", "called", "named"]:
                name = name.replace(w, "").strip()
            import os
            path = os.path.join(fm.current_dir, name)
            ok, msg = fm.create_folder(path)
            self.speak(msg)
            return

        if any(w in cmd for w in ["go up", "navigate up", "back folder", "parent folder"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            ok, msg = fm.navigate("up")
            self.speak(msg)
            return

        if any(w in cmd for w in ["where am i", "current folder", "current directory", "which folder"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            self.speak(f"You are in {fm.where_am_i()}")
            return

        if any(w in cmd for w in ["find file", "search file", "find my", "search for file"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            name = cmd
            for w in ["find file", "search file", "find my", "search for file", "find", "search"]:
                name = name.replace(w, "").strip()
            results = fm.find_file(name)
            if results:
                self.speak(f"Found {len(results)} file{'s' if len(results) > 1 else ''}. First match: {results[0]}")
            else:
                self.speak(f"No files found matching {name}.")
            return

        if any(w in cmd for w in ["latest file", "newest file", "most recent file", "find latest"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            ext = None
            for e in ["pdf", "txt", "py", "docx", "xlsx", "mp3", "mp4"]:
                if e in cmd:
                    ext = e
                    break
            result = fm.get_latest_file(file_type=ext)
            if result:
                import os
                self.speak(f"Latest file is {os.path.basename(result)}")
            else:
                self.speak("No files found in the current folder.")
            return

        if any(w in cmd for w in ["read file", "read the file", "read my file"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            name = cmd
            for w in ["read file", "read the file", "read my file", "read"]:
                name = name.replace(w, "").strip()
            results = fm.find_file(name)
            if results:
                ok, content = fm.read_text_file(results[0])
                if ok:
                    self.speak(content[:300])
                else:
                    self.speak(content)
            else:
                self.speak(f"No file named {name} found.")
            return

        if any(w in cmd for w in ["delete file", "delete the file", "remove file"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            fm.set_speak(self.speak)
            name = cmd
            for w in ["delete file", "delete the file", "remove file", "delete", "remove"]:
                name = name.replace(w, "").strip()
            results = fm.smart_find(name, ai_func=self.ai)
            if results:
                import os
                self.speak(f"Found {os.path.basename(results[0])}. This will delete it permanently.")
                ok, msg = fm.delete_file(results[0])
                if any(w in cmd for w in ["delete file", "delete this", "remove file"]):
                    # Face verify before delete
                    from modules.vision_engine import get_vision_engine
                    ve = get_vision_engine()
                    if ve and ve.verify_face("vansh"):
                        self.speak("Identity confirmed.")
                        # ... existing delete logic
                    else:
                        self.speak("Couldn't verify your face. Delete blocked.")
                    return
                if msg.startswith("PASSWORD_REQUIRED"):
                    self.speak("Dangerous action. Please type your password in the password box to confirm.")
                else:
                    self.speak(msg)
            else:
                self.speak(f"No file found matching {name}.")
            return

        if any(w in cmd for w in ["show file log", "file actions", "recent file actions"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            actions = fm.get_recent_actions(5)
            if actions:
                self.speak(f"Last {len(actions)} file actions:")
                for a in actions:
                    parts = a.split("|")
                    if len(parts) >= 3:
                        self.speak(f"{parts[1].strip()} — {parts[2].strip()}")
            else:
                self.speak("No file actions logged yet.")
            return

        if any(w in cmd for w in ["file manager status", "file permission", "what permission"]):
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            s = fm.get_status()
            self.speak(f"Permission level is {s['permission']}. Sandbox is {'on' if s['sandbox'] else 'off'}. Current folder is {s['current_dir']}.")
            return
        
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
                prompt = f"""A WhatsApp message was received from {sender}: "{text}"
Explain in one short sentence what they want or are saying, as if you're JARVIS briefing Vansh.
Start with the sender's name. Do not quote the message directly."""
                response = self.ai(prompt)
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
                prompt = f"""Write a WhatsApp reply message.
Original message from {sender}: "{original}"
Vansh's instruction: "{context}"

Rules:
- Write ONLY the message text, nothing else — no explanations, no quotes
- Detect the language of the original message:
  * If original is in Hinglish/Hindi → reply in Hinglish (Roman Hindi, casual)
  * If original is in English → reply in English
- Match the tone of the original message (casual if casual, formal if formal)
- Keep it short, natural, conversational
- Write from Vansh's perspective

Examples:
  Original: "Bhai kaisa hai" + instruction: "say i'm fine doing project"
  Reply: "Bhai sab theek hai, project kar rha hu"

  Original: "Hey what's up" + instruction: "say i'm busy"
  Reply: "Hey, bit busy rn, will catch up later"

  Original: "Notes bhej de" + instruction: "say will send later"
  Reply: "thodi der mein bhejta hu"
- Match the tone Vansh wants based on his instruction"""
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

        self.speak(response)

        try:
            response = self.ai(resolved)
        except Exception as e:
            print(f"[AI ERROR] {e}")
            response = None
        if response and not response.strip().startswith("{"):
            cm.add_turn(cmd, response)
            cm.update_entities_from_input(cmd)

            import re
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
        try:
            from modules.mongo_brain import get_preference, retrieve_context

            user_music = get_preference("music")
            # last_person = retrieve_context("last_person")

            print(f"[MEMORY] music={user_music}, last_person={last_person}")
        except:
            user_music = None
            last_person = None

        parsed = self.ai_parse(cmd)

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