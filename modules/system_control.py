"""System control dispatcher — routes to Windows or macOS implementations.

Platform-specific logic lives in system_control_windows.py / system_control_mac.py
(see those files for volume, brightness backend, WiFi, theme, battery, firewall,
network scan, drives, kill_app, process priority, shutdown/restart). Functions
below are genuinely platform-agnostic (pure psutil/screen_brightness_control/
stdlib) or orchestrate a platform-specific helper that got imported into this
module's namespace by the wildcard import below — see modules/system_control_mac.py
and modules/system_control_windows.py docstrings for why the split is structured
this way (callers all do `import modules.system_control as system_control` and
access functions as attributes, so this dispatcher's re-exported names are a
transparent drop-in — no caller changes needed, and test_agents.py's
unittest.mock.patch("modules.system_control.<fn>", ...) calls keep working).
"""
import datetime
import threading
import time

from modules.platform_utils import IS_WINDOWS, IS_MAC

if IS_WINDOWS:
    from modules.system_control_windows import *  # noqa: F401,F403
elif IS_MAC:
    from modules.system_control_mac import *  # noqa: F401,F403
else:
    from modules.system_control_unsupported import *  # noqa: F401,F403

_KILL_SKIP_WORDS = {"tab", "this", "window", "that", "the", "it", "file"}

# NOTE: brightness control is NOT platform-agnostic despite screen_brightness_control's
# name — that library has zero macOS backend as of the pinned 0.27.1 (confirmed by
# reading its source: `_OS_MODULE` is only set for Windows/Linux). adjust_brightness/
# set_brightness are implemented per-platform in system_control_windows.py (sbc) and
# system_control_mac.py (the `brightness` CLI, which itself may be blocked by macOS on
# some machines — see that file for the honest-failure fallback).


# ── Timer ─────────────────────────────────────────────────────

def set_timer(seconds: int, notify):
    if seconds <= 0:
        return False, "Timer duration must be greater than 0."
    minutes = seconds // 60
    label = (
        f"{minutes} minute{'s' if minutes != 1 else ''}"
        if minutes > 0
        else f"{seconds} second{'s' if seconds != 1 else ''}"
    )

    def _fire():
        time.sleep(seconds)
        notify(f"Timer done. {label} elapsed.")

    threading.Thread(target=_fire, daemon=True).start()
    return True, f"Timer set for {label}."


# ── Alarm ─────────────────────────────────────────────────────

def set_alarm(hour: int, minute: int, notify):
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return False, "Invalid time. Use 0-23 for hour and 0-59 for minute."
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    seconds_until = (target - now).total_seconds()
    label = target.strftime("%I:%M %p").lstrip("0")

    def _fire():
        time.sleep(seconds_until)
        notify(f"Alarm! It's {label}.")

    threading.Thread(target=_fire, daemon=True).start()
    return True, f"Alarm set for {label}."


# ── Battery / RAM (psutil is cross-platform) ────────────────────────────

def get_battery():
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return False, "No battery detected."
        pct = int(b.percent)
        status = "charging" if b.power_plugged else "on battery"
        return True, f"Battery at {pct}%, {status}."
    except Exception as e:
        return False, f"Battery check failed: {e}"


def get_ram_usage():
    try:
        import psutil
        pct = psutil.virtual_memory().percent
        if pct < 70:
            label = "good"
        elif pct < 90:
            label = "warning"
        else:
            label = "critical"
        return True, f"RAM usage is {pct:.0f}% — {label}."
    except Exception as e:
        return False, f"RAM check failed: {e}"


# ── External Drives (psutil watcher is cross-platform; label lookup is not) ──

def _get_connected_drives():
    try:
        import psutil
        return {p.device.rstrip("\\").upper() for p in psutil.disk_partitions(all=False)}
    except Exception:
        return set()


def list_drives():
    try:
        import psutil
        parts = psutil.disk_partitions(all=False)
        if not parts:
            return False, "No drives found."
        lines = []
        for p in parts:
            try:
                usage = psutil.disk_usage(p.mountpoint)
                total_gb = usage.total / (1024 ** 3)
                lines.append(f"{p.device} — {p.mountpoint} — {total_gb:.1f} GB total")
            except Exception:
                lines.append(f"{p.device} — {p.mountpoint}")
        return True, "Connected drives: " + ", ".join(lines)
    except Exception as e:
        return False, f"Could not list drives: {e}"


def _drive_poll_loop(notify, previous):
    while True:
        time.sleep(3)
        try:
            current = _get_connected_drives()
        except Exception:
            continue
        new = current - previous
        for drive in new:
            drive_map = _get_drive_map()
            label = drive_map.get(drive.rstrip("\\").upper(), "").strip()
            name = f"{label} ({drive})" if label else drive
            notify(f"{name} connected.")
        previous = current


_drive_watcher_started = False


def start_drive_watcher(notify):
    global _drive_watcher_started
    if _drive_watcher_started:
        return
    _drive_watcher_started = True
    previous = _get_connected_drives()
    threading.Thread(target=_drive_poll_loop, args=(notify, previous), daemon=True).start()


# ── Bluetooth Watcher (orchestration is common; device list is per-platform) ─

def _bluetooth_poll_loop(notify, previous):
    while True:
        time.sleep(1.5)
        try:
            current = _get_connected_bluetooth_devices()
        except Exception:
            continue
        for device in current - previous:
            notify(f"{device.strip() or 'A Bluetooth device'} connected.")
        for device in previous - current:
            notify(f"{device.strip() or 'A Bluetooth device'} disconnected.")
        previous = current


_watcher_started = False


def start_bluetooth_watcher(notify):
    global _watcher_started
    if _watcher_started:
        return
    _watcher_started = True
    previous = _get_connected_bluetooth_devices()
    threading.Thread(target=_bluetooth_poll_loop, args=(notify, previous), daemon=True).start()
