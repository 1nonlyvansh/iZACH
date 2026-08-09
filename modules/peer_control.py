"""
modules/peer_control.py
Server-side proxy to the dual-instance peer's boot_daemon.py /control/*
routes (Phase 3 — vitals/screenshot/processes/media/power only,
deliberately no file/exec surface, same scope cut as boot_daemon.py
itself). Mirrors remote_node.py's role for AlliedNode 2, but talks to
the peer Mac/Windows machine instead — keeps IZACH_PEER_TOKEN
server-side, browser JS never sees it.
"""
import os
import base64
import requests

_PEER_TOKEN = os.environ.get("IZACH_PEER_TOKEN", "")
_DAEMON_PORT = int(os.environ.get("IZACH_DAEMON_PORT", "5052"))
_TIMEOUT = 6


def _url(peer_host: str, path: str) -> str:
    return f"http://{peer_host}:{_DAEMON_PORT}{path}"


def _headers() -> dict:
    return {"X-iZACH-Peer-Token": _PEER_TOKEN}


def daemon_reachable(peer_host: str) -> bool:
    """Pings the peer's boot_daemon.py (port 5052) directly, NOT its main
    iZACH backend (port 5050, via instance_coordinator.check_peer()). The
    daemon runs independently and stays up even when the peer's main iZACH
    isn't — which is exactly the case open_app/vitals/screenshot/etc below
    execute through, so that's the service whose reachability actually
    matters for them. check_peer() answers a different question (is the
    peer's main backend up, for role/handoff negotiation)."""
    try:
        r = requests.get(_url(peer_host, "/daemon/ping"), timeout=3)
        return r.status_code == 200 and bool(r.json().get("ok"))
    except Exception:
        return False


def get_vitals(peer_host: str) -> dict:
    try:
        r = requests.get(_url(peer_host, "/control/vitals"), headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_processes(peer_host: str) -> dict:
    try:
        r = requests.get(_url(peer_host, "/control/processes"), headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_screenshot_b64(peer_host: str) -> dict:
    try:
        r = requests.get(_url(peer_host, "/control/screenshot"), headers=_headers(), timeout=15)
        if r.status_code != 200:
            try:
                return r.json()
            except Exception:
                return {"ok": False, "error": f"HTTP {r.status_code}"}
        return {"ok": True, "screenshot": base64.b64encode(r.content).decode("ascii")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def media(peer_host: str, action: str) -> dict:
    try:
        r = requests.post(
            _url(peer_host, "/control/media"), headers=_headers(),
            json={"action": action}, timeout=_TIMEOUT,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_app(peer_host: str, app: str) -> dict:
    try:
        r = requests.post(
            _url(peer_host, "/control/open_app"), headers=_headers(),
            json={"app": app}, timeout=_TIMEOUT,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def power(peer_host: str, action: str, delay_seconds: int = 0) -> dict:
    try:
        r = requests.post(
            _url(peer_host, "/control/power"), headers=_headers(),
            json={"action": action, "delay_seconds": delay_seconds}, timeout=_TIMEOUT,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
