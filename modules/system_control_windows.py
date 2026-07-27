"""Windows implementations of system_control's platform-specific functions.
Relocated from the original monolithic modules/system_control.py — logic is
unchanged from before the macOS port, only moved. See modules/system_control.py
for the dispatcher and modules/system_control_mac.py for the macOS equivalents."""
import re
import time
import subprocess
import threading
import winreg
import warnings

from modules.system_control_common import _get_local_subnet

warnings.filterwarnings('ignore', category=UserWarning, module='pycaw')
from pycaw.pycaw import AudioUtilities
import screen_brightness_control as sbc

# `from modules.system_control_windows import *` (in the dispatcher, system_control.py)
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
    "_get_current_theme", "_get_wifi_state", "_get_paired_bt_names",
    "_init_volume", "_ramp_volume", "_normalize_drive_letter",
    "_APP_EXE_MAP", "adjust_brightness", "set_brightness",
]


def _init_volume():
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        return AudioUtilities.GetSpeakers().EndpointVolume
    except Exception as e:
        print("VOLUME INIT ERROR:", e)
        return None


# ── WiFi ──────────────────────────────────────────────────────

def _get_wifi_state():
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5
        )
        out = result.stdout.lower()
        if "state" in out:
            if "connected" in out:
                return True
            if "disconnected" in out:
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

    action = "enable" if enable else "disable"
    try:
        result = subprocess.run(
            ["netsh", "interface", "set", "interface", "Wi-Fi", action],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, f"WiFi {'on' if enable else 'off'}."
        err = (result.stdout.strip() or result.stderr.strip() or "unknown error")
        if "elevation" in err.lower() or "administrator" in err.lower():
            return False, "WiFi toggle requires administrator privileges."
        return False, f"Failed to toggle WiFi: {err}"
    except Exception as e:
        return False, f"WiFi error: {e}"


def toggle_wifi():
    state = _get_wifi_state()
    return set_wifi(not state) if state is not None else set_wifi(True)


# ── Brightness ────────────────────────────────────────────────

def adjust_brightness(delta: int):
    try:
        current = sbc.get_brightness()
        level = current[0] if isinstance(current, list) else current
        target = max(0, min(100, level + delta))
        sbc.set_brightness(target)
        return True, f"Brightness set to {target}."
    except Exception as e:
        return False, f"Brightness error: {e}"


def set_brightness(level: int):
    level = max(0, min(100, level))
    try:
        sbc.set_brightness(level)
        return True, f"Brightness set to {level}."
    except Exception as e:
        return False, f"Brightness error: {e}"


def get_wifi_signal():
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5
        )
        matches = re.findall(r"Signal\s*:\s*(\d+)%", result.stdout)
        if not matches:
            return False, "Not connected to WiFi."
        return True, f"WiFi signal {matches[0]}%."
    except Exception as e:
        return False, f"Could not read WiFi signal: {e}"


# ── Volume ────────────────────────────────────────────────────

def _ramp_volume(current_pct: int, target_pct: int):
    # Re-initialize COM in this thread — volume COM objects are STA and
    # cannot be called from a thread different from the one that created them.
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    volume_obj = _init_volume()
    if volume_obj is None:
        return
    step = 5 if target_pct > current_pct else -5
    current = current_pct
    while (step > 0 and current < target_pct) or (step < 0 and current > target_pct):
        current = min(target_pct, current + step) if step > 0 else max(target_pct, current + step)
        try:
            volume_obj.SetMasterVolumeLevelScalar(current / 100.0, None)
        except Exception:
            break
        time.sleep(0.05)


def set_volume(target: int):
    target = max(0, min(100, target))
    volume_obj = _init_volume()
    if volume_obj is None:
        return False, "Could not access volume control."
    try:
        current_pct = int(volume_obj.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        current_pct = target
    threading.Thread(target=_ramp_volume, args=(current_pct, target), daemon=True).start()
    return True, f"Volume set to {target}."


def adjust_volume(delta: int):
    volume_obj = _init_volume()
    if volume_obj is None:
        return False, "Could not access volume control."
    try:
        current_pct = int(volume_obj.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return False, "Could not read current volume."
    target = max(0, min(100, current_pct + delta))
    threading.Thread(target=_ramp_volume, args=(current_pct, target), daemon=True).start()
    return True, f"Volume set to {target}."


def mute():
    volume_obj = _init_volume()
    if volume_obj is None:
        return False, "Could not access volume control."
    try:
        volume_obj.SetMute(1, None)
        return True, "Muted."
    except Exception as e:
        return False, f"Mute failed: {e}"


def unmute():
    volume_obj = _init_volume()
    if volume_obj is None:
        return False, "Could not access volume control."
    try:
        volume_obj.SetMute(0, None)
        return True, "Unmuted."
    except Exception as e:
        return False, f"Unmute failed: {e}"


# ── Dark / Light Mode ─────────────────────────────────────────

_THEME_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _get_current_theme():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_PATH) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val == 1 else "dark"
    except Exception:
        return None


def set_theme(mode: str):
    if mode not in ("dark", "light"):
        return False, "Mode must be 'dark' or 'light'."
    current = _get_current_theme()
    if current == mode:
        return False, f"{mode.capitalize()} mode already on."
    val = 1 if mode == "light" else 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, val)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, val)
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0, 5000, None)
        return True, f"{mode.capitalize()} mode on."
    except Exception as e:
        return False, f"Theme change failed: {e}"


# ── Bluetooth ─────────────────────────────────────────────────

_bt_names_cache = None
_bt_names_cache_time = 0.0
_BT_NAMES_TTL = 60.0

_BT_SYSTEM_PATTERNS = (
    "service", "enumerator", "protocol", "profile", "transport",
    "generic", "microsoft", "intel", "bluetooth device",
    "personal area", "object push", "sim access", "phonebook",
    "device information", "avrcp",
)


def _get_paired_bt_names():
    """Return cached set of paired BT device names. Refreshes every 60s."""
    global _bt_names_cache, _bt_names_cache_time
    now = time.monotonic()
    if _bt_names_cache is not None and (now - _bt_names_cache_time) < _BT_NAMES_TTL:
        return _bt_names_cache
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Bluetooth | Select-Object FriendlyName | ConvertTo-Csv -NoTypeInformation"],
            capture_output=True, text=True, timeout=8
        )
        names = set()
        for line in result.stdout.strip().splitlines()[1:]:
            name = line.strip().strip('"')
            if name and not any(p in name.lower() for p in _BT_SYSTEM_PATTERNS):
                names.add(re.sub(r'[^a-z0-9]', '', name.lower()))
        _bt_names_cache = names
        _bt_names_cache_time = now
        return names
    except Exception:
        return _bt_names_cache or set()


def _get_connected_bluetooth_devices():
    """Active audio endpoints cross-referenced with paired BT devices."""
    try:
        bt_names = _get_paired_bt_names()
        devices = set()
        for d in AudioUtilities.GetAllDevices():
            if str(d.state) != "AudioDeviceState.Active":
                continue
            name = (d.FriendlyName or "").strip()
            if not name:
                continue
            m = re.search(r'\((.+)\)', name)
            clean = m.group(1).strip() if m else name
            clean_norm = re.sub(r'[^a-z0-9]', '', clean.lower())
            # Match if extracted name overlaps with any known BT device name
            if any(clean_norm in re.sub(r'[^a-z0-9]', '', bt) or
                   re.sub(r'[^a-z0-9]', '', bt) in clean_norm
                   for bt in bt_names):
                devices.add(clean)
        return devices
    except Exception:
        return set()


# ── System Status ─────────────────────────────────────────────

def get_battery_health():
    import os
    _REPORT_PATH = os.path.join(os.environ.get("TEMP", "."), "izach_battery_report.html")
    try:
        if not os.path.exists(_REPORT_PATH) or (time.time() - os.path.getmtime(_REPORT_PATH)) > 86400:
            subprocess.run(
                ["powercfg", "/batteryreport", "/output", _REPORT_PATH],
                capture_output=True, timeout=10
            )
        with open(_REPORT_PATH, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        design_m = re.search(r'DESIGN CAPACITY.*?(\d[\d,]+)\s*mWh', html, re.IGNORECASE | re.DOTALL)
        full_m = re.search(r'FULL CHARGE CAPACITY.*?(\d[\d,]+)\s*mWh', html, re.IGNORECASE | re.DOTALL)
        if not design_m or not full_m:
            return False, "Could not read battery capacity data."
        design = int(design_m.group(1).replace(",", ""))
        full = int(full_m.group(1).replace(",", ""))
        if design == 0:
            return False, "Invalid battery data."
        wear = round((1 - full / design) * 100, 1)
        return True, f"Battery health: {100 - wear:.1f}% capacity remaining. Wear level is {wear}%."
    except Exception as e:
        return False, f"Battery health check failed: {e}"


def get_cpu_temperature():
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi | "
             "Select-Object -ExpandProperty CurrentTemperature"],
            capture_output=True, text=True, timeout=5
        )
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip().isdigit()]
        if not lines:
            return False, "CPU temperature not available on this system."
        temps = []
        for raw in lines:
            try:
                c = (int(raw) / 10) - 273.15
                if 0 <= c <= 120:
                    temps.append(c)
            except Exception:
                continue
        if not temps:
            return False, "CPU temperature not available on this system."
        avg = sum(temps) / len(temps)
        return True, f"CPU temperature is {avg:.0f}°C."
    except Exception:
        return False, "CPU temperature not available on this system."


def get_firewall_status():
    _FW_BASE = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
    profiles = {"Domain": "DomainProfile", "Private": "StandardProfile", "Public": "PublicProfile"}
    try:
        any_on = False
        for label, subkey in profiles.items():
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{_FW_BASE}\{subkey}") as k:
                    val, _ = winreg.QueryValueEx(k, "EnableFirewall")
                    if val == 1:
                        any_on = True
            except Exception:
                continue
        return True, f"Firewall {'on' if any_on else 'off'}."
    except Exception as e:
        return False, f"Could not read firewall status: {e}"


def get_update_status():
    _KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY).Close()
        return True, "Updates pending, restart required."
    except FileNotFoundError:
        return True, "No restart-required updates."
    except Exception as e:
        return False, f"Could not check update status: {e}"


def get_network_devices():
    import socket
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        # Populate ARP cache: parallel ping sweep of subnet
        subnet = _get_local_subnet()
        if subnet:
            def _ping(i):
                subprocess.run(
                    ["ping", "-n", "1", "-w", "200", f"{subnet}.{i}"],
                    capture_output=True, timeout=1
                )
            with ThreadPoolExecutor(max_workers=50) as ex:
                list(ex.map(_ping, range(1, 255), timeout=3))
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=5
        )
        ips = []
        _SKIP_PREFIXES = ("224.", "225.", "239.", "255.", "169.254.")
        _GATEWAY_SUFFIXES = (".1", ".254")
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower().startswith(("interface", "internet")):
                continue
            m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+([\w-]{11,17})\s+(\w+)", line)
            if not m:
                continue
            ip, mac = m.group(1), m.group(2)
            if any(ip.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if ip.endswith(".255") or mac.lower() == "ff-ff-ff-ff-ff-ff":
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

def _normalize_drive_letter(identifier: str) -> str:
    letter = identifier.strip().rstrip("\\").rstrip(":").upper()
    if len(letter) == 1 and letter.isalpha():
        return letter + ":"
    return identifier.strip().upper()


def _get_drive_map():
    """Returns {drive_letter: volume_label}, e.g. {'C:': 'OS', 'D:': 'SANDISK 64G'}"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Volume | Where-Object {$_.DriveLetter} | Select-Object DriveLetter,FileSystemLabel | ConvertTo-Csv -NoTypeInformation"],
            capture_output=True, text=True, timeout=5
        )
        drives = {}
        for line in result.stdout.strip().splitlines()[1:]:
            line = line.strip().strip('"')
            parts = line.split('","')
            if not parts or not parts[0].strip():
                continue
            letter = parts[0].strip().upper() + ":"
            name = parts[1].strip() if len(parts) > 1 else ""
            drives[letter] = name
        return drives
    except Exception:
        return {}


def eject_drive(identifier: str):
    identifier = identifier.strip()
    drive = _normalize_drive_letter(identifier)

    # Name-based lookup: if identifier isn't a single drive letter
    if not (len(identifier.rstrip(":\\")) == 1 and identifier[0].isalpha()):
        drive_map = _get_drive_map()
        id_lower = identifier.lower()
        matched = None
        for letter, vol_name in drive_map.items():
            if vol_name and id_lower in vol_name.lower():
                matched = letter
                break
        if matched:
            drive = matched
        else:
            named = [f"{v} ({k})" for k, v in drive_map.items() if v]
            hint = f"Named drives: {', '.join(named)}" if named else "No named drives found."
            return False, f"No drive named '{identifier}' found. {hint}"

    try:
        import psutil
        parts = [p.device.rstrip("\\").upper() for p in psutil.disk_partitions(all=False)]
        if drive not in parts:
            return False, f"Drive {drive} not found. Connected: {', '.join(parts)}"
    except Exception as e:
        return False, f"Could not check drives: {e}"

    ps_cmd = (
        f"$shell = New-Object -ComObject Shell.Application; "
        f"$shell.Namespace(17).ParseName('{drive}').InvokeVerb('Eject')"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, f"Drive {drive} ejected safely."
        err = result.stdout.strip() or result.stderr.strip() or "unknown error"
        return False, f"Could not eject {drive}: {err}"
    except Exception as e:
        return False, f"Eject failed: {e}"


# ── Apps / Processes ──────────────────────────────────────────

_APP_EXE_MAP = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "vlc": "vlc.exe",
    "notepad": "notepad.exe",
    "word": "WINWORD.EXE", "microsoft word": "WINWORD.EXE",
    "excel": "EXCEL.EXE", "microsoft excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE", "microsoft powerpoint": "POWERPNT.EXE",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "opera": "opera.exe",
    "vscode": "Code.exe", "vs code": "Code.exe", "visual studio code": "Code.exe",
    "whatsapp": "WhatsApp.exe",
    "teams": "Teams.exe", "microsoft teams": "Teams.exe",
    "zoom": "Zoom.exe",
    "telegram": "Telegram.exe",
    "steam": "steam.exe",
    "obs": "obs64.exe",
    "paint": "mspaint.exe",
    "calculator": "CalculatorApp.exe",
    "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "winrar": "WinRAR.exe",
    "photoshop": "Photoshop.exe",
}


def kill_app(name: str):
    name_lower = name.lower().strip()
    exe = _APP_EXE_MAP.get(name_lower)

    if not exe:
        try:
            import psutil
            _protected = {"system", "svchost.exe", "lsass.exe", "csrss.exe", "wininit.exe"}
            matches = [
                p.name() for p in psutil.process_iter(["name"])
                if name_lower in p.name().lower()
                and p.name().lower() not in _protected
            ]
            if matches:
                exe = matches[0]
            else:
                return False, f"No app named '{name}' is running."
        except Exception as e:
            return False, f"Could not scan processes: {e}"

    try:
        result = subprocess.run(
            ["taskkill", "/IM", exe, "/F"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return True, f"{name.title()} closed."
        out = (result.stdout + result.stderr).strip().lower()
        if "not found" in out or "no tasks" in out:
            return False, f"{name.title()} is not running."
        return False, f"Couldn't close {name}: {(result.stdout or result.stderr).strip()}"
    except Exception as e:
        return False, f"Kill failed: {e}"


def schedule_shutdown(seconds: int):
    try:
        subprocess.run(["shutdown", "/s", "/t", str(seconds)], capture_output=True, timeout=5)
        minutes = seconds // 60
        label = f"in {minutes} minute{'s' if minutes != 1 else ''}" if minutes > 0 else f"in {seconds} seconds"
        return True, f"Shutting down {label}."
    except Exception as e:
        return False, f"Shutdown failed: {e}"


def schedule_restart(seconds: int):
    try:
        subprocess.run(["shutdown", "/r", "/t", str(seconds)], capture_output=True, timeout=5)
        minutes = seconds // 60
        label = f"in {minutes} minute{'s' if minutes != 1 else ''}" if minutes > 0 else f"in {seconds} seconds"
        return True, f"Restarting {label}."
    except Exception as e:
        return False, f"Restart failed: {e}"


def cancel_shutdown():
    try:
        subprocess.run(["shutdown", "/a"], capture_output=True, timeout=5)
        return True, "Scheduled shutdown cancelled."
    except Exception as e:
        return False, f"Cancel failed: {e}"


def set_process_priority(app_name: str, level: str = "high"):
    try:
        import psutil
        _PRIORITY_MAP = {
            "low":      psutil.BELOW_NORMAL_PRIORITY_CLASS,
            "normal":   psutil.NORMAL_PRIORITY_CLASS,
            "high":     psutil.HIGH_PRIORITY_CLASS,
            "realtime": psutil.REALTIME_PRIORITY_CLASS,
        }
        priority = _PRIORITY_MAP.get(level.lower(), psutil.HIGH_PRIORITY_CLASS)
        name_lower = app_name.lower()
        exe = _APP_EXE_MAP.get(name_lower, "").lower()
        found = []
        for proc in psutil.process_iter(["name", "pid"]):
            pname = proc.name().lower()
            if name_lower in pname or (exe and exe in pname):
                found.append(proc)
        if not found:
            return False, f"No process named '{app_name}' is running."
        for proc in found:
            try:
                proc.nice(priority)
            except Exception:
                pass
        return True, f"Set {app_name} to {level} priority."
    except Exception as e:
        return False, f"Priority change failed: {e}"
