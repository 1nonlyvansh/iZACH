"""
modules/fitness_engine.py
Google Fit REST API integration for iZACH — Phase 3.

Features:
- OAuth2 flow via google-auth-oauthlib (copy-paste code, no local server)
- Steps, calories, active minutes, workout sessions for today
- Token auto-refresh stored in fitness_token.json
- REST surface: /fitness/summary, /fitness/auth/start, /fitness/auth/complete, /fitness/status
- Requires: pip install google-auth google-auth-oauthlib requests
- Credentials: download fitness_credentials.json from Google Cloud Console
  (Enable "Fitness API", create OAuth2 Desktop client, download JSON)
"""

import os
import time
import logging
from datetime import datetime

logger = logging.getLogger("iZACH.FitnessEngine")

_BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
_TOKEN_FILE = os.path.join(_BASE_DIR, "fitness_token.json")
_CREDS_FILE = os.path.join(_BASE_DIR, "fitness_credentials.json")

_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
]

_FIT_AGGREGATE_URL = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
_FIT_SESSIONS_URL  = "https://www.googleapis.com/fitness/v1/users/me/sessions"

_ACTIVITY_NAMES = {
    1: "Biking", 4: "Gym workout", 7: "Walking", 8: "Running",
    9: "Running on treadmill", 10: "Skiing", 17: "Basketball",
    20: "Football", 23: "Gymnastics", 26: "Jumping rope",
    28: "Martial arts", 31: "Pilates", 37: "Rock climbing",
    39: "Soccer", 44: "Swimming", 45: "Yoga", 80: "Sleep",
    93: "Strength training", 97: "Elliptical", 98: "Other",
}

_creds       = None
_auth_state  = {"status": "not_connected", "error": ""}


# =============================================================================
# Token management
# =============================================================================

def _save_token(creds):
    try:
        with open(_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    except Exception as e:
        logger.error(f"[FITNESS] Save token: {e}")


def _get_credentials():
    """Load / refresh OAuth2 creds. Returns None if not authorized."""
    global _creds, _auth_state
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if _creds and _creds.valid:
            return _creds

        if os.path.exists(_TOKEN_FILE):
            _creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)
            if _creds and _creds.expired and _creds.refresh_token:
                _creds.refresh(Request())
                _save_token(_creds)
            if _creds and _creds.valid:
                _auth_state["status"] = "connected"
                return _creds

        _auth_state["status"] = "not_connected"
        return None
    except ImportError:
        _auth_state["status"] = "missing_deps"
        _auth_state["error"] = "Run: pip install google-auth google-auth-oauthlib"
        return None
    except Exception as e:
        _auth_state["status"] = "error"
        _auth_state["error"] = str(e)
        logger.error(f"[FITNESS] Creds error: {e}")
        return None


# =============================================================================
# Data helpers
# =============================================================================

def _today_ms() -> tuple[int, int]:
    """(start_of_local_day_ms, now_ms) — uses LOCAL timezone so user in IST/etc
    doesn't lose morning data to UTC midnight boundary."""
    now_local = datetime.now()  # naive local
    start     = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int(now_local.timestamp() * 1000)


def _aggregate(creds, data_type: str) -> float:
    try:
        import requests as _req
        start_ms, end_ms = _today_ms()
        body = {
            "aggregateBy": [{"dataTypeName": data_type}],
            "bucketByTime": {"durationMillis": max(end_ms - start_ms, 1)},
            "startTimeMillis": start_ms,
            "endTimeMillis":   end_ms,
        }
        headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
        r = _req.post(_FIT_AGGREGATE_URL, json=body, headers=headers, timeout=10)
        if r.status_code != 200:
            logger.warning(f"[FITNESS] {data_type} → HTTP {r.status_code}: {r.text[:200]}")
            return 0.0
        total = 0.0
        for bucket in r.json().get("bucket", []):
            for ds in bucket.get("dataset", []):
                for pt in ds.get("point", []):
                    for v in pt.get("value", []):
                        total += v.get("intVal", 0) or v.get("fpVal", 0.0)
        return total
    except Exception as e:
        logger.debug(f"[FITNESS] Aggregate {data_type}: {e}")
        return 0.0


# =============================================================================
# Public API
# =============================================================================

def get_steps_today() -> int:
    c = _get_credentials()
    return int(_aggregate(c, "com.google.step_count.delta")) if c else 0


def get_calories_today() -> float:
    c = _get_credentials()
    return round(_aggregate(c, "com.google.calories.expended"), 1) if c else 0.0


def get_active_minutes_today() -> int:
    c = _get_credentials()
    return int(_aggregate(c, "com.google.active_minutes")) if c else 0


def get_workout_sessions(days_back: int = 7, limit: int = 5) -> list[dict]:
    c = _get_credentials()
    if not c:
        return []
    try:
        import requests as _req
        end_ms   = int(time.time() * 1000)
        start_ms = end_ms - (days_back * 86_400_000)
        headers  = {"Authorization": f"Bearer {c.token}"}
        params   = {
            "startTime": f"{start_ms}000000",
            "endTime":   f"{end_ms}000000",
        }
        r = _req.get(_FIT_SESSIONS_URL, headers=headers, params=params, timeout=10)
        if r.status_code != 200:
            return []
        sessions = []
        for s in r.json().get("session", [])[:limit]:
            s_ms   = int(s.get("startTimeMillis", 0))
            e_ms   = int(s.get("endTimeMillis",   0))
            dur    = max(0, (e_ms - s_ms) // 60_000)
            atype  = s.get("activityType", 98)
            sessions.append({
                "name":         s.get("name", "Workout"),
                "activity":     _ACTIVITY_NAMES.get(atype, f"Activity {atype}"),
                "duration_min": dur,
                "date":         datetime.fromtimestamp(s_ms / 1000).strftime("%b %d"),
                "calories":     0,  # would need separate aggregate per session
            })
        return sessions
    except Exception as e:
        logger.debug(f"[FITNESS] Sessions: {e}")
        return []


def get_summary() -> dict:
    """All today's metrics in one call (3 parallel aggregates if possible)."""
    c = _get_credentials()
    if not c:
        return {
            "connected": False,
            "status":    _auth_state.get("status", "not_connected"),
            "error":     _auth_state.get("error", ""),
            "steps": 0, "calories": 0.0, "active_minutes": 0, "sessions": [],
        }
    return {
        "connected":      True,
        "status":         "connected",
        "date":           datetime.now().strftime("%b %d, %Y"),
        "steps":          get_steps_today(),
        "calories":       get_calories_today(),
        "active_minutes": get_active_minutes_today(),
        "sessions":       get_workout_sessions(),
    }


# =============================================================================
# OAuth2 flow
# =============================================================================

def start_auth_flow() -> dict:
    """
    Kicks off the OAuth flow in a background thread and opens the user's
    browser to Google's consent screen. Was previously a copy-paste-code
    flow using redirect_uri="urn:ietf:wg:oauth:2.0:oob" — Google removed
    that special value in 2022 (the consent screen refuses to render at
    all for it now), which made this integration completely unusable
    regardless of OS. Rewritten to match the already-working run_local_server()
    pattern used by modules/email_agent.py and modules/calendar_agent.py in
    this same codebase: no code to copy, /fitness/auth/status is polled
    until it flips to "connected".
    """
    global _auth_state
    if not os.path.exists(_CREDS_FILE):
        return {
            "error": (
                "fitness_credentials.json not found. "
                "Go to Google Cloud Console → Fitness API → Credentials → "
                "Create OAuth2 Desktop client → Download JSON → save as fitness_credentials.json"
            )
        }
    if _auth_state.get("status") == "waiting_for_browser":
        return {"error": "A connect attempt is already in progress."}
    import threading
    threading.Thread(target=_run_auth_flow, daemon=True).start()
    return {"status": "waiting_for_browser"}


def _run_auth_flow():
    global _creds, _auth_state
    try:
        _auth_state = {"status": "waiting_for_browser", "error": ""}
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(_CREDS_FILE, _SCOPES)
        creds = flow.run_local_server(port=0)
        _creds = creds
        _save_token(_creds)
        _auth_state = {"status": "connected", "error": ""}
        logger.info("[FITNESS] Google Fit connected!")
    except ImportError:
        _auth_state = {"status": "error", "error": "Run: pip install google-auth-oauthlib"}
    except Exception as e:
        _auth_state = {"status": "error", "error": str(e)}
        logger.error(f"[FITNESS] Auth flow failed: {e}")


def get_auth_status() -> dict:
    c = _get_credentials()
    return {
        "status":      "connected" if (c and c.valid) else _auth_state.get("status", "not_connected"),
        "token_valid": bool(c and c.valid),
        "error":       _auth_state.get("error", ""),
    }


def disconnect() -> dict:
    """Remove saved token."""
    global _creds, _auth_state
    _creds = None
    _auth_state = {"status": "not_connected", "error": ""}
    try:
        if os.path.exists(_TOKEN_FILE):
            os.remove(_TOKEN_FILE)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Init
# =============================================================================

def init():
    _get_credentials()
    logger.info(f"[FITNESS] Engine ready. Status: {_auth_state['status']}")


try:
    init()
except Exception:
    pass
