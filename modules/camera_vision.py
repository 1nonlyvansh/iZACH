"""
modules/camera_vision.py
Camera-to-Gemini vision pipe for iZACH.
Grabs latest frame from VisionEngine → Gemini 1.5 Flash → returns description.
"""

import base64
import cv2
import time
from google import genai


GEMINI_KEYS = [
    "AIzaSyB7Dx5hx0HYvGKLPaytbCHZq7VH8mOLfNo",
    "AIzaSyAwb6UDEHkGgVwxTP5wPLa00vzAoG80Sfw",
    "AIzaSyA2X7oypXqRBaHYCFTIpeJx4Favn8CjQGQ"
]

_current_key_idx = 0
_last_call_time = 0
MIN_CALL_INTERVAL = 3

def _get_gemini_client():
    global _current_key_idx
    return genai.Client(api_key=GEMINI_KEYS[_current_key_idx])

def _rotate_key():
    global _current_key_idx
    _current_key_idx = (_current_key_idx + 1) % len(GEMINI_KEYS)

def capture_and_ask(question: str = "What do you see?") -> str:
    """
    Grab latest camera frame → send to Gemini with question → return answer.
    Returns error string if camera offline or Gemini fails.
    """
    try:
        global _last_call_time
        now = time.time()
        if now - _last_call_time < MIN_CALL_INTERVAL:
            return "Vision is cooling down, try again in a moment."
        _last_call_time = now
        from modules.vision_engine import get_vision_engine
        ve = get_vision_engine()
        if ve is None:
            return "Camera system not initialized."
        
        # Try fresh frame first, fall back to latest
        frame = None
        cap = ve._cap
        if cap and cap.isOpened():
            # Flush buffer by reading a few frames
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

        # Encode frame to JPEG bytes → base64
        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            return "Failed to encode camera frame."
        
        img_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        prompt = f"""The user is holding or showing something to the camera and asking: "{question}"

Your job:
- Focus on the FOREGROUND object being held or shown — not the background or room
- If you see a hand holding something, identify WHAT is being held
- Be specific: brand, type, color, shape if visible
- If it's food, give calorie estimate
- If you genuinely cannot identify the foreground object, say exactly that
- 2-3 sentences max, no preamble, start with what the object is"""

        import PIL.Image
        import io
        img_bytes = base64.b64decode(img_b64)
        pil_img = PIL.Image.open(io.BytesIO(img_bytes))

        last_error = None
        for attempt in range(len(GEMINI_KEYS)):
            try:
                client = _get_gemini_client()
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[pil_img, prompt]
                )
                if response and response.text:
                    return response.text.strip()
                last_error = "Empty response from vision API."
            except Exception as e:
                err = str(e)
                if "429" in err or "exhausted" in err.lower() or "quota" in err.lower():
                    print(f"[VISION] Key {_current_key_idx} rate limited, rotating...")
                    _rotate_key()
                    time.sleep(1)
                    continue
                elif "404" in err or "not found" in err.lower():
                    return "Vision model unavailable. Check Gemini API access."
                else:
                    last_error = err
                    break

        print(f"[VISION] All keys failed. Last error: {last_error}")
        return "Camera vision unavailable right now. Try again in a minute."

    except Exception as e:
        return f"Camera vision failed: {e}"


def get_camera_description() -> str:
    """Quick scene description — no specific question."""
    return capture_and_ask("Describe what you see in this camera frame in 2-3 sentences.")