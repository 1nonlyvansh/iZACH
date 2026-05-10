"""
modules/camera_vision.py
Camera-to-Gemini vision pipe for iZACH.
Grabs latest frame from VisionEngine → Gemini 1.5 Flash → returns description.
"""

import cv2
import time
from google import genai


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
    global _current_key_idx
    return genai.Client(api_key=GEMINI_KEYS[_current_key_idx])


def capture_and_ask(question: str = "What do you see?") -> str:
    """
    Grab latest camera frame → send to Gemini with question → return answer.
    Returns error string if camera offline or Gemini fails.
    """
    global _last_call_time, _vision_in_progress

    now = time.time()
    if _vision_in_progress:
        print("[VISION] Already in progress, skipping.")
        return "Vision is already processing a request."
    if now - _last_call_time < MIN_CALL_INTERVAL:
        print("[VISION] Called too soon, skipping.")
        return "Vision is cooling down, try again in a moment."

    _vision_in_progress = True
    _last_call_time = now
    print("VISION CALLED ONCE")

    try:
        from modules.vision_engine import get_vision_engine
        ve = get_vision_engine()
        if ve is None:
            return "Camera system not initialized."

        frame = None
        cap = ve._cap
        if cap and cap.isOpened():
            for _ in range(3):
                cap.read()
            ret, frame = cap.read()
            if not ret:
                frame = None
        if frame is None:
            frame = ve.get_latest_frame()
        if frame is None:
            return "Camera is offline or no frame available."
        frame = cv2.flip(frame, 1)

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
            print(f"[VISION] API error: {err}")
            return "Camera vision unavailable right now. Try again in a minute."

    except Exception as e:
        return f"Camera vision failed: {e}"
    finally:
        _vision_in_progress = False


def capture_image() -> str:
    """
    Capture one frame from camera, save to temp file, return file path.
    Returns empty string on failure.
    """
    try:
        from modules.vision_engine import get_vision_engine
        ve = get_vision_engine()
        if ve is None:
            print("[VISION] Camera system not initialized.")
            return ""

        frame = None
        cap = ve._cap
        if cap and cap.isOpened():
            for _ in range(3):
                cap.read()
            ret, frame = cap.read()
            if not ret:
                frame = None
        if frame is None:
            frame = ve.get_latest_frame()
        if frame is None:
            print("[VISION] No frame available.")
            return ""

        frame = cv2.flip(frame, 1)

        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        path = tmp.name
        tmp.close()

        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print("IMAGE SAVED:", path)
        return path

    except Exception as e:
        print(f"[VISION] capture_image failed: {e}")
        return ""


def get_camera_description() -> str:
    """Quick scene description — no specific question."""
    return capture_and_ask("Describe what you see in this camera frame in 2-3 sentences.")