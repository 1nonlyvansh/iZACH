"""
Notification system — push categorized PC events to Android.
Categories: system, downloads, transfers, automation, alerts
"""
import time

CATEGORIES = {"system", "downloads", "transfers", "automation", "alerts"}
_history: list[dict] = []
_MAX_HISTORY = 50


def push(title: str, category: str = "system", body: str = ""):
    if category not in CATEGORIES:
        category = "system"
    entry = {
        "title": title,
        "category": category,
        "body": body,
        "ts": int(time.time()),
    }
    _history.insert(0, entry)
    if len(_history) > _MAX_HISTORY:
        _history.pop()
    try:
        from modules.ws_bridge import emit
        emit("notification", category, {
            "title": title,
            "body": body,
            "category": category,
            "ts": int(time.time()),
        })
    except Exception:
        pass


def history() -> list:
    return list(_history)
