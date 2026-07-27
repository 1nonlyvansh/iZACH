"""macOS implementations of system_control's platform-specific functions.
Counterpart to modules/system_control_windows.py — see modules/system_control.py
for the dispatcher that picks one or the other at import time.

Known feature gaps vs Windows (no simple public macOS API, return an explicit
"unavailable" message instead of guessing): CPU temperature, pending-update
(restart-required) status. Bluetooth/network-device scans are best-effort,
parsing `system_profiler` text output rather than a structured API.
"""
import re
import subprocess
import threading
import time

from modules.platform_utils import run_applescript
from modules.system_control_common import _get_local_subnet

# `from modules.system_control_mac import *` (in the dispatcher, system_control.py)
# skips underscore-prefixed names unless explicitly listed here — system_control.py's
# own _drive_poll_loop/_bluetooth_poll_loop call _get_drive_map/_get_connected_bluetooth_devices,
# so those two must be re-exported even though they're "private" by naming convention.
__all__ = [
    "set_volume", "adjust_volume", "mute", "unmute",
    "set_wifi", "toggle_wifi", "get_wifi_signal",
    "set_theme", "get_battery_health", "get_cpu_temperature",
    "get_firewall_status", "get_update_status", "get_network_devices",
    "eject_drive", "kill_app", "schedule_shutdown", "schedule_restart",
    "cancel_shutdown", "set_process_priority",
    "_get_drive_map", "_get_connected_bluetooth_devices",
    "_get_current_theme", "_get_wifi_state", "_get_wifi_interface",
    "_get_current_volume_pct", "_APP_NAME_MAP", "adjust_brightness", "set_brightness",
]

_BRIGHTNESS_UNAVAILABLE_MSG = (
    "Brightness control isn't available on this Mac from a background process — "
    "Apple restricts direct display-brightness access on some Macs/macOS versions. "
    "Use the keyboard brightness keys or System Settings > Displays instead."
)


# ── Volume ────────────────────────────────────────────────────

def _get_current_volume_pct():
    ok, out = run_applescript("output volume of (get volume settings)")
    if not ok:
        return None
    try:
        return int(out.strip())
    except Exception:
        return None


def set_volume(target: int):
    target = max(0, min(100, target))
    ok, out = run_applescript(f"set volume output volume {target}")
    if ok:
        return True, f"Volume set to {target}."
    return False, f"Volume error: {out}"


def adjust_volume(delta: int):
    current = _get_current_volume_pct()
    if current is None:
        return False, "Could not read current volume."
    return set_volume(current + delta)


def mute():
    ok, out = run_applescript("set volume with output muted")
    return (True, "Muted.") if ok else (False, f"Mute failed: {out}")


def unmute():
    ok, out = run_applescript("set volume without output muted")
    return (True, "Unmuted.") if ok else (False, f"Unmute failed: {out}")


def is_muted() -> bool | None:
    ok, out = run_applescript("output muted of (get volume settings)")
    if not ok:
        return None
    return out.strip().lower() == "true"


def toggle_mute():
    muted = is_muted()
    if muted is None:
        return False, "Could not read mute state."
    return unmute() if muted else mute()


def media_playpause():
    """No universal system-wide media key on macOS without Accessibility-
    gated key-code injection — targets Spotify directly instead, matching
    iZACH's existing Spotify integration. Deliberately Spotify-only, not
    also falling back to Apple Music: Music.app is known to hang on its
    first AppleScript call for several seconds (sometimes past a 5s
    timeout) when it isn't already the active player, which made this
    action worse than just reporting "nothing to control" up front."""
    return _media_command("playpause")


def media_next():
    return _media_command("next track")


def media_previous():
    return _media_command("previous track")


def _media_command(verb: str):
    running_ok, running_out = run_applescript('application "Spotify" is running')
    if not (running_ok and running_out.strip().lower() == "true"):
        return False, "Spotify isn't running."
    ok, out = run_applescript(f'tell application "Spotify" to {verb}')
    return (True, f"Spotify: {verb}") if ok else (False, f"Spotify error: {out}")


# ── WiFi ──────────────────────────────────────────────────────

_wifi_iface_cache = None


def _get_wifi_interface():
    """Find the Device name (e.g. 'en0') of the Wi-Fi hardware port."""
    global _wifi_iface_cache
    if _wifi_iface_cache:
        return _wifi_iface_cache
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i + 1, min(i + 3, len(lines))):
                    if lines[j].startswith("Device:"):
                        _wifi_iface_cache = lines[j].split(":", 1)[1].strip()
                        return _wifi_iface_cache
    except Exception:
        pass
    return "en0"


def _get_wifi_state():
    iface = _get_wifi_interface()
    try:
        result = subprocess.run(
            ["networksetup", "-getairportpower", iface],
            capture_output=True, text=True, timeout=5
        )
        out = result.stdout.strip().lower()
        if "on" in out:
            return True
        if "off" in out:
            return False
        return None
    except Exception:
        return None


def set_wifi(enable: bool):
    state = _get_wifi_state()
    if state is not None:
        if enable and state:
            return False, "WiFi already on."
        if not enable and not state:
            return False, "WiFi already off."

    iface = _get_wifi_interface()
    action = "on" if enable else "off"
    try:
        result = subprocess.run(
            ["networksetup", "-setairportpower", iface, action],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, f"WiFi {'on' if enable else 'off'}."
        err = (result.stdout.strip() or result.stderr.strip() or "unknown error")
        return False, f"Failed to toggle WiFi: {err}"
    except Exception as e:
        return False, f"WiFi error: {e}"


def toggle_wifi():
    state = _get_wifi_state()
    return set_wifi(not state) if state is not None else set_wifi(True)


# ── Brightness ────────────────────────────────────────────────
# Uses the `brightness` CLI (brew install brightness), which itself uses a
# deprecated IOKit display API — macOS increasingly blocks this for
# unsigned/unentitled processes on some machines and macOS versions, in
# which case both functions fail with an honest message rather than a crash.

def _get_brightness_cli_pct():
    try:
        result = subprocess.run(["brightness", "-l"], capture_output=True, text=True, timeout=5)
        m = re.search(r"brightness\s+([\d.]+)", result.stdout)
        if m:
            return float(m.group(1)) * 100
        return None
    except Exception:
        return None


def set_brightness(level: int):
    level = max(0, min(100, level))
    try:
        result = subprocess.run(
            ["brightness", str(level / 100.0)],
            capture_output=True, text=True, timeout=5
        )
        # The `brightness` CLI's exit code is unreliable — it returns 0 even when
        # the underlying IOKit call fails (observed: "failed to set brightness of
        # display... error -536870201" printed to stderr, exit code still 0).
        # Some macOS versions/Macs block this IOKit path for unentitled processes.
        combined = f"{result.stdout}{result.stderr}".lower()
        if result.returncode == 0 and "failed" not in combined:
            return True, f"Brightness set to {level}."
        return False, _BRIGHTNESS_UNAVAILABLE_MSG
    except FileNotFoundError:
        return False, "Brightness control needs the `brightness` CLI — install with `brew install brightness`."
    except Exception as e:
        return False, f"Brightness error: {e}"


def adjust_brightness(delta: int):
    current = _get_brightness_cli_pct()
    if current is None:
        return False, _BRIGHTNESS_UNAVAILABLE_MSG
    return set_brightness(round(max(0, min(100, current + delta))))


def get_wifi_signal():
    try:
        result = subprocess.run(
            ["system_profiler", "SPAirPortDataType"],
            capture_output=True, text=True, timeout=8
        )
        m = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)\s*dBm", result.stdout)
        if not m:
            return False, "Not connected to WiFi."
        signal_dbm = int(m.group(1))
        # Rough dBm→percent mapping (same convention many WiFi status apps use)
        quality = max(0, min(100, 2 * (signal_dbm + 100)))
        return True, f"WiFi signal {quality}% ({signal_dbm} dBm)."
    except Exception as e:
        return False, f"Could not read WiFi signal: {e}"


# ── Dark / Light Mode ─────────────────────────────────────────

def _get_current_theme():
    ok, out = run_applescript(
        'tell application "System Events" to tell appearance preferences to get dark mode'
    )
    if not ok:
        return None
    return "dark" if out.strip().lower() == "true" else "light"


def set_theme(mode: str):
    if mode not in ("dark", "light"):
        return False, "Mode must be 'dark' or 'light'."
    current = _get_current_theme()
    if current == mode:
        return False, f"{mode.capitalize()} mode already on."
    val = "true" if mode == "dark" else "false"
    ok, out = run_applescript(
        f'tell application "System Events" to tell appearance preferences to set dark mode to {val}'
    )
    if ok:
        return True, f"{mode.capitalize()} mode on."
    return False, f"Theme change failed: {out}"


# ── Bluetooth ─────────────────────────────────────────────────

_BT_FIELD_LABELS = {
    "address", "battery level", "connected", "favorite", "firmware version",
    "manufacturer", "minor type", "modalias", "product id", "rssi",
    "services", "vendor id", "not connected", "devices (paired, configured, etc.)",
}


def _get_connected_bluetooth_devices():
    """Best-effort parse of `system_profiler SPBluetoothDataType` text output —
    macOS has no simple structured API for this like Windows' Get-PnpDevice."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPBluetoothDataType"],
            capture_output=True, text=True, timeout=8
        )
        devices = set()
        current_name = None
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith(":"):
                label = line[:-1].strip().lower()
                if label not in _BT_FIELD_LABELS:
                    current_name = line[:-1].strip()
                    continue
            if line.lower().startswith("connected:") and "yes" in line.lower() and current_name:
                devices.add(current_name)
        return devices
    except Exception:
        return set()


# ── System Status ─────────────────────────────────────────────

def get_battery_health():
    try:
        result = subprocess.run(
            ["system_profiler", "SPPowerDataType"],
            capture_output=True, text=True, timeout=10
        )
        text = result.stdout
        condition_m = re.search(r"Condition:\s*(.+)", text)
        cycle_m = re.search(r"Cycle Count:\s*(\d+)", text)
        max_cap_m = re.search(r"Maximum Capacity:\s*(\d+)%", text)
        parts = []
        if max_cap_m:
            parts.append(f"{max_cap_m.group(1)}% maximum capacity")
        if condition_m:
            parts.append(f"condition: {condition_m.group(1).strip()}")
        if cycle_m:
            parts.append(f"{cycle_m.group(1)} charge cycles")
        if not parts:
            return False, "Could not read battery capacity data."
        return True, "Battery health: " + ", ".join(parts) + "."
    except Exception as e:
        return False, f"Battery health check failed: {e}"


def get_cpu_temperature():
    return False, "CPU temperature isn't available on macOS without extra hardware-sensor tooling."


def get_firewall_status():
    try:
        result = subprocess.run(
            ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"],
            capture_output=True, text=True, timeout=5
        )
        out = (result.stdout or "").lower()
        on = "enabled" in out
        return True, f"Firewall {'on' if on else 'off'}."
    except Exception as e:
        return False, f"Could not read firewall status: {e}"


def get_update_status():
    return False, "Pending macOS update status isn't wired up yet — check System Settings > General > Software Update."


def get_network_devices():
    import socket
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        subnet = _get_local_subnet()
        if subnet:
            def _ping(i):
                subprocess.run(
                    ["ping", "-c", "1", "-t", "1", f"{subnet}.{i}"],
                    capture_output=True, timeout=2
                )
            with ThreadPoolExecutor(max_workers=50) as ex:
                list(ex.map(_ping, range(1, 255), timeout=5))
    except Exception:
        pass

    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        ips = []
        _SKIP_PREFIXES = ("224.", "225.", "239.", "255.", "169.254.")
        _GATEWAY_SUFFIXES = (".1", ".254")
        # BSD/macOS arp -a format: "hostname (192.168.0.5) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]"
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r".*\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-f:]{11,17})", line, re.IGNORECASE)
            if not m:
                continue
            ip, mac = m.group(1), m.group(2)
            if any(ip.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if mac.lower() in ("ff:ff:ff:ff:ff:ff", "(incomplete)"):
                continue
            if any(ip.endswith(s) for s in _GATEWAY_SUFFIXES):
                continue
            ips.append(ip)

        if not ips:
            return False, "No devices found on network."

        def _resolve(ip):
            try:
                return ip, socket.gethostbyaddr(ip)[0]
            except Exception:
                return ip, None

        names_map = {}
        ex = ThreadPoolExecutor(max_workers=len(ips))
        futures = {ex.submit(_resolve, ip): ip for ip in ips}
        try:
            for future in as_completed(futures, timeout=2.0):
                try:
                    ip, hostname = future.result()
                    names_map[ip] = hostname if hostname else "unknown device"
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            ex.shutdown(wait=False)

        names = [names_map.get(ip, "unknown device") for ip in ips]
        count = len(names)
        return True, f"{count} device{'s' if count != 1 else ''} on network: {', '.join(names)}."
    except Exception as e:
        return False, f"Could not scan network: {e}"


# ── External Drives ───────────────────────────────────────────

def _get_drive_map():
    """Returns {mount_path: volume_label} for macOS, e.g. {'/Volumes/SANDISK': 'SANDISK'}"""
    try:
        import psutil
        drives = {}
        for p in psutil.disk_partitions(all=False):
            if p.mountpoint.startswith("/Volumes/"):
                drives[p.mountpoint] = p.mountpoint.rsplit("/", 1)[-1]
        return drives
    except Exception:
        return {}


def eject_drive(identifier: str):
    identifier = identifier.strip()
    drive_map = _get_drive_map()
    id_lower = identifier.lower()

    candidate = None
    for mount, label in drive_map.items():
        if id_lower == label.lower() or id_lower == mount.lower():
            candidate = mount
            break
    if not candidate:
        for mount, label in drive_map.items():
            if label and id_lower in label.lower():
                candidate = mount
                break
    if not candidate:
        named = [f"{v} ({k})" for k, v in drive_map.items() if v]
        hint = f"Named drives: {', '.join(named)}" if named else "No named drives found."
        return False, f"No drive named '{identifier}' found. {hint}"

    try:
        result = subprocess.run(
            ["diskutil", "eject", candidate],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, f"Drive {drive_map.get(candidate, candidate)} ejected safely."
        err = result.stdout.strip() or result.stderr.strip() or "unknown error"
        return False, f"Could not eject {candidate}: {err}"
    except Exception as e:
        return False, f"Eject failed: {e}"


# ── Apps / Processes ──────────────────────────────────────────

_APP_NAME_MAP = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "spotify": "Spotify",
    "discord": "Discord",
    "vlc": "VLC",
    "notepad": "TextEdit",
    "word": "Microsoft Word", "microsoft word": "Microsoft Word",
    "excel": "Microsoft Excel", "microsoft excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint", "microsoft powerpoint": "Microsoft PowerPoint",
    "edge": "Microsoft Edge", "microsoft edge": "Microsoft Edge",
    "firefox": "firefox",
    "brave": "Brave Browser",
    "opera": "Opera",
    "vscode": "Code", "vs code": "Code", "visual studio code": "Code",
    "whatsapp": "WhatsApp",
    "teams": "Microsoft Teams", "microsoft teams": "Microsoft Teams",
    "zoom": "zoom.us",
    "telegram": "Telegram",
    "steam": "Steam",
    "obs": "OBS",
    "calculator": "Calculator",
    "explorer": "Finder", "file explorer": "Finder",
    "photoshop": "Photoshop",
    "preview": "Preview",
    "safari": "Safari",
    "mail": "Mail",
    "terminal": "Terminal",
    "slack": "Slack",
    "messages": "Messages",
    "music": "Music",
}

_KILL_PROTECTED = {"kernel_task", "launchd", "windowserver", "loginwindow"}


def kill_app(name: str):
    name_lower = name.lower().strip()
    target_lower = _APP_NAME_MAP.get(name_lower, name).lower()
    try:
        import psutil
        matches = [
            p for p in psutil.process_iter(["name"])
            if target_lower in (p.info["name"] or "").lower()
            and (p.info["name"] or "").lower() not in _KILL_PROTECTED
        ]
        if not matches:
            return False, f"{name.title()} is not running."
        for p in matches:
            try:
                p.terminate()
            except Exception:
                pass
        _, alive = psutil.wait_procs(matches, timeout=3)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        return True, f"{name.title()} closed."
    except Exception as e:
        return False, f"Kill failed: {e}"


def set_process_priority(app_name: str, level: str = "high"):
    try:
        import psutil
        # POSIX nice range is -20 (highest priority) .. 19 (lowest); raising
        # priority (negative nice) generally requires elevated privileges.
        _PRIORITY_MAP = {"low": 10, "normal": 0, "high": -10, "realtime": -20}
        nice_val = _PRIORITY_MAP.get(level.lower(), -10)
        name_lower = app_name.lower()
        target_lower = _APP_NAME_MAP.get(name_lower, app_name).lower()
        found = [
            p for p in psutil.process_iter(["name"])
            if name_lower in (p.info["name"] or "").lower()
            or target_lower in (p.info["name"] or "").lower()
        ]
        if not found:
            return False, f"No process named '{app_name}' is running."
        changed = 0
        for proc in found:
            try:
                proc.nice(nice_val)
                changed += 1
            except Exception:
                pass
        if not changed:
            return False, f"Could not change priority for {app_name} (may need admin privileges)."
        return True, f"Set {app_name} to {level} priority."
    except Exception as e:
        return False, f"Priority change failed: {e}"


# ── Shutdown / Restart ────────────────────────────────────────
# Uses System Events (no sudo needed for the logged-in user) with an
# in-process delay timer instead of shelling out to `shutdown`, which needs
# root and can't easily be scripted with a cancellable delay on macOS.

_shutdown_cancel_event = threading.Event()


def _delayed_power_action(verb: str, seconds: int):
    _shutdown_cancel_event.clear()

    def _fire():
        cancelled = _shutdown_cancel_event.wait(max(0, seconds))
        if not cancelled:
            run_applescript(f'tell application "System Events" to {verb}')

    threading.Thread(target=_fire, daemon=True).start()


def _format_delay_label(seconds: int) -> str:
    minutes = seconds // 60
    if minutes > 0:
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    return f"in {seconds} seconds" if seconds > 0 else "shortly"


def schedule_shutdown(seconds: int):
    _delayed_power_action("shut down", seconds)
    return True, f"Shutting down {_format_delay_label(seconds)}."


def schedule_restart(seconds: int):
    _delayed_power_action("restart", seconds)
    return True, f"Restarting {_format_delay_label(seconds)}."


def cancel_shutdown():
    _shutdown_cancel_event.set()
    return True, "Scheduled shutdown cancelled."
