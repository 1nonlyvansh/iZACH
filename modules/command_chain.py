import re
import time
import webbrowser
import logging
import json

_vision_in_progress = False
_chain_ref = None  # set by main.py after CommandChain is instantiated; used by ws_bridge

# Populated after each process() call — read by main.py voice_loop for synonym learning
_last_route_info: dict = {"domain": "chat", "handled": False, "confidence": 0.0}

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

_RECORDING_TRIGGER_SENTINEL = "__replay_recording__::"


def _match_recording_trigger(query: str):
    """Checks `query` against every saved Browser-widget recording's custom
    trigger phrases (set in the step editor's TRIGGER PHRASES field). A phrase
    may contain one {param} placeholder — e.g. "search for {q}" matches
    "search for cats" and captures q="cats" — mirroring the recording's own
    {param} fill-value placeholders (see cortex-ui.html's _seExtractParams).
    Returns (recording_name, params_dict) on match, else None.
    """
    import os
    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "browser_recordings")
    if not os.path.isdir(recordings_dir):
        return None
    for fname in os.listdir(recordings_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(recordings_dir, fname), encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        for phrase in rec.get("trigger_phrases") or []:
            phrase = phrase.strip().lower()
            if not phrase:
                continue
            m = re.search(r'\{(\w+)\}', phrase)
            if m:
                param_name = m.group(1)
                pattern = "^" + re.escape(phrase).replace(re.escape("{" + param_name + "}"), r'(.+)') + "$"
                pm = re.match(pattern, query)
                if pm:
                    return rec.get("name"), {param_name: pm.group(1).strip()}
            elif phrase == query:
                return rec.get("name"), {}
    return None

logger = logging.getLogger(__name__)

from modules.task_engine import TaskEngine, Task
from modules.automation import open_app, play_specific_youtube, snap_window
from modules.intent_router import IntentRouter
from modules.state_engine import state
import modules.camera_vision as vision
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

    def __init__(self, context_handler, scheduler_handler, ai_handler, raw_ai_handler, speak_func, orchestrator, context_manager, spotify_handler, agent_orch=None):
        self.context_handler = context_handler
        self.scheduler = scheduler_handler
        self.ai = ai_handler          # with memory — for conversations
        self._raw_ai = raw_ai_handler # without memory — for JSON parsing only
        self.speak = speak_func
        self.orchestrator = orchestrator
        self.ctx_mgr = context_manager
        self.spotify_handler = spotify_handler
        self.agent_orch = agent_orch  # OrchestratorAgent — intent classifier
        self._domain_ctx: dict = {}   # last classification result, for logging + fast-path

        # ── Specialized agents ────────────────────────────────────
        from Agents.whatsapp_agent import WhatsAppAgent
        self._wa_agent = WhatsAppAgent(
            speak_fn   = speak_func,
            raw_ai_fn  = raw_ai_handler,
        )
        from Agents.calendar_agent import CalendarAgent
        self._cal_agent = CalendarAgent(
            speak_fn   = speak_func,
            raw_ai_fn  = raw_ai_handler,
            scheduler  = scheduler_handler,
        )
        from Agents.system_agent import SystemAgent
        self._sys_agent = SystemAgent(
            speak_fn   = speak_func,
            raw_ai_fn  = raw_ai_handler,
        )
        from Agents.research_agent import ResearchAgent
        self._res_agent = ResearchAgent(
            speak_fn   = speak_func,
            raw_ai_fn  = raw_ai_handler,
        )
        from Agents.spotify_agent import SpotifyAgent
        self._spo_agent = SpotifyAgent(
            speak_fn        = speak_func,
            raw_ai_fn       = raw_ai_handler,
            spotify_handler = spotify_handler,
        )
        from Agents.file_agent import FileAgent
        self._file_agent = FileAgent(
            speak_fn  = speak_func,
            raw_ai_fn = raw_ai_handler,
        )
        from Agents.memory_agent import MemoryAgent
        self._mem_agent = MemoryAgent(
            speak_fn  = speak_func,
            raw_ai_fn = raw_ai_handler,
        )
        from Agents.vision_agent import VisionAgent
        self._vis_agent = VisionAgent(
            speak_fn  = speak_func,
            raw_ai_fn = raw_ai_handler,
        )

        self.task_engine = TaskEngine(self.spotify_handler, self.speak)
        self.router = IntentRouter(self.spotify_handler, self.speak, self.ai, self.task_engine)

        self.awaiting_playlist_selection = False
        self.available_playlists = {}

        self.awaiting_platform_choice = False
        self.pending_song_request = ""

        self.awaiting_app_or_web = False
        self.pending_open_service = ""

        self.awaiting_disambiguation = None  # {"action": "open"|"delete", "matches": [...], "query": str}
        self._pending_install: str | None = None

    def current_domain(self) -> str:
        """Return domain from the last orchestrator classification ('chat' if unknown)."""
        return self._domain_ctx.get("domain", "chat")

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
- switch_device ONLY when user explicitly says to switch Spotify/music playback to a different speaker or output device (e.g. "switch to TV", "play on my phone", "move to laptop speakers"). Mentioning the word "device" in any other context (e.g. "control my laptop", "laptop device", "feature for device") is NOT switch_device — use unknown instead.
- Extract app name if intent is open_app
- Extract song, artist, device, platform if present
- Include confidence (0 to 1)
- If the command is a question, conversation, or does not clearly match any intent, use unknown with low confidence

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
    
    

    def process(self, query, _sc_bypass: bool = False):
        query = query.lower().strip()
        # Strip filler words + the wake word at the start. STT mishears "iZACH"
        # constantly ("Isaac", "hijack", "i jack"...) since it's not a real
        # English word — modules.wake_word already maintains the list of
        # known mishearings for the wake-word-enabled path, so reuse it here
        # instead of only matching the literal string "izach".
        import re as _re
        try:
            from modules.wake_word import _NAME_VARIANTS as _WW_VARIANTS
        except Exception:
            _WW_VARIANTS = {"izach"}
        _fillers = ["hey", "please", "hi", "okay", "ok", "yo", "uh", "um",
                    "can you", "could you", "would you", "will you", "now"]
        _all_leading = sorted(_fillers + list(_WW_VARIANTS), key=len, reverse=True)
        _leading_re = "|".join(_re.escape(w) for w in _all_leading)
        # `+` repeats the whole group so multiple leading tokens strip in one
        # pass — "hey izach, play x" previously only stripped "hey ", leaving
        # "izach," glued onto every command that said both words.
        query = _re.sub(rf'^(?:(?:{_leading_re})[,\s]+)+', '', query).strip()
        # "dot txt" / "dot pdf" etc → ".txt" / ".pdf"
        query = _re.sub(r'\s*\bdot\s+([a-z0-9]{1,5})\b', r'.\1', query)
        query = _re.sub(r'\s+\.([a-z0-9]{1,5})\b', r'.\1', query)

        # ── DND (Do Not Disturb) commands — intercept before anything else ──
        try:
            from modules import dnd_mode as _dnd
            _DND_ON  = re.compile(
                r'\b(turn\s+on|enable|activate|start|begin)\b.*\b(dnd|do\s+not\s+disturb|silent\s*mode|meeting\s*mode)\b'
                r'|\b(dnd|do\s+not\s+disturb)\b.*(on|activate|enable)',
                re.IGNORECASE,
            )
            _DND_OFF = re.compile(
                r'\b(turn\s+off|disable|deactivate|stop|end)\b.*\b(dnd|do\s+not\s+disturb|silent\s*mode|meeting\s*mode)\b'
                r'|\b(dnd|do\s+not\s+disturb)\b.*(off|disable|deactivate)',
                re.IGNORECASE,
            )
            _DND_STATUS = re.compile(r'\b(dnd|do\s+not\s+disturb)\b.*(status|on\?|active\?)', re.IGNORECASE)
            if _DND_ON.search(query):
                _dnd.turn_on("manual")
                return
            if _DND_OFF.search(query):
                _dnd.turn_off()
                return
            if _DND_STATUS.search(query):
                s = _dnd.get_status()
                msg = f"DND is {'ON' if s['active'] else 'OFF'}. {s['queue_count']} queued alerts." if s["active"] else "Do Not Disturb is off."
                self.speak(msg)
                return
        except Exception as _dnd_err:
            logger.debug(f"[DND command] {_dnd_err}")

        # ── Email agent commands (order status, connection status) ──
        try:
            from Agents.email_agent import handle as _email_handle
            _email_reply = _email_handle(query)
            if _email_reply:
                self.speak(_email_reply)
                return
        except Exception as _email_err:
            logger.debug(f"[Email agent command] {_email_err}")

        # ── Busy Mode commands ────────────────────────────────────
        try:
            from modules import busy_mode as _busy
            import re as _re_busy
            # "busy mode on [for 90 minutes] [reason gym]"
            _BUSY_ON = _re_busy.compile(
                r'\b(turn\s+on|enable|activate|start|i.?m\s+going)\b.*\b(busy\s*mode|busy)\b'
                r'|\b(busy\s*mode|busy)\b.*(on|enable|activate)',
                _re_busy.IGNORECASE,
            )
            _BUSY_OFF = _re_busy.compile(
                r'\b(turn\s+off|disable|stop|end|i.?m\s+back|i\s+am\s+back)\b.*\b(busy\s*mode|busy)\b'
                r'|\b(busy\s*mode|busy)\b.*(off|disable|stop)',
                _re_busy.IGNORECASE,
            )
            _BUSY_STATUS = _re_busy.compile(r'\b(busy\s*mode|busy)\b.*(status|on\?|active\?)', _re_busy.IGNORECASE)
            if _BUSY_ON.search(query):
                # Extract reason and duration
                _reason_m = _re_busy.search(r'\b(gym|studying|study|sleeping|sleep|eating|eat|driving|drive|meeting)\b', query, _re_busy.IGNORECASE)
                _dur_m    = _re_busy.search(r'\b(\d+)\s*(min|minute|hour|hr)\b', query, _re_busy.IGNORECASE)
                _reason   = _reason_m.group(1).lower() if _reason_m else "manual"
                _dur      = None
                if _dur_m:
                    _val  = int(_dur_m.group(1))
                    _unit = _dur_m.group(2).lower()
                    _dur  = _val * 60 if _unit.startswith("h") else _val
                _busy.turn_on(reason=_reason, duration_min=_dur)
                return
            if _BUSY_OFF.search(query):
                _busy.turn_off()
                return
            if _BUSY_STATUS.search(query):
                s = _busy.get_status()
                if s["active"]:
                    _rem = f" {int(s['remaining_sec']//60)} min left." if s.get("remaining_sec") else ""
                    self.speak(f"Busy mode is on. Reason: {s['reason']}.{_rem} {s['msg_count']} messages handled.")
                else:
                    self.speak("Busy mode is off.")
                return
        except Exception as _busy_err:
            logger.debug(f"[BUSY command] {_busy_err}")

        # ── Dual-instance handoff ("hand off to mac", "move to windows") ──
        # Intercept before anything else reaches it — with no explicit check,
        # this fell all the way through to the generic AI intent classifier,
        # which grabbed the whole phrase as a kill_app app_name ("No app named
        # 'hands off to mac' is running.").
        # \bhands?\s+off\s+to\b tolerates "hands off to" (typo/mishear for
        # "hand off to") alongside the exact phrase and the other triggers.
        # (A second, later copy of this same check also exists further down
        # in the system-control dispatch chain as a fallback for whatever
        # path doesn't route through here first — harmless redundancy, first
        # match wins and returns.)
        try:
            if re.search(r'\bhands?\s+off\s+to\b', query) or any(
                w in query for w in ["handoff to", "move izach to", "move to windows", "move to mac"]
            ):
                _target_m = re.search(r'\b(windows|macos|mac)\b', query)
                if not _target_m:
                    self.speak("Hand off to which machine — Windows or Mac?")
                else:
                    _target = _target_m.group(1)
                    from modules.instance_coordinator import initiate_handoff
                    _ok, _msg = initiate_handoff(_target)
                    self.speak(_msg)
                return
        except Exception as _handoff_err:
            logger.debug(f"[Dual-instance handoff command] {_handoff_err}")

        # ── Recorded browser task replay (Cortex UI Browser widget) ──────
        # Two ways in: (a) the scheduler fires the sentinel action text set by
        # schedule_recording_job(), or (b) the user speaks a custom trigger
        # phrase set in the recording's step editor (e.g. "check my messages").
        # Either way, actual replay happens in the Electron renderer (not here)
        # because only it can decrypt any safeStorage-encrypted credential
        # steps before handing hydrated steps to the Playwright backend.
        try:
            if query.startswith(_RECORDING_TRIGGER_SENTINEL):
                _rec_name = query[len(_RECORDING_TRIGGER_SENTINEL):]
                from modules.ws_bridge import broadcast as _bc
                _bc({"type": "browser_command", "action": "replay_recording", "name": _rec_name, "params": {}})
                return
            _rec_match = _match_recording_trigger(query)
            if _rec_match:
                _rec_name, _rec_params = _rec_match
                try:
                    from modules.ws_bridge import broadcast as _bc
                    _bc({"type": "browser_command", "action": "replay_recording", "name": _rec_name, "params": _rec_params})
                    self.speak(f'Running "{_rec_name}".')
                except Exception:
                    self.speak("Browser isn't open.")
                return
        except Exception as _rec_err:
            logger.debug(f"[Recording trigger] {_rec_err}")

        # ── Subconsciousness permission gate (top-level, pre-split) ──
        # Dangerous whole-query check before we split into sub-commands.
        # Bypass flag is set when permission was already granted.
        if not _sc_bypass:
            try:
                from modules import subconsciousness as _sc_mod
                _is_danger, _danger_desc = _sc_mod.is_dangerous(query)
                if _is_danger:
                    _captured_query = query

                    def _permitted_exec():
                        self.process(_captured_query, _sc_bypass=True)

                    _sc_mod.request_permission(_danger_desc, _permitted_exec)
                    return  # wait for user to confirm
            except Exception as _sc_err:
                logger.debug(f"[SC gate] {_sc_err}")

        # ── Snap position pre-parse ───────────────────────────────
        # Pattern: "open X at left", "open X on the right", "snap X to left"
        _SNAP_RE = re.compile(
            r'\b(?:open|launch|start)\s+(.+?)\s+(?:at|in|on\s+(?:the\s+)?|snap\s+(?:to\s+)?)(?:the\s+)?(left|right|center|full(?:screen)?|maximize)\b',
            re.IGNORECASE,
        )

        # ── Parallel-eligible domain detector ────────────────────
        # Commands that don't share state and can safely run concurrently
        _PARALLEL_DOMAINS = {
            "spotify", "dnd", "busy", "brightness", "volume", "wifi",
            "youtube_play",  # tagged by YouTube regex
        }
        def _is_parallel_eligible(c: str) -> str | None:
            """Return a domain tag if this sub-command can run in parallel, else None."""
            c = c.lower()
            if re.search(r'\bplay\b.*\bspotify\b|\bspotify\b.*\bplay\b', c):
                return "spotify"
            if re.search(r'\b(turn\s+on|enable|activate)\b.*\b(dnd|do\s+not\s+disturb)\b', c):
                return "dnd"
            if re.search(r'\b(turn\s+on|enable|activate)\b.*\bbusy\b', c):
                return "busy"
            if re.search(r'\bbrightness\b|\bvolume\b|\bwifi\b', c):
                return "system"
            if re.search(r'\b(?:play|stream)\s+.+\s+on\s+(?:youtube|yt)\b|\bsearch\s+(?:on\s+)?youtube\b', c, re.IGNORECASE):
                return "youtube_play"
            return None

        sub_commands = [c.strip() for c in re.split(r'\b(?:and|then)\b', query) if c.strip()]

        # ── Parallel multitask detection ──────────────────────────
        # If query has 2 sub-commands and at least ONE is parallel-eligible
        # and the other is an app-open, run them concurrently.
        if len(sub_commands) == 2:
            _dom0 = _is_parallel_eligible(sub_commands[0])
            _dom1 = _is_parallel_eligible(sub_commands[1])
            _open0 = re.match(r'\b(open|launch|start)\b', sub_commands[0])
            _open1 = re.match(r'\b(open|launch|start)\b', sub_commands[1])
            # Parallel: one is open-app, other is non-open parallel domain
            if (_open0 and _dom1 and not _open1) or (_open1 and _dom0 and not _open0):
                import threading as _par_thr
                def _run_sub(sc):
                    self.process(sc, _sc_bypass=True)
                _par_thr.Thread(target=_run_sub, args=(sub_commands[0],), daemon=True).start()
                _par_thr.Thread(target=_run_sub, args=(sub_commands[1],), daemon=True).start()
                return
        for cmd in sub_commands:
            # ── Window snap intercept ─────────────────────────────
            # "open notepad at left", "open chrome on the right"
            _snap_m = _SNAP_RE.search(cmd)
            if _snap_m:
                _snap_app  = _snap_m.group(1).strip()
                _snap_dir  = _snap_m.group(2).strip().lower()
                import threading as _snap_thr
                def _open_and_snap(a=_snap_app, d=_snap_dir):
                    open_app(a)
                    snap_window(d)
                self.speak(f"Opening {_snap_app} on the {_snap_dir}.")
                _snap_thr.Thread(target=_open_and_snap, daemon=True).start()
                continue

            # Reset domain context per sub-command so domain from cmd 1 doesn't bleed into cmd 2
            self._domain_ctx = {"domain": None, "confidence": 0.0}
            _had_this = bool(re.search(r'\bthis\b', cmd))
            resolved_cmd = self._resolve_pronouns(cmd)
            _this_resolved = _had_this and resolved_cmd != cmd  # "this" was swapped for a topic

            # ── Remote Node fast-path (AlliedNode 2) ─────────────
            _NODE2_RE = re.compile(
                r'\b(?:'
                r'alliednode\s*2'
                r'|allied\s*node\s*2'
                r'|allied\s*note\s*2'
                r'|elite\s*node\s*2'
                r'|elite\s*note\s*2'
                r'|alliednote\s*2'
                r'|allied\s*no\s*2'
                r')\b',
                re.IGNORECASE,
            )
            if _NODE2_RE.search(resolved_cmd):
                self._handle_remote_node_command(resolved_cmd)
                continue


            # ── Alias resolution: substitute user-defined shortcuts ──
            try:
                from modules.alias_engine import resolve as _alias_resolve
                _alias_resolved = _alias_resolve(resolved_cmd)
                if _alias_resolved != resolved_cmd:
                    print(f"[ALIAS] '{resolved_cmd}' → '{_alias_resolved}'")
                    resolved_cmd = _alias_resolved
            except Exception:
                pass

            # ══════════════════════════════════════════════════════════
            # PRE-ORCHESTRATOR FAST-PATHS
            # Run BEFORE the orchestrator LLM so these never get mis-classified.
            # ══════════════════════════════════════════════════════════
            _rc = resolved_cmd.lower()

            # ── 0. UI screen / optics mode commands ───────────────────
            # "turn on optics mode", "show camera", "optics screen" etc.
            # Must run before orchestrator — SystemAgent mis-routes as WiFi.
            _OPTICS_RE = re.compile(
                r'\b(?:turn\s+on|open|show|enable|activate|start)\s+(?:optics|camera\s*mode|cam\s*mode|vision\s*mode|optics?\s*screen)\b'
                r'|\boptics\s*(?:mode|screen|on)\b'
                r'|\bcamera\s*(?:screen|mode|on|view)\b',
                re.IGNORECASE,
            )
            if _OPTICS_RE.search(resolved_cmd):
                try:
                    from modules.ws_bridge import broadcast as _bc
                    _bc({"type": "ui_command", "action": "set_screen", "screen": "cam"})
                    self.speak("Optics mode on.")
                except Exception:
                    self.speak("Opening optics screen.")
                continue

            # ── 1. Form fill — orchestrator misclassifies as open_app ─
            _FILL_TRIGS = [
                "fill form", "autofill", "fill the form", "fill this form",
                "fill these details", "fill my details", "fill this for me", "fill details",
                "feel this form", "feel these details", "feel my details",
            ]
            if any(t in _rc for t in _FILL_TRIGS):
                self._handle_web_automation(resolved_cmd)
                continue

            # ── 2. Software installer download ────────────────────────
            _DL_RE = re.compile(
                r'^(?:download|get me|fetch|grab)\s+(.+?)'
                r'(?:\s+(?:installer|setup|install file|app|application|software))?\s*$',
                re.IGNORECASE,
            )
            _dl_m = _DL_RE.match(resolved_cmd)
            if _dl_m:
                _dl_candidate = _dl_m.group(1).strip()
                try:
                    from modules.app_installer import get_installer_info as _gii
                    if _gii(_dl_candidate):
                        from modules.app_installer import download_installer as _dlfn
                        import threading as _dlthr
                        self.speak(f"Downloading {_dl_candidate.title()} installer. I'll let you know when it's ready.")
                        _dlthr.Thread(
                            target=lambda _a=_dl_candidate: self.speak(_dlfn(_a)[1]),
                            daemon=True,
                        ).start()
                        continue
                except Exception as _dle:
                    import logging as _ldl; _ldl.getLogger("iZACH.Chain").debug(f"[DL fast] {_dle}")

            # ── 3. System control (volume / brightness / open / close) ─
            _sc_handled = False
            try:
                import modules.system_control as _sc_fp
                from modules.automation import open_app as _open_fp
                _norm = _normalize_numbers(resolved_cmd)

                if re.search(r'\b(volume\s+up|increase volume|raise volume|turn up)\b', _rc):
                    _, _m = _sc_fp.adjust_volume(10); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(volume\s+down|decrease volume|lower volume|turn down|reduce volume)\b', _rc):
                    _, _m = _sc_fp.adjust_volume(-10); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(mute|silence|mute volume)\b', _rc) and 'unmute' not in _rc:
                    _, _m = _sc_fp.mute(); self.speak(_m); _sc_handled = True
                elif re.search(r'\bunmute\b', _rc):
                    _, _m = _sc_fp.unmute(); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(set volume|volume to|volume at|change volume)\b', _rc):
                    _vm = re.search(r'\b(\d{1,3})\b', _norm)
                    if _vm: _, _m = _sc_fp.set_volume(int(_vm.group(1))); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(brightness up|increase brightness|raise brightness|turn up brightness)\b', _rc):
                    _, _m = _sc_fp.adjust_brightness(10); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(brightness down|decrease brightness|lower brightness|turn down brightness|reduce brightness)\b', _rc):
                    _, _m = _sc_fp.adjust_brightness(-10); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(set brightness|brightness to|brightness at|change brightness)\b', _rc):
                    _bm = re.search(r'\b(\d{1,3})\b', _norm)
                    if _bm: _, _m = _sc_fp.set_brightness(int(_bm.group(1))); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(dark mode|switch to dark|turn on dark|enable dark)\b', _rc):
                    _, _m = _sc_fp.set_theme("dark"); self.speak(_m); _sc_handled = True
                elif re.search(r'\b(light mode|switch to light|turn on light|enable light)\b', _rc):
                    _, _m = _sc_fp.set_theme("light"); self.speak(_m); _sc_handled = True
                elif (re.match(r'^open\s+\w', _rc)
                      and not any(w in _rc for w in ('file', 'folder', 'document', 'note', 'pdf',
                                                      'assignment', 'report', 'lecture', 'homework'))
                      and not _SNAP_RE.search(resolved_cmd)):
                    _app_name = re.sub(r'^open\s+', '', resolved_cmd.strip(), flags=re.IGNORECASE).strip()
                    if _app_name and len(_app_name.split()) <= 3:
                        _open_fp(_app_name); self.speak(f"Opening {_app_name}."); _sc_handled = True
                elif re.search(r'\b(close|quit|exit|kill|force quit|force close)\b\s+(?!all\b)', _rc):
                    _km = re.search(r'\b(?:close|quit|exit|kill|force\s+(?:quit|close))\s+(.+)', _rc)
                    if _km:
                        _kt = _km.group(1).strip()
                        if len(_kt.split()) <= 3 and _kt not in ('all', 'everything', 'them'):
                            ok, _msg = _sc_fp.kill_app(_kt); self.speak(_msg); _sc_handled = True
            except Exception as _fpe:
                import logging as _lfp; _lfp.getLogger("iZACH.Chain").debug(f"[SC fast] {_fpe}")

            if _sc_handled:
                continue

            # ── 4. Spotify "play X on spotify" (phone sends this phrase) ─
            _SPO_DIRECT_RE = re.compile(
                r'^(?:play|stream|put on|start playing)\s+(.+?)\s+(?:on|in|via|through|using)\s+spotify\s*$',
                re.IGNORECASE,
            )
            _spo_m = _SPO_DIRECT_RE.match(resolved_cmd)
            if _spo_m:
                resolved_cmd = f"play {_spo_m.group(1).strip()}"
                self._domain_ctx = {"domain": "spotify", "confidence": 0.99}

            # ══════════════════════════════════════════════════════════
            # END FAST-PATHS — orchestrator runs below
            # ══════════════════════════════════════════════════════════

            # ── Synonym learner: pre-route known corrected phrasings ─
            _synonym_domain = None
            try:
                from modules.synonym_learner import match_synonym as _match_syn
                _synonym_domain = _match_syn(resolved_cmd)
            except Exception:
                pass

            # ── Orchestrator: classify intent before routing ───────
            if self.agent_orch:
                # Don't let the LLM classifier override a fast-path that
                # already pinned a domain with high confidence (e.g. the
                # Spotify "play X on spotify" regex above) — it was silently
                # discarding that every time, so an unusual song title could
                # get misclassified as "chat" and fall through to a generic
                # conversational reply that sounds like it played something
                # but never touches the real Spotify API at all.
                if self._domain_ctx.get("confidence", 0.0) < 0.9:
                    self._domain_ctx = self.agent_orch.classify(resolved_cmd)
                # If orchestrator is unsure (chat / low confidence) but synonym
                # learner has seen this phrasing succeed before, trust the synonym.
                if _synonym_domain and (
                    self._domain_ctx["domain"] == "chat"
                    or self._domain_ctx.get("confidence", 1.0) < 0.55
                ):
                    self._domain_ctx["domain"] = _synonym_domain
                    self._domain_ctx["confidence"] = 0.75  # synthetic confidence
            else:
                self._domain_ctx = {"domain": "chat", "confidence": 0.0, "summary": ""}
                if _synonym_domain:
                    self._domain_ctx["domain"] = _synonym_domain
            _domain = self._domain_ctx["domain"]

            # Update route info so voice_loop can track success/failure
            import modules.command_chain as _self_mod
            _self_mod._last_route_info = {
                "domain":     _domain,
                "handled":    False,  # updated to True if an agent handles it
                "confidence": float(self._domain_ctx.get("confidence", 0.0)),
            }

            # Broadcast classification to UI (skips "chat" — no pill for general convo)
            if _domain != "chat":
                try:
                    from modules.ws_bridge import broadcast as _bc
                    _bc({
                        "type":       "agent_active",
                        "domain":     _domain,
                        "confidence": round(float(self._domain_ctx.get("confidence", 0)), 2),
                    })
                except Exception:
                    pass

            # ── Subconsciousness: permission response intercept ───
            # If there's a pending permission gate, consume yes/no before
            # routing to any other handler.
            try:
                from modules import subconsciousness as _sc
                if _sc.get_pending() and _sc.handle_voice_response(resolved_cmd):
                    import modules.command_chain as _cc_mod
                    _cc_mod._last_route_info["handled"] = True
                    continue
            except Exception:
                pass

            # Curiosity engine answer intercept — captures reply to iZACH's
            # own question before any intent routing runs (text UI path).
            try:
                from modules.curiosity_engine import is_waiting_for_answer, capture_answer
                if is_waiting_for_answer():
                    capture_answer(resolved_cmd)
                    return
            except Exception:
                pass

            # Calendar event confirmation (JARVIS-style: "Should I add X?")
            try:
                from modules import event_extractor as _ev_ext
                if _ev_ext.has_pending_event():
                    _words = set(resolved_cmd.split())
                    _affirm = {"yes", "yeah", "yep", "sure", "ok", "okay", "haan", "add", "please"}
                    _negate = {"no", "nope", "nahi", "skip", "dont", "cancel"}
                    if _words & _affirm and len(_words) <= 4:
                        _ev_ext.confirm_pending_event()
                        continue
                    elif _words & _negate and len(_words) <= 4:
                        _ev_ext.reject_pending_event()
                        continue
            except Exception:
                pass

            # App install confirmation
            if self._pending_install:
                _words = set(resolved_cmd.split())
                _affirm = {"yes", "yeah", "yep", "sure", "ok", "okay", "download", "install", "haan"}
                _negate = {"no", "nope", "nahi", "skip", "cancel", "dont"}
                if _words & _affirm and len(_words) <= 4:
                    _app = self._pending_install
                    self._pending_install = None
                    from modules.app_installer import download_installer
                    import threading as _thr
                    _thr.Thread(
                        target=lambda a=_app: self.speak(download_installer(a)[1]),
                        daemon=True,
                    ).start()
                    continue
                elif _words & _negate and len(_words) <= 4:
                    self._pending_install = None
                    self.speak("Okay, skipping installation.")
                    continue

            # ── Widget voice commands (BEFORE agent fast-paths to avoid mis-routing) ──
            # "open spotify widget", "show whatsapp and phone widget"
            # "close all widgets except spotify and whatsapp widgets"
            _WIDGET_NAME_MAP = {
                'spotify': 'p-audio', 'music': 'p-audio', 'audio': 'p-audio',
                'chat': 'p-comm', 'comm': 'p-comm',
                'whatsapp messages': 'p-msg', 'messages': 'p-msg', 'msg': 'p-msg',
                'weather': 'p-wx', 'wx': 'p-wx',
                'phone': 'p-phone', 'android': 'p-phone',
                'system': 'p-sys', 'sysmon': 'p-sys',
                'intel': 'p-intel', 'intelligence': 'p-intel',
                'memory': 'p-mem', 'recall': 'p-mem',
                'schedule': 'p-sched', 'sched': 'p-sched',
                'relationship': 'p-rel', 'people': 'p-rel',
                'feed': 'p-feed', 'activity': 'p-feed',
                'history': 'p-hist',
                'clock': 'p-clock', 'world clock': 'p-clock',
                'fitness': 'p-fit', 'health': 'p-fit', 'steps': 'p-fit',
                'location': 'p-loc', 'whereami': 'p-loc', 'gps': 'p-loc',
                'ocr': 'p-ocr', 'scan document': 'p-ocr', 'document scan': 'p-ocr',
                'printer': 'p-print', 'print': 'p-print',
                'smart home': 'p-sh', 'home control': 'p-sh', 'iot': 'p-sh',
                'thermostat': 'p-sh', 'nest': 'p-sh', 'chromecast': 'p-sh',
                'instagram': 'p-ig', 'dms': 'p-ig', 'instagram inbox': 'p-ig',
                'news': 'p-news', 'headlines': 'p-news', 'live news': 'p-news',
                'market': 'p-news', 'stocks': 'p-news',
            }
            _has_widget_kw = (
                'widget' in resolved_cmd or
                'panel' in resolved_cmd or
                'cortex' in resolved_cmd   # "show spotify on cortex"
            )
            _close_all_except = ('close all' in resolved_cmd or 'hide all' in resolved_cmd) and 'except' in resolved_cmd
            _is_widget_cmd = _has_widget_kw and any(v in resolved_cmd for v in ('open', 'show', 'close', 'hide', 'display'))

            if _is_widget_cmd or _close_all_except:
                _wids = []
                for _wname, _wid in sorted(_WIDGET_NAME_MAP.items(), key=lambda x: -len(x[0])):
                    if _wname in resolved_cmd and _wid not in _wids:
                        _wids.append(_wid)
                try:
                    from modules.ws_bridge import broadcast as _bc
                    if _close_all_except:
                        _bc({"type": "ui_command", "action": "close_all_except", "ids": _wids})
                        self.speak("Done.")
                    elif 'close all' in resolved_cmd or 'hide all' in resolved_cmd:
                        _bc({"type": "ui_command", "action": "close_all_except", "ids": []})
                        self.speak("All widgets closed.")
                    elif ('show all' in resolved_cmd or 'open all' in resolved_cmd):
                        _bc({"type": "ui_command", "action": "show_all"})
                        self.speak("Opening all widgets.")
                    elif ('close' in resolved_cmd or 'hide' in resolved_cmd) and _wids:
                        _bc({"type": "ui_command", "action": "close_widget", "ids": _wids})
                        self.speak("Done.")
                    elif _wids:
                        _bc({"type": "ui_command", "action": "show_widget", "ids": _wids})
                        self.speak("Done.")
                    else:
                        self.speak("Which widget would you like me to open?")
                except Exception:
                    pass
                continue

            # ── Spotify device-switch fast-path ───────────────────
            # "switch to OnePlus/TV/phone" mid-playback was mis-routed to
            # SystemAgent as open_app. Intercept it here before agents run.
            _SPO_SWITCH_RE = re.compile(
                r'(?:switch|transfer|move|change|cast|play)\s+'
                r'(?:spotify|music|playback|audio|the\s+music|it)?\s*'
                r'(?:to|on)\s+(?:my\s+)?(.+)',
                re.IGNORECASE,
            )
            _DEVICE_HINTS = {
                'phone', 'mobile', 'tv', 'television', 'laptop', 'pc', 'computer',
                'speaker', 'oneplus', 'samsung', 'iphone', 'android', 'tablet',
                'allied', 'alliednode', 'echo', 'alexa', 'homepod', 'chromecast',
            }
            _spo_sw_m = _SPO_SWITCH_RE.match(resolved_cmd)
            if _spo_sw_m:
                _sw_target = _spo_sw_m.group(1).strip().lower()
                # Only intercept if target looks like a device, not an app/website
                _is_device_switch = any(h in _sw_target for h in _DEVICE_HINTS) or (
                    len(_sw_target.split()) <= 3 and
                    not any(w in _sw_target for w in ('mode', 'theme', 'tab', 'page', 'view'))
                )
                if _is_device_switch:
                    # Force spotify domain and let SpotifyAgent handle it
                    _domain = "spotify"
                    self._domain_ctx["domain"] = "spotify"
                    self._domain_ctx["confidence"] = 0.95

            # ── Smart Home fast-path (BEFORE agents, to prevent mis-routing to open_app) ──
            # "turn on samsung AC", "turn off LG TV", "ac on", "cool mode", etc.
            _SH_PRE_TRIGGERS = [
                "set ac", "turn on ac", "turn off ac", "ac on", "ac off",
                "set temperature", "set temp", "cool mode", "heat mode",
                "set thermostat", "fan on", "fan off", "start fan", "stop fan",
                "pause tv", "play tv", "resume tv", "stop tv", "mute tv",
                "cast to tv", "cast video",
            ]
            _SH_PRE_BRAND_RE = re.compile(
                r'\b(turn\s+(?:on|off)|switch\s+(?:on|off)|start|stop)\b'
                r'.*\b(?:samsung|lg|panasonic|daikin|hitachi|voltas|carrier|whirlpool|haier|'
                r'sony|toshiba|sharp|mitsubishi|midea|tcl|hisense|oneplus|mi|xiaomi)?\s*'
                r'(ac|air\s*conditioner|air\s*con|hvac|tv|television)\b',
                re.IGNORECASE,
            )
            if any(t in resolved_cmd for t in _SH_PRE_TRIGGERS) or _SH_PRE_BRAND_RE.search(resolved_cmd):
                try:
                    from modules.smart_home_engine import execute_voice_command as _sh_exec
                    _sh_result = _sh_exec(resolved_cmd)
                    if _sh_result.get("success"):
                        self.speak(_sh_result.get("message", "Done"))
                        continue
                    else:
                        _sh_err = _sh_result.get("error", "")
                        if _sh_err and _sh_err not in ("Command not recognized", ""):
                            self.speak(_sh_result.get("message", _sh_err))
                            continue
                        # Unrecognized by smart home engine — fall through to agents
                except Exception as _sh_pre_err:
                    import logging as _l; _l.getLogger("iZACH.Chain").debug(f"[SH-pre] {_sh_pre_err}")

            # ── Web automation (before agent dispatch, to intercept "open X" /
            # "play X on youtube" that the orchestrator/SystemAgent mis-routes
            # as domain=system, intent=open_app, app_name=youtube) ──────────
            _WEB_AUTOMATION_TRIGGERS = [
                # navigate
                "open youtube", "open google", "open github", "open gmail", "open reddit",
                "open instagram", "open linkedin", "open twitter", "open netflix",
                "open amazon", "open flipkart", "open website", "go to",
                "open chatgpt", "open chat gpt", "open perplexity", "open claude",
                "open pinterest", "open google slides", "open slides",
                "open google colab", "open colab",
                # search
                "search on google", "google search", "look up on google",
                # summarize
                "summarize this page", "summarize page", "what does this page say",
                "what's on this page", "read this page", "explain this page",
                "summarize this website", "what does this website say",
                # click
                "click on", "click the", "press the button", "press button",
                # scroll
                "scroll down", "scroll up", "scroll to top", "scroll to bottom",
                "scroll back up", "scroll back down",
                # tabs
                "open new tab", "new tab", "close tab", "close this tab",
                "switch tab", "next tab", "previous tab", "switch to tab",
                "list tabs", "show tabs", "what tabs",
                # youtube
                "play on youtube", "youtube play", "search youtube for",
                "find on youtube", "open youtube and play",
                "play something on youtube", "play on yt", "search on youtube",
                "search on youtube for", "find on youtube for", "youtube search",
                # news
                "what's in the news", "latest news", "read news",
                "today's news", "news headlines", "what's happening",
                "tell me the news", "any news",
                # price
                "check price of", "price of", "how much is", "how much does",
                "find price", "what's the price", "price check",
                # login
                "log in to", "login to", "sign in to", "log into",
                "auto login", "login automatically",
                # form / email (existing)
                "fill form", "autofill", "fill the form", "fill this form",
                "fill these details", "fill my details", "fill this for me", "fill details",
                "feel this form", "feel these details", "feel this details",
                "feel the form", "feel my details",
                "extract emails", "find emails", "scrape emails",
            ]
            # YouTube regex patterns: "play X on youtube", "search on youtube for X"
            _YT_RE = re.compile(
                r'\b(?:play|put on|stream)\s+.+\s+on\s+(?:youtube|yt)\b'
                r'|\bsearch\s+(?:on\s+)?youtube\s+(?:for\s+)?'
                r'|\bsearch\s+on\s+youtube\s+for\s+'
                r'|\byoutube\s+search\b',
                re.IGNORECASE,
            )
            if any(t in resolved_cmd for t in _WEB_AUTOMATION_TRIGGERS) or _YT_RE.search(resolved_cmd):
                self._handle_web_automation(resolved_cmd)
                continue

            # ── Agent fast-paths ──────────────────────────────────
            # Each agent returns True when it handled the command.
            # We mark _last_route_info["handled"] so the synonym learner in
            # voice_loop can call record_success() for the right domain.

            def _agent_handled():
                import modules.command_chain as _m
                _m._last_route_info["handled"] = True

            if _domain == "whatsapp" and self._wa_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "calendar" and self._cal_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "system" and self._sys_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "research" and self._res_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "spotify" and self._spo_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "file" and self._file_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "memory" and self._mem_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            if _domain == "vision" and self._vis_agent.handle(resolved_cmd, self._domain_ctx):
                _agent_handled(); continue

            # Multi-tab browser command
            _MULTI_TAB_MARKERS = ["one for", "another tab", "first tab", "second tab",
                                   "two tabs", "2 tabs", "3 tabs", "multiple tabs",
                                   "in one tab", "in a tab", "in another tab"]
            if "tab" in resolved_cmd and any(m in resolved_cmd for m in _MULTI_TAB_MARKERS):
                _tabs = self._parse_multi_tab_command(resolved_cmd)
                if _tabs and len(_tabs) >= 2:
                    from modules import web_automation as _wa
                    import threading as _thr
                    self.speak(f"Opening {len(_tabs)} tabs.")
                    _thr.Thread(
                        target=lambda t=_tabs: self.speak(_wa.open_multiple_tabs(t)[1]),
                        daemon=True,
                    ).start()
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
            "good morning", "good afternoon", "good evening", "daily briefing", "morning briefing", "give me a briefing",
            "force quit", "force close", "kill process", "end process", "terminate process", "end task",
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
            _ROUTINE_TRIGGERS = [
                "yes automate", "automate it", "yes automate it", "yeah automate",
                "no skip", "no don't automate", "skip it", "don't automate", "no automate",
                "show my routines", "list routines", "what routines", "my routines",
                "delete routine", "remove routine",
            ]
            if any(t in resolved_cmd for t in _ROUTINE_TRIGGERS):
                self._handle_routine_command(resolved_cmd)
                continue

            _CALENDAR_TRIGGERS = [
                "cancel my", "cancelled", "cancel the", "remove from calendar", "delete from calendar",
                "remove all events", "delete all events", "clear my calendar", "clear calendar",
                "reschedule", "rescheduled", "instead of", "moved to", "change the time",
                "change time", "now at", "meeting at", "class at", "gym at", "session at",
                "what's on my calendar", "what's in my calendar", "my schedule", "show my events",
                "what events", "upcoming events", "add to calendar", "add event",
            ]
            if any(t in resolved_cmd for t in _CALENDAR_TRIGGERS):
                self._handle_calendar_voice_command(resolved_cmd)
                continue

            # Smart clipboard response
            try:
                from modules.clipboard_sync import is_awaiting_clipboard_action, handle_clipboard_response
                if is_awaiting_clipboard_action():
                    if handle_clipboard_response(resolved_cmd):
                        continue
            except Exception:
                pass

            # Clipboard history search
            _CLIP_HIST_TRIGGERS = [
                "clipboard history", "what did i copy", "what i copied",
                "show clipboard", "paste the link i copied", "search clipboard",
                "find in clipboard", "what was i copying",
            ]
            if any(t in resolved_cmd for t in _CLIP_HIST_TRIGGERS):
                try:
                    from modules.clipboard_sync import get_history, search_history
                    # Extract search term if present
                    search_term = ""
                    for prefix in ["find in clipboard", "search clipboard for", "search clipboard"]:
                        if prefix in resolved_cmd:
                            search_term = resolved_cmd.split(prefix, 1)[-1].strip()
                            break
                    entries = search_history(search_term) if search_term else get_history()
                    if not entries:
                        self.speak("Clipboard history is empty." if not search_term else f"No clipboard entry matching '{search_term}'.")
                    else:
                        top = entries[:5]
                        lines = [f"{i+1}. [{e['ts']}] {e['text'][:60]}" for i, e in enumerate(top)]
                        self.speak(f"Last {len(top)} clipboard items: " + "; ".join(
                            f"{e['ts']}: {e['text'][:40]}" for e in top[:3]
                        ))
                        try:
                            from modules.ws_bridge import broadcast
                            broadcast({"type": "clipboard_history", "entries": top})
                        except Exception:
                            pass
                except Exception as _ce:
                    print(f"[CLIPBOARD HISTORY] Error: {_ce}")
                continue

            # Deep research
            _RESEARCH_TRIGGERS = [
                "research ", "deep research", "look into ", "investigate ",
                "find out about ", "what do you know about ",
                "gather info on ", "give me a report on ",
                "full report on ", "comprehensive info on ",
            ]
            if any(t in resolved_cmd for t in _RESEARCH_TRIGGERS) or _this_resolved:
                self._handle_deep_research(resolved_cmd)
                continue

            # WhatsApp group summarizer
            _GROUP_SUM_TRIGGERS = [
                "summarize", "catch me up on", "what happened in",
                "what's going on in", "group update", "group summary",
            ]
            _GROUP_WORDS = ["group", "chat", "whatsapp group"]
            if (any(t in resolved_cmd for t in _GROUP_SUM_TRIGGERS) and
                    any(w in resolved_cmd for w in _GROUP_WORDS)):
                self._handle_group_summarize(resolved_cmd)
                continue

            _SHELL_TRIGGERS = [
                "run command", "run powershell", "execute command", "run script",
                "run terminal command", "run this command", "execute this command",
                "open terminal", "open powershell", "shell command",
                "powershell command", "run ps", "run ps command",
                "confirm command", "yes run it", "run it", "confirm run",
                "cancel command", "cancel the command", "don't run",
            ]
            if any(t in resolved_cmd for t in _SHELL_TRIGGERS):
                self._handle_shell_command(resolved_cmd)
                continue

            # ── PHASE 4: SMART HOME VOICE COMMANDS ──────────────────────────
            _SH_TRIGGERS = [
                "set ac", "turn on ac", "turn off ac", "ac on", "ac off",
                "set temperature", "set temp", "cool mode", "heat mode",
                "set thermostat", "fan on", "fan off", "start fan", "stop fan",
                "pause tv", "play tv", "resume tv", "stop tv", "mute tv",
                "volume up", "volume down", "set volume",
                "cast to tv", "cast video",
                "smart home",
            ]
            # Regex catches brand-prefixed devices: "turn off Samsung AC",
            # "turn on LG AC", "turn off Samsung TV", etc.
            _SH_BRAND_RE = re.compile(
                r'\b(turn\s+(?:on|off)|switch\s+(?:on|off)|start|stop)\b'
                r'.*\b(?:samsung|lg|panasonic|daikin|hitachi|voltas|carrier|whirlpool|haier|'
                r'sony|toshiba|sharp|mitsubishi|midea|tcl|hisense|oneplus|mi|xiaomi)?\s*'
                r'(ac|air\s*conditioner|air\s*con|hvac|tv|television)\b',
                re.IGNORECASE,
            )
            if any(t in resolved_cmd for t in _SH_TRIGGERS) or _SH_BRAND_RE.search(resolved_cmd):
                try:
                    from modules.smart_home_engine import execute_voice_command
                    result = execute_voice_command(resolved_cmd)
                    if result.get("success"):
                        self.speak(result.get("message", "Done"))
                    else:
                        err = result.get("error", "")
                        if err and err != "Command not recognized":
                            self.speak(result.get("message", err))
                        else:
                            self._classify_and_execute(resolved_cmd)
                except Exception as _she:
                    import logging as _l; _l.getLogger("iZACH.Chain").debug(f"[SH] {_she}")
                    self._classify_and_execute(resolved_cmd)
                continue

            # ── PHASE 6: NEWS VOICE COMMANDS ─────────────────────────────────
            _NEWS_TRIGGERS = [
                "read news", "today's news", "latest news", "tell me the news",
                "news briefing", "what's in the news", "news headlines",
                "what's happening", "give me news", "any news",
                "india news", "world news", "tech news", "sports news",
                "business news", "cricket news", "politics news",
                "market update", "stock market", "sensex", "nifty",
                "market snapshot", "tell me more about headline",
            ]
            if any(t in resolved_cmd for t in _NEWS_TRIGGERS):
                try:
                    from modules.news_engine import execute_voice_command as _news_cmd
                    result = _news_cmd(resolved_cmd)
                    if result.get("success"):
                        pass  # news engine already spoke via _speak_fn
                    else:
                        self._classify_and_execute(resolved_cmd)
                except Exception as _ne:
                    import logging as _l; _l.getLogger("iZACH.Chain").debug(f"[NEWS] {_ne}")
                    self._classify_and_execute(resolved_cmd)
                continue

            # ── PHASE 5B: INSTAGRAM VOICE COMMANDS ──────────────────────────
            _IG_TRIGGERS = [
                "instagram", "my followers", "follower count", "how many followers",
                "check dms", "instagram inbox", "instagram messages",
                "post to instagram", "instagram post", "post a photo",
                "auto reply", "enable auto reply", "disable auto reply",
                "stop auto reply", "start auto reply",
            ]
            if any(t in resolved_cmd for t in _IG_TRIGGERS):
                try:
                    from modules.instagram_engine import execute_voice_command as _ig_cmd
                    result = _ig_cmd(resolved_cmd)
                    if result.get("success"):
                        self.speak(result.get("message", "Done"))
                    else:
                        msg = result.get("message", "")
                        if msg and msg != "Command not recognized for Instagram.":
                            self.speak(msg)
                        else:
                            self._classify_and_execute(resolved_cmd)
                except Exception as _ige:
                    import logging as _l; _l.getLogger("iZACH.Chain").debug(f"[IG] {_ige}")
                    self._classify_and_execute(resolved_cmd)
                continue

            _kill_route = any(resolved_cmd.startswith(p) for p in ("force quit ", "force close ", "end task ", "kill process ", "terminate process ", "close "))
            if "playlist" in resolved_cmd or resolved_cmd.startswith("open ") or _kill_route or any(t in resolved_cmd for t in _SYSTEM_CONTROL_TRIGGERS) or any(m in resolved_cmd for m in _FILE_FAST_PATH + ["screenshot", "capture screen", "take a screenshot", "screen capture", "what am i holding", "what's in my hand", "what do you see", "look at this", "what is this", "identify this", "what's this", "how many calories", "what food is this", "scan this", "describe what you see", "what can you see", "look at camera", "work mode", "focus mode", "gym mode", "idle mode", "switch to work", "switch to focus", "switch to gym", "switch to idle", "click on", "click the", "read the screen", "what's on screen", "read screen", "remember that", "remember this", "what do you remember", "forget that", "reply to", "reply her", "reply him", "what did he say", "what did she say", "bitcoin", "ethereum", "crypto", "btc price", "eth price", "dogecoin", "solana", "crypto rate"]):
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

        # "this" → last researched topic  ("who is the teacher in this?")
        if re.search(r'\bthis\b', query):
            try:
                from modules.context_memory import get_context_memory
                _rt = get_context_memory().get_entity("last_research_topic")
                if _rt:
                    resolved = re.sub(r'\bthis\b', _rt, resolved)
            except Exception:
                pass

        return resolved

    def _handle_web_automation(self, cmd):
        import threading
        from modules import web_automation

        def _bg(fn, *args, announce=None):
            if announce:
                self.speak(announce)
            def _run():
                ok, msg = fn(*args)
                if not ok or announce is None:
                    self.speak(msg)
            threading.Thread(target=_run, daemon=True).start()

        # ── Summarize page ─────────────────────────────────────
        if any(t in cmd for t in [
            "summarize this page", "summarize page", "what does this page say",
            "what's on this page", "read this page", "explain this page",
            "summarize this website", "what does this website say",
        ]):
            _bg(web_automation.summarize_page, announce="Reading the page.")
            return

        # ── Voice-driven browsing (internal Browser widget, not Playwright) ──
        # Distinct from "scroll down"/"click on X"/"go back" below, which stay
        # on the Playwright automation engine — these all require the word
        # "browser" so the two paths never collide.
        _BROWSER_ORDINALS = {
            "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4, "fifth": 5, "5th": 5,
        }
        if re.search(r'\bbrowser\s+scroll\s+(down|up)\b|\bscroll\s+(?:the\s+)?browser\s+(down|up)\b', cmd, re.IGNORECASE):
            _m = re.search(r'\b(down|up)\b', cmd, re.IGNORECASE)
            direction = _m.group(1).lower() if _m else "down"
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "browser_command", "action": "scroll", "direction": direction})
            except Exception:
                self.speak("Browser isn't open.")
            return

        if re.search(r'\bbrowser\s+(back|forward)\b|\b(?:go\s+)?back\s+in\s+(?:the\s+)?browser\b|\bforward\s+in\s+(?:the\s+)?browser\b', cmd, re.IGNORECASE):
            direction = "fwd" if "forward" in cmd.lower() else "back"
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "browser_command", "action": "nav", "direction": direction})
            except Exception:
                self.speak("Browser isn't open.")
            return

        _browser_link_m = re.search(
            r'\bbrowser\s+click\s+link\s+(\d+|\w+)\b|\bclick\s+(?:the\s+)?(\d+|\w+)(?:st|nd|rd|th)?\s+link\s+in\s+(?:the\s+)?browser\b',
            cmd, re.IGNORECASE,
        )
        if _browser_link_m:
            raw = next((g for g in _browser_link_m.groups() if g), "1").lower()
            index = int(raw) if raw.isdigit() else _BROWSER_ORDINALS.get(raw, 1)
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "browser_command", "action": "click_link", "index": index})
            except Exception:
                self.speak("Browser isn't open.")
            return

        # ── Click element ──────────────────────────────────────
        if any(t in cmd for t in ["click on", "click the", "press the button", "press button"]):
            target = cmd
            for phrase in ["click on", "click the", "click", "press the button", "press button", "press"]:
                target = target.replace(phrase, "").strip()
            if not target:
                self.speak("What should I click?")
                return
            _bg(web_automation.click_element, target, announce=f"Clicking {target}.")
            return

        # ── Scroll ─────────────────────────────────────────────
        if any(t in cmd for t in ["scroll down", "scroll up", "scroll to top",
                                   "scroll to bottom", "scroll back"]):
            if "bottom" in cmd:
                direction = "bottom"
            elif "top" in cmd:
                direction = "top"
            elif "up" in cmd or "back up" in cmd:
                direction = "up"
            else:
                direction = "down"
            _bg(web_automation.scroll, direction)
            return

        # ── Tab management ─────────────────────────────────────
        if any(t in cmd for t in ["list tabs", "show tabs", "what tabs"]):
            _, msg = web_automation.list_tabs()
            self.speak(msg)
            return

        if any(t in cmd for t in ["open new tab", "new tab"]):
            url = cmd
            for phrase in ["open new tab", "new tab", "open"]:
                url = url.replace(phrase, "").strip()
            _bg(web_automation.new_tab, url or None, announce="Opening new tab.")
            return

        if any(t in cmd for t in ["close tab", "close this tab"]):
            _bg(web_automation.close_tab)
            return

        if any(t in cmd for t in ["switch tab", "next tab", "previous tab", "switch to tab"]):
            if "next" in cmd:
                hint = "next"
            elif "previous" in cmd or "prev" in cmd or "back" in cmd:
                hint = "prev"
            else:
                hint = cmd
                for phrase in ["switch to tab", "switch to", "switch tab", "switch"]:
                    hint = hint.replace(phrase, "").strip()
                hint = hint or "next"
            _bg(web_automation.switch_tab, hint)
            return

        # ── YouTube autoplay ───────────────────────────────────
        _YT_TRIGGERS = [
            "play on youtube", "youtube play", "search youtube for",
            "find on youtube", "open youtube and play",
            "play something on youtube", "play on yt", "search on youtube",
            "search on youtube for", "youtube search",
        ]
        _YT_REGEX = re.compile(
            r'\b(?:play|put on|stream)\s+(.+?)\s+on\s+(?:youtube|yt)\b'
            r'|\bsearch\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)'
            r'|\bsearch\s+on\s+youtube\s+for\s+(.+)',
            re.IGNORECASE,
        )
        # "play X music video" / "play X video" (no "on youtube") → YouTube, visible.
        _YT_VIDEO_REGEX = re.compile(
            r'\b(?:play|put on|stream)\s+(.+?\b(?:music video|official video|video|mv|trailer))\b',
            re.IGNORECASE,
        )
        _yt_vid_only = _YT_VIDEO_REGEX.search(cmd)
        if any(t in cmd for t in _YT_TRIGGERS) or _YT_REGEX.search(cmd) or _yt_vid_only:
            # Try regex extraction first (handles "play X on youtube")
            _yt_m = _YT_REGEX.search(cmd)
            if _yt_m:
                query = next((g for g in _yt_m.groups() if g), "").strip()
            elif _yt_vid_only:
                query = _yt_vid_only.group(1).strip()
            else:
                query = cmd
                for phrase in sorted([
                    "open youtube and play", "search on youtube for", "search youtube for",
                    "play on youtube", "search on youtube", "youtube search",
                    "youtube play", "find on youtube", "play on yt",
                    "play something on youtube", "youtube",
                ], key=len, reverse=True):
                    query = query.replace(phrase, "").strip()
            if not query:
                self.speak("What should I play on YouTube?")
                return

            # Video mode (visible) when the command names a video; else audio
            # (background). Examples: "play X music video" → visible;
            # "play X on youtube" → background song.
            mode = "video" if re.search(r'\b(?:music video|official video|video|mv|trailer|watch)\b', cmd, re.IGNORECASE) else "audio"

            # Prefer iZACH's internal browser when the UI is connected;
            # fall back to the Playwright engine when running headless.
            try:
                from modules.ws_bridge import broadcast, has_clients
                if has_clients():
                    broadcast({"type": "browser_command", "action": "youtube_play",
                               "query": query, "mode": mode})
                    if mode == "video":
                        self.speak(f"Playing {query}.")
                    else:
                        self.speak(f"Playing {query} in the background.")
                    return
            except Exception:
                pass

            _bg(web_automation.youtube_play, query, announce=f"Finding {query} on YouTube.")
            return

        # ── News ───────────────────────────────────────────────
        if any(t in cmd for t in [
            "what's in the news", "latest news", "read news",
            "today's news", "news headlines", "what's happening",
            "tell me the news", "any news",
        ]):
            topic = cmd
            for phrase in ["what's in the news", "latest news", "read news", "today's news",
                           "news headlines", "what's happening", "tell me the news",
                           "any news", "about", "on"]:
                topic = topic.replace(phrase, "").strip()
            _bg(web_automation.get_news, topic, announce="Fetching the latest news.")
            return

        # ── Price lookup ───────────────────────────────────────
        if any(t in cmd for t in [
            "check price of", "price of", "how much is", "how much does",
            "find price", "what's the price", "price check",
        ]):
            product = cmd
            for phrase in ["check price of", "price of", "how much is", "how much does",
                           "find price of", "find price", "what's the price of",
                           "what's the price", "price check for", "price check"]:
                product = product.replace(phrase, "").strip()
            if not product:
                self.speak("What product should I check the price of?")
                return
            # Not using _bg() here — its `not ok or announce is None` check
            # means a SUCCESSFUL lookup's actual price never got spoken (only
            # the "Checking price of X" announce played, then silence).
            self.speak(f"Checking price of {product}.")
            def _speak_price_result():
                ok, msg = web_automation.lookup_price(product)
                self.speak(msg)
            threading.Thread(target=_speak_price_result, daemon=True).start()
            return

        # ── Login ──────────────────────────────────────────────
        if any(t in cmd for t in ["log in to", "login to", "sign in to",
                                   "log into", "auto login", "login automatically"]):
            _bg(web_automation.login_to_site, announce="Attempting auto login.")
            return

        # ── Restart browser (clear CAPTCHA-flagged session) ────
        if any(t in cmd for t in ["restart browser", "reset browser", "clear browser session"]):
            try:
                web_automation.restart_browser()
                self.speak("Browser restarted with a fresh session.")
            except Exception as e:
                self.speak(f"Could not restart browser: {e}")
            return

        # ── Google search ──────────────────────────────────────
        if any(t in cmd for t in ["search on google", "google search", "look up on google"]):
            query = cmd
            for t in ["search on google", "look up on google", "google search"]:
                query = query.replace(t, "").strip()
            if not query:
                self.speak("What should I search for?")
                return
            _bg(web_automation.search_google, query, announce=f"Searching for {query}.")
            return

        # ── Bookmarks (Browser widget / Settings → Custom Links) ────────────
        if any(t in cmd for t in [
            "my bookmarks", "list bookmarks", "list my bookmarks", "show my bookmarks",
            "show bookmarks", "what are my bookmarks", "bookmarks folder", "bookmark folder",
        ]):
            folder = None
            for marker in ("bookmarks folder", "bookmark folder"):
                if marker in cmd:
                    folder = cmd.split(marker, 1)[1].strip() or None
                    break
            self.speak(web_automation.list_bookmarks(folder))
            return

        # ── Open website ───────────────────────────────────────
        if any(t in cmd for t in ["open youtube", "open google", "open github", "open gmail",
                                   "open reddit", "open instagram", "open linkedin", "open twitter",
                                   "open netflix", "open amazon", "open flipkart",
                                   "open website", "go to",
                                   "open chatgpt", "open chat gpt", "open perplexity", "open claude",
                                   "open pinterest", "open google slides", "open slides",
                                   "open google colab", "open colab"]):
            target = cmd
            for phrase in sorted(
                ["go to", "open website", "open youtube", "open google", "open github",
                 "open gmail", "open reddit", "open instagram", "open linkedin",
                 "open twitter", "open netflix", "open amazon", "open flipkart",
                 "open pinterest", "open google slides", "open slides",
                 "open google colab", "open colab", "open"],
                key=len, reverse=True,
            ):
                target = target.replace(phrase, "").strip()
            if not target:
                for name in web_automation._SHORTNAMES:
                    if name in cmd:
                        target = name
                        break
            if not target:
                self.speak("Which website?")
                return
            # Check if user explicitly said "app" or "website"
            wants_app = any(w in cmd for w in ["as app", "the app", "app version", "app"])
            wants_web = any(w in cmd for w in ["website", "browser", "in chrome", "in browser", "web"])
            if wants_app and target in web_automation._APP_CAPABLE:
                from modules.automation import open_app
                _APP_LAUNCH_NAMES = {
                    "youtube":   "YouTube",
                    "github":    "GitHub Desktop",
                    "instagram": "Instagram",
                    "pinterest": "Pinterest",
                }
                app_name = _APP_LAUNCH_NAMES.get(target, target.title())
                open_app(app_name)
                self.speak(f"Opening {app_name} app.")
                return
            if not wants_web and target in web_automation._APP_CAPABLE:
                if web_automation.is_app_installed(target):
                    self.awaiting_app_or_web = True
                    self.pending_open_service = target
                    self.speak(f"Open {target.title()} as app or website?")
                    return
            # User wants to OPEN a website — use the system default browser,
            # not the Playwright/Chromium engine (which is reserved for
            # research/scraping/automation flows).
            try:
                url = web_automation._resolve_url(target)
                webbrowser.open(url)
                self.speak(f"Opening {target} in your default browser.")
            except Exception as _ow_err:
                # Fallback to Playwright Chromium if default-browser launch fails
                logger.warning(f"[open_website] Default browser failed: {_ow_err}")
                _bg(web_automation.open_website, target, announce=f"Opening {target}.")
            return

        # ── Form fill ──────────────────────────────────────────
        if any(t in cmd for t in [
            "fill form", "autofill", "fill the form", "fill this form",
            "fill these details", "fill my details", "fill this for me", "fill details",
            "feel this form", "feel these details", "feel this details",
            "feel the form", "feel my details",
        ]):
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
                self.speak("Filling form.")
            except Exception as e:
                self.speak(f"Could not fill form: {e}")
            return

        # ── Extract emails ─────────────────────────────────────
        if any(t in cmd for t in ["extract emails", "find emails", "scrape emails"]):
            _bg(web_automation.extract_emails, announce="Scanning page for emails.")
            return

    def _parse_multi_tab_command(self, cmd: str) -> list | None:
        """Use Groq to parse multi-tab voice command into [{action, target}, ...] list."""
        try:
            import json, os
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
            prompt = f"""Parse this browser command into a JSON array of tab actions.
Command: "{cmd}"

Return ONLY a valid JSON array. Each element must have:
  "action": "navigate" (open a website) or "search" (search Google)
  "target": website name/URL or search query string

Example output:
[{{"action": "navigate", "target": "github.com"}}, {{"action": "search", "target": "dog pictures"}}]

Return ONLY the JSON array. No explanation."""
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw.strip())
            if isinstance(parsed, list) and len(parsed) >= 2:
                return parsed
        except Exception:
            pass
        return None

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
            from modules.file_manager import get_file_manager
            fm = get_file_manager()
            fm.set_speak(self.speak)
            ok, msg = fm.delete_verified(chosen)
            self.speak(msg)
        return True

    def _delete_with_face_auth(self, filepath: str):
        """Verify owner identity then delete file."""
        import threading
        from modules import face_auth
        face_auth.init(self.speak)

        if not face_auth.is_enrolled():
            self.speak("Face auth not set up. Say 'enroll my face' first, then try deleting again.")
            return

        self.speak("Look at the camera to confirm deletion.")

        def _run():
            verified = face_auth.verify_owner()
            if verified:
                try:
                    import os as _os
                    name = _os.path.basename(filepath)
                    _os.remove(filepath)
                    self.speak(f"Identity confirmed. Deleted {name}.")
                except Exception as e:
                    self.speak(f"Verified but delete failed: {e}")
            else:
                self.speak("Face not recognized. Deletion cancelled.")

        threading.Thread(target=_run, daemon=True).start()

    # ── REMOTE NODE (AlliedNode 2) ──────────────────────────────────

    def _handle_remote_node_command(self, cmd: str):
        """Route commands targeting AlliedNode 2 over the local network."""
        import re as _re
        import threading as _thr
        from modules import remote_node as _rn

        node_name = "alliednode 2"

        # Strip node reference to get the bare action
        clean = _re.sub(
            r'\b(?:in|on|for|to)?\s*(?:'
            r'alliednode\s*2|allied\s*node\s*2|allied\s*note\s*2'
            r'|elite\s*node\s*2|elite\s*note\s*2|alliednote\s*2|allied\s*no\s*2'
            r')\b',
            '', cmd, flags=_re.IGNORECASE,
        ).strip()

        # ── Wake-on-LAN (works even when node is OFF) ────────────
        if any(w in cmd for w in ["turn on", "wake up", "power on", "wake ", "boot up", "switch on"]):
            r = _rn.wake_on_lan(node_name)
            if "error" in r:
                self.speak(f"Wake-on-LAN failed: {r['error']}")
            else:
                self.speak("Magic packet sent. AlliedNode 2 should wake up in about 10 seconds.")
            return

        # ── Install app via winget ────────────────────────────────
        _inst_m = _re.search(r'\binstall\s+(.+?)(?:\s+(?:in|on)\s+alliednode|$)', clean, _re.IGNORECASE)
        if _inst_m:
            app = _inst_m.group(1).strip()
            if not app:
                self.speak("What app should I install on AlliedNode 2?")
                return
            self.speak(f"Installing {app} on AlliedNode 2 via winget. May take a minute.")
            def _install(a=app):
                res = _rn.execute(
                    node_name,
                    f'winget install --exact --id "{a}" -h --accept-source-agreements --accept-package-agreements'
                )
                if "error" in res:
                    self.speak(f"Install failed: {res['error']}")
                elif (res.get("returncode") or 0) == 0:
                    self.speak(f"{a} installed successfully on AlliedNode 2.")
                else:
                    err = (res.get("stderr") or "")[:200]
                    self.speak(f"Install may have failed. {err}")
            _thr.Thread(target=_install, daemon=True).start()
            return

        # ── Screenshot ───────────────────────────────────────────
        if any(w in cmd for w in ["screenshot", "capture screen", "take screenshot",
                                   "screen grab", "screengrab", "screen capture"]):
            self.speak("Taking screenshot on AlliedNode 2.")
            r = _rn.take_screenshot(node_name)
            if "error" in r:
                self.speak(f"Screenshot failed: {r['error']}")
            else:
                import base64 as _b64, os as _os
                from datetime import datetime as _dt
                screenshots_dir = _os.path.join(_os.path.dirname(__file__), "..", "screenshots")
                _os.makedirs(screenshots_dir, exist_ok=True)
                fname = f"an2_{_dt.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                fpath = _os.path.join(screenshots_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(_b64.b64decode(r["screenshot"]))
                self.speak(f"Screenshot saved as {fname} in the screenshots folder.")
            return

        # ── Process list ─────────────────────────────────────────
        if any(w in cmd for w in ["processes", "running processes", "what's running",
                                   "task manager", "process list", "top processes", "what is running"]):
            r = _rn.get_processes(node_name, top=5)
            if "error" in r:
                self.speak(f"Couldn't get processes: {r['error']}")
            else:
                procs = r.get("processes", [])[:5]
                if not procs:
                    self.speak("No processes returned from AlliedNode 2.")
                else:
                    lines = ["Top processes on AlliedNode 2:"]
                    for p in procs:
                        mem = f"{p.get('memory_percent', 0):.1f}%"
                        lines.append(f"  {p['name']}: RAM {mem}")
                    self.speak("\n".join(lines))
            return

        # ── Vitals / status ──────────────────────────────────────
        if any(w in cmd for w in ["system status", "vitals", "cpu", "ram",
                                   "memory", "disk", "status", "how is",
                                   "system health", "how's", "performance"]):
            v = _rn.get_vitals(node_name)
            self.speak(_rn.format_vitals(v))
            return

        # ── Ping / online check ──────────────────────────────────
        if any(w in cmd for w in ["ping", "online", "reachable", "is it on",
                                   "is on", "connected", "available"]):
            r = _rn.ping(node_name)
            if "error" in r:
                self.speak(f"AlliedNode 2 is not reachable: {r['error']}")
            else:
                self.speak("AlliedNode 2 is online and ready.")
            return

        # ── Shutdown ─────────────────────────────────────────────
        if any(w in cmd for w in ["shutdown", "shut down", "turn off", "power off"]):
            r = _rn.system_control(node_name, "shutdown")
            self.speak(r.get("status", r.get("error", "Shutdown command sent to AlliedNode 2.")))
            return

        # ── Restart ──────────────────────────────────────────────
        if any(w in cmd for w in ["restart", "reboot"]) and "whatsapp" not in cmd and "bridge" not in cmd:
            r = _rn.system_control(node_name, "restart")
            self.speak(r.get("status", r.get("error", "Restart command sent to AlliedNode 2.")))
            return

        # ── Sleep ────────────────────────────────────────────────
        if "sleep" in clean:
            r = _rn.system_control(node_name, "sleep")
            self.speak(r.get("status", r.get("error", "AlliedNode 2 is going to sleep.")))
            return

        # ── Lock ─────────────────────────────────────────────────
        if "lock" in clean:
            r = _rn.system_control(node_name, "lock")
            self.speak(r.get("status", r.get("error", "AlliedNode 2 locked.")))
            return

        # ── Kill process ─────────────────────────────────────────
        _kill_m = _re.search(
            r'\b(?:kill|close|force quit|end)\s+(.+?)(?:\s+(?:in|on)\s+alliednode|$)',
            cmd, _re.IGNORECASE,
        )
        if _kill_m and any(w in cmd for w in ["kill", "force quit", "end process"]):
            proc = _kill_m.group(1).strip()
            r = _rn.system_control(node_name, "kill_process", process=proc)
            if "error" in r:
                self.speak(f"Couldn't kill {proc}: {r['error']}")
            elif r.get("count", 0) > 0:
                self.speak(f"Killed {proc} on AlliedNode 2.")
            else:
                self.speak(f"{proc} not found running on AlliedNode 2.")
            return

        # ── Send file TO AlliedNode 2 ────────────────────────────
        _send_m = _re.search(
            r'\b(?:send|transfer|copy)\s+(?:file\s+)?(.+?)\s+to\s+alliednode',
            cmd, _re.IGNORECASE,
        )
        if _send_m:
            filename = _send_m.group(1).strip()
            from modules.file_manager import get_file_manager
            import os as _os
            fm = get_file_manager()
            results = fm.smart_find(filename, ai_func=self.ai)
            if not results:
                self.speak(f"No file named {filename} found on this PC.")
                return
            local_path = results[0]
            dest = _os.path.join(r"C:\Users\Public\Downloads", _os.path.basename(local_path))
            self.speak(f"Transferring {_os.path.basename(local_path)} to AlliedNode 2.")
            def _send(lp=local_path, dp=dest):
                res = _rn.send_file(node_name, lp, dp)
                if "error" in res:
                    self.speak(f"Transfer failed: {res['error']}")
                else:
                    self.speak(f"Done. {res.get('size', 0) // 1024} KB sent to AlliedNode 2.")
            _thr.Thread(target=_send, daemon=True).start()
            return

        # ── Execute shell command on AlliedNode 2 ───────────────
        if any(w in cmd for w in ["run command", "execute command", "run script", "run powershell"]):
            _exec_m = _re.search(
                r'\b(?:run|execute)\s+(?:command\s+|script\s+)?(.+?)(?:\s+(?:in|on)\s+alliednode|$)',
                clean, _re.IGNORECASE,
            )
            command = _exec_m.group(1).strip() if _exec_m else clean
            if not command:
                self.speak("What command should I run on AlliedNode 2?")
                return
            self.speak(f"Running on AlliedNode 2.")
            def _exec(c=command):
                res = _rn.execute(node_name, c)
                out = (res.get("stdout") or res.get("error") or "No output.").strip()
                self.speak(out[:300] if out else "Command completed.")
            _thr.Thread(target=_exec, daemon=True).start()
            return

        # ── Open app ─────────────────────────────────────────────
        if any(w in clean for w in ["open", "launch", "start"]):
            app = clean
            for w in ["open", "launch", "start"]:
                app = app.replace(w, "").strip()
            app = " ".join(app.split())
            if not app:
                self.speak("What would you like me to open on AlliedNode 2?")
                return
            r = _rn.open_app(node_name, app)
            if "error" in r:
                self.speak(f"Couldn't open {app} on AlliedNode 2: {r['error']}")
            else:
                self.speak(f"Opening {app} on AlliedNode 2.")
            return

        # ── Fallback ─────────────────────────────────────────────
        self.speak(
            "Command for AlliedNode 2 not recognized. "
            "Try: 'open Chrome in AlliedNode 2', 'AlliedNode 2 system status', "
            "or 'shutdown AlliedNode 2'."
        )

    # ── SHELL EXECUTOR ──────────────────────────────────────────────
    _pending_shell_id: str = None

    def _handle_shell_command(self, cmd: str):
        from modules import shell_executor

        # Confirmation response for pending command
        if any(t in cmd for t in ["confirm command", "yes run it", "run it", "confirm run"]):
            if self._pending_shell_id:
                shell_executor.run_confirmed(self._pending_shell_id, speak_fn=self.speak)
                self._pending_shell_id = None
            else:
                self.speak("No command waiting for confirmation.")
            return

        if any(t in cmd for t in ["cancel command", "cancel the command", "don't run"]):
            if self._pending_shell_id:
                shell_executor.cancel_pending(self._pending_shell_id)
                self._pending_shell_id = None
                self.speak("Command cancelled.")
            else:
                self.speak("No command to cancel.")
            return

        # Extract the raw command from the voice input
        raw = cmd
        for prefix in [
            "run powershell", "run command", "execute command", "run script",
            "run terminal command", "run this command", "execute this command",
            "shell command", "powershell command", "run ps command", "run ps",
            "open terminal", "open powershell",
        ]:
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
                break

        if not raw:
            # No inline command — ask for it
            self.speak("What command should I run?")
            return

        # Use LLM to generate a clean PowerShell command from natural language
        ps_cmd = self._resolve_shell_intent(raw)

        # Broadcast confirm request, save pending id
        exec_id = shell_executor.request_confirmation(ps_cmd)
        self._pending_shell_id = exec_id
        self.speak(f"I'll run: {ps_cmd}. Say 'run it' to confirm or 'cancel command' to abort.")

    def _resolve_shell_intent(self, raw: str) -> str:
        """Use Groq to turn natural language into a PowerShell command."""
        import os
        from groq import Groq
        try:
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a PowerShell expert. Convert the user's natural language request "
                            "into a single PowerShell command. Reply with ONLY the command — no explanation, "
                            "no markdown fences, no extra text. Keep commands concise and safe."
                        ),
                    },
                    {"role": "user", "content": raw},
                ],
                max_tokens=120,
                temperature=0.1,
            )
            return resp.choices[0].message.content.strip().strip("`")
        except Exception:
            # Fall back to raw text if LLM fails
            return raw

    def _handle_briefing(self):
        import json as _j
        from datetime import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz=IST)

        try:
            with open("api_keys.json") as _f:
                cfg = _j.load(_f)
        except Exception:
            cfg = {}

        def _on(key, default=True, alt_key=None):
            """Check key; if missing, check alt_key; if still missing, use default."""
            if key in cfg:
                return bool(cfg[key])
            if alt_key and alt_key in cfg:
                return bool(cfg[alt_key])
            return default

        hour = now.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        parts = []

        if _on("briefing_greeting"):
            parts.append(f"{greeting}. Today is {now.strftime('%A, %d %B')}.")

        if _on("briefing_weather"):
            try:
                from modules.realtime_data import get_weather
                w = get_weather()
                if w:
                    parts.append(w)
            except Exception:
                pass

        if _on("briefing_news", False):
            try:
                from modules.realtime_data import get_news_headlines
                news = get_news_headlines()
                if news:
                    parts.append(news)
            except Exception:
                pass

        if _on("briefing_gold_rate", False):
            try:
                from modules.realtime_data import get_gold_rate
                parts.append(get_gold_rate())
            except Exception:
                pass

        if _on("briefing_silver_rate", False):
            try:
                from modules.realtime_data import get_silver_rate
                parts.append(get_silver_rate())
            except Exception:
                pass

        if _on("briefing_battery_status", True, "briefing_system"):
            try:
                _, bat = system_control.get_battery()
                parts.append(bat)
            except Exception:
                pass

        if _on("briefing_battery_health", False):
            try:
                _, bh = system_control.get_battery_health()
                parts.append(bh)
            except Exception:
                pass

        if _on("briefing_ram", True, "briefing_system"):
            try:
                _, ram = system_control.get_ram_usage()
                parts.append(ram)
            except Exception:
                pass

        if _on("briefing_events", True, "briefing_calendar"):
            try:
                from modules.calendar_agent import get_today_events
                events = get_today_events()
                upcoming = []
                for e in events:
                    start = e.get("start", {})
                    dt_str = start.get("dateTime") or start.get("date")
                    title = e.get("summary", "Event")
                    if not dt_str:
                        continue
                    try:
                        if "T" in dt_str:
                            dt = datetime.fromisoformat(dt_str)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=IST)
                            if dt > now:
                                t = dt.strftime("%I:%M %p").lstrip("0")
                                upcoming.append(f"{title} at {t}")
                        else:
                            upcoming.append(title)
                    except Exception:
                        pass
                if upcoming:
                    if len(upcoming) == 1:
                        parts.append(f"You have {upcoming[0]} on your schedule today.")
                    else:
                        joined = ", ".join(upcoming[:-1]) + f", and {upcoming[-1]}"
                        parts.append(f"You have {len(upcoming)} events: {joined}.")
                else:
                    parts.append("Your calendar is clear today.")
            except Exception:
                pass

        if _on("briefing_whatsapp", False):
            try:
                from modules.whatsapp_context import get_unread_count
                count = get_unread_count()
                if count:
                    parts.append(f"You have {count} unread WhatsApp message{'s' if count != 1 else ''}.")
                else:
                    parts.append("No unread WhatsApp messages.")
            except Exception:
                pass

        if not parts:
            parts.append(f"{greeting}.")

        self.speak(" ".join(parts))

    def _handle_document_command(self, cmd: str):
        import threading as _thr

        fmt      = "docx" if any(w in cmd for w in ["word", "docx", "doc"]) else "pdf"
        template = "custom"
        title    = "iZACH Document"

        if any(w in cmd for w in ["activity report", "today's report", "command report"]):
            template = "activity_report"
            title    = "Activity Report"
        elif any(w in cmd for w in ["weekly", "week"]):
            template = "weekly_summary"
            title    = "Weekly Summary"
        elif any(w in cmd for w in ["letter"]):
            template = "letter"
            title    = "Letter"

        # Extract custom content after "about" / "on"
        import re as _re
        m = _re.search(r'\b(?:about|on|regarding)\b\s+(.+)', cmd)
        content = m.group(1).strip() if m else ""

        self.speak(f"Generating {fmt.upper()}. Check shared folder when done.")

        def _run():
            from modules.document_engine import generate
            ok, msg, _ = generate(content, fmt, title, template)
            if not ok:
                self.speak(msg)

        _thr.Thread(target=_run, daemon=True).start()

    def _handle_network_monitor_command(self, cmd: str):
        try:
            from modules.network_monitor import get_devices, get_connections, summary, scan_now, get_alerts
        except Exception as e:
            self.speak(f"Network monitor error: {e}")
            return

        if any(w in cmd for w in ["scan", "refresh", "check"]):
            self.speak("Scanning network. Give me a moment.")
            import threading as _thr
            def _do():
                devs = scan_now()
                self.speak(f"Found {len(devs)} device(s) on network.")
            _thr.Thread(target=_do, daemon=True).start()
            return

        if any(w in cmd for w in ["connection", "active"]):
            conns = get_connections()
            if not conns:
                self.speak("No active outbound connections.")
                return
            top = conns[:5]
            msg = f"{len(conns)} active connection(s). Top: " + \
                  ", ".join(f"{c['process']} → {c['remote']}" for c in top)
            self.speak(msg)
            return

        if "alert" in cmd:
            alerts = get_alerts()
            if not alerts:
                self.speak("No network alerts.")
            else:
                self.speak(f"{len(alerts)} alert(s). Latest: {alerts[-1]['msg']}")
            return

        # Default: full summary
        self.speak(summary())

    def _handle_deep_research(self, cmd: str):
        """Multi-source web research synthesis."""
        import threading as _thr
        import re as _re
        # Strip trigger prefix to get clean topic
        for prefix in [
            "deep research on ", "research on ", "research ", "look into ",
            "investigate ", "find out about ", "give me a report on ",
            "gather info on ", "full report on ", "comprehensive info on ",
            "what do you know about ",
        ]:
            if cmd.startswith(prefix):
                topic = cmd[len(prefix):].strip()
                break
        else:
            topic = cmd.strip()

        if not topic:
            self.speak("What should I research?")
            return

        # Store so "this" in follow-up resolves back to this topic
        try:
            from modules.context_memory import get_context_memory
            get_context_memory().set_entity("last_research_topic", topic)
        except Exception:
            pass

        try:
            from modules.research_agent import research_async
            research_async(topic)
        except Exception as e:
            self.speak(f"Research module error: {e}")

    def _handle_group_summarize(self, cmd: str):
        """Summarize a WhatsApp group chat."""
        import re as _re
        # Extract group name
        group_name = cmd
        for stop in ["summarize", "catch me up on", "what happened in",
                     "what's going on in", "group update", "group summary",
                     "group", "chat", "today", "from today", "whatsapp"]:
            group_name = group_name.replace(stop, " ").strip()
        group_name = " ".join(group_name.split()).strip()

        hours = 6
        m = _re.search(r'last\s+(\d+)\s*h', cmd)
        if m:
            hours = int(m.group(1))
        elif "today" in cmd:
            hours = 12

        if not group_name:
            self.speak("Which group should I summarize?")
            return

        try:
            from modules.wa_group_summarizer import summarize_group_async
            summarize_group_async(group_name, hours=hours)
        except Exception as e:
            self.speak(f"Group summarizer error: {e}")

    def _handle_routine_command(self, cmd: str):
        from modules.pattern_learner import (
            confirm_suggestion, reject_suggestion,
            get_pending_suggestion, list_routines, delete_routine,
        )

        # Confirm
        if any(w in cmd for w in ["yes automate", "automate it", "yeah automate"]):
            pending = get_pending_suggestion()
            if not pending:
                self.speak("No pending automation suggestion right now.")
                return
            ok = confirm_suggestion()
            if ok:
                self.speak(f"Done. I'll run '{pending.get('example_cmd', 'that command')}' automatically from now on.")
            return

        # Reject
        if any(w in cmd for w in ["no skip", "skip it", "don't automate", "no automate", "no don't"]):
            pending = get_pending_suggestion()
            reject_suggestion()
            self.speak("Got it. I won't suggest that again.")
            return

        # List routines
        if any(w in cmd for w in ["show my routines", "list routines", "what routines", "my routines"]):
            routines = list_routines()
            if not routines:
                self.speak("No automated routines set up yet.")
                return
            parts = [r.get("cmd", "")[:40] for r in routines[:5]]
            self.speak(f"You have {len(routines)} automated routines: {', then '.join(parts)}.")
            return

        # Delete routine
        if any(w in cmd for w in ["delete routine", "remove routine"]):
            routines = list_routines()
            if not routines:
                self.speak("No routines to delete.")
                return
            # find matching by keyword in cmd
            for r in routines:
                if any(word in cmd for word in r.get("cmd", "").lower().split()[:3]):
                    delete_routine(r["id"])
                    self.speak(f"Removed routine: {r.get('cmd', '')[:40]}.")
                    return
            self.speak("Couldn't find that routine. Say 'list routines' to see them.")

    def _handle_calendar_voice_command(self, cmd: str):
        """
        Handle voice commands like:
        - "tomorrow gym session is cancelled"
        - "meeting is at 7pm instead of 6pm"
        - "what's on my calendar"
        - "add event gym tomorrow 10am"
        """
        import json as _json
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        IST = _ZI("Asia/Kolkata")
        today = _dt.now(tz=IST).strftime("%Y-%m-%d")
        today_name = _dt.now(tz=IST).strftime("%A, %d %B %Y")

        # Remove all events
        if any(w in cmd for w in ["remove all events", "delete all events", "clear my calendar", "clear calendar"]):
            try:
                from modules.calendar_agent import get_upcoming_events, cancel_event
                events = get_upcoming_events(hours=168)
                if not events:
                    self.speak("Your calendar is already empty.")
                    return
                count = 0
                for e in events:
                    try:
                        cancel_event(e["calendar_event_id"])
                        count += 1
                    except Exception:
                        pass
                self.speak(f"Removed {count} event{'s' if count != 1 else ''} from your calendar.")
            except Exception as _e:
                self.speak(f"Calendar error: {_e}")
            return

        # Read events query
        if any(w in cmd for w in ["what's on my calendar", "my schedule", "show my events", "what events", "upcoming events"]):
            try:
                from modules.calendar_agent import get_3day_events, format_event_for_speech, get_upcoming_events
                events = get_upcoming_events(hours=72)
                if not events:
                    self.speak("Nothing on your calendar for the next 3 days.")
                else:
                    parts = [format_event_for_speech(e) for e in events[:5]]
                    self.speak("Coming up: " + ", then ".join(parts) + ".")
            except Exception as _e:
                self.speak(f"Couldn't read calendar: {_e}")
            return

        # Use Groq to parse cancel/reschedule/add intent
        prompt = f"""You are a calendar command parser for a voice assistant.
Parse this voice command and return JSON.

Today is: {today_name} ({today})
Command: "{cmd}"

Return ONLY a JSON object:
{{
  "action": "cancel|reschedule|add|unknown",
  "event_title_hint": "what event is being referred to, in English",
  "original_date": "YYYY-MM-DD or null",
  "original_time": "HH:MM or null",
  "new_date": "YYYY-MM-DD or null",
  "new_time": "HH:MM in 24h or null",
  "link": "URL or null"
}}

Rules:
- "tomorrow" = date after {today}
- "cancelled", "is cancelled", "cancel" = action: cancel
- "instead of", "moved to", "now at", "at X instead", "rescheduled" = action: reschedule
- "add", "schedule", "put on calendar" = action: add
- For reschedule: original_time = OLD time, new_time = NEW time
- "7pm" = 19:00, "3pm" = 15:00, "10am" = 10:00, "7 baje" = 07:00 or 19:00 (use context)

Return ONLY JSON."""

        try:
            from groq import Groq as _Groq
            import os as _os
            from dotenv import load_dotenv as _lde
            _lde()
            _g = _Groq(api_key=_os.getenv("GROQ_API_KEY", ""))
            resp = _g.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=250,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = _json.loads(raw.strip())
        except Exception as _pe:
            self.speak("I couldn't understand that calendar command.")
            return

        action = parsed.get("action", "unknown")
        title_hint = parsed.get("event_title_hint", "")
        orig_date = parsed.get("original_date")
        new_time = parsed.get("new_time")
        new_date = parsed.get("new_date")

        if action == "cancel":
            try:
                from modules.calendar_agent import find_event_by_voice_cmd, cancel_event
                mapping = find_event_by_voice_cmd(title_hint, orig_date)
                if not mapping:
                    self.speak(f"I couldn't find a {title_hint} event on your calendar.")
                    return
                ok = cancel_event(mapping["calendar_event_id"])
                if ok:
                    self.speak(f"{mapping.get('title', title_hint)} cancelled and removed from your calendar.")
                else:
                    self.speak("Couldn't remove the event. Calendar error.")
            except Exception as _e:
                self.speak(f"Calendar error: {_e}")

        elif action == "reschedule":
            try:
                from modules.calendar_agent import find_event_by_voice_cmd, update_event
                mapping = find_event_by_voice_cmd(title_hint, orig_date)
                if not mapping:
                    self.speak(f"I couldn't find a {title_hint} event to reschedule.")
                    return
                ok = update_event(mapping["calendar_event_id"], time_str=new_time, date_str=new_date)
                if ok:
                    t_str = ""
                    if new_time:
                        try:
                            t_str = f" to {_dt.strptime(new_time, '%H:%M').strftime('%I:%M %p').lstrip('0')}"
                        except Exception:
                            t_str = f" to {new_time}"
                    self.speak(f"{mapping.get('title', title_hint)} rescheduled{t_str}. Calendar updated.")
                else:
                    self.speak("Couldn't update the event. Calendar error.")
            except Exception as _e:
                self.speak(f"Calendar error: {_e}")

        elif action == "add":
            try:
                from modules.calendar_agent import add_event
                add_date = new_date or orig_date or today
                add_time = new_time or parsed.get("original_time") or "09:00"
                event = add_event(title=title_hint, date_str=add_date, time_str=add_time,
                                  link=parsed.get("link"))
                if event:
                    try:
                        dt = _dt.strptime(f"{add_date} {add_time}", "%Y-%m-%d %H:%M")
                        t_str = dt.strftime("%I:%M %p").lstrip("0")
                        d_str = dt.strftime("%d %B")
                    except Exception:
                        t_str, d_str = add_time, add_date
                    self.speak(f"Added {title_hint} at {t_str} on {d_str} to your calendar.")
                else:
                    self.speak("Couldn't add the event. Calendar error.")
            except Exception as _e:
                self.speak(f"Calendar error: {_e}")

        else:
            self.speak("I couldn't determine what calendar action you wanted.")

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
        # System apps that superficially match file-open triggers — must fall through to app launcher
        _APP_OPEN_EXCEPTIONS = [
            "file explorer", "explorer", "notepad", "notepad++", "paint",
            "calculator", "control panel", "task manager", "wordpad",
        ]
        if any(exc in cmd for exc in _APP_OPEN_EXCEPTIONS):
            return False
        _FILE_OPEN_EXPLICIT = any(w in cmd for w in ["open file", "open my file", "open the file"])
        _FILE_OPEN_SUBJECT  = "open" in cmd and any(
            re.search(r'\b' + h + r'\b', cmd) for h in _FILE_SUBJECT_HINTS
        )

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

        # ── VOICE BIOMETRICS ──
        _VOICE_ENROLL_TRIGGERS = [
            "enroll my voice", "enroll voice", "setup voice auth", "set up voice auth",
            "register my voice", "train my voice", "learn my voice",
            "voice enrollment", "voice setup", "record my voice",
        ]
        if any(t in cmd for t in _VOICE_ENROLL_TRIGGERS):
            from modules import voice_id
            voice_id.init(self.speak)
            voice_id.enroll_voice_async()
            return

        if any(t in cmd for t in ["delete voice", "remove voice", "forget my voice",
                                   "clear voice auth", "delete voice data"]):
            from modules import voice_id
            ok = voice_id.delete_voice_data()
            self.speak("Voice data removed." if ok else "No voice data stored.")
            return

        if any(t in cmd for t in ["is voice enrolled", "voice auth status",
                                   "voice setup status", "voice status"]):
            from modules import voice_id
            if voice_id.is_enrolled():
                meta = voice_id.get_meta()
                self.speak(f"Voice enrolled since {meta.get('enrolled_at', 'unknown')}.")
            else:
                self.speak("No voice enrolled yet. Say 'enroll my voice' to set up.")
            return

        # ── FACE AUTH ──
        _FACE_TRIGGERS = [
            "enroll my face", "enroll face", "setup face auth", "set up face auth",
            "register my face", "add my face", "face enrollment", "face setup",
            "train face", "learn my face",
        ]
        if any(t in cmd for t in _FACE_TRIGGERS):
            from modules import face_auth
            face_auth.init(self.speak)
            face_auth.enroll_owner()
            return

        if any(t in cmd for t in ["delete face data", "remove face data", "forget my face", "clear face auth"]):
            from modules import face_auth
            ok = face_auth.delete_face_data()
            self.speak("Face data removed." if ok else "No face data stored.")
            return

        if any(t in cmd for t in ["is face enrolled", "face auth status", "face setup status"]):
            from modules import face_auth
            self.speak("Face is enrolled." if face_auth.is_enrolled() else "No face enrolled yet. Say 'enroll my face' to set up.")
            return

        # ── SCREENSHOT ──
        if any(t in cmd for t in ["screenshot", "capture screen", "take a screenshot", "screen capture"]):
            try:
                from modules.screenshot_engine import capture_sync
                from modules.ws_bridge import broadcast
                filename = capture_sync()
                if filename:
                    broadcast({"type": "screenshot_ready", "filename": filename, "ts": time.strftime("%H:%M")})
                    self.speak(f"Screenshot captured and sent to your phone.")
                else:
                    self.speak("Screenshot failed. Check pyautogui is installed.")
            except Exception as _e:
                self.speak(f"Screenshot error: {_e}")
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

        # Daily briefing
        if any(w in cmd for w in ["good morning", "good afternoon", "good evening", "daily briefing", "morning briefing", "give me a briefing"]):
            self._handle_briefing()
            return

        # Kill app by name
        _kill_prefixes = ("force quit ", "force close ", "end task ", "kill process ", "terminate process ", "end process ", "close ")
        for _kp in _kill_prefixes:
            if cmd.startswith(_kp):
                _app_name = cmd[len(_kp):].strip()
                if not _app_name:
                    break
                if _kp == "close " and _app_name.split()[0] in system_control._KILL_SKIP_WORDS:
                    break
                _, _msg = system_control.kill_app(_app_name)
                self.speak(_msg)
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

        # \bhands?\s+off\s+to\b tolerates "hands off to" (typo/mishear for
        # "hand off to") alongside the exact phrase and the other triggers.
        if re.search(r'\bhands?\s+off\s+to\b', cmd) or any(w in cmd for w in ["handoff to", "move izach to", "move to windows", "move to mac"]):
            target = "windows" if "windows" in cmd else ("mac" if "mac" in cmd else None)
            if not target:
                self.speak("Hand off to which device — Mac or Windows?")
                return
            from modules.instance_coordinator import initiate_handoff
            ok, msg = initiate_handoff(target)
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

        # ── SCHEDULED SHUTDOWN / RESTART ─────────────────────────────────────────
        _shutdown_pat = re.search(
            r'(?:shut\s*down|shutdown|turn\s+off|power\s+off)\s+(?:in\s+)?(\d+)\s*(minute|min|hour|hr)s?',
            cmd, re.IGNORECASE
        )
        if _shutdown_pat:
            n = int(_shutdown_pat.group(1))
            unit = _shutdown_pat.group(2).lower()
            secs = n * 3600 if unit.startswith("hour") or unit == "hr" else n * 60
            _, msg = system_control.schedule_shutdown(secs)
            self.speak(msg)
            return

        _restart_pat = re.search(
            r'(?:restart|reboot)\s+(?:in\s+)?(\d+)\s*(minute|min|hour|hr)s?',
            cmd, re.IGNORECASE
        )
        if _restart_pat:
            n = int(_restart_pat.group(1))
            unit = _restart_pat.group(2).lower()
            secs = n * 3600 if unit.startswith("hour") or unit == "hr" else n * 60
            _, msg = system_control.schedule_restart(secs)
            self.speak(msg)
            return

        if any(w in cmd for w in ["cancel shutdown", "abort shutdown", "cancel restart", "abort restart"]):
            _, msg = system_control.cancel_shutdown()
            self.speak(msg)
            return

        # ── PROCESS PRIORITY ─────────────────────────────────────────────────────
        _prio_pat = re.search(
            r'(?:boost|set|change)\s+(.+?)\s+(?:to\s+)?(?:(low|normal|high|realtime)\s+)?priority',
            cmd, re.IGNORECASE
        )
        if _prio_pat:
            app = _prio_pat.group(1).strip()
            level = (_prio_pat.group(2) or "high").lower()
            _, msg = system_control.set_process_priority(app, level)
            self.speak(msg)
            return

        # ── DOCUMENT GENERATION ───────────────────────────────────────────────────
        _DOC_TRIGGERS = [
            "generate report", "create report", "make report", "write report",
            "generate pdf", "create pdf", "make pdf", "export pdf",
            "generate document", "create document", "make document",
            "weekly summary", "weekly report", "activity report",
            "generate word", "create word doc", "make word",
            "write a letter", "draft a letter", "write letter",
        ]
        if any(t in cmd for t in _DOC_TRIGGERS):
            self._handle_document_command(cmd)
            return

        # ── NETWORK MONITOR ───────────────────────────────────────────────────────
        _NET_TRIGGERS = [
            "scan network", "scan my network", "who's on my wifi", "who is on my wifi",
            "network scan", "devices on wifi", "network connections",
            "active connections", "what's connected", "network security",
            "unknown devices", "network alerts", "check network",
            "who is connected", "check wifi devices",
        ]
        if any(t in cmd for t in _NET_TRIGGERS):
            self._handle_network_monitor_command(cmd)
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

        # If open_app intent and app not installed — offer download instead
        if parsed.get("intent") == "open_app":
            _app_name = (parsed.get("app") or "").strip()
            if _app_name:
                from modules.app_installer import is_app_installed, get_installer_info
                if not is_app_installed(_app_name) and get_installer_info(_app_name):
                    self._pending_install = _app_name.lower()
                    self.speak(f"{_app_name.title()} isn't installed on your PC. Want me to download the installer?")
                    return

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
            self.awaiting_app_or_web = False
            self.available_playlists = {}
            self.pending_song_request = ""
            self.pending_open_service = ""
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

        # ---------------- APP OR WEBSITE CHOICE ----------------
        if self.awaiting_app_or_web:
            self.awaiting_app_or_web = False
            svc = self.pending_open_service
            self.pending_open_service = ""
            if any(w in cmd for w in ["app", "application", "store"]):
                from modules.automation import open_app
                _APP_LAUNCH_NAMES = {
                    "youtube":   "YouTube",
                    "github":    "GitHub Desktop",
                    "instagram": "Instagram",
                    "pinterest": "Pinterest",
                }
                app_name = _APP_LAUNCH_NAMES.get(svc, svc.title())
                open_app(app_name)
                self.speak(f"Opening {app_name} app.")
            else:
                # Open in user's default browser (not Playwright Chromium)
                from modules import web_automation
                try:
                    url = web_automation._resolve_url(svc)
                    webbrowser.open(url)
                    self.speak(f"Opening {svc} in your default browser.")
                except Exception as _osvc_err:
                    logger.warning(f"[open svc] Default browser failed: {_osvc_err}")
                    self.speak(f"Opening {svc} in browser.")
                    import threading
                    threading.Thread(
                        target=lambda: web_automation.open_website(svc),
                        daemon=True,
                    ).start()
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
                # Speak immediately — TTS generates while Spotify API runs.
                # Deliberately not "Playing X." (a claim we can't back yet) —
                # if the lookup below fails, the follow-up correction used to
                # read as a contradiction ("Playing X. No active device.").
                self.speak(f"Looking for {full_query} on Spotify.")
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

        # device-only switch (no song) — e.g. "switch playback to AlliedNode"
        _sw_match = re.search(
            r'(?:switch|transfer|move|change)\s+(?:playback|spotify|music|audio|the music)?\s*(?:to|on)\s+(.+)',
            cmd, re.IGNORECASE
        )
        if _sw_match:
            _device_spoken = _sw_match.group(1).strip()
            _resolved      = _resolve_device_alias(_device_spoken)
            _status        = self.spotify_handler.switch_device(_resolved)
            _save_device_alias(_device_spoken, _resolved)
            self.speak(_status)
            return

        # ── SPOTIFY MOOD PLAY ─────────────────────────────────────────────────────
        _MOOD_WORDS = {"chill", "relaxing", "lofi", "study", "focus", "energetic",
                       "workout", "happy", "sad", "party", "sleepy", "morning",
                       "night", "romantic", "jazz", "classical"}
        _mood_match = re.search(r'\bplay\s+(?:something\s+|some\s+)?(.+)', cmd, re.IGNORECASE)
        if _mood_match and cmd.startswith("play "):
            _mood_query = _mood_match.group(1).strip()
            for _filler in [" music", " songs", " tracks", " vibes", " playlist"]:
                _mood_query = _mood_query.replace(_filler, "").strip()
            if any(w in _mood_query.lower() for w in _MOOD_WORDS) or "something" in cmd:
                _status = self.spotify_handler.play_mood(_mood_query)
                self.speak(_status)
                return

        # ── SPOTIFY SLEEP TIMER ───────────────────────────────────────────────────
        _sleep_pat = re.search(
            r'(?:sleep timer|stop music in|pause music in)\s+(?:in\s+)?(\d+)\s*(minute|min|hour|hr)s?',
            cmd, re.IGNORECASE
        )
        if _sleep_pat:
            _n = int(_sleep_pat.group(1))
            _unit = _sleep_pat.group(2).lower()
            _mins = _n * 60 if _unit.startswith("hour") or _unit == "hr" else _n
            _status = self.spotify_handler.sleep_timer(_mins)
            self.speak(_status)
            return

        if any(w in cmd for w in ["cancel sleep timer", "cancel music timer", "stop sleep timer"]):
            self.speak(self.spotify_handler.cancel_sleep_timer())
            return

        # ── SPOTIFY RECENTLY PLAYED ───────────────────────────────────────────────
        if any(w in cmd for w in ["recently played", "what was i listening to", "what did i play",
                                   "what was playing earlier", "last played on spotify"]):
            self.speak(self.spotify_handler.get_recently_played())
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

        # ── WHATSAPP SUMMARIZE ────────────────────────────────────────────────────
        if any(w in cmd for w in ["summarize my whatsapp", "summarize whatsapp",
                                   "any new messages on whatsapp", "new whatsapp messages",
                                   "whatsapp summary", "what's new on whatsapp"]):
            from modules.whatsapp_handler import ensure_bridge_running
            ensure_bridge_running()
            try:
                import requests as _req
                from collections import defaultdict as _dd
                _r = _req.get("http://localhost:3000/messages/history", params={"hours": 12}, timeout=5)
                _msgs = _r.json().get("messages", [])
                _unread = [m for m in _msgs if not m.get("fromMe", True) and m.get("text")]
                if not _unread:
                    self.speak("No new WhatsApp messages in the last 12 hours.")
                else:
                    _by_sender = _dd(list)
                    for _m in _unread:
                        _by_sender[_m.get("sender", "Unknown")].append(_m["text"])
                    _parts = []
                    for _sender, _texts in _by_sender.items():
                        if len(_texts) == 1:
                            _parts.append(f"{_sender}: {_texts[0]}")
                        else:
                            _parts.append(f"{_sender} sent {len(_texts)} messages, latest: {_texts[-1]}")
                    _summary = ". ".join(_parts)
                    if len(_by_sender) > 2:
                        _prompt = f"Summarize these WhatsApp messages in 2-3 sentences like JARVIS briefing:\n{_summary}"
                        self.speak(self._raw_ai(_prompt))
                    else:
                        self.speak(f"Messages from {len(_by_sender)} contact{'s' if len(_by_sender) > 1 else ''}. " + _summary)
            except Exception:
                self.speak("Could not fetch WhatsApp messages.")
            return

        # ── WHATSAPP READ FROM CONTACT ────────────────────────────────────────────
        _read_from_pat = re.search(
            r'(?:read|show).*whatsapp.*(?:messages?\s+)?(?:from|by)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
            cmd, re.IGNORECASE
        )
        if _read_from_pat or "read my whatsapp messages" in cmd:
            from modules.whatsapp_handler import ensure_bridge_running
            ensure_bridge_running()
            _contact_filter = _read_from_pat.group(1).strip().lower() if _read_from_pat else ""
            try:
                import requests as _req
                _r = _req.get("http://localhost:3000/messages/history", params={"hours": 24}, timeout=5)
                _msgs = _r.json().get("messages", [])
                _inbox = [m for m in _msgs if not m.get("fromMe", True) and m.get("text")]
                if _contact_filter:
                    _inbox = [m for m in _inbox if _contact_filter in m.get("sender", "").lower()]
                if not _inbox:
                    _who = f" from {_contact_filter.title()}" if _contact_filter else ""
                    self.speak(f"No messages{_who} in the last 24 hours.")
                else:
                    for _m in _inbox[-3:]:
                        self.speak(f"{_m.get('sender', 'Someone')} said: {_m['text']}")
            except Exception:
                self.speak("Could not fetch WhatsApp messages.")
            return

        # ── WHATSAPP SEND TO CONTACT ──────────────────────────────────────────────
        _send_wa_pat = re.search(
            r'(?:send\s+(?:a\s+)?(?:whatsapp\s+message|whatsapp|message|wa)\s+to)\s+'
            r'((?:(?!saying\b|that\b)[A-Za-z]+)(?:\s+(?!saying\b|that\b)[A-Za-z]+)*)'
            r'\s+(?:(?:saying|that)\s+)?(.+)',
            cmd, re.IGNORECASE
        )
        if _send_wa_pat:
            from modules.whatsapp_handler import _send_message, ensure_bridge_running, resolve_contact_by_name
            ensure_bridge_running()
            _wa_contact = _send_wa_pat.group(1).strip()
            _wa_text = _send_wa_pat.group(2).strip()
            _wa_number = resolve_contact_by_name(_wa_contact)
            if not _wa_number:
                self.speak(f"I don't have {_wa_contact}'s number. Add them to contacts.json.")
            else:
                _ok, _status = _send_message(_wa_number, _wa_text, _wa_contact)
                self.speak(f"Message sent to {_wa_contact}." if _ok else f"Failed: {_status}")
            return

        if _last_whatsapp_message_check(cmd):
            from modules.whatsapp_handler import get_last_message, ensure_bridge_running
            ensure_bridge_running()
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
        
        #WhatsApp Bridge Commands
        if any(w in cmd for w in ["restart whatsapp bridge", "restart whatsapp", "restart bridge",
                                   "reboot whatsapp", "reconnect whatsapp bridge"]):
            import subprocess as _subp, sys as _sys
            self.speak("Restarting WhatsApp bridge. Give it a moment.")
            try:
                # Kill existing bridge process on port 3000
                _kill = _subp.run(
                    ["powershell", "-Command",
                     "Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | "
                     "Select-Object -ExpandProperty OwningProcess | "
                     "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass
            import time as _t; _t.sleep(2)
            from modules.whatsapp_handler import ensure_bridge_running as _ebr
            _ebr()
            self.speak("WhatsApp bridge restarted. Scan the QR code in the UI if prompted.")
            return

        if any(w in cmd for w in ["connect whatsapp", "start whatsapp", "launch whatsapp"]):
            from modules.whatsapp_handler import ensure_bridge_running
            ensure_bridge_running()
            self.speak("Starting WhatsApp bridge now. Give it a moment to connect.")
            return

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
        
        # ── Relationship memory commands ──────────────────────────
        # "who is Divya" / "what do you know about Rohan"
        if any(w in cmd for w in ["who is ", "what do you know about ", "tell me about "]):
            import re as _re
            m = _re.search(r"(?:who is|what do you know about|tell me about)\s+([A-Za-z]+(?:\s[A-Za-z]+)?)", cmd, _re.IGNORECASE)
            if m:
                name = m.group(1).strip().title()
                from modules.relationship_memory import get_summary
                self.speak(get_summary(name))
            else:
                self.speak("Who do you want me to look up?")
            return

        # "X is my Y" / "remember that X works at Y" / "X studies at Y"
        if re.search(r"\b(is my|works at|studies at|goes to)\b", cmd, re.IGNORECASE) or \
           cmd.lower().startswith("remember that ") or cmd.lower().startswith("note that "):
            from modules.relationship_memory import extract_and_save_from_command
            # Capitalize first word so regex in extract_and_save works
            cap_cmd = cmd[0].upper() + cmd[1:] if cmd else cmd
            saved, msg = extract_and_save_from_command(cap_cmd)
            if saved:
                self.speak(msg)
                return
            # Fall through to AI if no pattern matched

        # ── Auto-draft WhatsApp reply ─────────────────────────────
        # "draft a reply to Divya" / "what should I say to her" / "auto reply"
        if any(w in cmd for w in ["draft a reply", "draft reply", "auto reply", "auto draft",
                                   "what should i say", "suggest a reply", "what to say to"]):
            from modules.whatsapp_handler import get_last_message, _send_message, ensure_bridge_running
            ensure_bridge_running()
            last = get_last_message()
            if not last or not last.get("number"):
                self.speak("No recent WhatsApp message to draft a reply for.")
                return
            from modules.wa_draft_engine import draft_reply, init as _init_draft
            from modules.whatsapp_handler import _ai_func
            _init_draft(self.speak, _ai_func, _send_message)
            # Extract optional instruction after trigger phrase
            instruction = ""
            for trigger in ["draft a reply to", "draft reply to", "what should i say to",
                            "suggest a reply to", "what to say to"]:
                if trigger in cmd:
                    instruction = cmd.split(trigger, 1)[-1].strip()
                    break
            draft_reply(last["number"], last.get("sender", "them"), instruction)
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
                self.speak(response or "Couldn't summarise that WhatsApp message.")
            else:
                self.speak("No recent WhatsApp message to elaborate.")
            return

        # Disable instant feedback for WhatsApp commands
        from modules.whatsapp_handler import ensure_bridge_running as _ebr
        _ebr()
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
                _ok, _status = _send_message(number, reply_text)
                if _ok:
                    self.speak(f"Replied to {sender}.")
                else:
                    # _send_message already retried internally (whatsapp_sender
                    # has its own retry loop) — a False here is a confirmed
                    # failure, not a fluke, so don't claim success.
                    _reason = _status.split(": ", 1)[-1] if ": " in _status else _status
                    self.speak(f"Couldn't send that to {sender} — {_reason}")
            else:
                self.speak("What should I say in the reply?")
            if _rg and _orig_instant:
                _rg.instant = _orig_instant
            return
        if _rg and _orig_instant:
            _rg.instant = _orig_instant

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
            from modules.app_installer import is_app_installed, get_installer_info
            if not is_app_installed(full) and get_installer_info(full):
                self._pending_install = full.lower()
                self.speak(f"{full.title()} isn't installed on your PC. Want me to download the installer?")
                return
            from modules.context_engine import handle_open_with_position
            open_result = handle_open_with_position(full, position)
            if "opened" in open_result.lower() or "front" in open_result.lower():
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
                _dnd_prefix = ""
                try:
                    from modules import dnd_mode as _dnd_fb
                    if _dnd_fb.is_active():
                        _dnd_prefix = _dnd_fb.concise_system_prefix()
                except Exception:
                    pass
                direct = self._raw_ai(f"{_dnd_prefix}{PERSONALITY_PROMPT}\n\nUser: {cmd}")
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