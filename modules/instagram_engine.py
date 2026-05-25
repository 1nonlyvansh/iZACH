"""
modules/instagram_engine.py  —  iZACH Phase 5B
Instagram Graph API integration.

Requirements:
    pip install requests

Setup (one-time):
    1. Create Facebook App at developers.facebook.com
       Type: Business → add "Instagram Graph API" product
    2. In App settings → Permissions: add all 5 scopes below
    3. Link Instagram Business/Creator account to a Facebook Page
    4. Run OAuth flow (use /instagram/auth/start endpoint)
    5. Paste the redirect URL back into /instagram/auth/complete

Scopes used:
    instagram_basic                — profile, media
    instagram_manage_messages      — read/send DMs
    instagram_content_publish      — post photos/reels/videos
    instagram_manage_insights      — account + media analytics
    instagram_manage_comments      — read/reply comments
    pages_show_list                — enumerate FB pages
    pages_read_engagement          — required alongside messaging

Rate-limit budgets (enforced internally):
    200 API calls / hour   (basic limit per token)
    50  posts / 24 hours   (25 reels max)
    DM replies: only within 24-h window of user's original message

Anti-ban measures:
    • Random 2–12s delay before every DM reply
    • Skip DMs older than 23 hours (outside safe window)
    • Dedup: never reply to same message_id twice
    • Auto-reply runs only when enabled in settings
    • Per-hour call budget tracked; pause if budget low
"""

import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("iZACH.Instagram")

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────

_BASE_DIR   = os.path.dirname(os.path.dirname(__file__))
_SETTINGS   = os.path.join(_BASE_DIR, "instagram_settings.json")
_GRAPH_BASE = "https://graph.instagram.com/v21.0"  # Instagram-specific endpoint

_SCOPES = (
    "instagram_basic,"
    "instagram_manage_messages,"
    "instagram_content_publish,"
    "instagram_manage_insights,"
    "instagram_manage_comments,"
    "pages_show_list,"
    "pages_read_engagement"
)

_DEFAULT_SETTINGS = {
    "app_id":             "",
    "app_secret":         "",
    "access_token":       "",
    "token_expiry":       0,          # unix timestamp
    "ig_user_id":         "",
    "username":           "",
    "auto_reply_enabled": False,
    "auto_reply_persona": (
        "You are managing iZACH's Instagram account. "
        "Reply to DMs in a friendly, genuine, casual tone. "
        "Keep replies to 1–2 sentences. Never reveal you are an AI. "
        "Match the energy of the person's message."
    ),
    "reply_delay_min":    3,
    "reply_delay_max":    12,
    "daily_post_limit":   50,
    "follower_baseline":  0,
    "follower_last_check": 0,
}

# ──────────────────────────────────────────────────────────────
# In-memory state
# ──────────────────────────────────────────────────────────────

_auth_state:   dict     = {"status": "not_connected", "error": ""}
_rate_tracker: dict     = {"calls": 0, "window_start": 0.0}   # 200 calls / hour
_reply_dedup:  set      = set()   # replied message IDs (this session)
_posts_today:  dict     = {"count": 0, "reset_date": ""}       # daily post counter
_speak_fn      = None
_ai_fn         = None
_running        = False
_dm_thread      = None

_RATE_LIMIT     = 180   # stay under 200; leave buffer
_RATE_WINDOW    = 3600  # 1 hour in seconds


# ──────────────────────────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        with open(_SETTINGS) as f:
            data = json.load(f)
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def _save_settings(cfg: dict):
    try:
        with open(_SETTINGS, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"[IG] Save settings: {e}")


def get_settings() -> dict:
    """Public: return settings (safe — no secrets stripped)."""
    cfg = _load_settings()
    safe = dict(cfg)
    # Mask app_secret in public response
    if safe.get("app_secret"):
        safe["app_secret"] = "••••••" + safe["app_secret"][-4:]
    return safe


def update_settings(patch: dict) -> dict:
    cfg = _load_settings()
    # Don't overwrite secret with masked value
    if patch.get("app_secret", "").startswith("••••"):
        patch.pop("app_secret")
    cfg.update(patch)
    _save_settings(cfg)
    return {"ok": True}


# ──────────────────────────────────────────────────────────────
# Rate limiter
# ──────────────────────────────────────────────────────────────

def _rate_check() -> bool:
    """Return True if call is allowed; updates counter."""
    now = time.time()
    if now - _rate_tracker["window_start"] > _RATE_WINDOW:
        _rate_tracker["calls"]        = 0
        _rate_tracker["window_start"] = now
    if _rate_tracker["calls"] >= _RATE_LIMIT:
        logger.warning("[IG] Rate limit reached — pausing.")
        return False
    _rate_tracker["calls"] += 1
    return True


def rate_status() -> dict:
    remaining = max(0, _RATE_LIMIT - _rate_tracker["calls"])
    reset_in  = max(0, int(_RATE_WINDOW - (time.time() - _rate_tracker["window_start"])))
    return {"calls_used": _rate_tracker["calls"], "remaining": remaining, "reset_in_sec": reset_in}


# ──────────────────────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────────────────────

def _get_token() -> Optional[str]:
    cfg = _load_settings()
    tok = cfg.get("access_token", "")
    if not tok:
        _auth_state.update({"status": "not_connected", "error": "No access token"})
        return None
    # Check expiry (7-day warning; tokens last 60 days)
    expiry = cfg.get("token_expiry", 0)
    if expiry and time.time() > expiry:
        _auth_state.update({"status": "token_expired", "error": "Access token expired — re-authenticate."})
        if _speak_fn:
            _speak_fn("iZACH Instagram token expired. Please re-authenticate from the Instagram widget.")
        return None
    if expiry and time.time() > expiry - 7 * 86400:
        logger.warning("[IG] Token expires in < 7 days — consider refreshing.")
    _auth_state["status"] = "connected"
    return tok


def _api_get(path: str, params: dict = None) -> Optional[dict]:
    token = _get_token()
    if not token or not _rate_check():
        return None
    p = {"access_token": token}
    if params:
        p.update(params)
    try:
        r = requests.get(f"{_GRAPH_BASE}/{path}", params=p, timeout=12)
        data = r.json()
        if "error" in data:
            logger.error(f"[IG] GET {path}: {data['error'].get('message')}")
            return None
        return data
    except Exception as e:
        logger.error(f"[IG] GET {path}: {e}")
        return None


def _api_post(path: str, payload: dict = None, files=None) -> Optional[dict]:
    token = _get_token()
    if not token or not _rate_check():
        return None
    params = {"access_token": token}
    try:
        if files:
            r = requests.post(f"{_GRAPH_BASE}/{path}", params=params, data=payload or {}, files=files, timeout=30)
        else:
            r = requests.post(f"{_GRAPH_BASE}/{path}", params=params, json=payload or {}, timeout=20)
        data = r.json()
        if "error" in data:
            logger.error(f"[IG] POST {path}: {data['error'].get('message')}")
            return None
        return data
    except Exception as e:
        logger.error(f"[IG] POST {path}: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# OAuth 2.0 Flow
# ──────────────────────────────────────────────────────────────

_REDIRECT_URI = "https://www.facebook.com/connect/login_success.html"


def start_auth_flow() -> dict:
    """Return OAuth URL for user to open in browser."""
    cfg = _load_settings()
    app_id = cfg.get("app_id", "")
    if not app_id:
        return {"error": "app_id not configured in instagram settings."}

    url = (
        f"https://www.facebook.com/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={_REDIRECT_URI}"
        f"&scope={_SCOPES}"
        f"&response_type=code"
    )
    _auth_state["status"] = "awaiting_code"
    return {"auth_url": url, "redirect_uri": _REDIRECT_URI}


def complete_auth(code: str) -> dict:
    """
    Exchange authorization code for short-lived token,
    then extend to long-lived (60-day) token.
    Fetch IG user ID and store everything.
    """
    cfg = _load_settings()
    app_id     = cfg.get("app_id", "")
    app_secret = cfg.get("app_secret", "")
    if not app_id or not app_secret:
        return {"error": "app_id and app_secret required."}

    try:
        # Step 1: exchange code → short-lived token
        r1 = requests.get(
            "https://graph.facebook.com/v21.0/oauth/access_token",
            params={
                "client_id":     app_id,
                "redirect_uri":  _REDIRECT_URI,
                "client_secret": app_secret,
                "code":          code.strip(),
            },
            timeout=15,
        )
        d1 = r1.json()
        if "error" in d1:
            return {"error": d1["error"].get("message", "Code exchange failed.")}
        short_token = d1.get("access_token", "")

        # Step 2: exchange short-lived → long-lived (60 days)
        r2 = requests.get(
            "https://graph.facebook.com/v21.0/oauth/access_token",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         app_id,
                "client_secret":     app_secret,
                "fb_exchange_token": short_token,
            },
            timeout=15,
        )
        d2 = r2.json()
        long_token  = d2.get("access_token", short_token)
        expires_in  = int(d2.get("expires_in", 5183944))  # ~60 days in seconds
        expiry_ts   = int(time.time()) + expires_in

        # Step 3: get IG user ID
        r3 = requests.get(
            f"{_GRAPH_BASE}/me",
            params={
                "access_token": long_token,
                "fields": "id,username,name,followers_count,follows_count,media_count",
            },
            timeout=10,
        )
        d3 = r3.json()
        if "error" in d3:
            return {"error": d3["error"].get("message", "Failed to fetch user info.")}

        ig_user_id  = d3.get("id", "")
        username    = d3.get("username", "")
        followers   = int(d3.get("followers_count", 0))

        cfg.update({
            "access_token":       long_token,
            "token_expiry":       expiry_ts,
            "ig_user_id":         ig_user_id,
            "username":           username,
            "follower_baseline":  followers,
            "follower_last_check": int(time.time()),
        })
        _save_settings(cfg)
        _auth_state["status"] = "connected"
        logger.info(f"[IG] Authenticated as @{username} (ID: {ig_user_id})")

        # Start background services if not running
        _ensure_bg_services()

        return {
            "ok":        True,
            "username":  username,
            "ig_user_id": ig_user_id,
            "expires_in_days": expires_in // 86400,
            "followers": followers,
        }

    except Exception as e:
        logger.error(f"[IG] complete_auth: {e}")
        return {"error": str(e)}


def disconnect() -> dict:
    cfg = _load_settings()
    cfg.update({"access_token": "", "token_expiry": 0, "ig_user_id": ""})
    _save_settings(cfg)
    _auth_state.update({"status": "not_connected", "error": ""})
    global _running
    _running = False
    return {"ok": True}


def auth_status() -> dict:
    cfg = _load_settings()
    tok = cfg.get("access_token", "")
    exp = cfg.get("token_expiry", 0)
    days_left = max(0, int((exp - time.time()) / 86400)) if exp else 0
    return {
        "status":     _auth_state["status"],
        "error":      _auth_state.get("error", ""),
        "username":   cfg.get("username", ""),
        "ig_user_id": cfg.get("ig_user_id", ""),
        "connected":  bool(tok) and _auth_state["status"] == "connected",
        "token_days_left": days_left,
        "auto_reply_enabled": cfg.get("auto_reply_enabled", False),
    }


# ──────────────────────────────────────────────────────────────
# Profile & Insights
# ──────────────────────────────────────────────────────────────

def get_profile() -> dict:
    cfg  = _load_settings()
    uid  = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}
    data = _api_get(uid, {
        "fields": "id,username,biography,followers_count,follows_count,media_count,profile_picture_url,website"
    })
    if not data:
        return {"error": "Failed to fetch profile."}

    # Follower change detection
    baseline = cfg.get("follower_baseline", 0)
    current  = int(data.get("followers_count", 0))
    delta    = current - baseline
    if abs(delta) >= 1:
        cfg["follower_baseline"]  = current
        cfg["follower_last_check"] = int(time.time())
        _save_settings(cfg)
        if _speak_fn and abs(delta) >= 5:
            direction = "gained" if delta > 0 else "lost"
            _speak_fn(f"iZACH Instagram has {direction} {abs(delta)} followers. Now at {current}.")

    return {**data, "follower_delta": delta}


def get_insights() -> dict:
    """Account-level insights: reach, impressions, follower activity."""
    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    data = _api_get(f"{uid}/insights", {
        "metric": "impressions,reach,profile_views,follower_count",
        "period": "day",
    })
    if not data:
        return {"error": "Insights unavailable — ensure instagram_manage_insights permission."}
    return data


# ──────────────────────────────────────────────────────────────
# Media / Posts
# ──────────────────────────────────────────────────────────────

def get_recent_posts(limit: int = 12) -> dict:
    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    data = _api_get(f"{uid}/media", {
        "fields": "id,caption,media_type,media_url,thumbnail_url,timestamp,like_count,comments_count,permalink",
        "limit": limit,
    })
    return data or {"error": "Failed to fetch posts."}


def get_post_insights(media_id: str) -> dict:
    data = _api_get(f"{media_id}/insights", {
        "metric": "impressions,reach,engagement,saved,video_views"
    })
    return data or {"error": "Insights unavailable."}


def generate_caption(context: str, style: str = "casual", hashtag_count: int = 10) -> str:
    """AI-generate an Instagram caption from context/description."""
    if not _ai_fn:
        return ""
    prompt = (
        f"Write an Instagram caption for this post:\n\n"
        f"Context: {context}\n\n"
        f"Style: {style} (options: casual, professional, funny, inspirational, minimal)\n"
        f"Requirements:\n"
        f"- 1–3 sentences max for the main caption\n"
        f"- Add exactly {hashtag_count} relevant hashtags at the end\n"
        f"- No quotation marks around the output\n"
        f"- Sound genuine and human — not like marketing copy\n\n"
        f"Output only the caption text with hashtags. Nothing else."
    )
    try:
        return _ai_fn(prompt).strip()
    except Exception as e:
        logger.error(f"[IG] Caption gen: {e}")
        return ""


def _check_post_limit() -> bool:
    """Returns True if under daily post limit."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _posts_today["reset_date"] != today:
        _posts_today["count"]      = 0
        _posts_today["reset_date"] = today
    cfg = _load_settings()
    limit = cfg.get("daily_post_limit", 50)
    if _posts_today["count"] >= limit:
        logger.warning(f"[IG] Daily post limit ({limit}) reached.")
        return False
    return True


def post_photo(image_url: str, caption: str = "") -> dict:
    """
    Publish a single photo post.
    image_url must be a publicly accessible URL.
    """
    if not _check_post_limit():
        return {"error": f"Daily post limit reached ({_load_settings().get('daily_post_limit', 50)} posts/day)."}

    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    # Step 1: create container
    container = _api_post(f"{uid}/media", {
        "image_url": image_url,
        "caption":   caption,
    })
    if not container or "id" not in container:
        return {"error": "Failed to create media container."}

    container_id = container["id"]
    time.sleep(2)  # brief pause before publish

    # Step 2: publish
    result = _api_post(f"{uid}/media_publish", {"creation_id": container_id})
    if not result:
        return {"error": "Failed to publish photo."}

    _posts_today["count"] += 1
    logger.info(f"[IG] Photo published: {result.get('id')}")
    return {"ok": True, "media_id": result.get("id")}


def post_reel(video_url: str, caption: str = "", cover_url: str = "", share_to_feed: bool = True) -> dict:
    """
    Publish a Reel.
    video_url must be publicly accessible. MP4, max 15 min, 4GB.
    """
    if not _check_post_limit():
        return {"error": "Daily post limit reached."}

    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    payload: dict = {
        "media_type":    "REELS",
        "video_url":     video_url,
        "caption":       caption,
        "share_to_feed": share_to_feed,
    }
    if cover_url:
        payload["cover_url"] = cover_url

    # Step 1: create container
    container = _api_post(f"{uid}/media", payload)
    if not container or "id" not in container:
        return {"error": "Failed to create reel container."}

    container_id = container["id"]

    # Step 2: poll until container is FINISHED (video processing)
    max_wait = 120  # seconds
    waited   = 0
    while waited < max_wait:
        status_data = _api_get(container_id, {"fields": "status_code"})
        status      = (status_data or {}).get("status_code", "")
        if status == "FINISHED":
            break
        if status == "ERROR":
            return {"error": "Video processing failed."}
        time.sleep(8)
        waited += 8
    else:
        return {"error": "Video processing timed out."}

    # Step 3: publish
    result = _api_post(f"{uid}/media_publish", {"creation_id": container_id})
    if not result:
        return {"error": "Failed to publish reel."}

    _posts_today["count"] += 1
    logger.info(f"[IG] Reel published: {result.get('id')}")
    return {"ok": True, "media_id": result.get("id")}


def post_video(video_url: str, caption: str = "", thumb_offset_ms: int = 0) -> dict:
    """Publish a regular video (not reel) to feed."""
    if not _check_post_limit():
        return {"error": "Daily post limit reached."}

    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    payload = {
        "media_type":      "VIDEO",
        "video_url":       video_url,
        "caption":         caption,
        "thumb_offset":    thumb_offset_ms,
    }
    container = _api_post(f"{uid}/media", payload)
    if not container or "id" not in container:
        return {"error": "Failed to create video container."}

    container_id = container["id"]
    for _ in range(15):
        sd = _api_get(container_id, {"fields": "status_code"})
        if (sd or {}).get("status_code") == "FINISHED":
            break
        time.sleep(8)

    result = _api_post(f"{uid}/media_publish", {"creation_id": container_id})
    if not result:
        return {"error": "Failed to publish video."}

    _posts_today["count"] += 1
    return {"ok": True, "media_id": result.get("id")}


# ──────────────────────────────────────────────────────────────
# DM Inbox (Instagram Messaging API)
# ──────────────────────────────────────────────────────────────

def get_inbox(limit: int = 20) -> dict:
    """Fetch DM conversations (threads)."""
    cfg = _load_settings()
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return {"error": "Not connected."}

    data = _api_get(f"{uid}/conversations", {
        "platform": "instagram",
        "fields":   "id,updated_time,participants,messages{id,message,from,created_time}",
        "limit":    limit,
    })
    return data or {"error": "Failed to fetch inbox. Ensure instagram_manage_messages permission."}


def get_thread_messages(thread_id: str, limit: int = 20) -> dict:
    """Fetch messages for a specific conversation thread."""
    data = _api_get(f"{thread_id}/messages", {
        "fields": "id,message,from,created_time,attachments",
        "limit":  limit,
    })
    return data or {"error": "Failed to fetch thread."}


def send_dm(thread_id: str, message: str) -> dict:
    """
    Reply to a conversation thread.
    Only works within 24h of user's last message (Instagram policy).
    """
    if not message.strip():
        return {"error": "Empty message."}

    result = _api_post(f"{thread_id}/messages", {"message": message})
    if not result:
        return {"error": "Send failed — check instagram_manage_messages scope."}

    logger.info(f"[IG] DM sent to thread {thread_id}")
    return {"ok": True, "message_id": result.get("id")}


def _is_within_24h(iso_timestamp: str) -> bool:
    """Check if a timestamp is within the 24-hour DM reply window."""
    try:
        dt  = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age < 23 * 3600   # 23h safety margin
    except Exception:
        return False


def _generate_dm_reply(incoming_message: str, sender_name: str) -> str:
    """Generate AI reply for a DM."""
    if not _ai_fn:
        return ""
    cfg    = _load_settings()
    persona = cfg.get("auto_reply_persona", _DEFAULT_SETTINGS["auto_reply_persona"])
    prompt = (
        f"{persona}\n\n"
        f"Someone named {sender_name} sent this DM:\n"
        f"\"{incoming_message}\"\n\n"
        f"Write a reply. Output only the reply text, nothing else."
    )
    try:
        reply = _ai_fn(prompt).strip()
        # Safety: strip any AI meta-commentary that leaked through
        reply = re.sub(r'^(reply|response|answer):?\s*', '', reply, flags=re.I).strip()
        return reply
    except Exception as e:
        logger.error(f"[IG] DM reply gen: {e}")
        return ""


# ──────────────────────────────────────────────────────────────
# Comments
# ──────────────────────────────────────────────────────────────

def get_comments(media_id: str, limit: int = 20) -> dict:
    data = _api_get(f"{media_id}/comments", {
        "fields": "id,text,username,timestamp,replies{id,text,username,timestamp}",
        "limit":  limit,
    })
    return data or {"error": "Failed to fetch comments."}


def reply_to_comment(comment_id: str, message: str) -> dict:
    result = _api_post(f"{comment_id}/replies", {"message": message})
    if not result:
        return {"error": "Reply failed."}
    return {"ok": True, "reply_id": result.get("id")}


def hide_comment(comment_id: str, hide: bool = True) -> dict:
    result = _api_post(comment_id, {"hide": hide})
    return result or {"error": "Failed."}


# ──────────────────────────────────────────────────────────────
# Follower tracker
# ──────────────────────────────────────────────────────────────

def check_follower_change() -> dict:
    """Compare current followers to baseline. Returns delta + new counts."""
    cfg      = _load_settings()
    uid      = cfg.get("ig_user_id", "")
    baseline = int(cfg.get("follower_baseline", 0))
    if not uid:
        return {"error": "Not connected."}

    data = _api_get(uid, {"fields": "followers_count,follows_count"})
    if not data:
        return {"error": "API error."}

    current   = int(data.get("followers_count", 0))
    following = int(data.get("follows_count", 0))
    delta     = current - baseline

    cfg["follower_baseline"]   = current
    cfg["follower_last_check"] = int(time.time())
    _save_settings(cfg)

    return {
        "followers":  current,
        "following":  following,
        "delta":      delta,
        "baseline":   baseline,
        "checked_at": int(time.time()),
    }


# ──────────────────────────────────────────────────────────────
# Voice command dispatcher
# ──────────────────────────────────────────────────────────────

def execute_voice_command(cmd: str) -> dict:
    cmd = cmd.lower()

    if any(w in cmd for w in ["how many followers", "follower count", "my followers", "instagram followers"]):
        data = get_profile()
        if "error" in data:
            return {"success": False, "message": data["error"]}
        followers = data.get("followers_count", 0)
        following = data.get("follows_count", 0)
        delta     = data.get("follower_delta", 0)
        delta_str = f" ({'+' if delta>=0 else ''}{delta} since last check)" if delta else ""
        return {"success": True, "message": f"iZACH Instagram has {followers} followers, following {following}.{delta_str}"}

    if "check instagram" in cmd or "instagram status" in cmd:
        status = auth_status()
        if status["connected"]:
            return {"success": True, "message": f"Instagram connected as @{status['username']}. Token valid for {status['token_days_left']} more days."}
        return {"success": False, "message": "Instagram not connected."}

    if "enable auto reply" in cmd or "turn on auto reply" in cmd or "start auto reply" in cmd:
        cfg = _load_settings()
        cfg["auto_reply_enabled"] = True
        _save_settings(cfg)
        _ensure_bg_services()
        return {"success": True, "message": "Instagram DM auto-reply enabled."}

    if "disable auto reply" in cmd or "turn off auto reply" in cmd or "stop auto reply" in cmd:
        cfg = _load_settings()
        cfg["auto_reply_enabled"] = False
        _save_settings(cfg)
        return {"success": True, "message": "Instagram DM auto-reply disabled."}

    if "instagram messages" in cmd or "instagram inbox" in cmd or "check dms" in cmd:
        inbox = get_inbox(limit=5)
        if "error" in inbox:
            return {"success": False, "message": inbox["error"]}
        threads = inbox.get("data", [])
        if not threads:
            return {"success": True, "message": "Instagram inbox is empty."}
        return {"success": True, "message": f"You have {len(threads)} recent DM conversations on Instagram."}

    if "instagram post" in cmd or "post to instagram" in cmd:
        return {"success": True, "message": "Use the Instagram widget to create a post with image URL and caption."}

    return {"success": False, "message": "Command not recognized for Instagram."}


# ──────────────────────────────────────────────────────────────
# Background services
# ──────────────────────────────────────────────────────────────

def init(speak_fn=None, ai_fn=None):
    global _speak_fn, _ai_fn
    _speak_fn = speak_fn
    _ai_fn    = ai_fn
    # Load token and set auth state
    _get_token()
    _ensure_bg_services()


def _ensure_bg_services():
    global _running, _dm_thread
    cfg = _load_settings()
    if not cfg.get("ig_user_id") or not cfg.get("access_token"):
        return
    if _running:
        return
    _running = True
    _dm_thread = threading.Thread(target=_dm_poll_loop, daemon=True, name="IG_DMPoll")
    _dm_thread.start()
    logger.info("[IG] Background DM poller started.")


_DM_POLL_INTERVAL = 90   # seconds between inbox checks

def _dm_poll_loop():
    """Background thread: poll inbox, auto-reply to new messages."""
    time.sleep(15)  # initial delay after startup
    while _running:
        try:
            cfg = _load_settings()
            if not cfg.get("auto_reply_enabled"):
                time.sleep(_DM_POLL_INTERVAL)
                continue

            token = _get_token()
            if not token:
                time.sleep(_DM_POLL_INTERVAL)
                continue

            _auto_reply_pass(cfg)

        except Exception as e:
            logger.error(f"[IG] DM poll error: {e}")

        time.sleep(_DM_POLL_INTERVAL)


def _auto_reply_pass(cfg: dict):
    """One pass: fetch inbox, reply to new messages within 24h."""
    uid = cfg.get("ig_user_id", "")
    if not uid:
        return

    inbox = get_inbox(limit=10)
    threads = inbox.get("data", [])
    if not threads:
        return

    delay_min = int(cfg.get("reply_delay_min", 3))
    delay_max = int(cfg.get("reply_delay_max", 12))

    for thread in threads:
        messages  = thread.get("messages", {}).get("data", [])
        if not messages:
            continue

        # Sort: oldest first
        messages.sort(key=lambda m: m.get("created_time", ""))
        last_msg  = messages[-1]
        msg_id    = last_msg.get("id", "")
        msg_text  = last_msg.get("message", "").strip()
        msg_from  = last_msg.get("from", {})
        sender_id = msg_from.get("id", "")
        sender_nm = msg_from.get("name", "User")
        created   = last_msg.get("created_time", "")

        # Skip if: already replied, our own message, outside 24h window, empty
        if msg_id in _reply_dedup:
            continue
        if sender_id == uid:
            continue
        if not msg_text:
            continue
        if not _is_within_24h(created):
            continue

        # Generate reply
        reply_text = _generate_dm_reply(msg_text, sender_nm)
        if not reply_text:
            continue

        # Human-like delay
        delay = random.uniform(delay_min, delay_max)
        logger.info(f"[IG] Auto-reply to {sender_nm} in {delay:.1f}s: {reply_text[:60]}")
        time.sleep(delay)

        thread_id = thread.get("id", "")
        result    = send_dm(thread_id, reply_text)
        if result.get("ok"):
            _reply_dedup.add(msg_id)
            if _speak_fn:
                _speak_fn(f"Replied to {sender_nm} on Instagram.")
