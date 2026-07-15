"""
modules/screen_awareness.py
Screen-aware assistance — periodically inspects the active window and
proactively offers help for two concrete, narrow cases:
  1. A stack trace / exception is visible (OCR + regex match — deterministic,
     no LLM call, so OCR'd text never leaves this process).
  2. The same browser tab has been sitting idle (foreground, unchanged) for
     a long time (pure timing signal from window_watcher — no OCR needed).

Off by default ("screen_aware_enabled") — nothing here runs until the user
opts in via Settings. A per-app exclusion list ("screen_aware_excluded_apps",
default: common password managers) is checked before any OCR happens, plus a
fixed, non-editable sensitive-title-keyword skip as a defense-in-depth net
(so a "Bank Login" browser tab is skipped even though browsers as a whole
are never excluded — excluding browsers wholesale would defeat the idle-tab
check, one of the two things this feature exists to catch).
"""
import json
import logging
import re
import threading
import time

logger = logging.getLogger("iZACH.ScreenAwareness")

_SETTINGS_FILE = "api_keys.json"
_POLL_INTERVAL_SECONDS = 120
_SUGGESTION_COOLDOWN_SECONDS = 900  # don't nag about the same class of thing more than once per 15 min
_IDLE_TAB_MINUTES = 20

_BROWSER_APPS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

_DEFAULT_EXCLUDED_APPS = ["keepass", "keepassxc", "1password", "bitwarden", "lastpass"]

# Fixed safety net, not user-editable — browsers are never excluded wholesale
# (that would defeat the idle-tab check), so sensitive-looking tab titles get
# their own always-on skip regardless of the app-level exclusion list.
_SENSITIVE_TITLE_KEYWORDS = (
    "password", "bank", "banking", "netbanking", "wallet", "paypal",
    "login", "sign in", "credit card", "otp", "credentials",
)

_STACK_TRACE_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"Exception in thread"),
    re.compile(r"Unhandled exception"),
    re.compile(r'File "[^"]+", line \d+'),
    re.compile(r"\bat [\w.$]+\([\w.]+:\d+\)"),  # Java-style stack frame
    re.compile(r"NullPointerException|IndexOutOfBoundsException|NullReferenceException"),
    re.compile(r"\b\w+Error\b[^\n]{0,80}\bat\b"),
]

_speak_func = None
_thread = None
_stop_event = threading.Event()

_last_suggestion_ts: dict[str, float] = {"stack_trace": 0.0, "idle_tab": 0.0}
_same_window_key: str | None = None
_same_window_since: float = 0.0
_idle_tab_offered_for: str | None = None
_flagged_windows: set[str] = set()  # (app,title) pairs already flagged this session — don't repeat


def init(speak_fn):
    global _speak_func
    _speak_func = speak_fn


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_excluded(app: str, title: str, excluded_apps: list) -> bool:
    app_l = (app or "").lower()
    title_l = (title or "").lower()
    if any(ex and ex.lower() in app_l for ex in excluded_apps):
        return True
    if any(kw in title_l for kw in _SENSITIVE_TITLE_KEYWORDS):
        return True
    return False


def _capture_active_window():
    try:
        import win32gui
        from PIL import ImageGrab
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        rect = win32gui.GetWindowRect(hwnd)
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            return None
        return ImageGrab.grab(bbox=rect)
    except Exception as e:
        logger.debug(f"Capture failed: {e}")
        return None


def _ocr(img) -> str:
    try:
        import pytesseract
        return (pytesseract.image_to_string(img) or "").strip()
    except Exception as e:
        logger.debug(f"OCR failed: {e}")
        return ""


def _looks_like_stack_trace(text: str) -> bool:
    return any(p.search(text) for p in _STACK_TRACE_PATTERNS)


def _check_stack_trace(app: str, title: str, window_key: str):
    if window_key in _flagged_windows:
        return
    if time.time() - _last_suggestion_ts["stack_trace"] < _SUGGESTION_COOLDOWN_SECONDS:
        return
    img = _capture_active_window()
    if img is None:
        return
    text = _ocr(img)
    if not text or not _looks_like_stack_trace(text):
        return
    _flagged_windows.add(window_key)
    _last_suggestion_ts["stack_trace"] = time.time()
    if _speak_func:
        _speak_func(
            f"Looks like there's an error on screen in {app}. Want me to take a look at it?"
        )
    logger.info(f"[ScreenAwareness] Stack trace flagged in {app} — {title!r}")


def _check_idle_tab(app: str, title: str, window_key: str):
    global _same_window_key, _same_window_since, _idle_tab_offered_for

    if window_key != _same_window_key:
        _same_window_key = window_key
        _same_window_since = time.time()
        return

    if app.lower() not in _BROWSER_APPS:
        return
    if _idle_tab_offered_for == window_key:
        return
    if time.time() - _same_window_since < _IDLE_TAB_MINUTES * 60:
        return
    if time.time() - _last_suggestion_ts["idle_tab"] < _SUGGESTION_COOLDOWN_SECONDS:
        return

    _idle_tab_offered_for = window_key
    _last_suggestion_ts["idle_tab"] = time.time()
    if _speak_func:
        _speak_func(
            f'"{title}" has been open and idle for a while. Want me to close it?'
        )
    logger.info(f"[ScreenAwareness] Idle tab flagged — {title!r}")


def _poll():
    settings = _load_settings()
    if not settings.get("screen_aware_enabled", False):
        return

    excluded_apps = settings.get("screen_aware_excluded_apps", None)
    if excluded_apps is None:
        excluded_apps = _DEFAULT_EXCLUDED_APPS

    from modules.window_watcher import get_active_window
    win = get_active_window()
    app = win.get("app", "")
    title = win.get("title", "")
    if not app or not title:
        return

    window_key = f"{app}|{title}"

    if _is_excluded(app, title, excluded_apps):
        return

    _check_idle_tab(app, title, window_key)
    _check_stack_trace(app, title, window_key)


def _loop():
    while not _stop_event.is_set():
        try:
            _poll()
        except Exception as e:
            logger.warning(f"[ScreenAwareness] Poll error: {e}")
        _stop_event.wait(_POLL_INTERVAL_SECONDS)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    logger.info("[ScreenAwareness] Started (idle-loop; no-ops unless screen_aware_enabled is set).")


def stop():
    _stop_event.set()
