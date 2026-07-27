"""
Clipboard sync — polls Windows clipboard every 1.5s, broadcasts changes via WS.
Smart clipboard: detects content type and suggests actions.
Uses PowerShell (no extra deps). Deduplicates to avoid echo loops.
"""
import hashlib
import re
import threading
import time

_last = ""
_history: list[dict] = []
_MAX_HISTORY = 50
_running = False
_thread: threading.Thread | None = None
_speak_fn = None
_chain_fn = None
_awaiting_clipboard_action: dict | None = None  # {type, text, suggestion}
_CLIPBOARD_ACTION_TIMEOUT = 20  # seconds


def init(speak_fn, chain_fn=None):
    global _speak_fn, _chain_fn
    _speak_fn = speak_fn
    _chain_fn = chain_fn


# ── Content classifier ────────────────────────────────────────

_URL_RE    = re.compile(r'^https?://\S+', re.IGNORECASE)
_EMAIL_RE  = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_PHONE_RE  = re.compile(r'^[\+\d][\d\s\-\(\)]{7,15}$')
_CODE_KWORDS = ('def ', 'function ', 'import ', 'class ', 'const ', 'var ', 'let ',
                'return ', 'if (', '#include', 'SELECT ', 'CREATE TABLE')


def _classify(text: str) -> str | None:
    """Return content type string or None if not actionable."""
    t = text.strip()
    if not t or len(t) > 2000:
        return None
    if _URL_RE.match(t):
        return "url"
    if _EMAIL_RE.match(t):
        return "email"
    if _PHONE_RE.match(t):
        return "phone"
    if any(t.startswith(kw) for kw in _CODE_KWORDS) or t.count('\n') >= 3:
        return "code"
    return None


def _build_suggestion(content_type: str, text: str) -> str:
    domain = ""
    if content_type == "url":
        try:
            m = re.search(r'https?://(?:www\.)?([^/\s]+)', text)
            domain = m.group(1) if m else text[:40]
        except Exception:
            domain = text[:40]
        return f"You copied a URL from {domain}. Should I open it?"
    if content_type == "email":
        return f"You copied an email address. Should I compose a message to {text[:40]}?"
    if content_type == "phone":
        return f"You copied a phone number. Should I WhatsApp {text.strip()}?"
    if content_type == "code":
        lines = len(text.strip().splitlines())
        return f"You copied {lines} lines of code. Should I explain it or save it to a note?"
    return ""


def _clipboard_action_timeout():
    """Clear pending clipboard action after timeout."""
    global _awaiting_clipboard_action
    time.sleep(_CLIPBOARD_ACTION_TIMEOUT)
    _awaiting_clipboard_action = None


def is_awaiting_clipboard_action() -> bool:
    return _awaiting_clipboard_action is not None


def get_history() -> list[dict]:
    """Return clipboard history (newest first). Each entry: {text, ts, hash}."""
    return list(_history)


def search_history(query: str) -> list[dict]:
    """Search clipboard history for items containing query text (case-insensitive)."""
    q = query.lower().strip()
    if not q:
        return list(_history)
    return [e for e in _history if q in e.get("text", "").lower()]


def get_last_n(n: int = 5) -> list[dict]:
    """Return the last N clipboard entries."""
    return list(_history[:n])


def handle_clipboard_response(cmd: str) -> bool:
    """
    Called from command_chain when user responds to a clipboard suggestion.
    Returns True if handled, False if no pending action.
    """
    global _awaiting_clipboard_action
    if not _awaiting_clipboard_action:
        return False

    action = _awaiting_clipboard_action
    _awaiting_clipboard_action = None

    affirm = {"yes", "yeah", "yep", "sure", "ok", "okay", "open", "do it", "go"}
    negate = {"no", "nope", "nahi", "skip", "cancel", "don't", "ignore"}

    words = set(cmd.lower().split())
    if words & negate:
        if _speak_fn:
            _speak_fn("Okay, skipping.")
        return True

    if words & affirm:
        content_type = action.get("type")
        text = action.get("text", "")

        if content_type == "url" and _chain_fn:
            threading.Thread(target=_chain_fn, args=(f"open website {text}",), daemon=True).start()
        elif content_type == "email" and _speak_fn:
            _speak_fn(f"Opening compose window for {text}. Opening Gmail.")
            if _chain_fn:
                threading.Thread(target=_chain_fn, args=(f"open gmail",), daemon=True).start()
        elif content_type == "phone" and _chain_fn:
            threading.Thread(target=_chain_fn, args=(f"whatsapp {text}",), daemon=True).start()
        elif content_type == "code" and _speak_fn:
            # Ask AI to explain
            if _chain_fn:
                threading.Thread(
                    target=_chain_fn,
                    args=(f"explain this code: {text[:500]}",),
                    daemon=True,
                ).start()
        return True

    return False


def _ps_get() -> str:
    # Despite the name (kept for minimal diff — was PowerShell-based), this is now
    # cross-platform via pyperclip (pbcopy/pbpaste on macOS, PowerShell/win32
    # clipboard API on Windows, xclip/xsel on Linux) instead of shelling out to
    # PowerShell directly, which was Windows-only and much slower to boot per poll.
    try:
        import pyperclip
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def _ps_set(text: str):
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        pass


def _push(text: str):
    global _last, _awaiting_clipboard_action
    _last = text
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
    entry = {"text": text[:500], "ts": time.strftime("%H:%M"), "hash": text_hash}
    _history.insert(0, entry)
    if len(_history) > _MAX_HISTORY:
        _history.pop()
    try:
        from modules.ws_bridge import broadcast
        broadcast({
            "type": "clipboard_changed",
            "text": text[:500],
            "hash": text_hash,
            "source_id": "pc",
            "ts": int(time.time()),
        })
    except Exception:
        pass

    # Smart clipboard suggestion
    content_type = _classify(text)
    if content_type and _speak_fn:
        suggestion = _build_suggestion(content_type, text)
        if suggestion:
            _awaiting_clipboard_action = {"type": content_type, "text": text, "suggestion": suggestion}
            threading.Thread(target=_clipboard_action_timeout, daemon=True).start()
            _speak_fn(suggestion)


def _monitor():
    global _last
    while _running:
        try:
            current = _ps_get()
            if current and current != _last and len(current) < 5000:
                _push(current)
        except Exception:
            pass
        time.sleep(1.5)


def start():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_monitor, daemon=True, name="clipboard-sync")
    _thread.start()
    print("[CLIPBOARD] Monitor started")


def stop():
    global _running
    _running = False


def get() -> str:
    return _ps_get()


def set_from_phone(text: str):
    """Set PC clipboard from Android — suppress echo."""
    global _last
    _last = text  # prevent re-broadcasting back to phone
    _ps_set(text)


def history() -> list:
    return list(_history)
