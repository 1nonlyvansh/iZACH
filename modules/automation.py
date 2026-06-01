import time
import pyautogui
import pygetwindow as gw
import logging
from datetime import datetime

# Configure logging for debugging window transitions
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. WINDOW SYNC ENGINE ---

def get_active_window_safe(window_title_keyword, timeout=10):
    """
    Ensures the application window is fully loaded, restored, and focused.
    """
    start_time = time.time()
    logger.info(f"[SYNC] Waiting for: {window_title_keyword}")

    while time.time() - start_time < timeout:
        all_windows = gw.getWindowsWithTitle('')
        # Search for keyword in any active window title
        target_windows = [w for w in all_windows if window_title_keyword.lower() in w.title.lower()]
        
        if target_windows:
            target_win = target_windows[0]
            try:
                try:
                    _is_min = bool(target_win.isMinimized)
                except Exception:
                    _is_min = False  # Stale handle — assume not minimised
                if _is_min:
                    target_win.restore()

                target_win.activate()
                time.sleep(1.0) # Buffer for UI thread stabilization

                if target_win.isActive:
                    logger.info(f"[SUCCESS] {target_win.title} is focused.")
                    return True
            except Exception as e:
                logger.warning(f"[RETRY] Window found but not ready: {e}")
        
        time.sleep(0.5)
    
    logger.error(f"[TIMEOUT] Failed to sync with {window_title_keyword}")
    return False

# --- 2. CORE AUTOMATION ---

_INSTALLED_APPS_CACHE: list = []
_INSTALLED_APPS_TS: float = 0.0
_INSTALLED_APPS_TTL = 300.0  # refresh every 5 min


def get_installed_apps() -> list[str]:
    """Return lowercased list of installed app names from Start menu + registry."""
    global _INSTALLED_APPS_CACHE, _INSTALLED_APPS_TS
    if time.time() - _INSTALLED_APPS_TS < _INSTALLED_APPS_TTL and _INSTALLED_APPS_CACHE:
        return _INSTALLED_APPS_CACHE

    apps: set[str] = set()

    # 1. Scan Start Menu .lnk shortcuts (most reliable — includes pinned/installed apps)
    import glob as _glob, os as _os
    for _root in (
        _os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        _os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    ):
        for _lnk in _glob.glob(_os.path.join(_root, "**", "*.lnk"), recursive=True):
            _name = _os.path.splitext(_os.path.basename(_lnk))[0].lower()
            if _name:
                apps.add(_name)

    # 2. Windows registry App Paths (covers .exe installers)
    try:
        import winreg as _reg
        _PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for _hive in (_reg.HKEY_LOCAL_MACHINE, _reg.HKEY_CURRENT_USER):
            try:
                with _reg.OpenKey(_hive, _PATHS_KEY) as _k:
                    i = 0
                    while True:
                        try:
                            _exe = _reg.EnumKey(_k, i)
                            apps.add(_os.path.splitext(_exe)[0].lower())
                            i += 1
                        except OSError:
                            break
            except Exception:
                pass
    except Exception:
        pass

    # 3. UWP / Microsoft Store apps via PowerShell (async, best-effort)
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object -ExpandProperty Name"],
            text=True, timeout=5, creationflags=_sp.CREATE_NO_WINDOW,
        )
        for line in out.splitlines():
            if line.strip():
                apps.add(line.strip().lower())
    except Exception:
        pass

    _INSTALLED_APPS_CACHE = sorted(apps)
    _INSTALLED_APPS_TS = time.time()
    return _INSTALLED_APPS_CACHE


def is_app_installed(app_name: str) -> bool:
    """Check if app_name (or close match) exists in installed apps list."""
    q = app_name.lower().strip()
    installed = get_installed_apps()
    # Exact or starts-with match
    return any(q == a or a.startswith(q) or q.startswith(a) for a in installed)


# Common aliases for apps that have unexpected names in Start menu
_APP_ALIASES: dict[str, str] = {
    "chrome":          "google chrome",
    "edge":            "microsoft edge",
    "excel":           "microsoft excel",
    "word":            "microsoft word",
    "powerpoint":      "microsoft powerpoint",
    "notepad++":       "notepad++",
    "vscode":          "visual studio code",
    "vs code":         "visual studio code",
    "file explorer":   "file explorer",
    "explorer":        "file explorer",
    "snippet":         "snipping tool",
    "snippingtool":    "snipping tool",
    "snipping":        "snipping tool",
    "snip":            "snipping tool",
    "screenshot tool": "snipping tool",
    "calc":            "calculator",
    "paint":           "mspaint",
    "task manager":    "taskmgr",
    "cmd":             "command prompt",
    "terminal":        "windows terminal",
    "sticky":          "sticky notes",
    "sticky notes":    "sticky notes",
}


def open_app(app_name: str):
    """
    Launches app via Windows Search (Win + Name + Enter).
    Validates app_name against installed apps before typing — prevents
    random words (e.g. 'play', 'open') from triggering Windows Search.
    """
    import logging as _log
    _logger = _log.getLogger("iZACH.automation")

    resolved = _APP_ALIASES.get(app_name.lower().strip(), app_name)

    # Guard: only proceed if app looks real
    # Skip guard only for very short single-word ambiguous inputs that won't match anything
    _q = resolved.lower().strip()
    _ambiguous = len(_q.split()) == 1 and len(_q) <= 5
    if _ambiguous and not is_app_installed(resolved):
        _logger.warning(f"[open_app] '{app_name}' not found in installed apps — blocked.")
        return None

    pyautogui.press('win')
    time.sleep(0.5)
    pyautogui.write(resolved, interval=0.1)
    time.sleep(0.5)
    pyautogui.press('enter')

    return get_active_window_safe(app_name)


def snap_window(direction: str, app_name: str = None):
    """
    Snap the foreground window using Win+Arrow hotkeys.
    direction: 'left' | 'right' | 'maximize' | 'minimize'
    app_name:  optional — if given, tries to focus that window before snapping.
    Waits for the window to be fully launched and focused.
    """
    d = direction.lower().strip()
    if d in ("left", "left half", "at left", "on the left", "snap left"):
        key = "left"
    elif d in ("right", "right half", "at right", "on the right", "snap right"):
        key = "right"
    elif d in ("maximize", "max", "full", "fullscreen", "center"):
        key = "up"
    elif d in ("minimize", "min"):
        key = "down"
    else:
        return

    # Try to explicitly focus the target window via Win32 so the hotkey
    # lands on the right window even if focus drifted after open_app().
    _focused = False
    if app_name:
        try:
            import win32gui, win32con
            _query = app_name.lower()
            def _find(hwnd, out):
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd).lower()
                    if _query in t or t in _query:
                        out.append(hwnd)
                return True
            _candidates = []
            for _attempt in range(6):       # retry up to 3 s
                win32gui.EnumWindows(_find, _candidates)
                if _candidates:
                    _hwnd = _candidates[0]
                    win32gui.ShowWindow(_hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(_hwnd)
                    time.sleep(0.25)
                    _focused = True
                    break
                time.sleep(0.5)
        except Exception:
            pass

    if not _focused:
        time.sleep(3.0)   # fallback: wait for app to settle and take focus

    pyautogui.hotkey("win", key)

def navigate_to_url(url, browser_name="chrome"):
    """
    Ensures browser focus and types URL into address bar.
    """
    if not get_active_window_safe(browser_name, timeout=2):
        open_app(browser_name)
    
    if get_active_window_safe(browser_name):
        pyautogui.hotkey('ctrl', 'l') 
        time.sleep(0.3)
        pyautogui.write(url, interval=0.05)
        pyautogui.press('enter')
        return True
    return False

# --- 3. REFACTORED MEDIA METHODS ---

def play_specific_youtube(song_name):
    """Searches and plays media via YouTube in Chrome."""
    url = f"https://www.youtube.com/results?search_query={song_name.replace(' ', '+')}"
    return navigate_to_url(url, "chrome")



# --- 4. SYSTEM TOOLS ---

def get_current_time():
    return f"It is {datetime.now().strftime('%I:%M %p')}."

def get_current_date():
    return f"Today is {datetime.now().strftime('%A, %B %d')}."

def get_delhi_intel():
    return "Local weather protocols active."

def get_realtime_coordinates():
    return "GPS coordinates synchronized."

def system_media_control(command):
    """Hardware-level media key simulation."""
    if any(word in command for word in ["pause", "stop", "resume"]):
        pyautogui.press("playpause")
    elif "next" in command:
        pyautogui.press("nexttrack")
    elif "previous" in command:
        pyautogui.press("prevtrack")