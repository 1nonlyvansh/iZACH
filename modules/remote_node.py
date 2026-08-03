"""
iZACH Remote Node Controller
Runs on AlliedNode (main PC).
Sends commands to registered remote nodes (e.g. AlliedNode 2).
"""

import base64
import os
import json as _json
import requests
from pathlib import Path

# ─── Node registry ────────────────────────────────────────────
# Was a hardcoded dict here — now loaded from api_keys.json's "allied_nodes"
# key (Settings UI's AlliedNode card writes there, same wholesale-accept
# pattern as dual_instance/peer devices), with the original hardcoded
# values kept as the fallback default so nothing breaks for anyone who
# hasn't touched the new Settings card yet. Token is deliberately NOT part
# of this config — same security posture as IZACH_PEER_TOKEN, it lives in
# .env (ALLIEDNODE2_TOKEN) and is never written by the Settings UI.
_API_KEYS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api_keys.json")

_DEFAULT_NODES: dict[str, dict] = {
    "alliednode 2": {
        "label": "AlliedNode 2",
        "host":  "192.168.0.137",
        "port":  9797,
        "mac":   "F8-89-D2-00-DD-C9",  # Wi-Fi MAC (WoWLAN)
    },
}

TIMEOUT_SHORT  = 5   # seconds — open/control commands
TIMEOUT_EXEC   = 15  # seconds — shell execute
TIMEOUT_XFER   = 60  # seconds — file transfer


# ─── Helpers ──────────────────────────────────────────────────

def _load_nodes_config() -> dict:
    try:
        with open(_API_KEYS_PATH, encoding="utf-8") as f:
            saved = (_json.load(f) or {}).get("allied_nodes")
        if saved:
            return saved
    except Exception:
        pass
    return _DEFAULT_NODES


def _node(name: str) -> dict | None:
    key = name.lower().strip()
    entry = _load_nodes_config().get(key)
    if not entry:
        return None
    node = dict(entry)
    env_key = key.replace(" ", "").upper() + "_TOKEN"  # "alliednode 2" -> ALLIEDNODE2_TOKEN
    node["token"] = os.environ.get(env_key, "")
    return node

def _url(node: dict, path: str) -> str:
    return f"http://{node['host']}:{node['port']}{path}"

def _headers(node: dict) -> dict:
    return {"X-iZACH-Token": node["token"]}

def _err(msg: str) -> dict:
    return {"error": msg}


# ─── Public API ───────────────────────────────────────────────

def ping(node_name: str) -> dict:
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.get(_url(node, "/ping"), timeout=3)
        return r.json()
    except Exception as e:
        return _err(str(e))


def get_vitals(node_name: str) -> dict:
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.get(_url(node, "/vitals"), headers=_headers(node), timeout=TIMEOUT_SHORT)
        return r.json()
    except Exception as e:
        return _err(str(e))


def open_app(node_name: str, app: str) -> dict:
    """Open an application by name or exe path on the remote node."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        # Use 'start' so Windows resolves app via shell association (e.g. 'chrome', 'notepad')
        launch_cmd = app if app.endswith(".exe") or "\\" in app else f'start "" {app}'
        r = requests.post(
            _url(node, "/open_app"),
            json={"app": launch_cmd},
            headers=_headers(node),
            timeout=TIMEOUT_SHORT,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def open_file(node_name: str, path: str) -> dict:
    """Open a file with its default application on the remote node."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.post(
            _url(node, "/open_file"),
            json={"path": path},
            headers=_headers(node),
            timeout=TIMEOUT_SHORT,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def execute(node_name: str, command: str) -> dict:
    """Run a shell command on the remote node and return stdout/stderr."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.post(
            _url(node, "/execute"),
            json={"command": command},
            headers=_headers(node),
            timeout=TIMEOUT_EXEC,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def send_file(node_name: str, local_path: str, remote_path: str) -> dict:
    """Transfer a file from AlliedNode to the remote node."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        content = Path(local_path).read_bytes()
        r = requests.post(
            _url(node, "/upload"),
            json={"path": remote_path, "content": base64.b64encode(content).decode()},
            headers=_headers(node),
            timeout=TIMEOUT_XFER,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def fetch_file(node_name: str, remote_path: str, local_path: str) -> dict:
    """Download a file from the remote node to AlliedNode."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.get(
            _url(node, f"/download/{remote_path}"),
            headers=_headers(node),
            timeout=TIMEOUT_XFER,
        )
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return {"status": "downloaded", "path": local_path, "size": len(r.content)}
    except Exception as e:
        return _err(str(e))


def system_control(node_name: str, action: str, **kwargs) -> dict:
    """
    Control remote node power/process state.
    action: 'shutdown' | 'restart' | 'sleep' | 'lock' | 'kill_process'
    kwargs: process=<name> for kill_process
    """
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.post(
            _url(node, "/system_control"),
            json={"action": action, **kwargs},
            headers=_headers(node),
            timeout=TIMEOUT_SHORT,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def get_processes(node_name: str, top: int = 20) -> dict:
    """Return top processes sorted by memory on the remote node."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.get(
            _url(node, f"/processes?top={top}"),
            headers=_headers(node),
            timeout=TIMEOUT_SHORT,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def take_screenshot(node_name: str) -> dict:
    """Capture the remote node's screen. Returns base64 JPEG."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.get(
            _url(node, "/screenshot"),
            headers=_headers(node),
            timeout=TIMEOUT_SHORT,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def upload_bytes(node_name: str, dest_path: str, file_bytes: bytes) -> dict:
    """Upload raw bytes to dest_path on the remote node."""
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    try:
        r = requests.post(
            _url(node, "/upload"),
            json={"path": dest_path, "content": base64.b64encode(file_bytes).decode()},
            headers=_headers(node),
            timeout=TIMEOUT_XFER,
        )
        return r.json()
    except Exception as e:
        return _err(str(e))


def wake_on_lan(node_name: str) -> dict:
    """Send WOL magic packet. Works even when the node is powered off."""
    import socket
    node = _node(node_name)
    if not node:
        return _err(f"Unknown node: {node_name}")
    mac = node.get("mac", "00-00-00-00-00-00")
    mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(mac_clean) != 12 or mac_clean == "000000000000":
        return _err(
            "MAC address not set. Set it in Settings -> Device Connection -> AlliedNode 2."
        )
    try:
        mac_bytes = bytes.fromhex(mac_clean)
        magic = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, ("<broadcast>", 9))
        return {"status": "magic_packet_sent", "node": node_name, "mac": mac}
    except Exception as e:
        return _err(str(e))


def format_vitals(v: dict) -> str:
    """Format vitals dict into a human-readable string for iZACH response."""
    if "error" in v:
        return f"Could not reach {v.get('node', 'node')}: {v['error']}"
    lines = [
        f"{v['node']} system status:",
        f"  CPU   {v['cpu_percent']}%",
        f"  RAM   {v['ram_used_gb']} / {v['ram_total_gb']} GB  ({v['ram_percent']}%)",
        f"  Disk  {v['disk_used_gb']} / {v['disk_total_gb']} GB  ({v['disk_percent']}%)",
    ]
    if v.get("temps_c"):
        for sensor, temp in v["temps_c"].items():
            lines.append(f"  Temp  {temp} °C  ({sensor})")
    return "\n".join(lines)
