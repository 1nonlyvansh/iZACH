"""
modules/camera_vision.py
Camera-to-Gemini vision pipe for iZACH.
Opens camera on demand, captures one frame, sends to Gemini, releases.
No persistent camera thread — zero idle RAM usage.
"""

import cv2
import time
import os as _os
from dotenv import load_dotenv as _ldenv
_ldenv()

GEMINI_KEYS = [
    _os.getenv("GEMINI_KEY_1", ""),
    _os.getenv("GEMINI_KEY_2", ""),
    _os.getenv("GEMINI_KEY_3", ""),
]

_current_key_idx = 0
_last_call_time = 0
_vision_in_progress = False
MIN_CALL_INTERVAL = 10


def _get_gemini_client():
    from google import genai
    return genai.Client(api_key=GEMINI_KEYS[_current_key_idx])


def _capture_frame():
    """Open camera, grab one frame, release immediately."""
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        for _ in range(3):
            cap.read()
        ret, frame = cap.read()
        if ret:
            return cv2.flip(frame, 1)
        return None
    finally:
        cap.release()


def capture_and_ask(question: str = "What do you see?") -> str:
    """Capture one camera frame → send to Gemini with question → return answer."""
    global _last_call_time, _vision_in_progress

    now = time.time()
    if _vision_in_progress:
        return "Vision is already processing a request."
    if now - _last_call_time < MIN_CALL_INTERVAL:
        return "Vision is cooling down, try again in a moment."

    _vision_in_progress = True
    _last_call_time = now

    try:
        frame = _capture_frame()
        if frame is None:
            return "Camera unavailable or no frame captured."

        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            return "Failed to encode camera frame."

        import PIL.Image
        import io
        pil_img = PIL.Image.open(io.BytesIO(buf.tobytes()))

        prompt = f"""The user is holding or showing something to the camera and asking: "{question}"

Your job:
- Focus on the FOREGROUND object being held or shown — not the background or room
- If you see a hand holding something, identify WHAT is being held
- Be specific: brand, type, color, shape if visible
- If it's food, give calorie estimate
- If you genuinely cannot identify the foreground object, say exactly that
- 2-3 sentences max, no preamble, start with what the object is"""

        try:
            client = _get_gemini_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[pil_img, prompt]
            )
            if response and response.text:
                return response.text.strip()
            return "Camera vision returned empty response."
        except Exception as e:
            err = str(e)
            if "404" in err or "not found" in err.lower():
                return "Vision model unavailable. Check Gemini API access."
            return "Camera vision unavailable right now. Try again in a minute."

    except Exception as e:
        return f"Camera vision failed: {e}"
    finally:
        _vision_in_progress = False


def capture_image() -> str:
    """Capture one frame, save to temp file, return path. Empty string on failure."""
    try:
        frame = _capture_frame()
        if frame is None:
            return ""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        path = tmp.name
        tmp.close()
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path
    except Exception as e:
        print(f"[VISION] capture_image failed: {e}")
        return ""


def get_camera_description() -> str:
    return capture_and_ask("Describe what you see in this camera frame in 2-3 sentences.")


_screen_last_call_time = 0
_SCREEN_COOLDOWN = 8


def smart_locate_and_click(target: str, vision_client=None):
    """Screenshot → Gemini locates target → pyautogui clicks it.
    Returns True on success, 'COOLDOWN_N' string on cooldown, False on failure."""
    global _screen_last_call_time
    import re
    import pyautogui

    now = time.time()
    elapsed = now - _screen_last_call_time
    if elapsed < _SCREEN_COOLDOWN:
        return f"COOLDOWN_{int(_SCREEN_COOLDOWN - elapsed)}"

    _screen_last_call_time = now

    try:
        screenshot = pyautogui.screenshot()
        width, height = pyautogui.size()

        prompt = (
            f'Find "{target}" in this screenshot. '
            f'Screen is {width}x{height} pixels. '
            'Reply ONLY: x=<number> y=<number> — center pixel of that element. '
            'If not found reply: NOT_FOUND'
        )

        try:
            client = _get_gemini_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[screenshot, prompt]
            )
            text = response.text.strip() if response and response.text else ""
        except Exception:
            return False

        if not text or "NOT_FOUND" in text:
            return False

        x_match = re.search(r'x=(\d+)', text)
        y_match = re.search(r'y=(\d+)', text)
        if not x_match or not y_match:
            return False

        x, y = int(x_match.group(1)), int(y_match.group(1))
        if not (0 <= x <= width and 0 <= y <= height):
            return False

        pyautogui.click(x, y)
        return True

    except Exception:
        return False
