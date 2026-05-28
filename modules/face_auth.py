"""
face_auth.py
Owner face enrollment + verification for iZACH.

face_recognition (dlib) runs in a subprocess — the main process never loads
dlib, so its ~200-400 MB is freed the moment the subprocess exits.

Broadcasts face_verify WebSocket events:
  {type: 'face_verify', state: 'enrolling'}  — during enrollment capture
  {type: 'face_verify', state: 'scanning'}   — during verification
  {type: 'face_verify', state: 'success'}    — identity confirmed
  {type: 'face_verify', state: 'failed'}     — mismatch or no face found
  {type: 'face_verify', state: 'idle'}       — reset UI
"""

import os
import time
import logging
import threading
import multiprocessing

logger = logging.getLogger(__name__)

FACE_DATA_FILE = "owner_face.pkl"
FACE_TOLERANCE = 0.50
ENROLL_FRAMES  = 5
VERIFY_TIMEOUT = 8.0

_speak_func = None
_enrolling  = False   # voice_loop checks this to pause mic during face enrollment


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
    except Exception as e:
        logger.debug(f"[FaceAuth] Broadcast failed ({state}): {e}")


def is_enrolled() -> bool:
    return os.path.exists(FACE_DATA_FILE)


# ── Subprocess workers ─────────────────────────────────────────
# Must be module-level for multiprocessing spawn pickling on Windows.
# face_recognition is imported ONLY inside these functions so dlib
# never touches the main process address space.

def _grab_rgb():
    """Open camera, grab one RGB frame, release immediately."""
    import cv2
    try:
        from modules.camera_vision import _cam_device_index as _idx
    except Exception:
        _idx = 0
    cap = cv2.VideoCapture(_idx, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        for _ in range(3):
            cap.read()
        ret, frame = cap.read()
        if ret:
            return cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
        return None
    finally:
        cap.release()


def _enroll_worker(data_file: str, result_q):
    """Subprocess target. Puts ('progress', n), ('done', True), or ('fail', reason)."""
    import pickle, time
    import numpy as np
    try:
        import face_recognition
    except ImportError:
        result_q.put(("fail", "face_recognition not installed"))
        return

    encodings = []
    attempts  = 0
    while len(encodings) < ENROLL_FRAMES and attempts < 20:
        time.sleep(0.7)
        attempts += 1
        frame = _grab_rgb()
        if frame is None:
            continue
        locs = face_recognition.face_locations(frame, model="hog")
        if not locs:
            continue
        enc = face_recognition.face_encodings(frame, locs)
        if not enc:
            continue
        encodings.append(enc[0])
        result_q.put(("progress", len(encodings)))

    if len(encodings) < 3:
        result_q.put(("fail", "not_enough_frames"))
        return

    avg = np.mean(encodings, axis=0)
    try:
        with open(data_file, "wb") as f:
            pickle.dump(avg, f)
        result_q.put(("done", True))
    except Exception as e:
        result_q.put(("fail", str(e)))


def _verify_worker(data_file: str, result_q):
    """Subprocess target. Puts ('done', bool) or ('fail', reason) or ('timeout', False)."""
    import pickle, time
    try:
        import face_recognition
    except ImportError:
        result_q.put(("fail", "face_recognition not installed"))
        return

    try:
        with open(data_file, "rb") as f:
            known = pickle.load(f)
    except Exception as e:
        result_q.put(("fail", f"load_error:{e}"))
        return

    deadline = time.time() + VERIFY_TIMEOUT
    while time.time() < deadline:
        frame = _grab_rgb()
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
        match = face_recognition.compare_faces([known], encs[0], tolerance=FACE_TOLERANCE)
        result_q.put(("done", bool(match[0])))
        return

    result_q.put(("timeout", False))


def _spawn_process(target, args):
    """Spawn a subprocess using the 'spawn' context (safe on Windows)."""
    ctx = multiprocessing.get_context("spawn")
    q   = ctx.Queue()
    p   = ctx.Process(target=target, args=(*args, q), daemon=True)
    p.start()
    return p, q


def _reap(p):
    p.join(timeout=5)
    if p.is_alive():
        p.terminate()


# ── Enrollment ────────────────────────────────────────────────

def enroll_owner(callback=None):
    """Non-blocking. dlib runs in subprocess and is freed on completion."""
    global _enrolling
    if _enrolling:
        logger.info("[FaceAuth] Enrollment already in progress.")
        return
    _enrolling = True

    def _monitor():
        global _enrolling
        try:
            _do_enroll()
        finally:
            _enrolling = False

    def _do_enroll():
        logger.info("[FaceAuth] Enrollment started — spawning subprocess.")
        _broadcast("enrolling")
        # Release any active camera stream in the main process so the
        # subprocess can open the camera. Windows allows only one process
        # to hold a camera handle at a time.
        try:
            from modules import camera_vision as _cv_mod
            with _cv_mod._stream_lock:
                if _cv_mod._stream_cap is not None:
                    _cv_mod._stream_cap.release()
                    _cv_mod._stream_cap = None
                    logger.info("[FaceAuth] Released main-process camera stream.")
        except Exception as _rel_err:
            logger.debug(f"[FaceAuth] Could not release stream: {_rel_err}")

        _speak("Look directly at the camera. Stay still — capturing your face now.")
        try:
            p, q = _spawn_process(_enroll_worker, (FACE_DATA_FILE,))
        except Exception as _spawn_err:
            logger.error(f"[FaceAuth] Subprocess spawn failed: {_spawn_err}")
            _broadcast("failed")
            _speak("Could not start face enrollment subprocess.")
            if callback:
                callback(False)
            return

        while True:
            try:
                event, value = q.get(timeout=30)
            except Exception:
                logger.warning("[FaceAuth] Enrollment timed out waiting for subprocess.")
                _broadcast("failed")
                _speak("Face enrollment timed out.")
                p.terminate()
                break

            if event == "progress":
                _speak(f"Frame {value} of {ENROLL_FRAMES}.")
            elif event == "done":
                _broadcast("success")
                _speak("Face enrolled. I'll recognize you from now on.")
                logger.info("[FaceAuth] Owner face enrolled successfully.")
                time.sleep(3)
                _broadcast("idle")
                if callback:
                    callback(True)
                break
            elif event == "fail":
                _broadcast("failed")
                if value == "not_enough_frames":
                    _speak("Could not detect your face in enough frames. Try again with better lighting.")
                else:
                    _speak(f"Could not save face data: {value}")
                time.sleep(3)
                _broadcast("idle")
                if callback:
                    callback(False)
                break

        _reap(p)

    threading.Thread(target=_monitor, daemon=True).start()


# ── Verification ──────────────────────────────────────────────

def verify_owner() -> bool:
    """Blocking. dlib runs in subprocess and is freed on return."""
    if not is_enrolled():
        _speak("No face enrolled yet. Say 'enroll my face' first.")
        return False

    _broadcast("scanning")
    p, q = _spawn_process(_verify_worker, (FACE_DATA_FILE,))

    try:
        event, value = q.get(timeout=VERIFY_TIMEOUT + 5)
    except Exception:
        _broadcast("failed")
        time.sleep(2.5)
        _broadcast("idle")
        p.terminate()
        _reap(p)
        return False

    _reap(p)

    if event == "done":
        _broadcast("success" if value else "failed")
        time.sleep(2.5)
        _broadcast("idle")
        return bool(value)

    _broadcast("failed")
    time.sleep(2.5)
    _broadcast("idle")
    return False


# ── Cleanup ───────────────────────────────────────────────────

def delete_face_data() -> bool:
    if os.path.exists(FACE_DATA_FILE):
        os.remove(FACE_DATA_FILE)
        logger.info("[FaceAuth] Face data deleted.")
        return True
    return False
