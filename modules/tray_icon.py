"""
tray_icon.py — Windows system-tray icon for iZACH Background Mode.

Runs in-process inside the backend (main.py). Only started when run mode is
"background" (no Electron window). Right-click menu lets the user open a UI,
toggle the mic, toggle DND / Busy, and quit — without any window open.

Lightweight: pystray + Pillow only (~tens of MB), vs ~400 MB for Electron.
"""

import os
import threading
import subprocess

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICON = None          # pystray.Icon singleton
_ICON_FILES = ("iZACH logo.png", "iZACH Cropped logo.png", "Full Size iZACH Icon.png")

# ── Dot colors by state ───────────────────────────────────────
# Priority (highest first): dnd > busy > mic_off > normal
_DOT_COLORS = {
    "dnd":     (255, 120,   0, 255),  # orange
    "busy":    (255, 179,   0, 255),  # yellow
    "mic_off": (255,  61,  61, 255),  # red
    "normal":  ( 29, 185,  84, 255),  # green
}
_last_state = "normal"

# ── Icon image ────────────────────────────────────────────────
def _load_base_image():
    from PIL import Image
    for name in _ICON_FILES:
        p = os.path.join(_BASE, name)
        if os.path.exists(p):
            try:
                img = Image.open(p).convert("RGBA")
                return img.resize((64, 64), Image.LANCZOS)
            except Exception:
                continue
    return Image.new("RGBA", (64, 64), (0, 229, 255, 255))


def _make_icon_image(state: str):
    """Return base logo with a colored indicator dot in bottom-right corner."""
    from PIL import Image, ImageDraw
    base = _load_base_image()
    draw = ImageDraw.Draw(base)
    dot_rgba = _DOT_COLORS.get(state, _DOT_COLORS["normal"])

    # Dot: 14×14 px, bottom-right, white outline for contrast
    cx, cy, r = 52, 52, 7
    draw.ellipse([cx-r-1, cy-r-1, cx+r+1, cy+r+1],
                 fill=(255, 255, 255, 200))           # white ring
    draw.ellipse([cx-r,   cy-r,   cx+r,   cy+r  ],
                 fill=dot_rgba)
    return base


def _load_image():
    """Initial icon image (resolves to current state)."""
    return _make_icon_image(_last_state)


# ── State watcher — updates dot every 2 s ────────────────────
def _get_state() -> str:
    try:
        from modules import dnd_mode
        if dnd_mode.is_active():
            return "dnd"
    except Exception:
        pass
    try:
        from modules import busy_mode
        if busy_mode.is_active():
            return "busy"
    except Exception:
        pass
    try:
        from modules import ui_api
        if not ui_api.is_mic_active():
            return "mic_off"
    except Exception:
        pass
    return "normal"


def _state_watcher():
    global _last_state
    while _ICON is not None:
        try:
            new_state = _get_state()
            if new_state != _last_state:
                _last_state = new_state
                if _ICON is not None:
                    _ICON.icon  = _make_icon_image(new_state)
                    _ICON.title = (
                        "iZACH — DND ON"     if new_state == "dnd"     else
                        "iZACH — Busy Mode"  if new_state == "busy"    else
                        "iZACH — Mic OFF"    if new_state == "mic_off" else
                        "iZACH — Background"
                    )
        except Exception:
            pass
        import time; time.sleep(2)


# ── State helpers ─────────────────────────────────────────────
def _mic_active():
    try:
        from modules import ui_api
        return ui_api.is_mic_active()
    except Exception:
        return True


def _set_mic(active):
    try:
        from modules import ui_api
        ui_api._mic_active = bool(active)
    except Exception:
        pass
    # Mirror to UI clients if any are connected
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "mic_state", "active": bool(active)})
    except Exception:
        pass


def _dnd_active():
    try:
        from modules import dnd_mode
        return dnd_mode.is_active()
    except Exception:
        return False


def _busy_active():
    try:
        from modules import busy_mode
        return busy_mode.is_active()
    except Exception:
        return False


# ── Menu actions ──────────────────────────────────────────────
def _toggle_mic(icon, item):
    _set_mic(not _mic_active())
    icon.update_menu()


def _toggle_dnd(icon, item):
    try:
        from modules import dnd_mode
        if dnd_mode.is_active():
            dnd_mode.turn_off()
        else:
            # MUST be "manual" — any other reason marks DND as auto-triggered,
            # and the meeting-detector loop then auto-disables it ("Meeting ended").
            dnd_mode.turn_on("manual")
    except Exception as e:
        print(f"[TRAY] DND toggle failed: {e}")
    icon.update_menu()


def _toggle_busy(icon, item):
    try:
        from modules import busy_mode
        if busy_mode.is_active():
            busy_mode.turn_off()
        else:
            busy_mode.turn_on("manual")
    except Exception as e:
        print(f"[TRAY] Busy toggle failed: {e}")
    icon.update_menu()


_opening = False

def _open_ui(mode, icon=None):
    """Persist the ui choice and launch Electron with that UI (build first)."""
    global _opening
    if _opening:
        return   # a build/launch is already in flight — ignore double-clicks
    _opening = True

    def _run():
        global _opening
        try:
            if icon is not None:
                try:
                    icon.notify(f"Building {mode} UI — about 30s…", "iZACH")
                except Exception:
                    pass
            import json
            p = os.path.join(_BASE, "api_keys.json")
            data = {}
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
            data["ui"] = mode
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            ui_dir = os.path.join(_BASE, "izach-ui")
            if not os.path.isdir(ui_dir):
                print(f"[TRAY] izach-ui not found at {ui_dir}")
                return
            env = os.environ.copy()
            env["NODE_ENV"] = "production"
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            # Build (so latest source + chosen UI is reflected), then launch.
            subprocess.run(
                ["cmd", "/c", "npm", "run", "build"], cwd=ui_dir, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=no_win,
            )
            ebin = os.path.join(ui_dir, "node_modules", ".bin", "electron.cmd")
            cmd = [ebin, "."] if os.path.exists(ebin) else ["npx", "--yes", "electron", "."]
            subprocess.Popen(
                cmd, cwd=ui_dir, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[TRAY] Launching {mode} UI...")
            # A window UI is now open — remove the tray icon (tray is background-only).
            stop()
        except Exception as e:
            print(f"[TRAY] Open UI failed: {e}")
        finally:
            _opening = False
    threading.Thread(target=_run, daemon=True, name="Tray-OpenUI").start()


def _quit(icon, item):
    try:
        icon.stop()
    except Exception:
        pass
    try:
        import sys
        main_mod = sys.modules.get("__main__")
        if main_mod is not None and hasattr(main_mod, "safe_shutdown"):
            main_mod.safe_shutdown()
            return
    except Exception:
        pass
    os._exit(0)


# ── Menu ──────────────────────────────────────────────────────
def _build_menu():
    import pystray
    from pystray import MenuItem as Item, Menu
    return Menu(
        Item("iZACH — Background Mode", None, enabled=False),
        Menu.SEPARATOR,
        Item("Open Forge UI",  lambda i, it: _open_ui("classic", i)),
        Item("Open Cortex UI", lambda i, it: _open_ui("scifi", i)),
        Menu.SEPARATOR,
        Item("Mic Active",     _toggle_mic,  checked=lambda it: _mic_active()),
        Item("Do Not Disturb", _toggle_dnd,  checked=lambda it: _dnd_active()),
        Item("Busy Mode",      _toggle_busy, checked=lambda it: _busy_active()),
        Menu.SEPARATOR,
        Item("Quit iZACH",     _quit),
    )


# ── Lifecycle ─────────────────────────────────────────────────
def start():
    """Create and run the tray icon (non-blocking)."""
    global _ICON
    if _ICON is not None:
        return
    try:
        import pystray
    except Exception as e:
        print(f"[TRAY] pystray unavailable — tray disabled: {e}")
        return
    try:
        _ICON = pystray.Icon(
            "iZACH", _load_image(), "iZACH — Background Mode", _build_menu()
        )
    except Exception as e:
        print(f"[TRAY] Icon build failed: {e}")
        _ICON = None
        return
    try:
        _ICON.run_detached()   # spawns its own thread
        print("[TRAY] System tray icon active — right-click for menu.")
    except Exception as e:
        # Fallback: run in a daemon thread
        try:
            threading.Thread(target=_ICON.run, daemon=True, name="Tray").start()
            print(f"[TRAY] run_detached failed ({e}); started in thread.")
        except Exception as e2:
            print(f"[TRAY] Failed to start: {e2}")
            _ICON = None
            return

    # Start state watcher — updates dot color every 2 s (DND/Busy/Mic-off)
    threading.Thread(target=_state_watcher, daemon=True, name="TrayStateWatch").start()


def stop():
    global _ICON
    if _ICON is not None:
        try:
            _ICON.stop()
        except Exception:
            pass
        _ICON = None
