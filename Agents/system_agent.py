"""
SystemAgent — full LLM-driven handler for all OS/system commands.

Replaces/consolidates these command_chain.py blocks:
  _SYSTEM_CONTROL_TRIGGERS keyword block   (~lines 332-351)
  WiFi, mute, volume, brightness handlers  (~lines 1862-1936)
  Timer handler                            (~lines 1938-1950)
  Alarm handler                            (~lines 1952-1972)
  Drives, battery, firewall, updates       (~lines 1974-2016)
  Shutdown, restart, cancel_shutdown       (~lines 2019-2046)
  Kill/force-quit process                  (~lines 1794-1805)
  Screenshot                               (~lines 1730-1742)
  App open → ai_parse → IntentRouter path  (ai_parse + route)

Intents handled:
  open_app           launch an application
  kill_app           force-quit an app / process
  set_volume         set volume to X%
  adjust_volume      increase / decrease volume
  mute               mute audio
  unmute             unmute audio
  set_brightness     set brightness to X%
  adjust_brightness  increase / decrease brightness
  set_theme          switch dark / light mode
  set_timer          countdown timer
  screenshot         capture screen
  shutdown           schedule or immediate shutdown  (confirm first)
  restart            schedule or immediate restart   (confirm first)
  cancel_shutdown    abort a pending shutdown
  wifi_on            enable WiFi
  wifi_off           disable WiFi
  wifi_toggle        toggle WiFi
  battery_status     battery % and charge state
  battery_health     battery wear level
  cpu_temp           CPU temperature
  ram_usage          RAM usage
  firewall_status    Windows Firewall status
  update_status      pending Windows updates
  wifi_signal        WiFi signal strength
  network_devices    devices on local network
  list_drives        list connected drives
  eject_drive        safely eject a drive
  process_priority   set process CPU priority
"""

from __future__ import annotations

import json
import re

import modules.system_control as _sc

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's system control command parser. Parse the user command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "app_name": "<application name or null>",
  "volume_level": <0-100 or null>,
  "volume_delta": <positive or negative int or null>,
  "brightness_level": <0-100 or null>,
  "brightness_delta": <positive or negative int or null>,
  "theme": "<dark|light or null>",
  "timer_seconds": <int or null>,
  "shutdown_delay_seconds": <int — 0 for immediate, or null>,
  "wifi_enable": <true|false|null — null means toggle>,
  "drive_id": "<drive letter or name or null>",
  "process_name": "<process/app name or null>",
  "priority_level": "<low|normal|high|realtime or null>",
  "target_platform": "<mac|windows or null>"
}}

Intents (pick exactly one):
- open_app          : open/launch/start an application or website. If the command names a specific machine ("open chrome IN WINDOWS", "open notepad ON MAC"), still intent=open_app (there IS an app_name) — just also set target_platform to "mac" or "windows" so it launches there instead of locally.
- kill_app          : force quit/close/end/terminate an app or process
- set_volume        : "set volume to X", "volume X percent"
- adjust_volume     : "increase/raise/boost/lower/decrease/reduce volume" (delta: +10 or -10 default)
- mute              : mute audio, silence
- unmute            : unmute audio
- set_brightness    : "set brightness to X", "brightness X percent"
- adjust_brightness : "raise/lower brightness" (delta: +10 or -10 default)
- set_theme         : "dark mode", "light mode", "switch to dark/light"
- set_timer         : "set timer for X minutes/hours/seconds"
- screenshot        : "take screenshot", "capture screen", "screenshot"
- shutdown          : "shut down", "power off", "turn off PC"
- restart           : "restart", "reboot"
- cancel_shutdown   : "cancel shutdown", "abort shutdown", "cancel restart"
- wifi_on           : "turn on wifi", "enable wifi", "connect wifi"
- wifi_off          : "turn off wifi", "disable wifi", "disconnect wifi"
- wifi_toggle       : "toggle wifi"
- battery_status    : "battery", "battery level", "how much battery"
- battery_health    : "battery health", "battery wear", "battery condition"
- cpu_temp          : "cpu temperature", "cpu temp", "how hot is cpu"
- ram_usage         : "ram usage", "memory usage", "how much ram"
- firewall_status   : "firewall", "is firewall on", "firewall status"
- update_status     : "windows update", "pending updates", "check for updates"
- wifi_signal       : "wifi signal", "signal strength", "how strong is wifi"
- network_devices   : "who's on my network", "connected devices", "network devices"
- list_drives       : "list drives", "show drives", "connected drives"
- eject_drive       : "eject X", "safely remove X", "remove drive X"
- process_priority  : "boost X priority", "set X to high priority"
- switch_machine    : "hand off to windows/mac", "switch to windows/mac", "move izach to windows/mac" — moving THIS iZACH session to the other computer (Mac<->Windows dual-instance). This is NOT open_app — "windows"/"mac" here means the other computer, not launching an application. Extract target_platform as "mac" or "windows".

Rules:
- volume_delta: positive = increase, negative = decrease; default ±10 unless user says a number
- timer_seconds: convert "5 minutes" → 300, "1 hour" → 3600, "30 seconds" → 30
- shutdown/restart delay: "in 10 minutes" → 600, "now"/"immediately" → 0, no time specified → 0
- app_name: extract the app name without open/close/kill verbs
- "hand off"/"switch"/"move" + "to windows"/"to mac" (no app name, referring to the other computer) = switch_machine, NEVER open_app with app_name="windows"/"mac"
- "open/launch <app> in/on windows/mac" (HAS an app name) = open_app with app_name=<app> AND target_platform set — this runs the app on the OTHER machine, distinct from switch_machine above which has no app name
- Output ONLY the JSON object
"""

_CONFIRM_INTENTS = {"shutdown", "restart", "switch_machine"}   # require confirmation before executing

# open_app's LLM parser occasionally misreads a command like "play X on
# youtube" as "open youtube" — before blindly typing the app name into
# Windows Search (which launches whatever the top result happens to be),
# check whether it's actually installed. Well-known websites that have no
# native Windows app get opened in the browser instead; anything else gets
# an honest "not installed" rather than a false "opened" claim.
_OPEN_APP_WEBSITE_FALLBACKS = {
    "youtube": "https://youtube.com", "netflix": "https://netflix.com",
    "twitter": "https://twitter.com", "x": "https://x.com",
    "instagram": "https://instagram.com", "reddit": "https://reddit.com",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "linkedin": "https://linkedin.com", "amazon": "https://amazon.com",
    "chatgpt": "https://chat.openai.com", "netflix.com": "https://netflix.com",
}


class SystemAgent:
    """
    Handles all system/OS domain commands via LLM intent parsing + system_control calls.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak    = speak_fn
        self._raw_ai  = raw_ai_fn
        # Confirmation state for destructive ops (shutdown/restart)
        self._pending_confirm: dict | None = None

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute system command.
        Returns True if handled, False to fall through.
        """
        # Confirmation state: user was asked "are you sure?"
        if self._pending_confirm:
            return self._resolve_confirm(cmd)

        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[SYS_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "open_app":          self._open_app,
            "kill_app":          self._kill_app,
            "set_volume":        self._set_volume,
            "adjust_volume":     self._adjust_volume,
            "mute":              self._mute,
            "unmute":            self._unmute,
            "set_brightness":    self._set_brightness,
            "adjust_brightness": self._adjust_brightness,
            "set_theme":         self._set_theme,
            "set_timer":         self._set_timer,
            "screenshot":        self._screenshot,
            "shutdown":          self._shutdown,
            "restart":           self._restart,
            "cancel_shutdown":   self._cancel_shutdown,
            "wifi_on":           self._wifi_on,
            "wifi_off":          self._wifi_off,
            "wifi_toggle":       self._wifi_toggle,
            "battery_status":    self._battery_status,
            "battery_health":    self._battery_health,
            "cpu_temp":          self._cpu_temp,
            "ram_usage":         self._ram_usage,
            "firewall_status":   self._firewall_status,
            "update_status":     self._update_status,
            "wifi_signal":       self._wifi_signal,
            "network_devices":   self._network_devices,
            "list_drives":       self._list_drives,
            "eject_drive":       self._eject_drive,
            "process_priority":  self._process_priority,
            "switch_machine":    self._switch_machine,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[SYS_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Confirmation flow (shutdown / restart / switch_machine) ────

    def _ask_confirm(self, intent: str, intent_data: dict) -> bool:
        self._pending_confirm = {"intent": intent, "data": intent_data}
        if intent == "shutdown":
            label = "shut down your PC"
        elif intent == "restart":
            label = "restart your PC"
        else:
            target = intent_data.get("target_platform") or "the other computer"
            label = f"switch iZACH over to {target} and shut down here"
        self.speak(f"Are you sure you want to {label}?")
        return True

    def _resolve_confirm(self, cmd: str) -> bool:
        pending = self._pending_confirm
        self._pending_confirm = None
        if not pending:
            # Defensive — should not happen because caller checks _pending_confirm first
            return False
        _yes = {"yes", "yeah", "yep", "sure", "ok", "okay", "do it", "confirm", "haan"}
        _no  = {"no", "nope", "nahi", "cancel", "abort", "stop", "never mind"}
        words = set(cmd.lower().split())
        if words & _yes:
            # Execute the confirmed action
            intent = pending["intent"]
            d      = pending["data"]
            if intent == "shutdown":
                self._execute_shutdown(d)
            elif intent == "restart":
                self._execute_restart(d)
            elif intent == "switch_machine":
                self._execute_switch_machine(d)
        else:
            self.speak("Okay, cancelled.")
        return True

    # ── Handlers ─────────────────────────────────────────────────

    def _open_app(self, d: dict, cmd: str) -> bool:
        app = (d.get("app_name") or "").strip()
        if not app:
            self.speak("Which app should I open?")
            return True

        target_platform = (d.get("target_platform") or "").strip().lower()
        if target_platform:
            from modules.personality import get_platform_name
            if target_platform not in get_platform_name().lower():
                return self._open_app_on_peer(app, target_platform)
            # target_platform matches THIS machine (e.g. "open chrome on mac"
            # while already on Mac) — fall through to the normal local path.

        try:
            from modules.context_engine import handle_open_with_position, _APP_DIRECT_LAUNCH
            from modules.automation import is_app_installed

            app_lower = app.lower().strip()
            if app_lower not in _APP_DIRECT_LAUNCH and not is_app_installed(app):
                website = _OPEN_APP_WEBSITE_FALLBACKS.get(app_lower)
                if website:
                    from modules.ws_bridge import broadcast
                    broadcast({"type": "browser_command", "action": "open_url", "url": website})
                    self.speak(f"{app} isn't installed as an app here — opening it in the browser instead.")
                else:
                    self.speak(f"I don't see '{app}' installed on this PC — if I misheard you, try again.")
                return True

            result = handle_open_with_position(app, None)
            if result:
                self.speak(result)
        except Exception as e:
            self.speak(f"Couldn't open {app}: {e}")
        return True

    def _open_app_on_peer(self, app: str, target_platform: str) -> bool:
        """Handles 'open <app> in windows/mac' — routes to the dual-instance
        peer machine (Mac<->Windows switchable install, see
        modules/instance_coordinator.py), NOT AlliedNode 2 (a separate,
        unrelated satellite PC handled by modules/remote_node.py)."""
        from modules.instance_coordinator import is_configured, check_peer, get_peer_label
        if not is_configured():
            self.speak("No peer device is configured for cross-machine control.")
            return True

        label = get_peer_label() or target_platform.capitalize()
        if check_peer() is None:
            self.speak(f"{label} is not reachable.")
            return True

        from modules.instance_coordinator import get_peer_host
        from modules.peer_control import open_app as _peer_open_app
        result = _peer_open_app(get_peer_host(), app)
        if result.get("ok"):
            self.speak(f"Opened {app} on {label}.")
        else:
            self.speak(f"Couldn't open {app} on {label}: {result.get('error', 'unknown error')}")
        return True

    def _kill_app(self, d: dict, cmd: str) -> bool:
        name = (d.get("app_name") or d.get("process_name") or "").strip()
        if not name:
            # Fallback: strip kill verbs from cmd
            for v in ["force quit", "force close", "kill process", "end task",
                      "terminate process", "end process", "close"]:
                name = cmd.replace(v, "").strip()
                if name:
                    break
        if not name:
            self.speak("Which app should I close?")
            return True
        _, msg = _sc.kill_app(name)
        self.speak(msg)
        return True

    def _set_volume(self, d: dict, cmd: str) -> bool:
        level = d.get("volume_level")
        if level is None:
            m = re.search(r'\b(\d{1,3})\b', cmd)
            level = int(m.group(1)) if m else None
        if level is None:
            self.speak("What percentage should I set the volume to?")
            return True
        _, msg = _sc.set_volume(int(level))
        self.speak(msg)
        return True

    def _adjust_volume(self, d: dict, cmd: str) -> bool:
        delta = d.get("volume_delta")
        if delta is None:
            # Determine direction from command
            down_words = {"decrease", "lower", "reduce", "down", "softer", "quieter"}
            up_words   = {"increase", "raise", "boost", "up", "louder", "higher"}
            words      = set(cmd.lower().split())
            delta = -10 if words & down_words else 10
        _, msg = _sc.adjust_volume(int(delta))
        self.speak(msg)
        return True

    def _mute(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.mute()
        self.speak(msg)
        return True

    def _unmute(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.unmute()
        self.speak(msg)
        return True

    def _set_brightness(self, d: dict, cmd: str) -> bool:
        level = d.get("brightness_level")
        if level is None:
            m = re.search(r'\b(\d{1,3})\b', cmd)
            level = int(m.group(1)) if m else None
        if level is None:
            self.speak("What percentage should I set the brightness to?")
            return True
        _, msg = _sc.set_brightness(int(level))
        self.speak(msg)
        return True

    def _adjust_brightness(self, d: dict, cmd: str) -> bool:
        delta = d.get("brightness_delta")
        if delta is None:
            down_words = {"decrease", "lower", "reduce", "down", "dim", "dimmer"}
            up_words   = {"increase", "raise", "boost", "up", "brighter", "higher"}
            words      = set(cmd.lower().split())
            delta = -10 if words & down_words else 10
        _, msg = _sc.adjust_brightness(int(delta))
        self.speak(msg)
        return True

    def _set_theme(self, d: dict, cmd: str) -> bool:
        theme = (d.get("theme") or "").lower()
        if not theme:
            theme = "dark" if "dark" in cmd.lower() else "light"
        _, msg = _sc.set_theme(theme)
        self.speak(msg)
        return True

    def _set_timer(self, d: dict, cmd: str) -> bool:
        seconds = d.get("timer_seconds")
        if seconds is None:
            # Fallback regex parse
            seconds = 0
            h = re.search(r'(\d+)\s*hour', cmd)
            m = re.search(r'(\d+)\s*min', cmd)
            s = re.search(r'(\d+)\s*sec', cmd)
            if h: seconds += int(h.group(1)) * 3600
            if m: seconds += int(m.group(1)) * 60
            if s: seconds += int(s.group(1))
        if not seconds:
            self.speak("How long should the timer be?")
            return True
        _, msg = _sc.set_timer(int(seconds), self.speak)
        self.speak(msg)
        return True

    def _screenshot(self, d: dict, cmd: str) -> bool:
        try:
            from modules.screenshot_engine import capture_sync
            from modules.ws_bridge import broadcast
            filename = capture_sync()
            if filename:
                import time as _t
                broadcast({"type": "screenshot_ready", "filename": filename, "ts": _t.time()})
                self.speak("Screenshot captured.")
            else:
                self.speak("Screenshot failed.")
        except Exception as e:
            self.speak(f"Screenshot error: {e}")
        return True

    def _shutdown(self, d: dict, cmd: str) -> bool:
        return self._ask_confirm("shutdown", d)

    def _execute_shutdown(self, d: dict) -> None:
        delay = int(d.get("shutdown_delay_seconds") or 0)
        _, msg = _sc.schedule_shutdown(delay)
        self.speak(msg)

    def _restart(self, d: dict, cmd: str) -> bool:
        return self._ask_confirm("restart", d)

    def _execute_restart(self, d: dict) -> None:
        delay = int(d.get("shutdown_delay_seconds") or 0)
        _, msg = _sc.schedule_restart(delay)
        self.speak(msg)

    def _cancel_shutdown(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.cancel_shutdown()
        self.speak(msg)
        return True

    def _switch_machine(self, d: dict, cmd: str) -> bool:
        target = (d.get("target_platform") or "").strip().lower()
        if target not in ("mac", "windows"):
            self.speak("Switch to which computer — Mac or Windows?")
            return True
        return self._ask_confirm("switch_machine", d)

    def _execute_switch_machine(self, d: dict) -> None:
        target = (d.get("target_platform") or "").strip().lower()
        from modules.instance_coordinator import switch_to_peer
        ok, msg = switch_to_peer(target)
        self.speak(msg)

    def _wifi_on(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.set_wifi(True)
        self.speak(msg)
        return True

    def _wifi_off(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.set_wifi(False)
        self.speak(msg)
        return True

    def _wifi_toggle(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.toggle_wifi()
        self.speak(msg)
        return True

    def _battery_status(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_battery()
        self.speak(msg)
        return True

    def _battery_health(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_battery_health()
        self.speak(msg)
        return True

    def _cpu_temp(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_cpu_temperature()
        self.speak(msg)
        return True

    def _ram_usage(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_ram_usage()
        self.speak(msg)
        return True

    def _firewall_status(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_firewall_status()
        self.speak(msg)
        return True

    def _update_status(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_update_status()
        self.speak(msg)
        return True

    def _wifi_signal(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_wifi_signal()
        self.speak(msg)
        return True

    def _network_devices(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.get_network_devices()
        self.speak(msg)
        return True

    def _list_drives(self, d: dict, cmd: str) -> bool:
        _, msg = _sc.list_drives()
        self.speak(msg)
        return True

    def _eject_drive(self, d: dict, cmd: str) -> bool:
        drive_id = (d.get("drive_id") or "").strip()
        if not drive_id:
            # Fallback: strip known verbs/fillers from cmd
            for phrase in ["safely remove", "remove drive", "eject drive",
                           "eject the", "eject"]:
                drive_id = cmd.replace(phrase, "").strip()
                if drive_id:
                    break
            for filler in ["pendrive", "pen drive", "usb drive",
                           "usb", "the drive", "the", "drive"]:
                drive_id = drive_id.replace(filler, "").strip()
        if not drive_id:
            self.speak("Which drive should I eject?")
            return True
        _, msg = _sc.eject_drive(drive_id)
        self.speak(msg)
        return True

    def _process_priority(self, d: dict, cmd: str) -> bool:
        name  = (d.get("process_name") or d.get("app_name") or "").strip()
        level = (d.get("priority_level") or "high").lower()
        if not name:
            m = re.search(
                r'(?:boost|set|change)\s+(.+?)\s+(?:to\s+)?(?:low|normal|high|realtime)\s*priority',
                cmd, re.IGNORECASE
            )
            name = m.group(1).strip() if m else ""
        if not name:
            self.speak("Which process should I change priority for?")
            return True
        _, msg = _sc.set_process_priority(name, level)
        self.speak(msg)
        return True
