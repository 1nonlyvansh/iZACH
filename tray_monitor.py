"""
tray_monitor.py — Lightweight always-on iZACH tray monitor.

Runs as its own tiny process (NOT inside the backend). Can start with Windows
via a registry Run key so iZACH is always reachable from the tray even when
the backend is offline.

Indicator dot on the iZACH icon:
  🔴 Red    — Python backend offline (can't reach :5050/health)
  🟡 Yellow — Busy mode active
  🟠 Orange — DND mode active
  🟢 Green  — All good / backend online

Right-click menu:
  • Start iZACH     (if offline)
  • Stop iZACH      (if online — graceful /shutdown)
  • Open Forge UI   (launches Electron)
  • Open Cortex UI  (launches Electron)
  • Status          (backend version/uptime)
  • Start with Windows (toggle registry Run key)
  ─────────────────
  • Quit Monitor

Usage:
  python tray_monitor.py
"""

import os
import sys
import time
import json
import threading
import subprocess
import urllib.request

import pystray
from PIL import Image, ImageDraw

# ── Paths ─────────────────────────────────────────────────────
BASE         = r"C:\Projects\iZACH"
VENV_PY      = os.path.join(BASE, r".venv\Scripts\python.exe")
MAIN_PY      = os.path.join(BASE, "main.py")
ELECTRON_DIR = os.path.join(BASE, "izach-ui")
ELECTRON_BIN = os.path.join(ELECTRON_DIR, "node_modules", ".bin", "electron.cmd")
APIKEYS      = os.path.join(BASE, "api_keys.json")
ICON_FILES   = [
    os.path.join(BASE, "iZACH logo.png"),
    os.path.join(BASE, "iZACH Cropped logo.png"),
    os.path.join(BASE, "Full Size iZACH Icon.png"),
]

API          = "http://localhost:5050"
REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_KEY_NAME = "iZACH-Monitor"

# ── State ─────────────────────────────────────────────────────
_icon        = None
_state       = "offline"          # "offline" | "normal" | "dnd" | "busy"
_opening     = False

_DOT = {
    "offline": (255,  61,  61, 255),  # red
    "dnd":     (255, 120,   0, 255),  # orange
    "busy":    (255, 179,   0, 255),  # yellow
    "mic_off": (255,  61,  61, 255),  # red (same as offline but backend alive)
    "normal":  ( 29, 185,  84, 255),  # green
}

_TITLE = {
    "offline": "iZACH — Backend OFFLINE",
    "dnd":     "iZACH — DND ON",
    "busy":    "iZACH — Busy Mode",
    "mic_off": "iZACH — Mic OFF",
    "normal":  "iZACH — Online",
}


# ── Icon builder ──────────────────────────────────────────────
def _base_img():
    for p in ICON_FILES:
        if os.path.exists(p):
            try:
                return Image.open(p).convert("RGBA").resize((64, 64), Image.LANCZOS)
            except Exception:
                continue
    img = Image.new("RGBA", (64, 64), (0, 229, 255, 255))
    return img


def _make_icon(state: str) -> Image.Image:
    base = _base_img()
    draw = ImageDraw.Draw(base)
    dot  = _DOT.get(state, _DOT["normal"])
    cx, cy, r = 52, 52, 7
    draw.ellipse([cx-r-1, cy-r-1, cx+r+1, cy+r+1], fill=(255, 255, 255, 200))
    draw.ellipse([cx-r,   cy-r,   cx+r,   cy+r  ], fill=dot)
    return base


# ── Backend probe ─────────────────────────────────────────────
def _probe() -> str:
    """Return current state string by querying the backend."""
    try:
        with urllib.request.urlopen(f"{API}/health", timeout=2) as r:
            if r.status >= 500:
                return "offline"
    except Exception:
        return "offline"

    # Backend alive — check DND > Busy > Mic priority
    try:
        with urllib.request.urlopen(f"{API}/dnd", timeout=2) as r:
            if json.loads(r.read()).get("active"):
                return "dnd"
    except Exception:
        pass
    try:
        with urllib.request.urlopen(f"{API}/busy", timeout=2) as r:
            if json.loads(r.read()).get("active"):
                return "busy"
    except Exception:
        pass
    try:
        with urllib.request.urlopen(f"{API}/mic", timeout=2) as r:
            if not json.loads(r.read()).get("mic_active", True):
                return "mic_off"
    except Exception:
        pass
    return "normal"


# ── HTTP action helpers ───────────────────────────────────────
def _http_post(path, payload=None):
    import urllib.request as _ur
    data = json.dumps(payload or {}).encode()
    req  = urllib.request.Request(f"{API}{path}", data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with _ur.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"[MONITOR] POST {path} failed: {e}")

def _http_get_json(path):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


# ── DND timer helpers ─────────────────────────────────────────
def _dnd_timer(seconds: int):
    """Turn DND on now, auto-off after `seconds`."""
    _http_post("/dnd", {"action": "on", "reason": "manual"})
    def _off():
        _http_post("/dnd", {"action": "off", "reason": "timer"})
    threading.Timer(seconds, _off).start()


def _toggle_dnd(icon, item):
    online = _state != "offline"
    if not online:
        return
    d = _http_get_json("/dnd")
    _http_post("/dnd", {"action": "off" if d.get("active") else "on", "reason": "manual"})

def _toggle_busy(icon, item):
    online = _state != "offline"
    if not online:
        return
    d = _http_get_json("/busy")
    _http_post("/busy", {"action": "off" if d.get("active") else "on", "reason": "manual"})

def _toggle_mic(icon, item):
    online = _state != "offline"
    if not online:
        return
    d = _http_get_json("/mic")
    cur = d.get("mic_active", True)
    _http_post("/mic", {"active": not cur})


def _watcher():
    global _state
    while True:
        try:
            new = _probe()
            if new != _state:
                _state = new
                if _icon is not None:
                    _icon.icon  = _make_icon(new)
                    _icon.title = _TITLE.get(new, "iZACH")
                    _icon.update_menu()
        except Exception:
            pass
        time.sleep(3)


# ── Registry (Start with Windows) ────────────────────────────
def _is_startup_enabled() -> bool:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH)
        winreg.QueryValueEx(k, REG_KEY_NAME)
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def _toggle_startup(icon, item):
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0,
                           winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        if _is_startup_enabled():
            winreg.DeleteValue(k, REG_KEY_NAME)
            print("[MONITOR] Removed from Windows startup.")
        else:
            cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(k, REG_KEY_NAME, 0, winreg.REG_SZ, cmd)
            print(f"[MONITOR] Added to Windows startup: {cmd}")
        winreg.CloseKey(k)
        icon.update_menu()
    except Exception as e:
        print(f"[MONITOR] Startup toggle failed: {e}")


# ── Actions ───────────────────────────────────────────────────
def _start_izach(icon, item):
    def _run():
        try:
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [VENV_PY, MAIN_PY], cwd=BASE,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=no_win,
            )
            print("[MONITOR] iZACH backend starting…")
        except Exception as e:
            print(f"[MONITOR] Start failed: {e}")
    threading.Thread(target=_run, daemon=True).start()


def _stop_izach(icon, item):
    def _run():
        try:
            import urllib.request as _ur
            req = urllib.request.Request(f"{API}/shutdown", method="POST")
            _ur.urlopen(req, timeout=5)
            print("[MONITOR] Sent shutdown to backend.")
        except Exception as e:
            print(f"[MONITOR] Stop failed: {e}")
    threading.Thread(target=_run, daemon=True).start()


def _open_ui(mode):
    global _opening
    if _opening:
        return
    _opening = True
    def _run():
        global _opening
        try:
            # Write chosen ui mode to api_keys.json first
            data = {}
            try:
                with open(APIKEYS, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
            data["ui"] = mode
            with open(APIKEYS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            env = os.environ.copy()
            env["NODE_ENV"] = "production"
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["cmd", "/c", "npm", "run", "build"], cwd=ELECTRON_DIR,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=no_win, env=env,
            )
            cmd = [ELECTRON_BIN, "."] if os.path.exists(ELECTRON_BIN) else \
                  ["npx", "--yes", "electron", "."]
            subprocess.Popen(
                cmd, cwd=ELECTRON_DIR, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[MONITOR] Open UI failed: {e}")
        finally:
            _opening = False
    threading.Thread(target=_run, daemon=True).start()


def _quit(icon, item):
    icon.stop()


# ── Menu ──────────────────────────────────────────────────────
def _build_menu():
    Item = pystray.MenuItem
    Menu = pystray.Menu
    online = _state != "offline"

    # ── Live state for checkmarks (queried fresh each menu open) ──
    def _dnd_on(it):
        try: return _http_get_json("/dnd").get("active", False)
        except: return False
    def _busy_on(it):
        try: return _http_get_json("/busy").get("active", False)
        except: return False
    def _mic_on(it):
        try: return _http_get_json("/mic").get("mic_active", True)
        except: return True

    # ── Quit iZACH (backend + monitor) ───────────────────────────
    def _quit_izach(icon, item):
        def _run():
            _http_post("/shutdown")
            time.sleep(2)
            icon.stop()
        threading.Thread(target=_run, daemon=True).start()

    # ── DND timer submenu ─────────────────────────────────────────
    dnd_timer_menu = Menu(
        Item("30 minutes", lambda i, it: _dnd_timer(1800)),
        Item("1 hour",     lambda i, it: _dnd_timer(3600)),
        Item("2 hours",    lambda i, it: _dnd_timer(7200)),
    )

    if online:
        return Menu(
            Item("iZACH",          None, enabled=False),
            Menu.SEPARATOR,
            Item("Open Forge UI",  lambda i, it: _open_ui("classic")),
            Item("Open Cortex UI", lambda i, it: _open_ui("scifi")),
            Menu.SEPARATOR,
            Item("Mic Active",     _toggle_mic,  checked=_mic_on),
            Item("Do Not Disturb", _toggle_dnd,  checked=_dnd_on),
            Item("DND Timer ▶", dnd_timer_menu),
            Item("Busy Mode",      _toggle_busy, checked=_busy_on),
            Menu.SEPARATOR,
            Item("Stop iZACH",         _stop_izach),
            Item("Start with Windows", _toggle_startup,
                 checked=lambda it: _is_startup_enabled()),
            Menu.SEPARATOR,
            Item("Quit Monitor",   _quit),
            Item("Quit iZACH",     _quit_izach),
        )
    else:
        return Menu(
            Item("iZACH — OFFLINE", None, enabled=False),
            Menu.SEPARATOR,
            Item("Start iZACH",        _start_izach),
            Menu.SEPARATOR,
            Item("Start with Windows", _toggle_startup,
                 checked=lambda it: _is_startup_enabled()),
            Menu.SEPARATOR,
            Item("Quit Monitor",   _quit),
        )


# ── Main ──────────────────────────────────────────────────────
def main():
    global _icon
    _state_now = _probe()
    _icon = pystray.Icon(
        "iZACH-Monitor",
        _make_icon(_state_now),
        _TITLE.get(_state_now, "iZACH"),
        _build_menu(),
    )
    threading.Thread(target=_watcher, daemon=True, name="MonitorWatcher").start()
    print("[MONITOR] iZACH tray monitor running.")
    _icon.run()          # blocks until quit


if __name__ == "__main__":
    main()
