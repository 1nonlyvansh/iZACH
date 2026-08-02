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

os.makedirs(os.path.join(_PROJECT_ROOT, "logs"), exist_ok=True)
logging.basicConfig(
    filename=os.path.join(_PROJECT_ROOT, "logs", "boot_daemon.log"),
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


if __name__ == "__main__":
    logger.info(f"Boot daemon starting on port {_DAEMON_PORT}")
    app.run(host="0.0.0.0", port=_DAEMON_PORT)
