"""
modules/instance_coordinator.py
Dual-instance (Windows + macOS) coordination — mutual "already running"
detection, primary/secondary role negotiation, and the "Secondary Connector"
lightweight mode this feeds into (see main.py's start_brain()).

Config lives in two places, matching the codebase's existing convention:
  - api_keys.json["dual_instance"]: {enabled, peer_host, peer_port,
    primary_pin ("auto"|"always_mac"|"always_windows"),
    auto_promote_enabled, auto_promote_timeout_minutes} — user-editable
    settings, no secrets, set from Settings UI.
  - .env IZACH_PEER_TOKEN — shared secret between the two machines' own
    installs, same pattern as N8N_SHARED_TOKEN/MMA_TOKEN.

A solo install (no peer_host configured) behaves exactly as before this
feature existed — decide_role() returns "primary" immediately with no
network calls. Nothing here activates unless the user deliberately sets up
a peer.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

from modules.personality import get_platform_name
from modules.platform_utils import IS_MAC, IS_WINDOWS

_API_KEYS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api_keys.json")
_PEER_TOKEN = os.environ.get("IZACH_PEER_TOKEN", "")
_PEER_TIMEOUT = 3  # seconds — LAN call, must not hang startup if peer's down

_START_TIME = time.time()
_ROLE_LOCK = threading.Lock()
_role = "primary"
_role_reason = "dual-instance not configured"
_peer_info: dict | None = None   # last-seen /peer/status payload from the peer, for UI display


def _load_config() -> dict:
    try:
        with open(_API_KEYS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("dual_instance") or {}
    except Exception:
        return {}


def is_configured() -> bool:
    cfg = _load_config()
    return bool(cfg.get("enabled") and cfg.get("peer_host"))


def get_peer_host() -> str | None:
    """Public accessor for peer_control.py — avoids reaching into the
    private _load_config() from another module."""
    return _load_config().get("peer_host") or None


def get_role() -> str:
    with _ROLE_LOCK:
        return _role


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _mac_address() -> str:
    """This machine's MAC address, for display in the peer-status UI —
    uuid.getnode() is cross-platform (Windows/macOS) and needs no extra deps."""
    try:
        import uuid
        node = uuid.getnode()
        return ':'.join(f'{(node >> shift) & 0xff:02x}' for shift in range(40, -8, -8))
    except Exception:
        return "unknown"


def get_status() -> dict:
    """Served at GET /peer/status — what the OTHER machine calls to check us."""
    with _ROLE_LOCK:
        role, reason = _role, _role_reason
    return {
        "platform": get_platform_name(),
        "hostname": _hostname(),
        "mac_address": _mac_address(),
        "is_primary": role == "primary",
        "role": role,
        "reason": reason,
        "since": _START_TIME,
        "owner": os.environ.get("OWNER_NAME", "User"),
    }


def get_peer_info() -> dict | None:
    """Last-seen /peer/status payload from the peer (platform/hostname/mac_address/etc),
    for this machine's OWN UI to show 'iZACH is already running on <peer>'. None if no
    peer has ever been seen reachable (solo install, or peer never came up)."""
    with _ROLE_LOCK:
        return _peer_info


def _peer_url(cfg: dict, path: str) -> str:
    host = cfg.get("peer_host")
    port = cfg.get("peer_port", 5050)
    return f"http://{host}:{port}{path}"


def check_peer(cfg: dict = None) -> dict | None:
    """GET the peer's /peer/status. Returns None if unreachable/unconfigured
    — callers must treat that as 'no conflict, proceed normally' (this
    coordination is offline-first: a missing peer never blocks startup)."""
    cfg = cfg or _load_config()
    if not cfg.get("peer_host"):
        return None
    try:
        import requests
        r = requests.get(
            _peer_url(cfg, "/peer/status"), timeout=_PEER_TIMEOUT,
            headers={"X-iZACH-Peer-Token": _PEER_TOKEN},
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _pin_wants_this_machine(pin: str):
    """True/False if the pin has an opinion, None if 'auto' (no preference)."""
    if pin == "always_mac":
        return IS_MAC
    if pin == "always_windows":
        return IS_WINDOWS
    return None


def _platform_wins_tiebreak() -> bool:
    """Deterministic fallback for the case where both machines start around
    the same moment and neither has claimed primary yet — a coin-flip based
    on timestamps would be unreliable (clock drift between two machines), so
    this uses a fixed, platform-based rule instead: whichever side evaluates
    this locally always reaches the same answer, so exactly one side claims
    primary and the other defers, with no network round-trip needed to agree."""
    return IS_MAC


def decide_role(notify=None) -> tuple[str, str]:
    """Call once, early in startup (before the heavy voice-loop/agent init
    in main.py's start_brain()). Returns (role, human_readable_reason).
    notify(msg) is an optional callback (e.g. speak()) for a one-line status
    announcement to the user."""
    global _role, _role_reason, _peer_info
    cfg = _load_config()

    if not cfg.get("enabled") or not cfg.get("peer_host"):
        role, reason = "primary", "dual-instance not configured"
        with _ROLE_LOCK:
            _role, _role_reason = role, reason
        return role, reason

    peer = check_peer(cfg)
    if peer is not None:
        with _ROLE_LOCK:
            _peer_info = peer
    pin = cfg.get("primary_pin", "auto")
    pin_wants_me = _pin_wants_this_machine(pin)

    if peer is None:
        role, reason = "primary", "peer unreachable — starting as primary"
    elif peer.get("is_primary"):
        # An already-active primary always wins — never force a takeover at
        # startup even if the pin disagrees. A pin mismatch here is resolved
        # by the user saying a handoff command, not by silently overriding
        # a machine that's mid-session.
        peer_platform = peer.get("platform", "the other machine")
        if pin_wants_me is True:
            role = "secondary"
            reason = (f"iZACH is already running on {peer_platform}. Your pin says this "
                      f"machine should be primary — say \"move to {get_platform_name()}\" to switch.")
        else:
            role = "secondary"
            reason = f"iZACH is already running on {peer_platform}. Starting Secondary Connector mode."
    elif pin_wants_me is True:
        role, reason = "primary", "peer reachable but idle — pin claims primary for this machine"
    elif pin_wants_me is False:
        role, reason = "secondary", "peer reachable but idle — pin claims primary for the other machine"
    else:
        # "auto" pin, neither side has claimed primary yet — deterministic
        # tiebreak so simultaneous startups never both become primary.
        if _platform_wins_tiebreak():
            role, reason = "primary", "no active primary detected — starting as primary"
        else:
            role, reason = "secondary", "peer reachable, deferring to it as primary (tiebreak)"

    with _ROLE_LOCK:
        _role, _role_reason = role, reason
    if notify:
        try:
            notify(reason)
        except Exception:
            pass
    return role, reason


def become_primary(reason: str = "promoted"):
    global _role, _role_reason
    with _ROLE_LOCK:
        _role, _role_reason = "primary", reason


def become_secondary(reason: str = "demoted"):
    global _role, _role_reason
    with _ROLE_LOCK:
        _role, _role_reason = "secondary", reason


def verify_peer_token(token: str) -> bool:
    return bool(_PEER_TOKEN) and token == _PEER_TOKEN


# ── Handoff ("move to Windows/Mac") ─────────────────────────────
# Deliberately restart-based, not a live in-process demotion: this instance
# may have 30+ background threads running (voice loop, wake word, agents) that
# were never designed to be torn down cleanly mid-session. Promoting a
# SECONDARY instance in-process would also risk double-binding ports 5050/5051
# since the lightweight Flask/WS servers are already up. Both directions of a
# role change are safer as "mark the new state, then the process exits/gets
# restarted" — decide_role() at the next startup picks up the new reality
# correctly either way.

def initiate_handoff(target_platform: str) -> tuple[bool, str]:
    """target_platform: 'mac' or 'windows' (case-insensitive substring match
    against get_platform_name()). 2-phase: promote the peer FIRST and confirm
    it succeeded, THEN mark this instance secondary — so there's never a
    moment with zero primaries if the peer call fails partway."""
    cfg = _load_config()
    if not cfg.get("peer_host"):
        return False, "No peer configured for dual-instance handoff."

    my_platform = get_platform_name().lower()
    if target_platform.lower() in my_platform:
        return False, f"This machine is already the {get_platform_name()} instance."

    try:
        import requests
        r = requests.post(
            _peer_url(cfg, "/peer/handoff"), json={"action": "promote"},
            headers={"X-iZACH-Peer-Token": _PEER_TOKEN}, timeout=5,
        )
        if r.status_code != 200 or not r.json().get("ok"):
            return False, "Could not hand off — the other machine rejected the request."
    except Exception:
        return False, "Could not hand off — the other machine is unreachable right now."

    become_secondary("handed off to peer")
    return True, (
        "Handed off — the other machine is now primary. Restart iZACH on this "
        "machine to finish switching it into Secondary Connector mode."
    )


_DAEMON_PORT = int(os.environ.get("IZACH_DAEMON_PORT", "5052"))


def _exit_after_delay(seconds: float = 2.0):
    """Runs on a background thread so the HTTP caller (ui_api.py's
    /switch_machine route) gets its response before this process exits."""
    time.sleep(seconds)
    os._exit(0)


def switch_to_peer(target_platform: str) -> tuple[bool, str]:
    """The "Switch to Windows/Mac" button — unlike initiate_handoff() (which
    only works if the peer is ALREADY running, and leaves this machine's own
    shutdown to the user), this also handles a completely offline peer: boots
    it via boot_daemon.py's /daemon/boot first, waits for it to come up
    healthy, then automatically hands off and exits this machine's iZACH.
    Never touches the local process unless the peer is confirmed reachable
    and healthy first — a network hiccup mid-switch leaves this machine
    running, not dead with no primary anywhere."""
    cfg = _load_config()
    if not cfg.get("peer_host"):
        return False, "No peer configured for dual-instance switching."

    my_platform = get_platform_name().lower()
    if target_platform.lower() in my_platform:
        return False, f"This machine is already the {get_platform_name()} instance."

    if check_peer(cfg) is None:
        # Peer's not running at all — boot it via its daemon first.
        ok, msg = _boot_peer(cfg)
        if not ok:
            return False, msg
        if not _wait_for_peer_healthy(cfg, timeout=90):
            return False, "Peer didn't come up healthy within 90s — this machine stays primary, nothing was shut down."

    try:
        import requests
        r = requests.post(
            _peer_url(cfg, "/peer/handoff"), json={"action": "promote"},
            headers={"X-iZACH-Peer-Token": _PEER_TOKEN}, timeout=5,
        )
        if r.status_code != 200 or not r.json().get("ok"):
            return False, "Peer came up but rejected the handoff request — this machine stays primary."
    except Exception:
        return False, "Peer came up but became unreachable during handoff — this machine stays primary."

    become_secondary("switched to peer")
    threading.Thread(target=_exit_after_delay, daemon=True).start()
    return True, "Switched — the peer machine is now primary, this one is shutting down."


def _boot_peer(cfg: dict) -> tuple[bool, str]:
    host = cfg.get("peer_host")
    try:
        import requests
        r = requests.post(
            f"http://{host}:{_DAEMON_PORT}/daemon/boot", timeout=5,
            headers={"X-iZACH-Peer-Token": _PEER_TOKEN},
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True, "boot triggered"
        if r.status_code == 401:
            return False, "Peer's boot daemon rejected the request — IZACH_PEER_TOKEN doesn't match on both machines."
        return False, "Peer's boot daemon returned an unexpected error."
    except Exception:
        return False, (
            f"Could not reach {host}:{_DAEMON_PORT} — the peer machine appears to be "
            "offline, or its boot daemon isn't installed/running."
        )


def _wait_for_peer_healthy(cfg: dict, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_peer(cfg) is not None:
            return True
        time.sleep(3)
    return False


def watch_for_auto_promotion(poll_interval_s: int = 30):
    """Call from Secondary Connector mode (main.py's _start_secondary_connector).
    Runs forever in a background thread — if auto_promote_enabled and the
    peer stays unreachable past auto_promote_timeout_minutes, exits the
    process so it can restart as primary (decide_role() will then find no
    peer and correctly claim primary). Requires the process to actually be
    auto-restarted (e.g. a launchd/Task Scheduler supervisor with
    keep-alive/restart-on-exit) to be a real self-healing story — without
    that, this just stops cleanly rather than silently hanging in a broken
    secondary state forever."""
    import os
    import time as _time
    unreachable_since = None
    while True:
        _time.sleep(poll_interval_s)
        cfg = _load_config()
        if not cfg.get("auto_promote_enabled"):
            unreachable_since = None
            continue
        timeout_s = cfg.get("auto_promote_timeout_minutes", 5) * 60
        peer = check_peer(cfg)
        if peer is None:
            if unreachable_since is None:
                unreachable_since = _time.time()
                print("[DUAL-INSTANCE] Peer unreachable — auto-promotion timer started.")
            elif _time.time() - unreachable_since > timeout_s:
                print(f"[DUAL-INSTANCE] Peer unreachable for over "
                      f"{cfg.get('auto_promote_timeout_minutes', 5)} min — auto-promoting. "
                      f"Exiting so this process restarts as primary.")
                os._exit(0)
        else:
            if unreachable_since is not None:
                print("[DUAL-INSTANCE] Peer reachable again — auto-promotion timer reset.")
            unreachable_since = None


# ── Auto-promotion watchdog (Task Scheduler on Windows, launchd on macOS) ─
# watch_for_auto_promotion() above exits the process on os._exit(0) — for
# that to actually self-heal (restart as primary) instead of just leaving
# iZACH dead, SOMETHING has to relaunch it. Neither Task Scheduler nor
# launchd can "watch" an arbitrary already-running process — each can only
# relaunch a process IT directly spawns — so when auto-promote is enabled,
# the OS scheduler becomes the thing that starts main.py, and
# launch_izach.py's backend step defers to it (kickstart_watchdog) instead
# of spawning its own subprocess, so there's never two main.py instances
# fighting over port 5050.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows — Task Scheduler running a PowerShell relaunch-loop script.
_WATCHDOG_TASK_NAME = "iZACH_Watchdog"
_WATCHDOG_SCRIPT_PATH = os.path.join(_PROJECT_ROOT, "izach_watchdog.ps1")

# macOS — launchd agent (RunAtLoad + KeepAlive) running main.py directly.
_WATCHDOG_LABEL = "com.izach.watchdog"
_WATCHDOG_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{_WATCHDOG_LABEL}.plist")


def is_watchdog_installed() -> bool:
    if IS_MAC:
        return os.path.exists(_WATCHDOG_PLIST)
    if IS_WINDOWS:
        try:
            r = subprocess.run(
                ["schtasks", "/query", "/tn", _WATCHDOG_TASK_NAME],
                capture_output=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False
    return False


def _write_windows_watchdog_script():
    """The wrapper loop is what actually provides restart-on-exit — Task
    Scheduler has no launchd-style KeepAlive, so its only job is to start
    this loop once at logon; the loop itself relaunches main.py forever."""
    python_exe = sys.executable
    main_py = os.path.join(_PROJECT_ROOT, "main.py")
    script = (
        "# iZACH watchdog — relaunches main.py whenever it exits, so a\n"
        "# Secondary Connector auto-promoting itself (os._exit(0) in\n"
        "# instance_coordinator.watch_for_auto_promotion) actually comes back\n"
        "# up instead of just staying dead. Uninstalled by uninstall_watchdog().\n"
        "# Set-Location matters — main.py opens config files (api_keys.json etc.)\n"
        "# via bare relative paths, assuming cwd is the project root. Task\n"
        "# Scheduler's default working directory is NOT that, so without this\n"
        "# main.py boots partway then crashes on a missing-file error.\n"
        f"Set-Location \"{_PROJECT_ROOT}\"\n"
        "while ($true) {\n"
        f"    & \"{python_exe}\" \"{main_py}\"\n"
        "    Start-Sleep -Seconds 2\n"
        "}\n"
    )
    with open(_WATCHDOG_SCRIPT_PATH, "w", encoding="utf-8") as f:
        f.write(script)


def install_watchdog() -> tuple[bool, str]:
    """Register main.py with the OS's own service/scheduler so it's
    relaunched on ANY exit (including the clean os._exit(0) auto-promotion
    uses): Task Scheduler + a relaunch-loop script on Windows, launchd
    RunAtLoad+KeepAlive on macOS."""
    if IS_MAC:
        try:
            python_bin = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")
            main_py = os.path.join(_PROJECT_ROOT, "main.py")
            os.makedirs(os.path.dirname(_WATCHDOG_PLIST), exist_ok=True)
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{_WATCHDOG_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{main_py}</string>
    </array>
    <key>WorkingDirectory</key><string>{_PROJECT_ROOT}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{_PROJECT_ROOT}/logs/watchdog.log</string>
    <key>StandardErrorPath</key><string>{_PROJECT_ROOT}/logs/watchdog.log</string>
</dict>
</plist>
"""
            with open(_WATCHDOG_PLIST, "w", encoding="utf-8") as f:
                f.write(plist)
            subprocess.run(["launchctl", "load", _WATCHDOG_PLIST], capture_output=True, timeout=5)
            return True, "Watchdog installed — iZACH backend now auto-restarts on exit."
        except Exception as e:
            return False, f"Watchdog install failed: {e}"
    if IS_WINDOWS:
        try:
            _write_windows_watchdog_script()
            cmd = [
                "schtasks", "/create", "/tn", _WATCHDOG_TASK_NAME,
                "/tr", f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{_WATCHDOG_SCRIPT_PATH}"',
                "/sc", "onlogon", "/f",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return True, "Watchdog installed — main.py restarts automatically if it exits."
            return False, f"schtasks failed: {(r.stderr or r.stdout).strip()}"
        except Exception as e:
            return False, f"Could not install watchdog: {e}"
    return False, "Watchdog is only supported on Windows and macOS."


def uninstall_watchdog() -> tuple[bool, str]:
    if IS_MAC:
        try:
            if os.path.exists(_WATCHDOG_PLIST):
                subprocess.run(["launchctl", "unload", _WATCHDOG_PLIST], capture_output=True, timeout=5)
                os.remove(_WATCHDOG_PLIST)
            return True, "Watchdog removed."
        except Exception as e:
            return False, f"Watchdog removal failed: {e}"
    if IS_WINDOWS:
        # Deleting the scheduled task only stops FUTURE starts — the wrapper
        # loop, if already running from a prior logon, keeps relaunching
        # main.py forever until it's actually killed too.
        try:
            ps_find = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*{os.path.basename(_WATCHDOG_SCRIPT_PATH)}*' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_find],
                capture_output=True, text=True, timeout=10,
            )
            for pid in r.stdout.split():
                pid = pid.strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["schtasks", "/delete", "/tn", _WATCHDOG_TASK_NAME, "/f"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return True, "Watchdog uninstalled."
            # Already gone is not an error worth surfacing as one
            if "cannot find" in (r.stderr or "").lower() or "cannot find" in (r.stdout or "").lower():
                return True, "Watchdog was not installed."
            return False, f"schtasks failed: {(r.stderr or r.stdout).strip()}"
        except Exception as e:
            return False, f"Could not uninstall watchdog: {e}"
    return False, "Watchdog is only supported on Windows and macOS."


def kickstart_watchdog() -> bool:
    """Force the OS-managed backend to (re)start right now, rather than
    waiting for the next login. Used by launch_izach.py's backend step when
    the watchdog is installed, instead of spawning its own subprocess — the
    scheduler already owns this process's lifecycle at that point."""
    if IS_MAC:
        try:
            uid = os.getuid()
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{_WATCHDOG_LABEL}"],
                            capture_output=True, timeout=10)
            return True
        except Exception:
            return False
    if IS_WINDOWS:
        try:
            r = subprocess.run(
                ["schtasks", "/run", "/tn", _WATCHDOG_TASK_NAME],
                capture_output=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False
    return False


# ── Boot daemon (cross-machine "Switch to Mac/Windows") ─────────────
# Deliberately separate from the watchdog above: the watchdog only restarts
# main.py if it exits — it does nothing when main.py has never been started
# this session. The boot daemon is a second, independent always-on service
# (boot_daemon.py) whose only job is to be reachable and listen for a
# remote-start request even when iZACH itself isn't running at all.
_BOOT_DAEMON_LABEL = "com.izach.boot"
_BOOT_DAEMON_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{_BOOT_DAEMON_LABEL}.plist")
_BOOT_DAEMON_TASK_NAME = "iZACH_BootDaemon"
_BOOT_DAEMON_SCRIPT_PATH = os.path.join(_PROJECT_ROOT, "izach_boot_daemon_watchdog.ps1")


def is_boot_daemon_installed() -> bool:
    if IS_MAC:
        return os.path.exists(_BOOT_DAEMON_PLIST)
    if IS_WINDOWS:
        try:
            r = subprocess.run(
                ["schtasks", "/query", "/tn", _BOOT_DAEMON_TASK_NAME],
                capture_output=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False
    return False


def _write_windows_boot_daemon_script():
    python_exe = sys.executable
    daemon_py = os.path.join(_PROJECT_ROOT, "boot_daemon.py")
    script = (
        "# iZACH boot daemon wrapper — relaunches boot_daemon.py whenever it\n"
        "# exits, so the always-on remote-start listener stays up. Uninstalled\n"
        "# by uninstall_boot_daemon(). Set-Location matters for the same reason\n"
        "# as the main watchdog script: boot_daemon.py reads .env via a bare\n"
        "# relative path, assuming cwd is the project root.\n"
        f"Set-Location \"{_PROJECT_ROOT}\"\n"
        "while ($true) {\n"
        f"    & \"{python_exe}\" \"{daemon_py}\"\n"
        "    Start-Sleep -Seconds 2\n"
        "}\n"
    )
    with open(_BOOT_DAEMON_SCRIPT_PATH, "w", encoding="utf-8") as f:
        f.write(script)


def install_boot_daemon() -> tuple[bool, str]:
    """Register boot_daemon.py as an OS-managed background service, running
    independently of iZACH's own process — same RunAtLoad+KeepAlive pattern
    as install_watchdog(), pointed at a different script/port."""
    if IS_MAC:
        try:
            python_bin = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")
            daemon_py = os.path.join(_PROJECT_ROOT, "boot_daemon.py")
            os.makedirs(os.path.dirname(_BOOT_DAEMON_PLIST), exist_ok=True)
            log_dir = os.path.expanduser("~/Library/Logs/iZACH")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "boot_daemon.log")
            # No WorkingDirectory key, and logs write to ~/Library/Logs (not
            # this project's own logs/ folder) deliberately — this project
            # lives under ~/Desktop, one of macOS's TCC-protected folders.
            # A LaunchAgent whose WorkingDirectory or log-file writes point
            # inside Desktop gets silently killed by launchd shortly after
            # spawning (posix_spawn "Operation not permitted", confirmed via
            # `log show`), even though the exact same binary/script args
            # spawn and run fine when cwd/logs point elsewhere. boot_daemon.py
            # itself doesn't need cwd (resolves paths from __file__), so this
            # has no functional cost.
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{_BOOT_DAEMON_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{daemon_py}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{log_path}</string>
    <key>StandardErrorPath</key><string>{log_path}</string>
</dict>
</plist>
"""
            with open(_BOOT_DAEMON_PLIST, "w", encoding="utf-8") as f:
                f.write(plist)
            subprocess.run(["launchctl", "load", _BOOT_DAEMON_PLIST], capture_output=True, timeout=5)
            return True, "Boot daemon installed — this Mac can now be remotely started by its peer."
        except Exception as e:
            return False, f"Boot daemon install failed: {e}"
    if IS_WINDOWS:
        try:
            _write_windows_boot_daemon_script()
            cmd = [
                "schtasks", "/create", "/tn", _BOOT_DAEMON_TASK_NAME,
                "/tr", f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{_BOOT_DAEMON_SCRIPT_PATH}"',
                "/sc", "onlogon", "/f",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return True, "Boot daemon installed — this PC can now be remotely started by its peer."
            return False, f"schtasks failed: {(r.stderr or r.stdout).strip()}"
        except Exception as e:
            return False, f"Could not install boot daemon: {e}"
    return False, "Boot daemon is only supported on Windows and macOS."


def uninstall_boot_daemon() -> tuple[bool, str]:
    if IS_MAC:
        try:
            if os.path.exists(_BOOT_DAEMON_PLIST):
                subprocess.run(["launchctl", "unload", _BOOT_DAEMON_PLIST], capture_output=True, timeout=5)
                os.remove(_BOOT_DAEMON_PLIST)
            return True, "Boot daemon removed."
        except Exception as e:
            return False, f"Boot daemon removal failed: {e}"
    if IS_WINDOWS:
        try:
            ps_find = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*{os.path.basename(_BOOT_DAEMON_SCRIPT_PATH)}*' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_find],
                capture_output=True, text=True, timeout=10,
            )
            for pid in r.stdout.split():
                pid = pid.strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["schtasks", "/delete", "/tn", _BOOT_DAEMON_TASK_NAME, "/f"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return True, "Boot daemon uninstalled."
            if "cannot find" in (r.stderr or "").lower() or "cannot find" in (r.stdout or "").lower():
                return True, "Boot daemon was not installed."
            return False, f"schtasks failed: {(r.stderr or r.stdout).strip()}"
        except Exception as e:
            return False, f"Could not uninstall boot daemon: {e}"
    return False, "Boot daemon is only supported on Windows and macOS."
