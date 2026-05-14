"""
modules/wa_draft_engine.py
Auto-draft WhatsApp replies.

Flow:
  1. User: "draft a reply to Divya" / "what should I say to Divya"
  2. iZACH fetches last N messages from that chat via /messages/chat
  3. iZACH fetches relationship context (who is Divya?)
  4. AI generates a contextually appropriate draft
  5. iZACH speaks: "Draft: '[text]'. Send it, or tell me to change it."
  6. Next voice input → "yes" / "send" → sends
                      → "no" / "cancel" → drops
                      → "change it to X" / "say X instead" → revise
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

WA_BRIDGE = "http://localhost:3000"

_pending_draft: dict | None = None   # {"number", "sender", "text", "expires_at"}
_pending_lock  = threading.Lock()

_speak_func  = None
_ai_func     = None
_send_fn     = None   # injected from whatsapp_handler

_DRAFT_TIMEOUT = 30   # seconds user has to respond


# ── Public API ────────────────────────────────────────────────


def init(speak_fn, ai_fn, send_fn):
    global _speak_func, _ai_func, _send_fn
    _speak_func = speak_fn
    _ai_func    = ai_fn
    _send_fn    = send_fn


def is_waiting_for_approval() -> bool:
    with _pending_lock:
        if _pending_draft is None:
            return False
        if time.time() > _pending_draft["expires_at"]:
            _clear_unsafe()
            return False
        return True


def handle_approval(text: str) -> bool:
    """
    Called from voice loop when is_waiting_for_approval() is True.
    Returns True if handled (consume the input), False if not.
    """
    with _pending_lock:
        if _pending_draft is None:
            return False
        draft = dict(_pending_draft)

    text_lower = text.lower().strip()

    # Send
    if any(w in text_lower for w in ["yes", "send", "send it", "go ahead", "haan", "haan bhai", "bhej de", "bhej do"]):
        _do_send(draft)
        return True

    # Cancel
    if any(w in text_lower for w in ["no", "cancel", "nahi", "mat bhejo", "drop it", "forget it", "nope"]):
        with _pending_lock:
            _clear_unsafe()
        if _speak_func:
            _speak_func("Alright, draft cancelled.")
        return True

    # Revise — "change it to X" / "say X instead" / "make it X"
    revise_triggers = ["change it to", "say instead", "say", "make it", "write", "instead say", "badal ke"]
    for trigger in revise_triggers:
        if trigger in text_lower:
            new_instruction = text_lower.split(trigger, 1)[-1].strip()
            if new_instruction:
                threading.Thread(
                    target=_generate_and_set_draft,
                    args=(draft["number"], draft["sender"], new_instruction),
                    daemon=True
                ).start()
                return True

    # Not a clear response — re-prompt
    if _speak_func:
        _speak_func(f"Say 'send it', 'cancel', or 'change it to [something]'.")
    return True


def draft_reply(number: str, sender: str, instruction: str = "") -> bool:
    """
    Entry point from command_chain.
    Fetches conversation history, generates draft, speaks it for approval.
    """
    threading.Thread(
        target=_generate_and_set_draft,
        args=(number, sender, instruction),
        daemon=True
    ).start()
    return True


# ── Internal ─────────────────────────────────────────────────


def _clear_unsafe():
    global _pending_draft
    _pending_draft = None


def _fetch_chat_history(number: str, limit: int = 10) -> list[dict]:
    try:
        r = requests.get(f"{WA_BRIDGE}/messages/chat", params={"number": number, "limit": limit}, timeout=8)
        return r.json().get("messages", [])
    except Exception as e:
        logger.warning(f"[WaDraft] Bridge fetch failed: {e}")
        return []


def _build_conversation_str(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        speaker = "Me" if m.get("fromMe") else m.get("sender", "Them")
        lines.append(f"{speaker}: {m.get('text', '')}")
    return "\n".join(lines)


def _generate_draft(sender: str, conversation: str, relationship: str, instruction: str) -> str:
    if not _ai_func:
        return ""

    rel_note = f"\nContext about {sender}: {relationship}" if relationship else ""
    inst_note = f"\nUser's instruction: \"{instruction}\"" if instruction else ""

    prompt = f"""You are drafting a WhatsApp reply on behalf of Vansh.

Sender name: {sender}{rel_note}
Recent conversation:
{conversation}
{inst_note}

Rules:
- Write ONLY the message text — nothing else, no quotes, no explanations
- Match the language of the conversation:
  * Hinglish conversation → reply in Hinglish (Roman Hindi + English, casual)
  * English conversation  → reply in English
- Keep it short, natural, conversational — like a real person texting
- Match the tone (casual if casual, formal if formal)
- If no specific instruction, generate what seems like the most natural reply
- Do NOT add "Hi" or greetings if the conversation is already mid-way"""

    return (_ai_func(prompt) or "").strip().strip('"')


def _generate_and_set_draft(number: str, sender: str, instruction: str):
    global _pending_draft

    if _speak_func:
        _speak_func("Give me a second, drafting a reply.")

    messages = _fetch_chat_history(number, limit=12)
    conversation = _build_conversation_str(messages) if messages else f"[No history available — message from {sender}]"

    # Fetch relationship context
    relationship = ""
    try:
        from modules.relationship_memory import get_person
        person = get_person(sender)
        if person:
            parts = []
            for k, v in person.items():
                parts.append(f"{k.replace('_', ' ')}: {v}")
            relationship = ", ".join(parts)
    except Exception:
        pass

    draft_text = _generate_draft(sender, conversation, relationship, instruction)

    if not draft_text:
        if _speak_func:
            _speak_func("Couldn't generate a draft. Try telling me what to say.")
        return

    with _pending_lock:
        _pending_draft = {
            "number":     number,
            "sender":     sender,
            "text":       draft_text,
            "expires_at": time.time() + _DRAFT_TIMEOUT,
        }

    if _speak_func:
        _speak_func(f'Draft: "{draft_text}". Send it, or tell me to change it.')


def _do_send(draft: dict):
    with _pending_lock:
        _clear_unsafe()
    try:
        if _send_fn:
            ok, _ = _send_fn(draft["number"], draft["text"], draft["sender"])
        else:
            r = requests.post(f"{WA_BRIDGE}/send-message",
                              json={"number": draft["number"], "text": draft["text"]}, timeout=8)
            ok = r.json().get("status") == "sent"
    except Exception as e:
        logger.error(f"[WaDraft] Send failed: {e}")
        ok = False

    if _speak_func:
        if ok:
            _speak_func(f"Sent to {draft['sender']}.")
        else:
            _speak_func("Couldn't send. WhatsApp bridge might be offline.")
