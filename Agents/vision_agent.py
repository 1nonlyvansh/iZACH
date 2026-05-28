"""
VisionAgent — full LLM-driven handler for camera, screen, and face recognition.

Replaces/consolidates in command_chain.py:
  vision_triggers block    (line ~1796) — camera_vision.capture_and_ask()
  screenshot block         (line ~1781) — screenshot_engine.capture_sync()
  click element block      (line ~2443) — camera_vision.smart_locate_and_click()
  read screen block        (line ~2459) — pytesseract OCR
  face enroll/delete/status(line ~1763) — face_auth.*

Intents handled:
  camera_describe    describe what camera sees (general)
  identify_object    what is this object / what am I holding
  calorie_estimate   food calorie estimate from camera
  take_photo         capture and save image from camera
  screenshot         capture screenshot → ws broadcast
  analyze_screen     read text on screen via OCR
  click_element      locate and click UI element on screen
  enroll_face        enroll owner face for face auth
  verify_face        verify if current face is owner
  delete_face        delete stored face data
  face_status        check whether face is enrolled
"""

from __future__ import annotations

import re

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's vision command parser. Parse this voice command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "question": "<custom question to ask the camera or null — use verbatim user question>",
  "target": "<UI element to click, or null>",
  "custom_prompt": "<extra context for vision model or null>"
}}

Intents (pick exactly one):
- camera_describe    : what do you see / describe the scene / look around / what's in front of you
- identify_object    : what is this / what am I holding / identify this / what's this object / what brand
- calorie_estimate   : how many calories / what food / rate this food / calorie count / food scan
- take_photo         : take a photo / capture image / take a picture / save photo
- screenshot         : screenshot / capture screen / take a screenshot / screen capture
- analyze_screen     : read the screen / what's on screen / read screen / screen text / what does screen say
- click_element      : click on X / press X button / click the X / tap X
- enroll_face        : enroll my face / register my face / setup face auth / train face / learn my face
- verify_face        : verify my identity / face check / is that me / face verify / who am I
- delete_face        : delete face data / remove face data / forget my face / clear face auth
- face_status        : face auth status / is face enrolled / face setup status / face check status

Rules:
- question: for camera_describe use the user's exact question; null for other intents
- target: only for click_element — the element name stripped of "click on/press/tap"
- custom_prompt: only if user adds extra context like "focus on the label" or "in low light"
- Output ONLY the JSON object
"""


class VisionAgent:
    """
    Handles all vision domain commands via LLM intent parsing.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak   = speak_fn
        self._raw_ai = raw_ai_fn

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute vision command.
        Returns True if handled, False to fall through.
        """
        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[VIS_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "camera_describe": self._camera_describe,
            "identify_object": self._identify_object,
            "calorie_estimate":self._calorie_estimate,
            "take_photo":      self._take_photo,
            "screenshot":      self._screenshot,
            "analyze_screen":  self._analyze_screen,
            "click_element":   self._click_element,
            "enroll_face":     self._enroll_face,
            "verify_face":     self._verify_face,
            "delete_face":     self._delete_face,
            "face_status":     self._face_status,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        import json
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[VIS_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Handlers ─────────────────────────────────────────────────

    def _camera_describe(self, d: dict, cmd: str) -> bool:
        question = (d.get("question") or cmd).strip()
        self.speak("Looking through the camera.")
        try:
            from modules.camera_vision import capture_and_ask
            answer = capture_and_ask(question)
            self.speak(answer)
        except Exception as e:
            self.speak(f"Camera vision error: {e}")
        return True

    def _identify_object(self, d: dict, cmd: str) -> bool:
        custom = (d.get("custom_prompt") or "").strip()
        prompt = (
            "Identify the main object or item being shown or held in the camera frame. "
            "Be specific: brand, model, type, color if visible. "
            "If it is food, mention what it is. "
            "2-3 sentences max, no preamble."
        )
        if custom:
            prompt += f" Additional context: {custom}"
        self.speak("Identifying what I see.")
        try:
            from modules.camera_vision import capture_and_ask
            answer = capture_and_ask(prompt)
            self.speak(answer)
        except Exception as e:
            self.speak(f"Vision error: {e}")
        return True

    def _calorie_estimate(self, d: dict, cmd: str) -> bool:
        self.speak("Scanning for food and estimating calories.")
        prompt = (
            "The user is showing food to the camera. "
            "Identify the food item(s) visible. "
            "Estimate the calorie content for a typical portion size. "
            "Format: food name, approximate weight/portion, calorie estimate. "
            "2-4 sentences, direct and concise. No preamble."
        )
        try:
            from modules.camera_vision import capture_and_ask
            answer = capture_and_ask(prompt)
            self.speak(answer)
        except Exception as e:
            self.speak(f"Vision error: {e}")
        return True

    def _take_photo(self, d: dict, cmd: str) -> bool:
        self.speak("Taking a photo now.")
        try:
            from modules.camera_vision import capture_image
            path = capture_image()
            if path:
                import os
                self.speak(f"Photo saved: {os.path.basename(path)}")
                try:
                    from modules.ws_bridge import broadcast
                    broadcast({"type": "photo_ready", "path": path})
                except Exception:
                    pass
            else:
                self.speak("Camera unavailable. Couldn't take a photo.")
        except Exception as e:
            self.speak(f"Photo capture failed: {e}")
        return True

    def _screenshot(self, d: dict, cmd: str) -> bool:
        try:
            from modules.screenshot_engine import capture_sync
            from modules.ws_bridge import broadcast
            import time
            filename = capture_sync()
            if filename:
                broadcast({
                    "type": "screenshot_ready",
                    "filename": filename,
                    "ts": time.strftime("%H:%M"),
                })
                self.speak("Screenshot captured and sent to your screen.")
            else:
                self.speak("Screenshot failed. Check that pyautogui is installed.")
        except Exception as e:
            self.speak(f"Screenshot error: {e}")
        return True

    def _analyze_screen(self, d: dict, cmd: str) -> bool:
        self.speak("Reading the screen.")
        try:
            from PIL import ImageGrab
            import pytesseract
            img  = ImageGrab.grab()
            text = pytesseract.image_to_string(img).strip()
            if text:
                # Collapse excessive whitespace
                text = re.sub(r'\s+', ' ', text)
                self.speak(f"I can see: {text[:300]}" + ("..." if len(text) > 300 else ""))
            else:
                self.speak("I couldn't read any text on the screen.")
        except ImportError:
            # Fall back to Gemini screenshot analysis if pytesseract unavailable
            try:
                import pyautogui
                from modules.camera_vision import _get_gemini_client
                import io
                screenshot = pyautogui.screenshot()
                buf = io.BytesIO()
                screenshot.save(buf, format="JPEG", quality=75)
                buf.seek(0)
                import PIL.Image
                pil_img = PIL.Image.open(buf)
                client   = _get_gemini_client()
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[
                        pil_img,
                        "Describe the text and key content visible on this screen. "
                        "Be concise, 2-4 sentences.",
                    ],
                )
                self.speak(response.text.strip() if response and response.text else "Screen unreadable.")
            except Exception as e2:
                self.speak(f"Screen analysis failed: {e2}")
        except Exception as e:
            self.speak(f"Screen read error: {e}")
        return True

    def _click_element(self, d: dict, cmd: str) -> bool:
        target = (d.get("target") or "").strip()
        if not target:
            # Strip trigger words from raw command
            for phrase in ["click on", "click the", "click", "press the button",
                           "press button", "press the", "press", "tap the", "tap"]:
                lc = cmd.lower()
                if lc.startswith(phrase):
                    target = cmd[len(phrase):].strip()
                    break
            if not target:
                target = cmd

        if not target:
            self.speak("What should I click?")
            return True

        self.speak(f"Looking for {target} on screen.")
        try:
            from modules.camera_vision import smart_locate_and_click
            result = smart_locate_and_click(target)
            if result is True:
                self.speak(f"Clicked {target}.")
            elif isinstance(result, str) and result.startswith("COOLDOWN"):
                secs = result.split("_")[1]
                self.speak(f"Screen click on cooldown. Try again in {secs} seconds.")
            else:
                self.speak(f"Couldn't find {target} on screen.")
        except Exception as e:
            self.speak(f"Click failed: {e}")
        return True

    def _enroll_face(self, d: dict, cmd: str) -> bool:
        try:
            from modules import face_auth
            face_auth.init(self.speak)
            face_auth.enroll_owner()
        except Exception as e:
            self.speak(f"Face enrollment error: {e}")
        return True

    def _verify_face(self, d: dict, cmd: str) -> bool:
        try:
            from modules import face_auth
            face_auth.init(self.speak)
            if not face_auth.is_enrolled():
                self.speak("No face enrolled yet. Say 'enroll my face' first.")
                return True
            self.speak("Verifying your identity. Look at the camera.")
            verified = face_auth.verify_owner()
            self.speak("Identity confirmed." if verified else "Face not recognized.")
        except Exception as e:
            self.speak(f"Face verification error: {e}")
        return True

    def _delete_face(self, d: dict, cmd: str) -> bool:
        try:
            from modules import face_auth
            ok = face_auth.delete_face_data()
            self.speak("Face data removed." if ok else "No face data stored.")
        except Exception as e:
            self.speak(f"Face delete error: {e}")
        return True

    def _face_status(self, d: dict, cmd: str) -> bool:
        try:
            from modules import face_auth
            enrolled = face_auth.is_enrolled()
            self.speak(
                "Face is enrolled and ready." if enrolled
                else "No face enrolled yet. Say 'enroll my face' to set up."
            )
        except Exception as e:
            self.speak(f"Face status error: {e}")
        return True
