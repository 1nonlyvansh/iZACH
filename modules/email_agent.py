"""
modules/email_agent.py
Email monitoring — OTPs, replies to sent mail, user-configured keyword/sender
watches, and shipment/order tracking. Off by default (email_agent_enabled);
each watch category has its own sub-toggle.

Uses a SEPARATE Gmail OAuth token (token_gmail.json, gmail.readonly scope)
from Calendar's token.json — reusing the same credentials.json Desktop OAuth
client (Gmail API just needs to be enabled on the same Cloud project) but a
distinct token file, so enabling Calendar never forces Gmail re-consent and
vice versa; each feature is opted into independently.

OTP detection and reply/keyword matching are all deterministic (regex/string
match) — no email content is ever sent to an LLM for those. Only shipment
emails (already filtered by a cheap keyword pre-check) go through a one-shot
Groq extraction call, mirroring modules/event_extractor.py's pattern.
"""
import base64
import json
import logging
import os
import re
import threading
import time

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_TOKEN_PATH = "token_gmail.json"
CREDS_PATH = "credentials.json"

_SETTINGS_FILE = "api_keys.json"
_STATE_FILE = "email_agent_state.json"       # {"seen_ids": [...]}
_ORDERS_FILE = "tracked_orders.json"          # list[dict]

_POLL_INTERVAL_SECONDS = 90
_MAX_SEEN_IDS = 500

_speak_func = None
_thread = None
_stop_event = threading.Event()

_reconnect_lock = threading.Lock()
_reconnect_state = {"status": "idle", "error": "", "user": None}

_groq_client = None


def init(speak_fn=None):
    global _speak_func, _groq_client
    _speak_func = speak_fn
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        try:
            from dotenv import dotenv_values
            groq_key = dotenv_values(".env").get("GROQ_API_KEY", "")
        except Exception:
            pass
    if groq_key:
        from groq import Groq
        _groq_client = Groq(api_key=groq_key)


# ── OAuth (mirrors modules/calendar_agent.py's pattern, own token file) ────

def _get_service():
    creds = None
    if os.path.exists(GMAIL_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(GMAIL_TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                logger.warning(f"[EmailAgent] Token refresh failed ({e}). Deleting token — re-run OAuth flow.")
                try:
                    os.remove(GMAIL_TOKEN_PATH)
                except OSError:
                    pass
                raise RuntimeError(
                    "Gmail token revoked. Open iZACH Settings → re-authenticate Email Agent."
                ) from e
        else:
            raise RuntimeError("token_gmail.json missing or invalid. Re-run OAuth flow.")
    return build("gmail", "v1", credentials=creds)


def get_auth_status() -> dict:
    if _reconnect_state["status"] in ("connecting", "waiting_for_browser"):
        return {"connected": False, **_reconnect_state}
    try:
        service = _get_service()
        profile = service.users().getProfile(userId="me").execute()
        return {"connected": True, "status": "connected", "error": "", "user": profile.get("emailAddress")}
    except Exception as e:
        return {"connected": False, "status": "idle", "error": str(e), "user": None}


def _run_reconnect():
    global _reconnect_state
    try:
        _reconnect_state = {"status": "waiting_for_browser", "error": "", "user": None}
        if not os.path.exists(CREDS_PATH):
            raise RuntimeError(f"{CREDS_PATH} not found — download it from Google Cloud Console first.")
        try:
            if os.path.exists(GMAIL_TOKEN_PATH):
                os.remove(GMAIL_TOKEN_PATH)
        except Exception as e:
            logger.warning(f"[EmailAgent] Could not remove old token: {e}")

        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)

        with open(GMAIL_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        user = profile.get("emailAddress")

        _reconnect_state = {"status": "connected", "error": "", "user": user}
        logger.info(f"[EmailAgent] Reconnected as {user}.")
    except Exception as e:
        logger.error(f"[EmailAgent] Reconnect failed: {e}")
        _reconnect_state = {"status": "error", "error": str(e), "user": None}


def start_reconnect() -> dict:
    with _reconnect_lock:
        if _reconnect_state["status"] == "waiting_for_browser":
            return {"ok": False, "error": "A connect attempt is already in progress."}
        threading.Thread(target=_run_reconnect, daemon=True).start()
        return {"ok": True, "status": "waiting_for_browser"}


def disconnect() -> dict:
    global _reconnect_state
    try:
        if os.path.exists(GMAIL_TOKEN_PATH):
            os.remove(GMAIL_TOKEN_PATH)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _reconnect_state = {"status": "idle", "error": "", "user": None}
    logger.info("[EmailAgent] Disconnected.")
    return {"ok": True}


# ── Settings ────────────────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_watchlist() -> list:
    return _load_settings().get("email_watchlist", [])


def set_watchlist(items: list) -> dict:
    try:
        data = _load_settings()
        data["email_watchlist"] = [str(v).strip() for v in items if str(v).strip()]
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Seen-message state (avoid reprocessing the same email every poll) ──────

def _load_seen_ids() -> set:
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("seen_ids", []))
    except Exception:
        return set()


def _save_seen_ids(ids: set):
    try:
        trimmed = list(ids)[-_MAX_SEEN_IDS:]
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_ids": trimmed}, f, indent=2)
    except Exception as e:
        logger.warning(f"[EmailAgent] Failed to save seen-ids: {e}")


# ── Tracked orders store (list[dict], modeled on calendar_agent.py's
# calendar_event_map.json list-of-records convention) ──────────────────────

def _load_orders() -> list:
    try:
        with open(_ORDERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_orders(orders: list):
    with open(_ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)


def get_tracked_orders() -> list:
    return _load_orders()


def _order_key(extracted: dict) -> str:
    tracking = (extracted.get("tracking_number") or "").strip()
    if tracking:
        return f"track:{tracking.lower()}"
    carrier = (extracted.get("carrier") or "").strip().lower()
    desc = (extracted.get("description") or "").strip().lower()[:40]
    return f"desc:{carrier}:{desc}"


def _upsert_order(extracted: dict, msg_id: str):
    orders = _load_orders()
    key = _order_key(extracted)
    now = time.strftime("%Y-%m-%d %H:%M")
    for o in orders:
        if o.get("key") == key:
            o["status"] = extracted.get("status") or o.get("status")
            o["delivery_date"] = extracted.get("delivery_date") or o.get("delivery_date")
            o["carrier"] = extracted.get("carrier") or o.get("carrier")
            o["description"] = extracted.get("description") or o.get("description")
            o["last_msg_id"] = msg_id
            o["updated"] = now
            _save_orders(orders)
            return o
    entry = {
        "key": key,
        "carrier": extracted.get("carrier") or "",
        "description": extracted.get("description") or "",
        "tracking_number": extracted.get("tracking_number") or "",
        "status": extracted.get("status") or "",
        "delivery_date": extracted.get("delivery_date") or "",
        "last_msg_id": msg_id,
        "created": now,
        "updated": now,
    }
    orders.insert(0, entry)
    _save_orders(orders[:200])
    return entry


# ── Message parsing ─────────────────────────────────────────────────────────

def _decode_part(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _walk_parts_for_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        return _decode_part(body["data"])
    for part in payload.get("parts", []) or []:
        text = _walk_parts_for_text(part)
        if text:
            return text
    if mime == "text/html" and body.get("data"):
        html = _decode_part(body["data"])
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _get_message(service, msg_id: str) -> dict:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body_text = _walk_parts_for_text(msg.get("payload", {})) or msg.get("snippet", "")
    return {
        "id": msg_id,
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "in_reply_to": headers.get("in-reply-to", ""),
        "body": body_text,
        "label_ids": msg.get("labelIds", []),
    }


# ── Classification (deterministic — no LLM for these) ──────────────────────

_OTP_PATTERN = re.compile(
    r"(?:\botp\b|verification code|one[- ]time (?:password|code)|security code)\D{0,20}(\d{4,8})",
    re.IGNORECASE,
)
_OTP_FALLBACK = re.compile(r"\b(\d{4,8})\b.{0,40}(?:is your|to verify|otp)", re.IGNORECASE | re.DOTALL)

_SHIPMENT_KEYWORDS = (
    "shipped", "out for delivery", "delivered", "tracking", "your order",
    "order confirmation", "dispatch", "courier", "package", "parcel",
    "amazon", "flipkart", "myntra", "meesho", "fedex", "bluedart", "blue dart",
    "delhivery", "dtdc", "ups", "dhl", "usps", "ecom express", "xpressbees",
)


def _extract_otp(text: str) -> str | None:
    m = _OTP_PATTERN.search(text)
    if m:
        return m.group(1)
    m = _OTP_FALLBACK.search(text)
    if m:
        return m.group(1)
    return None


def _looks_like_shipment(subject: str, sender: str, body: str) -> bool:
    hay = f"{subject} {sender} {body[:500]}".lower()
    return any(k in hay for k in _SHIPMENT_KEYWORDS)


def _extract_order_info(subject: str, sender: str, body: str) -> dict | None:
    if not _groq_client:
        return None
    prompt = f"""You extract shipping/order info from an email for a personal assistant.

From: {sender}
Subject: {subject}
Body (may be truncated): {body[:2000]}

Return ONLY a valid JSON object with these fields:
{{
  "is_shipment_update": true or false,
  "carrier": "delivery brand/carrier name, e.g. Amazon, FedEx, Blue Dart, or null",
  "description": "short description of what's in the order, or null",
  "tracking_number": "tracking/order number if present, or null",
  "status": "ordered|shipped|out_for_delivery|delivered|other",
  "delivery_date": "YYYY-MM-DD if a specific expected/actual delivery date is given, else null",
  "confidence": 0.0 to 1.0
}}

Return ONLY the JSON. No explanation, no markdown, no code blocks."""
    raw = ""
    try:
        resp = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        if not data.get("is_shipment_update") or data.get("confidence", 0) < 0.6:
            return None
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"[EmailAgent] Order JSON parse failed: {e} | raw: {raw[:100]}")
        return None
    except Exception as e:
        logger.error(f"[EmailAgent] Groq order-extraction call failed: {e}")
        return None


def _matches_watchlist(subject: str, sender: str, watchlist: list) -> str | None:
    hay = f"{subject} {sender}".lower()
    for term in watchlist:
        if term.lower() in hay:
            return term
    return None


# ── Delivery ────────────────────────────────────────────────────────────────

def _deliver_otp(code: str, sender: str):
    if _speak_func:
        _speak_func(f"OTP from {sender}: {code}")
    try:
        from modules.fcm_push import send_push
        send_push("🔐 OTP received", f"{code} — from {sender}", category="alerts")
    except Exception:
        pass


def _deliver_passive(title: str, body: str):
    try:
        from modules.notification_system import push
        push(title, category="alerts", body=body)
    except Exception:
        pass


# ── Poll loop ───────────────────────────────────────────────────────────────

def _poll():
    settings = _load_settings()
    if not settings.get("email_agent_enabled", False):
        return

    try:
        service = _get_service()
    except Exception as e:
        logger.debug(f"[EmailAgent] Not connected: {e}")
        return

    watch_otp = settings.get("email_watch_otp", True)
    watch_replies = settings.get("email_watch_replies", True)
    watch_keywords = settings.get("email_watch_keywords", True)
    track_orders = settings.get("email_track_orders", True)
    watchlist = settings.get("email_watchlist", [])

    seen = _load_seen_ids()
    try:
        resp = service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=15).execute()
    except Exception as e:
        logger.warning(f"[EmailAgent] Message list failed: {e}")
        return

    for ref in resp.get("messages", []):
        msg_id = ref["id"]
        if msg_id in seen:
            continue
        seen.add(msg_id)
        try:
            msg = _get_message(service, msg_id)
        except Exception as e:
            logger.debug(f"[EmailAgent] Fetch failed for {msg_id}: {e}")
            continue

        subject, sender, body = msg["subject"], msg["from"], msg["body"]

        if watch_otp:
            code = _extract_otp(f"{subject}\n{body}")
            if code:
                _deliver_otp(code, sender)
                continue  # an OTP email is never also a shipment/keyword match worth double-handling

        if watch_replies and msg.get("in_reply_to"):
            _deliver_passive("Reply received", f'{sender}: "{subject}"')

        if watch_keywords and watchlist:
            hit = _matches_watchlist(subject, sender, watchlist)
            if hit:
                _deliver_passive(f'Email matched "{hit}"', f'{sender}: "{subject}"')

        if track_orders and _looks_like_shipment(subject, sender, body):
            extracted = _extract_order_info(subject, sender, body)
            if extracted:
                entry = _upsert_order(extracted, msg_id)
                _deliver_passive(
                    f"Order update: {entry['carrier'] or 'Package'}",
                    f"{entry['description'] or subject} — {entry['status'] or 'update'}"
                    + (f", ETA {entry['delivery_date']}" if entry.get("delivery_date") else ""),
                )

    _save_seen_ids(seen)


def _loop():
    while not _stop_event.is_set():
        try:
            _poll()
        except Exception as e:
            logger.warning(f"[EmailAgent] Poll error: {e}")
        _stop_event.wait(_POLL_INTERVAL_SECONDS)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    logger.info("[EmailAgent] Started (off unless email_agent_enabled is set).")


def stop():
    _stop_event.set()
