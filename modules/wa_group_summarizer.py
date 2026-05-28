"""
modules/wa_group_summarizer.py
WhatsApp group chat summarizer.

Voice trigger (in command_chain):
  "summarize [group name] group"
  "what happened in [group] today"
  "catch me up on [group]"
  "summarize college group from today"

Flow:
  1. Find group chat ID by name via bridge
  2. Fetch last N messages (default: 50 or 6h)
  3. AI synthesizes into spoken summary
  4. Speak the summary
"""

import os
import time
import logging
import requests
import threading

logger = logging.getLogger(__name__)

BRIDGE_BASE = "http://localhost:3000"
_speak_fn = None
_groq_client = None
_ai_fn = None


def init(speak_fn, ai_fn=None):
    global _speak_fn, _ai_fn
    _speak_fn = speak_fn
    _ai_fn = ai_fn


def _groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _groq_client


def _call_ai(system: str, user: str, max_tokens: int = 300) -> str:
    if _ai_fn:
        return _ai_fn(f"{system}\n\n{user}")
    resp = _groq().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── Bridge communication ──────────────────────────────────────

def _get_chats() -> list[dict]:
    """Fetch all chats from bridge."""
    try:
        r = requests.get(f"{BRIDGE_BASE}/chats", timeout=8)
        return r.json() if r.ok else []
    except Exception as e:
        logger.warning(f"[GroupSum] Could not fetch chats: {e}")
        return []


def _find_group_id(name: str) -> tuple[str, str]:
    """
    Find WhatsApp group chat ID by fuzzy name match.
    Returns (chat_id, real_name) or ("", "") if not found.
    """
    name_lower = name.lower().replace(" group", "").strip()
    chats = _get_chats()
    for chat in chats:
        chat_name = (chat.get("name") or "").lower()
        if name_lower in chat_name or chat_name.startswith(name_lower):
            is_group = chat.get("isGroup") or "@g.us" in chat.get("id", "")
            if is_group:
                return chat["id"], chat.get("name", name)
    # Fallback: any chat matching
    for chat in chats:
        chat_name = (chat.get("name") or "").lower()
        if name_lower in chat_name:
            return chat["id"], chat.get("name", name)
    return "", ""


def _fetch_group_messages(chat_id: str, limit: int = 60) -> list[dict]:
    """Fetch last N messages from a group chat."""
    try:
        r = requests.get(
            f"{BRIDGE_BASE}/messages/{chat_id}",
            params={"limit": limit},
            timeout=10,
        )
        if r.ok:
            return r.json() if isinstance(r.json(), list) else []
    except Exception as e:
        logger.warning(f"[GroupSum] Fetch messages failed: {e}")
    return []


def _format_messages(messages: list[dict]) -> str:
    """Convert raw message list to readable thread for AI."""
    lines = []
    for msg in messages[-50:]:  # cap at 50
        sender = msg.get("sender") or msg.get("author") or "Unknown"
        # Strip phone number if name is a number
        if sender.replace("+", "").replace(" ", "").isdigit():
            sender = "Contact"
        text = msg.get("body") or msg.get("text") or ""
        if not text or text.startswith("[sticker]") or text.startswith("[media]"):
            continue
        ts = ""
        try:
            epoch = int(msg.get("timestamp", 0))
            if epoch:
                ts = time.strftime("%H:%M", time.localtime(epoch))
        except Exception:
            pass
        lines.append(f"[{ts}] {sender}: {text[:200]}")
    return "\n".join(lines)


# ── Main function ─────────────────────────────────────────────

def summarize_group(group_name: str, hours: int = 6) -> str:
    """
    Fetch and summarize a WhatsApp group. Returns spoken summary string.
    Speaks progress updates via _speak_fn.
    """
    if _speak_fn:
        _speak_fn(f"Fetching messages from {group_name}.")

    chat_id, real_name = _find_group_id(group_name)

    if not chat_id:
        msg = f"Could not find a group called {group_name} in your WhatsApp chats."
        if _speak_fn:
            _speak_fn(msg)
        return msg

    messages = _fetch_group_messages(chat_id, limit=80)

    if not messages:
        msg = f"No recent messages found in {real_name}."
        if _speak_fn:
            _speak_fn(msg)
        return msg

    # Filter to last N hours
    cutoff = time.time() - hours * 3600
    recent = [m for m in messages if int(m.get("timestamp", 0)) >= cutoff]
    if not recent:
        recent = messages[-30:]  # fallback: last 30 regardless of time

    thread = _format_messages(recent)

    if not thread.strip():
        msg = f"Messages in {real_name} are media-only or unreadable."
        if _speak_fn:
            _speak_fn(msg)
        return msg

    summary = _call_ai(
        "You are iZACH, a JARVIS-style assistant. Summarize this WhatsApp group conversation "
        "into a concise spoken briefing. Cover: main topics discussed, any decisions or plans made, "
        "anything requiring action. Max 100 words. Speak naturally — no bullet points.",
        f"Group: {real_name}\nMessages (last {hours}h):\n{thread}",
        max_tokens=200,
    )

    return summary


def summarize_group_async(group_name: str, hours: int = 6):
    """Non-blocking version — speaks when ready."""
    def _run():
        summary = summarize_group(group_name, hours)
        if _speak_fn:
            _speak_fn(summary)
    threading.Thread(target=_run, daemon=True).start()
