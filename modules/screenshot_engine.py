"""
Screenshot capture — uses pyautogui (already in venv) + PIL.
Stores in temp/screenshots/, max 20 files.
"""
import time
import threading
from pathlib import Path

_ROOT = Path(__file__).parent.parent
SCREENSHOT_DIR = _ROOT / "screenshots"
MAX_SHOTS = 20


def _ensure():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup():
    files = sorted(SCREENSHOT_DIR.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
    for f in files[:-MAX_SHOTS]:
        try:
            f.unlink()
        except Exception:
            pass


def capture(monitor: int = 0, notify: bool = True) -> str | None:
    """Capture full screen, compress to JPEG, return filename. Non-blocking via thread."""
    def _do():
        try:
            _ensure()
            import pyautogui
            img = pyautogui.screenshot()
            img.thumbnail((1280, 720))
            filename = f"screen_{int(time.time())}.jpg"
            path = SCREENSHOT_DIR / filename
            img.save(str(path), "JPEG", quality=75)
            _cleanup()
            if notify:
                try:
                    from modules.ws_bridge import broadcast
                    broadcast({
                        "type": "screenshot_ready",
                        "filename": filename,
                        "ts": time.strftime("%H:%M"),
                    })
                except Exception:
                    pass
            return filename
        except Exception as e:
            print(f"[SCREENSHOT] Capture error: {e}")
            return None

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    # Return predictable filename immediately for REST response
    filename = f"screen_{int(time.time())}.jpg"
    return filename


def capture_sync() -> str | None:
    """Blocking capture — for REST endpoints that need the file ready."""
    try:
        _ensure()
        import pyautogui
        img = pyautogui.screenshot()
        img.thumbnail((1280, 720))
        filename = f"screen_{int(time.time())}.jpg"
        path = SCREENSHOT_DIR / filename
        img.save(str(path), "JPEG", quality=75)
        _cleanup()
        return filename
    except Exception as e:
        print(f"[SCREENSHOT] Sync capture error: {e}")
        return None


def latest() -> str | None:
    _ensure()
    files = sorted(SCREENSHOT_DIR.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
    return files[-1].name if files else None


def get_dir() -> Path:
    _ensure()
    return SCREENSHOT_DIR
