"""
Clipboard sync — polls Windows clipboard every 1.5s, broadcasts changes via WS.
Uses PowerShell (no extra deps). Deduplicates to avoid echo loops.
"""
import hashlib
import subprocess
import threading
import time

_last = ""
_history: list[dict] = []
_MAX_HISTORY = 10
_running = False
_thread: threading.Thread | None = None


def _ps_get() -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=2
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _ps_set(text: str):
    try:
        safe = text.replace("'", '"')
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{safe}'"],
            timeout=2, capture_output=True
        )
    except Exception:
        pass


def _push(text: str):
    global _last
    _last = text
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
    entry = {"text": text[:500], "ts": time.strftime("%H:%M"), "hash": text_hash}
    _history.insert(0, entry)
    if len(_history) > _MAX_HISTORY:
        _history.pop()
    try:
        from modules.ws_bridge import emit
        emit("clipboard_changed", "clipboard_sync", {
            "text": text[:500],
            "hash": text_hash,
            "source_id": "pc",
            "ts": int(time.time()),
        })
    except Exception:
        pass


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
