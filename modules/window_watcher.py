"""
modules/window_watcher.py
Tracks foreground window every 2s, broadcasts changes via WS.
Provides get_active_window() for AI context injection.
"""

import threading
import time

from modules.platform_utils import IS_WINDOWS, IS_MAC

if IS_WINDOWS:
    import win32gui
    import win32process
import psutil

_current: dict = {"app": "", "title": "", "pid": 0}
_lock    = threading.Lock()
_running = False

# Apps to ignore (noise)
_IGNORE_TITLES = {"", "Program Manager", "Windows Input Experience"}
_IGNORE_APPS   = {"TextInputHost", "SearchHost", "ShellExperienceHost"}


def get_active_window() -> dict:
    with _lock:
        return dict(_current)


def _get_foreground_windows() -> dict | None:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd)
        if title in _IGNORE_TITLES:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            proc = psutil.Process(pid)
            app  = proc.name().replace(".exe", "")
        except Exception:
            app = "unknown"
        if app in _IGNORE_APPS:
            return None
        return {"app": app, "title": title, "pid": pid}
    except Exception:
        return None


def _get_frontmost_window_title_mac(pid: int) -> str | None:
    """Best-effort window title via Quartz — modern macOS requires Screen
    Recording permission for real window titles; without it this silently
    returns None and _get_foreground_mac() falls back to just the app name."""
    try:
        import Quartz
        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        for w in windows:
            if w.get("kCGWindowOwnerPID") == pid:
                title = w.get("kCGWindowName")
                if title:
                    return str(title)
        return None
    except Exception:
        return None


def _get_foreground_mac() -> dict | None:
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        app_name = str(app.localizedName() or "unknown")
        if app_name in _IGNORE_APPS:
            return None
        pid = int(app.processIdentifier())
        title = _get_frontmost_window_title_mac(pid) or app_name
        return {"app": app_name, "title": title, "pid": pid}
    except Exception:
        return None


def _get_foreground() -> dict | None:
    if IS_MAC:
        return _get_foreground_mac()
    if IS_WINDOWS:
        return _get_foreground_windows()
    return None


def _watch_loop():
    last_title = ""
    while _running:
        info = _get_foreground()
        if info and info["title"] != last_title:
            last_title = info["title"]
            with _lock:
                _current.update(info)
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "window_change", "app": info["app"],
                           "title": info["title"], "pid": info["pid"]})
            except Exception:
                pass
        time.sleep(2)


def start(speak_fn=None):
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_watch_loop, daemon=True, name="WindowWatcher").start()
    print("[WINDOW] Watcher started.")


def stop():
    global _running
    _running = False
