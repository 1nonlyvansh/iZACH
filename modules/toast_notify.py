"""
toast_notify.py — Windows toast notifications for iZACH using winotify.

Usage:
    from modules import toast_notify as _toast
    _toast.notify("iZACH", "Some message")
"""

import os
import sys

_APP_ID   = "iZACH"
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICON     = os.path.join(_BASE_DIR, "iZACH logo.png")


def notify(title: str, message: str, duration: int = 5):
    """Show a native OS notification. Silent fail on unsupported platforms or missing library."""
    if sys.platform == "win32":
        _notify_windows(title, message, duration)
    elif sys.platform == "darwin":
        _notify_mac(title, message)


def _notify_windows(title: str, message: str, duration: int):
    try:
        from winotify import Notification, audio  # type: ignore
        toast = Notification(
            app_id=_APP_ID,
            title=str(title)[:64],
            msg=str(message)[:200],
            duration="short" if duration <= 5 else "long",
            icon=_ICON if os.path.exists(_ICON) else "",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception:
        pass


def _notify_mac(title: str, message: str):
    try:
        from modules.platform_utils import run_applescript

        def _escape(s: str) -> str:
            return str(s).replace("\\", "\\\\").replace('"', '\\"')

        script = f'display notification "{_escape(message)[:200]}" with title "{_escape(title)[:64]}"'
        run_applescript(script)
    except Exception:
        pass
