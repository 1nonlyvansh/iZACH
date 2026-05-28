import subprocess
import pygetwindow as gw
import win32gui
import win32con
import time
import pyautogui
from screeninfo import get_monitors

def safe_activate(window):
    """Bring window to foreground using win32gui to avoid pygetwindow's error-code-0 false raise."""
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
    """Polls until a window with app_name appears or timeout hits."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        windows = [w for w in gw.getWindowsWithTitle(app_name) if w.title != ""]
        if windows:
            return windows[0]
        time.sleep(0.5)
    return None

def snap_window(window, position):
    """Calculates coordinates and snaps window to a region of the primary screen."""
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
    """Launches app using Windows search simulation."""
    pyautogui.press('win')
    time.sleep(0.4)
    pyautogui.write(app_name, interval=0.05)
    time.sleep(0.4)
    pyautogui.press('enter')

import os as _os

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

def handle_open_with_position(app_name, position=None):
    """
    Core Logic:
    1. Check if running.
    2. If not, launch.
    3. Wait for window to exist.
    4. Apply snap if position is provided.
    """
    app_lower = app_name.lower().strip()

    # Direct-launch known system apps — bypass Windows Search
    if app_lower in _APP_DIRECT_LAUNCH:
        exe, window_title = _APP_DIRECT_LAUNCH[app_lower]
        windows = [w for w in gw.getAllWindows() if window_title.lower() in w.title.lower() and w.title]
        if not windows:
            import os as _os2
            if _os2.path.isfile(exe):
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