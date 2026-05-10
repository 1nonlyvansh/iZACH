"""
modules/vision_engine.py
AURA Vision Engine integrated into iZACH.

This module is the single entry point for all camera-based features:
- Camera feed with 15fps cap (no lag)
- Gesture detection (pinch = volume/brightness, five = swipe, fist = show desktop)
- Face verification for sensitive commands
- Camera switching (webcam / integrated cam)
- Callback-based design — never imports from ui.py or main.py directly

Architecture:
  CameraService  → grabs frames, flips, distributes to:
  GestureEngine  → detects gestures, fires on_gesture callback
  FaceVerifier   → verifies identity on demand (blocking call, runs on current frame)
  VisionEngine   → public API, owns all of the above
"""

import threading
import time
import queue
import cv2
import numpy as np
from typing import Optional, Callable

# ─────────────────────────────────────────────
# AURA imports — copy vision/ and config/ from
# AURA into C:\Projects\iZACH\modules\vision\
# and C:\Projects\iZACH\modules\vision_config\
# ─────────────────────────────────────────────

_GESTURE_ENGINE_OK = False
_FACE_AUTH_OK      = False

try:
    import sys, os, types
    # Allow importing AURA modules from modules/vision_config and modules/vision_modules
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(_HERE, "vision_config"))
    sys.path.insert(0, _HERE)

    # vision_modules internally import 'config.constants' — alias to vision_config
    if "config" not in sys.modules:
        _config_pkg = types.ModuleType("config")
        _config_pkg.__path__ = [os.path.join(_HERE, "vision_config")]
        _config_pkg.__package__ = "config"
        sys.modules["config"] = _config_pkg

    from vision_modules.gesture_engine import GestureEngine
    from vision_config.constants import DEFAULT_DESKTOP_MAPPINGS, DEFAULT_MUSIC_MAPPINGS
    _GESTURE_ENGINE_OK = True
    print("[VISION] Gesture engine loaded.")
except ImportError as e:
    print(f"[VISION] Gesture engine not available: {e}")

try:
    from vision_modules.face_auth import FaceVerifier
    _FACE_AUTH_OK = True
    print("[VISION] Face auth loaded.")
except ImportError as e:
    print(f"[VISION] Face auth not available: {e}")


# ─────────────────────────────────────────────
# Face DB — minimal JSON-based store
# (replaces AURA's full user_manager for iZACH)
# ─────────────────────────────────────────────

class _FaceDB:
    """Minimal face encoding database backed by users.json."""

    def __init__(self, path: str = "users.json"):
        import json
        self._path = path
        self._data: dict = {}
        try:
            with open(path) as f:
                raw = json.load(f)
            # Convert list encodings back to numpy arrays
            for username, info in raw.items():
                if "encoding" in info and info["encoding"]:
                    self._data[username] = np.array(info["encoding"])
        except Exception:
            pass

    def get_encoding(self, username: str) -> Optional[np.ndarray]:
        return self._data.get(username)

    def get_all_encodings(self):
        names     = list(self._data.keys())
        encodings = list(self._data.values())
        return encodings, names

    def reload(self):
        """Reload encodings from disk in-place (keeps verifier reference valid)."""
        import json as _json
        self._data = {}
        try:
            with open(self._path) as f:
                raw = _json.load(f)
            for username, info in raw.items():
                if "encoding" in info and info["encoding"]:
                    self._data[username] = np.array(info["encoding"])
        except Exception:
            pass


# ─────────────────────────────────────────────
# Camera discovery
# ─────────────────────────────────────────────

def list_cameras(max_check: int = 6) -> list[int]:
    """Return list of available camera indices."""
    available = []
    for i in range(max_check):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available.append(i)
        cap.release()
    return available or [0]


# ─────────────────────────────────────────────
# VisionEngine — public API
# ─────────────────────────────────────────────

class VisionEngine:
    """
    Public API for iZACH vision features.

    Usage:
        ve = VisionEngine(on_gesture=handle_gesture, on_frame=ui.update_camera)
        ve.start()
        ...
        ve.stop()

    on_gesture(gesture_name, action, metadata) — called on each gesture
    on_frame(bgr_frame)                        — called ~15fps for UI display
    """

    TARGET_FPS    = 15
    FRAME_DELAY   = 1.0 / TARGET_FPS
    GESTURE_MODE  = "desktop"   # "desktop" or "music"

    def __init__(
        self,
        on_gesture: Optional[Callable] = None,
        on_frame:   Optional[Callable] = None,
        camera_idx: int = 0,
    ):
        self._on_gesture  = on_gesture
        self._on_frame    = on_frame
        self._cam_idx     = camera_idx
        self._running     = False
        self._thread      = None
        self._cap         = None
        self._lock        = threading.Lock()

        # Latest frame (BGR) — readable externally
        self._latest_frame: Optional[np.ndarray] = None
        self._pending_frame = False

        # Gesture engine
        self._gesture_engine: Optional[GestureEngine] = None
        if _GESTURE_ENGINE_OK:
            try:
                self._gesture_engine = GestureEngine(
                    on_gesture=self._gesture_callback,
                    draw_landmarks=True
                )
            except Exception as _ge_err:
                print(f"[VISION] Gesture init failed (protobuf conflict?): {_ge_err}")

        # Face verifier
        self._face_db = _FaceDB("users.json")
        self._verifier: Optional[FaceVerifier] = None
        if _FACE_AUTH_OK:
            try:
                self._verifier = FaceVerifier(self._face_db)
            except Exception as _fv_err:
                print(f"[VISION] Face verifier init failed: {_fv_err}")

        # Camera list
        self._available_cameras: list[int] = []

    # ─────────────────────────────────────────
    # Start / Stop
    # ─────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._available_cameras = list_cameras()
        print(f"[VISION] Cameras found: {self._available_cameras}")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[VISION] Started on camera {self._cam_idx}")

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
        if self._gesture_engine:
            self._gesture_engine.close()
        print("[VISION] Stopped.")

    def switch_camera(self, idx: int):
        """Switch to a different camera index."""
        with self._lock:
            self._cam_idx = idx
            if self._cap:
                self._cap.release()
                self._cap = None
        print(f"[VISION] Switching to camera {idx}")

    def next_camera(self) -> int:
        """Cycle to next available camera. Returns new index."""
        if not self._available_cameras:
            return self._cam_idx
        current_pos = self._available_cameras.index(self._cam_idx) \
            if self._cam_idx in self._available_cameras else 0
        next_pos = (current_pos + 1) % len(self._available_cameras)
        new_idx = self._available_cameras[next_pos]
        self.switch_camera(new_idx)
        return new_idx

    def get_camera_list(self) -> list[int]:
        return self._available_cameras

    def set_gesture_mode(self, mode: str):
        """Switch gesture profile: 'desktop' or 'music'."""
        if not self._gesture_engine:
            return
        if mode == "music":
            from vision_config.constants import DEFAULT_MUSIC_MAPPINGS
            self._gesture_engine.set_profile("music", DEFAULT_MUSIC_MAPPINGS)
        else:
            from vision_config.constants import DEFAULT_DESKTOP_MAPPINGS
            self._gesture_engine.set_profile("desktop", DEFAULT_DESKTOP_MAPPINGS)
        print(f"[VISION] Gesture mode → {mode}")

    # ─────────────────────────────────────────
    # Face auth — DeepFace (ArcFace) backend
    # Reads/writes users.json directly on every
    # call so enrolled faces persist across sessions
    # with no stale in-memory reference issues.
    # ─────────────────────────────────────────

    _DEEPFACE_MODEL    = "ArcFace"
    _DEEPFACE_DETECTOR = "opencv"
    _DEEPFACE_THRESHOLD = 0.68   # cosine distance; lower = stricter

    def _load_face_db(self) -> dict:
        """Read users.json fresh from disk."""
        import json as _json
        try:
            with open(self._face_db._path) as f:
                return _json.load(f)
        except Exception:
            return {}

    def _save_face_db(self, data: dict):
        """Write users.json to disk and reload in-memory cache."""
        import json as _json
        with open(self._face_db._path, "w") as f:
            _json.dump(data, f, indent=2)
        self._face_db.reload()

    def _get_embedding(self, frame_bgr: np.ndarray, enforce_detection: bool = True):
        """
        Return DeepFace ArcFace embedding for a BGR frame.
        Returns numpy array or raises on failure.
        """
        from deepface import DeepFace
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = DeepFace.represent(
            img_path=rgb,
            model_name=self._DEEPFACE_MODEL,
            detector_backend=self._DEEPFACE_DETECTOR,
            enforce_detection=enforce_detection,
            align=True,
        )
        if not result:
            raise ValueError("No face detected.")
        return np.array(result[0]["embedding"])

    def verify_face(self, expected_username: str = "vansh") -> bool:
        """
        Verify identity against stored DeepFace embedding.
        Reads users.json fresh each call — persistent across sessions.
        Returns True if face matches.
        """
        frame = self._latest_frame
        if frame is None:
            print("[VISION] No frame — is camera running?")
            return False

        data = self._load_face_db()
        if expected_username not in data:
            print(f"[VISION] No enrolled face for '{expected_username}'. Say 'enroll my face' first.")
            return False

        stored = np.array(data[expected_username].get("encoding", []))
        if stored.size == 0:
            print("[VISION] Stored encoding is empty — re-enroll.")
            return False

        try:
            live = self._get_embedding(frame, enforce_detection=False)
            # Cosine distance: 0 = identical, 1 = orthogonal, 2 = opposite
            stored_n = stored / (np.linalg.norm(stored) + 1e-10)
            live_n   = live   / (np.linalg.norm(live)   + 1e-10)
            dist = float(1.0 - np.dot(stored_n, live_n))
            verified = dist < self._DEEPFACE_THRESHOLD
            conf = round(1.0 - dist, 3)
            print(f"[VISION] DeepFace verify: dist={dist:.4f} threshold={self._DEEPFACE_THRESHOLD} match={verified} conf={conf}")
            return verified
        except ImportError:
            print("[VISION] DeepFace not installed. Run: pip install deepface tf-keras")
            return False
        except Exception as e:
            print(f"[VISION] Verification error: {e}")
            return False

    def enroll_face(self, username: str) -> tuple:
        """
        Capture current frame, extract ArcFace 512D embedding, save to users.json.
        Face stays enrolled permanently — no need to re-enroll each session.
        Returns (True, message) on success, (False, message) on failure.
        """
        frame = self._latest_frame
        if frame is None:
            return False, "No camera frame. Is the camera on?"
        try:
            embedding = self._get_embedding(frame, enforce_detection=True)
            data = self._load_face_db()
            data[username] = {
                "encoding": embedding.tolist(),
                "model": self._DEEPFACE_MODEL,
            }
            self._save_face_db(data)
            print(f"[VISION] DeepFace enrolled '{username}' — {len(embedding)}D ArcFace embedding saved.")
            return True, f"Face enrolled. I'll recognize you from now on, no need to enroll again."
        except ImportError:
            return False, "DeepFace not installed. Run: pip install deepface tf-keras"
        except ValueError as e:
            return False, f"No face detected. Look directly at the camera and try again."
        except Exception as e:
            return False, f"Enrollment failed: {e}"

    def get_latest_frame(self) -> Optional[np.ndarray]:
        return self._latest_frame

    # ─────────────────────────────────────────
    # Internal loop
    # ─────────────────────────────────────────

    def _open_camera(self) -> bool:
        try:
            self._cap = cv2.VideoCapture(self._cam_idx, cv2.CAP_DSHOW)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FPS, 30)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # minimize buffer lag
            return self._cap.isOpened()
        except Exception as e:
            print(f"[VISION] Camera open error: {e}")
            return False

    def _loop(self):
        if not self._open_camera():
            print(f"[VISION] Could not open camera {self._cam_idx}")
            return

        while self._running:
            t_start = time.time()

            with self._lock:
                cam_idx = self._cam_idx

            # Reopen if camera changed
            if self._cap and not self._cap.isOpened():
                self._open_camera()
                time.sleep(0.5)
                continue

            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            # Flip for mirror view
            frame = cv2.flip(frame, 1)

            # Run gesture engine — modifies frame with landmarks
            if self._gesture_engine:
                try:
                    frame = self._gesture_engine.process_frame(frame)
                except Exception as e:
                    pass  # gesture errors never crash the camera

            # Store latest frame
            self._latest_frame = frame

            # Push to UI — skip if previous frame not consumed
            if self._on_frame and not self._pending_frame:
                self._pending_frame = True
                try:
                    self._on_frame(frame, self._done_with_frame)
                except Exception:
                    self._pending_frame = False

            # Sleep to hit target FPS
            elapsed = time.time() - t_start
            sleep_t = self.FRAME_DELAY - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

        if self._cap:
            self._cap.release()

    def _done_with_frame(self):
        """Called by UI after it finishes processing a frame."""
        self._pending_frame = False

    def _gesture_callback(self, gesture_name: str, action: str, metadata: dict):
        """Internal — fires the user-provided on_gesture callback."""
        if self._on_gesture:
            try:
                self._on_gesture(gesture_name, action, metadata)
            except Exception as e:
                print(f"[VISION] Gesture callback error: {e}")


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_engine: Optional[VisionEngine] = None
_aura_enabled: bool = False  # AURA off by default in Electron mode

def get_vision_engine() -> Optional[VisionEngine]:
    return _engine

def is_aura_enabled() -> bool:
    return _aura_enabled

def set_aura_enabled(enabled: bool):
    global _aura_enabled
    _aura_enabled = enabled
    if _engine:
        if enabled and not _engine._running:
            _engine.start()
        elif not enabled and _engine._running:
            # Stop gesture processing but keep camera alive for vision queries
            if _engine._gesture_engine:
                _engine._gesture_engine = None
    print(f"[VISION] AURA gestures {'enabled' if enabled else 'disabled'}")

def init_vision_engine(
    on_gesture: Optional[Callable] = None,
    on_frame:   Optional[Callable] = None,
    camera_idx: int = 0,
) -> VisionEngine:
    global _engine
    _engine = VisionEngine(on_gesture=on_gesture, on_frame=on_frame, camera_idx=camera_idx)
    return _engine