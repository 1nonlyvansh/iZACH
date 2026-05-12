"""
face_auth.py
Owner face enrollment + verification for iZACH.

Uses face_recognition (dlib) — CPU-only, no GPU needed.

Lifecycle:
  enroll_owner()       — capture 5 frames, average encoding, save to owner_face.pkl
  verify_owner()       — capture frame, compare to stored, returns bool
  is_enrolled()        — check if owner_face.pkl exists
  delete_face_data()   — remove enrollment

Broadcasts face_verify WebSocket events:
  {type: 'face_verify', state: 'enrolling'}  — during enrollment capture
  {type: 'face_verify', state: 'scanning'}   — during verification
  {type: 'face_verify', state: 'success'}    — identity confirmed
  {type: 'face_verify', state: 'failed'}     — mismatch or no face found
  {type: 'face_verify', state: 'idle'}       — reset UI
"""

import os
import cv2
import time
import pickle
import logging
import threading
import numpy as np

logger = logging.getLogger(__name__)

FACE_DATA_FILE  = "owner_face.pkl"
FACE_TOLERANCE  = 0.50   # lower = stricter match
ENROLL_FRAMES   = 5      # frames captured during enrollment
VERIFY_TIMEOUT  = 8.0    # seconds before verification gives up

_speak_func = None


def init(speak_fn):
    global _speak_func
    _speak_func = speak_fn


def _speak(text: str):
    if _speak_func:
        _speak_func(text)


def _broadcast(state: str):
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "face_verify", "state": state})
    except Exception:
        pass


def is_enrolled() -> bool:
    return os.path.exists(FACE_DATA_FILE)


def _capture_rgb():
    """Grab one camera frame, return as RGB numpy array or None."""
    from modules.camera_vision import _capture_frame
    bgr = _capture_frame()
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


# ── Enrollment ────────────────────────────────────────────────

def enroll_owner(callback=None):
    """
    Non-blocking. Captures ENROLL_FRAMES frames with face detection,
    averages encodings, persists to owner_face.pkl.
    callback(success: bool) called when done.
    """
    def _run():
        import face_recognition
        _broadcast("enrolling")
        _speak("Look directly at the camera. Stay still — capturing your face now.")

        encodings = []
        attempts  = 0
        max_attempts = 20

        while len(encodings) < ENROLL_FRAMES and attempts < max_attempts:
            time.sleep(0.7)
            attempts += 1
            frame = _capture_rgb()
            if frame is None:
                continue

            locs = face_recognition.face_locations(frame, model="hog")
            if not locs:
                continue

            enc = face_recognition.face_encodings(frame, locs)
            if not enc:
                continue

            encodings.append(enc[0])
            _speak(f"Frame {len(encodings)} of {ENROLL_FRAMES}.")

        if len(encodings) < 3:
            _broadcast("failed")
            _speak("Could not detect your face in enough frames. Try again with better lighting and face the camera directly.")
            time.sleep(3)
            _broadcast("idle")
            if callback:
                callback(False)
            return

        avg_encoding = np.mean(encodings, axis=0)
        try:
            with open(FACE_DATA_FILE, "wb") as f:
                pickle.dump(avg_encoding, f)
        except Exception as e:
            _broadcast("failed")
            _speak(f"Could not save face data: {e}")
            time.sleep(3)
            _broadcast("idle")
            if callback:
                callback(False)
            return

        _broadcast("success")
        _speak("Face enrolled. I'll recognize you from now on.")
        logger.info("[FaceAuth] Owner face enrolled successfully.")
        time.sleep(3)
        _broadcast("idle")
        if callback:
            callback(True)

    threading.Thread(target=_run, daemon=True).start()


# ── Verification ──────────────────────────────────────────────

def verify_owner() -> bool:
    """
    Blocking. Captures frames until face found or timeout.
    Broadcasts scanning/success/failed to UI.
    Returns True if identity confirmed.
    """
    import face_recognition

    if not is_enrolled():
        _speak("No face enrolled yet. Say 'enroll my face' first.")
        return False

    try:
        with open(FACE_DATA_FILE, "rb") as f:
            known_encoding = pickle.load(f)
    except Exception as e:
        logger.error(f"[FaceAuth] Could not load face data: {e}")
        _speak("Face data corrupted. Please re-enroll.")
        return False

    _broadcast("scanning")
    deadline = time.time() + VERIFY_TIMEOUT

    while time.time() < deadline:
        frame = _capture_rgb()
        if frame is None:
            time.sleep(0.4)
            continue

        locs = face_recognition.face_locations(frame, model="hog")
        if not locs:
            time.sleep(0.3)
            continue

        encs = face_recognition.face_encodings(frame, locs)
        if not encs:
            time.sleep(0.3)
            continue

        match = face_recognition.compare_faces(
            [known_encoding], encs[0], tolerance=FACE_TOLERANCE
        )
        if match[0]:
            _broadcast("success")
            time.sleep(2.5)
            _broadcast("idle")
            return True
        else:
            _broadcast("failed")
            time.sleep(2.5)
            _broadcast("idle")
            return False

    # Timed out — no face detected in frame
    _broadcast("failed")
    time.sleep(2.5)
    _broadcast("idle")
    return False


def delete_face_data() -> bool:
    """Remove stored face encoding."""
    if os.path.exists(FACE_DATA_FILE):
        os.remove(FACE_DATA_FILE)
        logger.info("[FaceAuth] Face data deleted.")
        return True
    return False
