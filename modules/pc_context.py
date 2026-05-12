"""
PC introspection — RAM, CPU, disk, battery, internet, apps, file search.
Uses psutil (already installed) + stdlib only. No full disk scans.
"""
import os
import socket
import time
import psutil
from pathlib import Path

_HOME = Path.home()
_SEARCH_ROOTS: list[Path] = []

for _rel in ["Desktop", "Downloads", "Documents", "Pictures"]:
    _p = _HOME / _rel
    if _p.is_dir():
        _SEARCH_ROOTS.append(_p)
for _od in ["OneDrive", "OneDrive - Personal"]:
    _od_path = _HOME / _od
    if _od_path.is_dir():
        for _rel in ["Desktop", "Documents", "Pictures"]:
            _p = _od_path / _rel
            if _p.is_dir():
                _SEARCH_ROOTS.append(_p)


def ram() -> dict:
    m = psutil.virtual_memory()
    return {
        "total_gb": round(m.total / 1e9, 1),
        "used_gb": round(m.used / 1e9, 1),
        "available_gb": round(m.available / 1e9, 1),
        "percent": m.percent,
    }


def cpu() -> dict:
    return {"percent": psutil.cpu_percent(interval=0.3), "cores": psutil.cpu_count()}


def disks() -> list:
    result = []
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
            result.append({
                "drive": p.mountpoint,
                "total_gb": round(u.total / 1e9, 1),
                "used_gb": round(u.used / 1e9, 1),
                "free_gb": round(u.free / 1e9, 1),
                "percent": u.percent,
            })
        except Exception:
            continue
    return result


def battery() -> dict | None:
    b = psutil.sensors_battery()
    if not b:
        return None
    return {
        "percent": round(b.percent, 1),
        "plugged": b.power_plugged,
        "charging": b.power_plugged and b.percent < 100,
    }


def internet() -> dict:
    ok = False
    try:
        socket.setdefaulttimeout(2)
        socket.create_connection(("8.8.8.8", 53))
        ok = True
    except Exception:
        pass
    return {"connected": ok}


def running_apps(limit: int = 15) -> list:
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
        try:
            if p.info["cpu_percent"] > 0.1 or p.info["memory_percent"] > 0.3:
                procs.append({
                    "name": p.info["name"],
                    "cpu": round(p.info["cpu_percent"], 1),
                    "mem": round(p.info["memory_percent"], 1),
                })
        except Exception:
            continue
    procs.sort(key=lambda x: x["cpu"] + x["mem"], reverse=True)
    return procs[:limit]


def search_files(query: str, max_results: int = 8) -> list:
    """Lazy search in known dirs only — no recursive full scan."""
    q = query.lower().strip()
    results = []
    for root in _SEARCH_ROOTS:
        try:
            for f in root.iterdir():
                if f.is_file() and q in f.name.lower():
                    results.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "modified": f.stat().st_mtime,
                    })
                if len(results) >= max_results:
                    return sorted(results, key=lambda x: x["modified"], reverse=True)
        except Exception:
            continue
    return sorted(results, key=lambda x: x["modified"], reverse=True)


def recent_files(limit: int = 10) -> list:
    """Most recently modified files across known roots."""
    all_files = []
    for root in _SEARCH_ROOTS:
        try:
            for f in root.iterdir():
                if f.is_file():
                    all_files.append((f.stat().st_mtime, f))
        except Exception:
            continue
    all_files.sort(reverse=True)
    return [
        {"name": f.name, "path": str(f), "modified": ts}
        for ts, f in all_files[:limit]
    ]


def answer(query: str) -> dict:
    """Auto-detect query intent → return data + text summary."""
    q = query.lower()

    if any(k in q for k in ("ram", "memory", "mem")):
        d = ram()
        return {"type": "ram", "data": d,
                "text": f"RAM: {d['used_gb']}GB used / {d['total_gb']}GB total ({d['percent']}% used)"}

    if any(k in q for k in ("cpu", "processor", "processing power")):
        d = cpu()
        return {"type": "cpu", "data": d,
                "text": f"CPU: {d['percent']}% usage across {d['cores']} cores"}

    if any(k in q for k in ("disk", "storage", "space", "drive", "ssd")):
        d = disks()
        lines = " | ".join(f"{x['drive']} {x['free_gb']}GB free" for x in d[:3])
        return {"type": "disk", "data": d, "text": f"Storage: {lines}"}

    if any(k in q for k in ("battery", "charge", "charging")):
        d = battery()
        if not d:
            return {"type": "battery", "data": None, "text": "No battery (desktop PC)"}
        st = "Charging" if d["charging"] else ("Plugged in" if d["plugged"] else "On battery")
        return {"type": "battery", "data": d, "text": f"Battery: {d['percent']}% — {st}"}

    if any(k in q for k in ("internet", "wifi", "network", "online", "connection")):
        d = internet()
        return {"type": "internet", "data": d,
                "text": "Internet: Connected ✓" if d["connected"] else "Internet: No connection ✗"}

    if any(k in q for k in ("running", "apps", "processes", "programs", "open")):
        d = running_apps()
        names = ", ".join(p["name"] for p in d[:6])
        return {"type": "apps", "data": d, "text": f"Top processes: {names}"}

    if any(k in q for k in ("recent", "latest file", "last file")):
        d = recent_files()
        names = ", ".join(f["name"] for f in d[:5])
        return {"type": "recent", "data": d, "text": f"Recent files: {names}"}

    for prefix in ("where is", "find", "search for", "locate", "where's my", "where's"):
        if prefix in q:
            term = q.split(prefix, 1)[-1].strip()
            d = search_files(term)
            if d:
                return {"type": "search", "data": d,
                        "text": f"Found {len(d)}: {', '.join(x['name'] for x in d[:3])}"}
            return {"type": "search", "data": [],
                    "text": f"No files matching '{term}' in Desktop, Downloads, Documents, Pictures"}

    return {"type": "unknown", "data": None, "text": None}
