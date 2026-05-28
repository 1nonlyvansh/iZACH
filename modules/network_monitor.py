"""
modules/network_monitor.py
LAN device discovery + active connection monitoring + unknown-device alerts.
Discovery: arp -a (no extra deps) with optional nmap upgrade.
Connections: psutil (already installed).
"""

import json
import os
import subprocess
import threading
import time
import re

import psutil

_KNOWN_FILE  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "known_devices.json")
_SCAN_SEC    = 60           # rescan interval
_speak_fn    = None
_running     = False
_lock        = threading.Lock()

_devices: list[dict]     = []   # latest scan result
_connections: list[dict] = []   # latest connection snapshot
_alerts: list[dict]      = []   # alert history (last 50)


# ── Known-device store ────────────────────────────────────────

def _load_known() -> dict:
    try:
        with open(_KNOWN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_known(known: dict):
    with open(_KNOWN_FILE, "w") as f:
        json.dump(known, f, indent=2)


def trust_device(mac: str, label: str = ""):
    known = _load_known()
    known[mac.lower()] = label or mac
    _save_known(known)


# ── ARP scanner (no deps) ─────────────────────────────────────

def _arp_scan() -> list[dict]:
    """Parse Windows ARP table — instant, no nmap needed."""
    devices = []
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        r = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                           timeout=10, creationflags=flags)
        # Lines look like:  192.168.1.5   aa-bb-cc-dd-ee-ff   dynamic
        for line in r.stdout.splitlines():
            m = re.match(
                r'\s*([\d.]+)\s+([0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}'
                r'[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2})\s+(\w+)',
                line, re.IGNORECASE
            )
            if m:
                ip, mac, atype = m.group(1), m.group(2).replace("-", ":").lower(), m.group(3)
                if atype.lower() != "static" and not ip.endswith(".255"):
                    devices.append({"ip": ip, "mac": mac, "type": atype})
    except Exception:
        pass
    return devices


def _nmap_scan() -> list[dict]:
    """Enhanced scan via python-nmap (optional upgrade)."""
    try:
        import nmap
        nm = nmap.PortScanner()
        # Detect local subnet
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        subnet = ".".join(local_ip.split(".")[:3]) + ".0/24"
        nm.scan(hosts=subnet, arguments="-sn --host-timeout 5s")
        devices = []
        for host in nm.all_hosts():
            mac = nm[host].get("addresses", {}).get("mac", "")
            vendor = nm[host].get("vendor", {}).get(mac, "") if mac else ""
            devices.append({"ip": host, "mac": mac.lower(), "vendor": vendor})
        return devices
    except Exception:
        return []


# ── Connection monitor ────────────────────────────────────────

def _snapshot_connections() -> list[dict]:
    conns = []
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status != "ESTABLISHED":
                continue
            try:
                proc_name = psutil.Process(c.pid).name() if c.pid else "unknown"
            except Exception:
                proc_name = "unknown"
            raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
            if not raddr:
                continue
            conns.append({
                "process": proc_name,
                "pid":     c.pid,
                "remote":  raddr,
                "local":   f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
            })
    except Exception:
        pass
    return conns


# ── Alert engine ──────────────────────────────────────────────

_first_scan_done = False


def _check_new_devices(current: list[dict]):
    global _first_scan_done
    known = _load_known()
    first_run = not os.path.exists(_KNOWN_FILE)

    new_found = []
    for dev in current:
        mac = dev["mac"]
        if mac and mac not in known:
            if not first_run and _first_scan_done:
                new_found.append(dev)
            # Always add to known to avoid future re-alerts
            known[mac] = ""

    _save_known(known)
    _first_scan_done = True

    for dev in new_found:
        msg = f"New device on your network — IP {dev['ip']}, MAC {dev['mac']}."
        _push_alert(msg)
        if _speak_fn:
            _speak_fn(msg)


def _push_alert(msg: str):
    global _alerts
    entry = {"msg": msg, "ts": time.strftime("%H:%M:%S"), "epoch": time.time()}
    with _lock:
        _alerts.append(entry)
        if len(_alerts) > 50:
            _alerts = _alerts[-50:]
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "network_alert", "msg": msg, "ts": entry["ts"]})
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────

def get_devices() -> list[dict]:
    with _lock:
        return list(_devices)


def get_connections() -> list[dict]:
    with _lock:
        return list(_connections)


def get_alerts() -> list[dict]:
    with _lock:
        return list(_alerts)


def scan_now() -> list[dict]:
    """Force immediate scan — updates both _devices and _connections."""
    found = _nmap_scan() or _arp_scan()
    conns = _snapshot_connections()
    with _lock:
        _devices.clear()
        _devices.extend(found)
        _connections.clear()
        _connections.extend(conns)
    return found


def summary() -> str:
    devs  = get_devices()
    conns = get_connections()
    known = _load_known()
    unknown = [d for d in devs if d["mac"] not in known or not known[d["mac"]]]
    lines = [f"{len(devs)} device(s) on network, {len(conns)} active connection(s)."]
    if unknown:
        lines.append(f"{len(unknown)} unrecognised device(s): "
                     + ", ".join(d["ip"] for d in unknown[:5]))
    return " ".join(lines)


# ── Background loop ───────────────────────────────────────────

def _watch_loop():
    while _running:
        try:
            found = _nmap_scan() or _arp_scan()
            with _lock:
                _devices.clear()
                _devices.extend(found)
            _check_new_devices(found)

            conns = _snapshot_connections()
            with _lock:
                _connections.clear()
                _connections.extend(conns)

            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "network_update",
                           "device_count": len(found),
                           "connection_count": len(conns)})
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(_SCAN_SEC)


def start(speak_fn=None):
    global _speak_fn, _running
    _speak_fn = speak_fn
    if _running:
        return
    _running = True
    # First scan non-blocking
    threading.Thread(target=scan_now, daemon=True).start()
    threading.Thread(target=_watch_loop, daemon=True, name="NetworkMonitor").start()
    print("[NETWORK] Monitor started.")


def stop():
    global _running
    _running = False
