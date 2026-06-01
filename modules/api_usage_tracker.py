"""
modules/api_usage_tracker.py
Tracks API call counts per key, resets daily at midnight UTC.
Persists to api_usage.json. Thread-safe.
"""
from __future__ import annotations
import json, threading
from datetime import datetime, timezone

_USAGE_FILE = "api_usage.json"
_lock = threading.Lock()

# Daily limits (free tier estimates)
_LIMITS: dict[str, int] = {
    "groq_main":       14400,
    "groq_vision":     14400,
    "groq_wa":         14400,
    "gemini_1":         1500,
    "gemini_2":         1500,
    "gemini_3":         1500,
    "gemini_vision_1":  1500,
    "gemini_vision_2":  1500,
    "gemini_vision_3":  1500,
    "openrouter":      99999,  # no daily hard limit on free models
    "deepseek":        99999,  # pay-per-use, no daily limit
}

_DISPLAY_NAMES: dict[str, str] = {
    "groq_main":       "Groq · Main",
    "groq_vision":     "Groq · Vision",
    "groq_wa":         "Groq · WhatsApp",
    "gemini_1":        "Gemini Flash · Key 1",
    "gemini_2":        "Gemini Flash · Key 2",
    "gemini_3":        "Gemini Flash · Key 3",
    "gemini_vision_1": "Gemini Vision · Key 1",
    "gemini_vision_2": "Gemini Vision · Key 2",
    "gemini_vision_3": "Gemini Vision · Key 3",
    "openrouter":      "OpenRouter · Fallback",
    "deepseek":        "DeepSeek · Skills",
}

_COLORS: dict[str, str] = {
    "groq_main":       "#f97316",  # orange
    "groq_vision":     "#fb923c",
    "groq_wa":         "#fdba74",
    "gemini_1":        "#3b82f6",  # blue
    "gemini_2":        "#60a5fa",
    "gemini_3":        "#93c5fd",
    "gemini_vision_1": "#8b5cf6",  # purple
    "gemini_vision_2": "#a78bfa",
    "gemini_vision_3": "#c4b5fd",
    "openrouter":      "#10b981",  # green
    "deepseek":        "#06b6d4",  # cyan
}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        with open(_USAGE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Reset if it's a new day
        if data.get("date") != _today_utc():
            return {"date": _today_utc(), "calls": {}}
        return data
    except Exception:
        return {"date": _today_utc(), "calls": {}}


def _save(data: dict):
    try:
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def record(key_name: str, count: int = 1):
    """Increment call count for a key. key_name must match _LIMITS keys."""
    with _lock:
        data = _load()
        calls = data.setdefault("calls", {})
        calls[key_name] = calls.get(key_name, 0) + count
        _save(data)


def get_stats() -> list[dict]:
    """Return usage stats for all tracked keys."""
    with _lock:
        data = _load()
    calls = data.get("calls", {})
    stats = []
    for key, limit in _LIMITS.items():
        used  = calls.get(key, 0)
        pct   = min(100, round(used / limit * 100, 1)) if limit < 99999 else 0
        stats.append({
            "id":      key,
            "name":    _DISPLAY_NAMES.get(key, key),
            "color":   _COLORS.get(key, "#00e5ff"),
            "calls":   used,
            "limit":   limit if limit < 99999 else None,
            "pct":     pct,
            "warning": pct >= 80,
            "capped":  limit >= 99999,
        })
    return stats


def reset_key(key_name: str):
    """Manually reset a key's counter (e.g. after getting new key)."""
    with _lock:
        data = _load()
        data.setdefault("calls", {}).pop(key_name, None)
        _save(data)
