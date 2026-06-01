"""
subconsciousness.py  —  iZACH Phase 5A
JARVIS-style background intelligence layer.

Responsibilities:
  1. Permission gate — dangerous actions queue for user approval before exec
  2. System health monitor — battery / RAM / disk proactive alerts
  3. Ambient context — WhatsApp attachment awareness, active window context
  4. Self-initiated micro-tasks — close idle chrome tabs, suggest cleanup, etc.

Integration points:
  • command_chain.py: call request_permission() before destructive ops
  • ui_api.py: /subconsciousness/* REST endpoints
  • Cortex UI: permission overlay widget
  • main.py: init(speak_fn) + start()
"""

import logging
import threading
import time
import uuid
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Module state
# ─────────────────────────────────────────────────────────────

_speak_fn: Optional[Callable]   = None
_chain_fn:  Optional[Callable]  = None   # chain_engine.process — for self-initiated tasks
_running    = False
_lock       = threading.Lock()

# Permission gate — keyed by action_id
# {id: {desc, callback, created_at, expires_at, status: pending|granted|denied}}
_pending: dict[str, dict] = {}

# Alert dedup — avoid spam
_last_battery_warn_ts:  float = 0.0
_last_ram_warn_ts:      float = 0.0
_last_disk_warn_ts:     float = 0.0
_last_temp_warn_ts:     float = 0.0

# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def init(speak_fn: Callable, chain_fn: Optional[Callable] = None):
    global _speak_fn, _chain_fn
    _speak_fn = speak_fn
    _chain_fn  = chain_fn


def start():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_monitor_loop, daemon=True, name="SubconsciousnessMonitor").start()
    logger.info("[Subconsciousness] Started.")


def stop():
    global _running
    _running = False


# ─────────────────────────────────────────────────────────────
# Permission Gate
# ─────────────────────────────────────────────────────────────

PERMISSION_TIMEOUT_SEC = 60   # auto-deny after 60s of no response

def request_permission(description: str, callback: Callable, auto_speak: bool = True) -> str:
    """
    Queue an action for user approval.
    Returns action_id. callback() is called only if user grants.

    Usage (in command_chain):
        def _do_delete():
            os.remove(path)
        subconsciousness.request_permission(f"delete {path}", _do_delete)
    """
    action_id = str(uuid.uuid4())[:8]
    now = time.time()
    entry = {
        "id":          action_id,
        "description": description,
        "callback":    callback,
        "created_at":  now,
        "expires_at":  now + PERMISSION_TIMEOUT_SEC,
        "status":      "pending",
    }
    with _lock:
        _pending[action_id] = entry

    # Push to UI via websocket
    _push_permission_event(action_id, description)

    # Speak the permission request
    if auto_speak and _speak_fn:
        _speak_fn(f"Should I {description}? Say yes to confirm or no to cancel.")

    # Start expiry watcher
    threading.Thread(target=_expiry_watcher, args=(action_id,), daemon=True).start()

    logger.info(f"[Subconsciousness] Permission requested: [{action_id}] {description}")
    return action_id


def grant(action_id: str) -> bool:
    """User approved — execute callback."""
    with _lock:
        entry = _pending.get(action_id)
        if not entry or entry["status"] != "pending":
            return False
        entry["status"] = "granted"

    logger.info(f"[Subconsciousness] Granted: [{action_id}] {entry['description']}")
    if _speak_fn:
        _speak_fn("Alright, doing it now.")
    try:
        entry["callback"]()
    except Exception as e:
        logger.error(f"[Subconsciousness] Callback error [{action_id}]: {e}")
        if _speak_fn:
            _speak_fn(f"Something went wrong: {e}")
    _push_permission_resolved(action_id, "granted")
    return True


def deny(action_id: str, reason: str = "Cancelled.") -> bool:
    """User denied or timeout — discard callback."""
    with _lock:
        entry = _pending.get(action_id)
        if not entry or entry["status"] != "pending":
            return False
        entry["status"] = "denied"

    logger.info(f"[Subconsciousness] Denied: [{action_id}] {entry['description']}")
    if _speak_fn:
        _speak_fn(reason)
    _push_permission_resolved(action_id, "denied")
    return True


def get_pending() -> list[dict]:
    """Return list of pending permission requests (no callbacks — UI-safe)."""
    now = time.time()
    with _lock:
        return [
            {
                "id":          e["id"],
                "description": e["description"],
                "created_at":  e["created_at"],
                "expires_at":  e["expires_at"],
                "status":      e["status"],
                "seconds_left": max(0, int(e["expires_at"] - now)),
            }
            for e in _pending.values()
            if e["status"] == "pending"
        ]


def get_all() -> list[dict]:
    """All entries including resolved (for audit log)."""
    with _lock:
        return [
            {k: v for k, v in e.items() if k != "callback"}
            for e in _pending.values()
        ]


def handle_voice_response(text: str) -> bool:
    """
    Call this from voice loop when user speaks after a permission was requested.
    Returns True if text was consumed as a permission response.
    """
    t = text.lower().strip()
    pending_list = get_pending()
    if not pending_list:
        return False

    # Pick most recent pending
    entry = sorted(pending_list, key=lambda x: x["created_at"])[-1]
    aid   = entry["id"]

    YES = {"yes", "yeah", "yep", "do it", "confirm", "sure", "ok", "okay", "go ahead", "proceed"}
    NO  = {"no", "nope", "cancel", "stop", "abort", "don't", "dont", "skip", "nevermind", "never mind"}

    if any(w in t for w in YES):
        grant(aid)
        return True
    if any(w in t for w in NO):
        deny(aid, "Okay, cancelled.")
        return True

    return False


def clear_resolved():
    """Remove granted/denied entries (house-keeping)."""
    with _lock:
        to_del = [k for k, v in _pending.items() if v["status"] != "pending"]
        for k in to_del:
            del _pending[k]


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _expiry_watcher(action_id: str):
    time.sleep(PERMISSION_TIMEOUT_SEC + 2)
    with _lock:
        entry = _pending.get(action_id)
        if entry and entry["status"] == "pending":
            entry["status"] = "denied"
    if _speak_fn:
        _speak_fn("Permission request timed out. Action cancelled.")
    _push_permission_resolved(action_id, "timeout")
    logger.info(f"[Subconsciousness] Timed out: [{action_id}]")


def _push_permission_event(action_id: str, description: str):
    try:
        from modules.ws_bridge import emit
        emit("permission_requested", "subconsciousness", {
            "id":          action_id,
            "description": description,
            "expires_in":  PERMISSION_TIMEOUT_SEC,
        })
    except Exception:
        pass


def _push_permission_resolved(action_id: str, status: str):
    try:
        from modules.ws_bridge import emit
        emit("permission_resolved", "subconsciousness", {
            "id":     action_id,
            "status": status,
        })
    except Exception:
        pass


def _alert(msg: str):
    """Speak + push notification."""
    if _speak_fn:
        _speak_fn(msg)
    try:
        from modules.notification_system import push
        push(msg, category="alerts")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Background monitor loop
# ─────────────────────────────────────────────────────────────

MONITOR_INTERVAL = 120   # seconds between health checks

def _monitor_loop():
    time.sleep(20)  # let system fully boot first
    while _running:
        try:
            _check_battery()
            _check_ram()
            _check_disk()
            _check_cpu_temp()
            _expire_pending()
        except Exception as e:
            logger.error(f"[Subconsciousness] Monitor error: {e}")
        time.sleep(MONITOR_INTERVAL)


def _expire_pending():
    """Quietly expire overdue pending actions (belt+suspenders with _expiry_watcher)."""
    now = time.time()
    with _lock:
        for entry in _pending.values():
            if entry["status"] == "pending" and now > entry["expires_at"] + 5:
                entry["status"] = "denied"


# ─────────────────────────────────────────────────────────────
# Health checks
# ─────────────────────────────────────────────────────────────

_BATTERY_WARN_COOLDOWN  = 1800   # 30 min between battery alerts
_RAM_WARN_COOLDOWN      = 900    # 15 min between RAM alerts
_DISK_WARN_COOLDOWN     = 3600   # 1 hour between disk alerts
_TEMP_WARN_COOLDOWN     = 600    # 10 min between temp alerts

_notif_perf_cache: tuple[bool, float] = (True, 0.0)

def _notif_perf_enabled() -> bool:
    """Read notif_performance from settings (cached 60s)."""
    global _notif_perf_cache
    val, ts = _notif_perf_cache
    if time.time() - ts < 60:
        return val
    try:
        import json as _j
        with open("api_keys.json") as _f:
            val = bool(_j.load(_f).get("notif_performance", True))
    except Exception:
        val = True
    _notif_perf_cache = (val, time.time())
    return val


def _check_battery():
    global _last_battery_warn_ts
    try:
        import psutil
        bat = psutil.sensors_battery()
        if bat is None:
            return
        pct   = bat.percent
        plugged = bat.power_plugged

        now = time.time()
        cooldown_ok = (now - _last_battery_warn_ts) > _BATTERY_WARN_COOLDOWN

        if not plugged and pct <= 10 and cooldown_ok:
            _last_battery_warn_ts = now
            if _notif_perf_enabled():
                _alert(f"Battery critically low at {pct:.0f}%. Please plug in your charger.")
        elif not plugged and pct <= 20 and cooldown_ok:
            _last_battery_warn_ts = now
            if _notif_perf_enabled():
                _alert(f"Battery at {pct:.0f}%. You might want to plug in soon.")
        elif plugged and pct >= 95 and cooldown_ok:
            _last_battery_warn_ts = now
            if _notif_perf_enabled():
                _alert(f"Battery is at {pct:.0f}% and still charging. Consider unplugging to preserve battery health.")
    except Exception:
        pass


def _check_ram():
    global _last_ram_warn_ts
    try:
        import psutil
        vm  = psutil.virtual_memory()
        pct = vm.percent
        now = time.time()
        if pct >= 90 and (now - _last_ram_warn_ts) > _RAM_WARN_COOLDOWN:
            _last_ram_warn_ts = now
            if _notif_perf_enabled():
                used_gb  = vm.used  / (1024 ** 3)
                total_gb = vm.total / (1024 ** 3)
                _alert(
                    f"Memory usage is very high — {pct:.0f}% used, "
                    f"{used_gb:.1f} of {total_gb:.1f} gigabytes. "
                    f"You may want to close some applications."
                )
    except Exception:
        pass


def _check_disk():
    global _last_disk_warn_ts
    try:
        import psutil
        disk = psutil.disk_usage("C:\\")
        free_gb = disk.free / (1024 ** 3)
        pct_used = disk.percent
        now = time.time()
        if free_gb < 5 and (now - _last_disk_warn_ts) > _DISK_WARN_COOLDOWN:
            _last_disk_warn_ts = now
            _alert(
                f"Low disk space — only {free_gb:.1f} gigabytes free on your C drive. "
                f"Consider clearing some files."
            )
    except Exception:
        pass


def _check_cpu_temp():
    global _last_temp_warn_ts
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if not temps:
            return
        # Try common sensor keys
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if key in temps:
                max_temp = max(t.current for t in temps[key])
                now = time.time()
                if max_temp >= 90 and (now - _last_temp_warn_ts) > _TEMP_WARN_COOLDOWN:
                    _last_temp_warn_ts = now
                    _alert(
                        f"CPU temperature is high at {max_temp:.0f} degrees Celsius. "
                        f"Make sure your laptop has proper ventilation."
                    )
                break
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Dangerous command classifier
# ─────────────────────────────────────────────────────────────

# Patterns that REQUIRE permission before executing.
# Each entry: (regex_pattern, human_description_template)
import re as _re

_DANGEROUS_PATTERNS: list[tuple] = [
    # File deletion
    (_re.compile(r'\b(delete|remove|erase|wipe)\b.*\b(file|folder|directory|document|photo|image|video|all)\b', _re.I),
     "delete files"),
    (_re.compile(r'\b(empty|clear)\b.*\b(recycle\s*bin|trash|temp|downloads)\b', _re.I),
     "empty the trash"),
    # Format / wipe drive
    (_re.compile(r'\b(format|wipe|reformat)\b.*\b(disk|drive|usb|sd|partition)\b', _re.I),
     "format a drive"),
    # Shutdown / restart
    (_re.compile(r'\b(shutdown|shut\s*down|restart|reboot|power\s*off|turn\s*off\s*(the\s*)?(pc|computer|laptop|system))\b', _re.I),
     "shut down the computer"),
    # Uninstall
    (_re.compile(r'\b(uninstall|remove)\b.{0,30}\b(app|application|program|software)\b', _re.I),
     "uninstall an application"),
    # Mass send messages
    (_re.compile(r'\b(send|message|text)\b.{0,20}\b(everyone|all contacts|all groups|broadcast)\b', _re.I),
     "send a broadcast message"),
    # System registry / hosts file
    (_re.compile(r'\b(edit|modify|change|delete)\b.{0,20}\b(registry|hosts\s*file|system\s*file)\b', _re.I),
     "modify a system file"),
    # Git force push / destructive git
    (_re.compile(r'\bgit\b.{0,20}\b(force\s*push|reset\s*--hard|clean\s*-f|branch\s*-[Dd])\b', _re.I),
     "run a destructive git operation"),
    # Kill / terminate processes
    (_re.compile(r'\b(kill|terminate|force\s*quit)\b.{0,20}\b(all|every|process)\b', _re.I),
     "kill multiple processes"),
    # Clear browser data
    (_re.compile(r'\b(clear|delete|wipe)\b.{0,20}\b(browser\s*data|cookies|history|cache\s*and\s*cookies)\b', _re.I),
     "clear browser data"),
]


def is_dangerous(cmd: str) -> tuple[bool, str]:
    """
    Returns (True, description) if command matches a dangerous pattern.
    Returns (False, '') otherwise.
    """
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            return True, description
    return False, ""


def check_and_gate(cmd: str, callback: Callable) -> bool:
    """
    Check if cmd is dangerous. If so, request permission and return True (gated).
    If safe, return False (caller should proceed normally).

    Usage in command_chain:
        if subconsciousness.check_and_gate(resolved_cmd, lambda: _do_delete(path)):
            return  # gated — waiting for permission
        # otherwise fall through to normal execution
    """
    dangerous, desc = is_dangerous(cmd)
    if dangerous:
        request_permission(desc, callback)
        return True
    return False
