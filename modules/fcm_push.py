"""
modules/fcm_push.py
Push-notification fallback for DND/reminder/handoff alerts when the phone's
WebSocket connection is down (app killed, backend restarted mid-session,
phone briefly offline). Runs *alongside* the existing ws_bridge broadcast,
never replacing it.

Inert until firebase_service_account.json (a real Firebase service-account
key, downloaded from Firebase Console > Project Settings > Service Accounts)
is placed at the repo root — every call degrades to a harmless no-op + one
log line until then.
"""
import os
import json

_SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "firebase_service_account.json")
_TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fcm_tokens.json")

_firebase_app = None
_warned = False


def _get_firebase_app():
    global _firebase_app, _warned
    if _firebase_app is not None:
        return _firebase_app
    if not os.path.exists(_SERVICE_ACCOUNT_FILE):
        if not _warned:
            print("[FCM] firebase_service_account.json not found — push notifications disabled "
                  "(expected until a real Firebase project is configured)")
            _warned = True
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(_SERVICE_ACCOUNT_FILE)
        _firebase_app = firebase_admin.initialize_app(cred)
        return _firebase_app
    except Exception as e:
        print(f"[FCM] Failed to initialize Firebase: {e}")
        return None


def save_token(token: str, device_name: str = ""):
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            tokens = json.load(f)
    except Exception:
        tokens = {}
    tokens[token] = {"device_name": device_name}
    with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def _get_tokens() -> list:
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            return list(json.load(f).keys())
    except Exception:
        return []


def send_push(title: str, body: str, category: str = "system"):
    """Best-effort push to every registered device. Silently no-ops if
    Firebase isn't configured yet or no device has registered a token."""
    app = _get_firebase_app()
    tokens = _get_tokens()
    if not app or not tokens:
        return
    try:
        from firebase_admin import messaging
        for token in tokens:
            try:
                messaging.send(messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={"category": category},
                    token=token,
                ), app=app)
            except Exception as e:
                print(f"[FCM] Send failed for a token: {e}")
    except Exception as e:
        print(f"[FCM] send_push failed: {e}")
