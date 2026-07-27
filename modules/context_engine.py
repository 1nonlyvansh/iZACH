import os as _os
import subprocess
import time

from modules.platform_utils import IS_WINDOWS, IS_MAC

if IS_WINDOWS:
    import pygetwindow as gw
    import win32gui
    import win32con
    import pyautogui
from screeninfo import get_monitors


def safe_activate(window):
    """Bring window to foreground using win32gui to avoid pygetwindow's error-code-0 false raise."""
    if not IS_WINDOWS:
        return
    try:
        hwnd = window._hWnd
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        window.restore()
        window.activate()


def get_screen_resolution():
    """Gets the primary monitor's dimensions."""
    monitor = get_monitors()[0]
    return monitor.width, monitor.height


def wait_for_window(app_name, timeout=10):
    """Polls until a window with app_name appears or timeout hits. Windows-only —
    pygetwindow has no meaningful macOS backend; see handle_open_with_position's
    macOS branch, which doesn't depend on this at all."""
    if not IS_WINDOWS:
        return None
    start_time = time.time()
    while time.time() - start_time < timeout:
        windows = [w for w in gw.getWindowsWithTitle(app_name) if w.title != ""]
        if windows:
            return windows[0]
        time.sleep(0.5)
    return None


def snap_window(window, position):
    """Calculates coordinates and snaps window to a region of the primary screen.
    Windows-only — no native macOS equivalent pre-Sequoia's Window Tiling;
    implementing this via System Events/Accessibility is future work (Phase 5)."""
    if not IS_WINDOWS:
        return False
    try:
        sw, sh = get_screen_resolution()
        # Ensure window is restored and focusable
        if window.isMinimized:
            window.restore()
        safe_activate(window)

        # Define Regions
        # Note: Windows handles taskbars/borders; these are raw offsets
        if position == "left":
            window.moveTo(0, 0)
            window.resizeTo(sw // 2, sh)
        elif position == "right":
            window.moveTo(sw // 2, 0)
            window.resizeTo(sw // 2, sh)
        elif position == "top":
            window.moveTo(0, 0)
            window.resizeTo(sw, sh // 2)
        elif position == "bottom":
            window.moveTo(0, sh // 2)
            window.resizeTo(sw, sh // 2)
        elif position == "maximize":
            window.maximize()

        return True
    except Exception as e:
        print(f"[SNAP ERROR] {e}")
        return False


def launch_app_via_search(app_name):
    """Launches app using Windows search simulation. macOS has no equivalent
    concept — see handle_open_with_position's macOS branch, which uses `open -a`
    directly instead of calling this."""
    if not IS_WINDOWS:
        return
    pyautogui.press('win')
    time.sleep(0.4)
    pyautogui.write(app_name, interval=0.05)
    time.sleep(0.4)
    pyautogui.press('enter')


_SPOTIFY_EXE = _os.path.join(_os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")

_APP_DIRECT_LAUNCH = {
    "file explorer": ("explorer.exe", "File Explorer"),
    "explorer":      ("explorer.exe", "File Explorer"),
    "notepad":       ("notepad.exe",  "Notepad"),
    "paint":         ("mspaint.exe",  "Paint"),
    "calculator":    ("calc.exe",     "Calculator"),
    "wordpad":       ("wordpad.exe",  "WordPad"),
    "task manager":  ("taskmgr.exe",  "Task Manager"),
    "control panel": ("control.exe",  "Control Panel"),
    "spotify":       (_SPOTIFY_EXE,   "Spotify"),
}

# macOS app-name map for `open -a` — no .exe suffix, uses actual .app bundle names.
_APP_NAME_MAP_MAC = {
    "file explorer": "Finder", "explorer": "Finder",
    "notepad": "TextEdit",
    "paint": "Preview",
    "calculator": "Calculator",
    "wordpad": "TextEdit",
    "task manager": "Activity Monitor",
    "control panel": "System Settings",
    "spotify": "Spotify",
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "mail": "Mail",
    "messages": "Messages",
    "music": "Music",
    "photos": "Photos",
    "preview": "Preview",
    "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "slack": "Slack",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "zoom": "zoom.us",
}


def _open_app_mac(app_name: str) -> bool:
    """Launch an app via `open -a <name>` — macOS's equivalent of Windows Search
    launch, and generally more reliable since it resolves the real app bundle
    directly instead of simulating keystrokes."""
    target = _APP_NAME_MAP_MAC.get(app_name.lower().strip(), app_name)
    try:
        result = subprocess.run(["open", "-a", target], capture_output=True, text=True, timeout=8)
        return result.returncode == 0
    except Exception:
        return False


def handle_open_with_position(app_name, position=None):
    """
    Core Logic:
    1. Check if running.
    2. If not, launch.
    3. Wait for window to exist.
    4. Apply snap if position is provided.

    macOS: window snapping isn't implemented yet (no native pre-Sequoia snap
    API, would need System Events/Accessibility geometry control — a bigger
    follow-up), so this just launches/activates the app via `open -a` and
    says so if a position was requested.
    """
    if IS_MAC:
        ok = _open_app_mac(app_name)
        if not ok:
            return f"Couldn't find or open {app_name}."
        if position:
            return f"Opened {app_name} — window snapping isn't available on macOS yet, so it wasn't positioned to the {position}."
        return f"Opened {app_name}."

    app_lower = app_name.lower().strip()

    # Direct-launch known system apps — bypass Windows Search
    if app_lower in _APP_DIRECT_LAUNCH:
        exe, window_title = _APP_DIRECT_LAUNCH[app_lower]
        windows = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower() and w.title]
        if not windows:
            if _os.path.isfile(exe):
                subprocess.Popen([exe])
            else:
                launch_app_via_search(window_title)
            target_window = wait_for_window(window_title)
        else:
            target_window = windows[0]
        if not target_window:
            return f"Opened {app_name}."
        if position:
            snap_window(target_window, position)
            return f"Opening {app_name} snapped to the {position}."
        safe_activate(target_window)
        return f"Opened {app_name}."

    # 1. Launch if not running
    windows = [w for w in gw.getWindowsWithTitle(app_name) if w.title != ""]

    if not windows:
        launch_app_via_search(app_name)
        target_window = wait_for_window(app_name)
    else:
        target_window = windows[0]

    if not target_window:
        return f"I tried launching {app_name}, but it's not showing up."

    # 2. Apply Snap
    if position:
        success = snap_window(target_window, position)
        if success:
            return f"Opening {app_name} and snapping it to the {position}."
        else:
            return f"Opened {app_name}, but the snap failed."

    # 3. Default behavior (just bring to front)
    target_window.restore()
    safe_activate(target_window)
    return f"Brought {app_name} to the front."
