"""
boot_daemon.py — Phase 1 of the cross-machine daemon architecture.

Lightweight, always-on, independent of iZACH's own process (main.py). Its
only job right now: listen for an authenticated "start iZACH" request from
the peer machine and launch it. Remote system control (volume/brightness/
power/etc, Phase 3) extends this same HTTP surface later — nothing about
that is built here yet.

Runs as its own OS-managed background service (LaunchAgent on macOS,
Scheduled Task + wrapper on Windows — see instance_coordinator.py's
install_boot_daemon()/uninstall_boot_daemon()), separate from iZACH's own
watchdog, since this must be reachable even when iZACH has never been
started this session.

Auth reuses the peer-token scheme instance_coordinator.py already
established (.env IZACH_PEER_TOKEN, X-iZACH-Peer-Token header) rather than
inventing a new mechanism for something this powerful.
"""
import os
import sys
import logging
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass

from flask import Flask, request, jsonify
from modules.platform_utils import IS_MAC, IS_WINDOWS

_PEER_TOKEN = os.environ.get("IZACH_PEER_TOKEN", "")
_DAEMON_PORT = int(os.environ.get("IZACH_DAEMON_PORT", "5052"))

# macOS-only: log outside the project's own logs/ folder. This project
# lives under ~/Desktop, a TCC-protected folder — a LaunchAgent whose log
# writes land inside Desktop gets silently killed by launchd shortly after
# spawning (posix_spawn "Operation not permitted", confirmed via `log show`
# on a real launchd-managed run). Windows has no equivalent restriction, so
# it keeps using the project's own logs/ folder as normal.
if IS_MAC:
    _LOG_DIR = os.path.expanduser("~/Library/Logs/iZACH")
else:
    _LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(_LOG_DIR, "boot_daemon.log"),
    level=logging.INFO,
    format="%(asctime)s [DAEMON] %(message)s",
)
logger = logging.getLogger("izach.boot_daemon")

app = Flask(__name__)


def _authorized(req) -> bool:
    token = req.headers.get("X-iZACH-Peer-Token", "")
    return bool(_PEER_TOKEN) and token == _PEER_TOKEN


def _is_izach_running() -> bool:
    try:
        import requests
        r = requests.get("http://127.0.0.1:5050/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@app.route("/daemon/ping", methods=["GET"])
def ping():
    # Deliberately unauthenticated — this only reveals "the daemon is up and
    # which platform it's on," nothing sensitive. Boot (and later, control)
    # routes below all require the peer token.
    return jsonify({
        "ok": True,
        "platform": "mac" if IS_MAC else ("windows" if IS_WINDOWS else "unknown"),
    })


@app.route("/daemon/boot", methods=["POST"])
def boot():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    if _is_izach_running():
        return jsonify({"ok": True, "already_running": True})

    try:
        launcher = os.path.join(_PROJECT_ROOT, "launch_izach.py")
        if IS_MAC:
            python_bin = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")
            subprocess.Popen([python_bin, launcher], cwd=_PROJECT_ROOT, start_new_session=True)
        elif IS_WINDOWS:
            python_bin = os.path.join(_PROJECT_ROOT, ".venv", "Scripts", "python.exe")
            subprocess.Popen(
                [python_bin, launcher], cwd=_PROJECT_ROOT,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            return jsonify({"ok": False, "error": "unsupported platform"}), 500
        logger.info("Boot triggered by authenticated peer request.")
        return jsonify({"ok": True, "already_running": False})
    except Exception as e:
        logger.error(f"Boot failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# Phase 3 — Mac<->Windows remote control (read/power/media only).
# Deliberately excludes file browse/upload/delete and arbitrary
# command execution/remote-input — that's node_receiver/receiver.py's
# territory for the AlliedNode satellite-PC case, and bundling it here
# would widen what a leaked IZACH_PEER_TOKEN could do. Everything below
# reuses system_control_mac.py/system_control_windows.py functions
# already built and tested elsewhere in this project — no new platform
# logic, just an authenticated HTTP surface over what exists. Works
# independently of whether main.py/iZACH itself is running, same as
# /daemon/boot above.
# ─────────────────────────────────────────────────────────────

@app.route("/control/vitals", methods=["GET"])
def control_vitals():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/" if IS_MAC else "C:\\")
        battery_percent = None
        battery_charging = None
        try:
            b = psutil.sensors_battery()
            if b is not None:
                battery_percent = round(b.percent, 1)
                battery_charging = bool(b.power_plugged)
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "platform": "mac" if IS_MAC else "windows",
            "cpu_percent": cpu,
            "ram_used_gb": round(ram.used / 1e9, 2),
            "ram_total_gb": round(ram.total / 1e9, 2),
            "ram_percent": ram.percent,
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_percent": disk.percent,
            "battery_percent": battery_percent,
            "battery_charging": battery_charging,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/control/processes", methods=["GET"])
def control_processes():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                if (info["cpu_percent"] or 0) > 0.1 or (info["memory_percent"] or 0) > 0.3:
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu_percent": round(info["cpu_percent"] or 0, 1),
                        "memory_percent": round(info["memory_percent"] or 0, 1),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        return jsonify({"ok": True, "processes": procs[:30]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/control/screenshot", methods=["GET"])
def control_screenshot():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        from modules.screenshot_engine import capture_sync
        filename = capture_sync()
        if not filename:
            hint = " (check Screen Recording permission for this Python process in System Settings)" if IS_MAC else ""
            return jsonify({"ok": False, "error": f"Capture failed{hint}"}), 500
        from flask import send_from_directory
        from modules.screenshot_engine import SCREENSHOT_DIR
        return send_from_directory(str(SCREENSHOT_DIR), filename, mimetype="image/jpeg")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/control/media", methods=["POST"])
def control_media():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    try:
        if IS_MAC:
            from modules import system_control_mac as _scm
            _ACTIONS = {
                "volume_up":   lambda: _scm.adjust_volume(6),
                "volume_down": lambda: _scm.adjust_volume(-6),
                "mute":        _scm.toggle_mute,
                "play_pause":  _scm.media_playpause,
                "next_track":  _scm.media_next,
                "prev_track":  _scm.media_previous,
            }
            if action not in _ACTIONS:
                return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400
            ok, msg = _ACTIONS[action]()
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)
        elif IS_WINDOWS:
            from pynput.keyboard import Key, Controller as _KC
            _KEY_MAP = {
                "volume_up":   Key.media_volume_up,
                "volume_down": Key.media_volume_down,
                "mute":        Key.media_volume_mute,
                "play_pause":  Key.media_play_pause,
                "next_track":  Key.media_next,
                "prev_track":  Key.media_previous,
            }
            if action not in _KEY_MAP:
                return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400
            kb = _KC()
            kb.press(_KEY_MAP[action])
            kb.release(_KEY_MAP[action])
            return jsonify({"ok": True, "message": action.replace("_", " ").title()})
        return jsonify({"ok": False, "error": "unsupported platform"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/control/power", methods=["POST"])
def control_power():
    if not _authorized(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    delay = int(data.get("delay_seconds") or 0)
    try:
        if action == "lock":
            if IS_MAC:
                from modules.platform_utils import run_applescript
                ok, out = run_applescript(
                    'tell application "System Events" to key code 12 using {control down, command down}'
                )
                if ok:
                    return jsonify({"ok": True, "message": "Locked"})
                return jsonify({"ok": False, "error": f"Lock failed (check Accessibility permission): {out}"}), 500
            elif IS_WINDOWS:
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return jsonify({"ok": True, "message": "Locked"})

        elif action == "sleep":
            if IS_MAC:
                r = subprocess.run(["pmset", "sleepnow"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return jsonify({"ok": True, "message": "Sleeping"})
                return jsonify({"ok": False, "error": r.stderr.strip() or "pmset failed"}), 500
            elif IS_WINDOWS:
                r = subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    capture_output=True, text=True, timeout=10,
                )
                return jsonify({"ok": True, "message": "Sleeping"})

        elif action == "shutdown":
            if IS_MAC:
                from modules import system_control_mac as _scm
            else:
                from modules import system_control_windows as _scm
            ok, msg = _scm.schedule_shutdown(delay)
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)

        elif action == "restart":
            if IS_MAC:
                from modules import system_control_mac as _scm
            else:
                from modules import system_control_windows as _scm
            ok, msg = _scm.schedule_restart(delay)
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)

        elif action == "cancel_shutdown":
            if IS_MAC:
                from modules import system_control_mac as _scm
            else:
                from modules import system_control_windows as _scm
            ok, msg = _scm.cancel_shutdown()
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)

        else:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        return jsonify({"ok": False, "error": "unsupported platform"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info(f"Boot daemon starting on port {_DAEMON_PORT}")
    app.run(host="0.0.0.0", port=_DAEMON_PORT)
