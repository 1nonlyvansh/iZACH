# =============================================================================
# vision/face_auth.py
# Face recognition logic — no camera, no PyQt5, no UI of any kind.
#
# iZACH / AURA provides frames from its own camera service.
# These classes process one frame at a time and return structured results.
#
# Two operating modes:
#   1. FaceAuthenticator  — full login flow (nod-to-confirm)
#   2. FaceVerifier       — quick mid-session check for sensitive commands
#
# Usage example (iZACH):
#
#   auth = FaceAuthenticator(db_manager, username="vansh")
#   result = auth.process_frame(rgb_frame)
#   # result.status in ["scanning", "matched", "nod_required", "confirmed", "mismatch"]
#   if result.status == "confirmed":
#       izach.login(result.username)
#
#   verifier = FaceVerifier(db_manager)
#   result = verifier.verify(rgb_frame)
#   if result.verified:
#       execute_sensitive_command()
# =============================================================================

import time
from dataclasses import dataclass, field
from typing import Optional

import face_recognition
import numpy as np

from config.constants import FACE_SCAN_HOLD_FRAMES, FACE_RECOGNITION_TOL, NOD_THRESHOLD


# =============================================================================
# Shared result types
# =============================================================================

@dataclass
class AuthResult:
    """Returned by FaceAuthenticator.process_frame() each frame."""
    status: str                     # "scanning" | "matched" | "nod_required" | "confirmed" | "mismatch" | "unknown"
    username: Optional[str] = None  # populated once face is matched
    face_location: Optional[tuple] = None  # (top, right, bottom, left) in ORIGINAL frame coords
    message: str = ""               # human-readable status for overlays / TTS


@dataclass
class VerifyResult:
    """Returned by FaceVerifier.verify()."""
    verified: bool
    username: Optional[str] = None
    confidence: float = 0.0         # 1.0 - face_distance; higher = more confident
    message: str = ""


@dataclass
class RegistrationResult:
    """Returned by FaceRegistrar.process_frame() each frame."""
    status: str                     # "scanning" | "holding" | "duplicate" | "success" | "no_face"
    frames_held: int = 0
    frames_needed: int = FACE_SCAN_HOLD_FRAMES
    face_location: Optional[tuple] = None
    message: str = ""


# =============================================================================
# FaceRegistrar — collects a stable face encoding for a new user
# =============================================================================

class FaceRegistrar:
    """
    Feed it RGB frames from your camera service.
    When status == "success", call db_manager.add_user() with the encoding.

    Example:
        registrar = FaceRegistrar(db_manager)
        # per frame:
        result = registrar.process_frame(rgb_frame)
        if result.status == "success":
            db_manager.add_user(username, password, display_name, registrar.captured_encoding)
    """

    def __init__(self, db_manager, frames_needed: int = FACE_SCAN_HOLD_FRAMES):
        self.db_manager = db_manager
        self.frames_needed = frames_needed
        self.frames_held = 0
        self.captured_encoding: Optional[np.ndarray] = None
        self._frame_counter = 0

    def reset(self):
        self.frames_held = 0
        self.captured_encoding = None
        self._frame_counter = 0

    def process_frame(self, rgb_frame: np.ndarray) -> RegistrationResult:
        """
        rgb_frame: HxWx3 numpy array in RGB colour space.
        Only runs face detection every 4 frames for performance.
        """
        self._frame_counter += 1

        # Skip heavy processing on non-key frames
        if self._frame_counter % 4 != 0:
            return RegistrationResult(
                status="scanning",
                frames_held=self.frames_held,
                frames_needed=self.frames_needed,
                message="Scanning...",
            )

        small = _resize(rgb_frame, 0.25)
        locations = face_recognition.face_locations(small)

        if not locations:
            self.frames_held = 0
            return RegistrationResult(
                status="scanning",
                frames_held=0,
                frames_needed=self.frames_needed,
                message="No face detected. Position yourself in frame.",
            )

        # Scale location back to original frame size
        loc = tuple(v * 4 for v in locations[0])  # (top, right, bottom, left)
        self.frames_held += 1

        if self.frames_held < self.frames_needed:
            return RegistrationResult(
                status="holding",
                frames_held=self.frames_held,
                frames_needed=self.frames_needed,
                face_location=loc,
                message=f"Hold still... {self.frames_held}/{self.frames_needed}",
            )

        # Enough frames held — capture encoding at full resolution
        encodings = face_recognition.face_encodings(rgb_frame)
        if not encodings:
            self.frames_held = 0
            return RegistrationResult(
                status="no_face",
                frames_held=0,
                frames_needed=self.frames_needed,
                message="Could not extract face encoding. Try again.",
            )

        new_encoding = encodings[0]

        # Duplicate check
        known_encodings, _ = self.db_manager.get_all_encodings()
        if known_encodings:
            matches = face_recognition.compare_faces(
                known_encodings, new_encoding, tolerance=FACE_RECOGNITION_TOL
            )
            if True in matches:
                return RegistrationResult(
                    status="duplicate",
                    message="This face is already registered to another account.",
                )

        self.captured_encoding = new_encoding
        return RegistrationResult(
            status="success",
            frames_held=self.frames_held,
            frames_needed=self.frames_needed,
            face_location=loc,
            message="Face captured successfully.",
        )


# =============================================================================
# FaceAuthenticator — login flow with nod-to-confirm
# =============================================================================

class FaceAuthenticator:
    """
    Stateful per-login-attempt authenticator.
    Two sub-modes:
        mode="specific"  → matches against one known username (standard login)
        mode="global"    → scans all users and identifies whoever is present
                           (used for face-only login and password recovery)

    Nod detection:
        Once face is matched, user must nod (head dip then rise) to confirm.
        This prevents a photo from being held up to the camera to log in.

    Reset between attempts with .reset().
    """

    def __init__(self, db_manager, username: Optional[str] = None):
        """
        username: if provided, only matches against this user (specific mode).
                  if None, matches against all users (global mode).
        """
        self.db_manager = db_manager
        self.target_username = username
        self.mode = "specific" if username else "global"
        self.reset()

    def reset(self):
        self.matched_username: Optional[str] = None
        self.face_matched = False
        self.initial_nose_y: float = 0
        self.nod_down = False
        self._frame_counter = 0

    def process_frame(self, rgb_frame: np.ndarray) -> AuthResult:
        """
        rgb_frame: HxWx3 numpy array in RGB.
        Call this once per frame from your camera service loop.
        """
        self._frame_counter += 1

        # Process every other frame only
        if self._frame_counter % 2 != 0:
            status = "nod_required" if self.face_matched else "scanning"
            return AuthResult(status=status, username=self.matched_username, message="")

        small = _resize(rgb_frame, 0.5)
        locations = face_recognition.face_locations(small)
        encodings = face_recognition.face_encodings(small, locations)
        landmarks_list = face_recognition.face_landmarks(small, locations)

        if not encodings:
            # Face lost — reset nod state but keep matched_username if we had one
            self.face_matched = False
            self.initial_nose_y = 0
            self.nod_down = False
            return AuthResult(
                status="scanning",
                message="No face detected.",
            )

        # --- Match phase ---
        if not self.face_matched:
            matched_name = self._match(encodings[0])
            if matched_name:
                self.face_matched = True
                self.matched_username = matched_name
                if landmarks_list:
                    self.initial_nose_y = landmarks_list[0]["nose_bridge"][0][1]
            else:
                status = "mismatch" if self.target_username else "unknown"
                msg = "Identity mismatch." if self.target_username else "Unknown face."
                loc = _scale_location(locations[0], 2)
                return AuthResult(status=status, face_location=loc, message=msg)

        # --- Nod phase ---
        loc = _scale_location(locations[0], 2)
        if landmarks_list:
            current_nose_y = landmarks_list[0]["nose_bridge"][0][1]

            if current_nose_y > self.initial_nose_y + NOD_THRESHOLD:
                self.nod_down = True

            if self.nod_down and current_nose_y < self.initial_nose_y - NOD_THRESHOLD:
                return AuthResult(
                    status="confirmed",
                    username=self.matched_username,
                    face_location=loc,
                    message=f"Identity confirmed: {self.matched_username}",
                )

        return AuthResult(
            status="nod_required",
            username=self.matched_username,
            face_location=loc,
            message=f"Face matched: {self.matched_username}. Please nod once to confirm.",
        )

    def _match(self, encoding: np.ndarray) -> Optional[str]:
        if self.mode == "specific":
            known = self.db_manager.get_encoding(self.target_username)
            if known is None:
                return None
            match = face_recognition.compare_faces(
                [known], encoding, tolerance=FACE_RECOGNITION_TOL
            )
            return self.target_username if match[0] else None
        else:
            known_encodings, known_names = self.db_manager.get_all_encodings()
            if not known_encodings:
                return None
            matches = face_recognition.compare_faces(
                known_encodings, encoding, tolerance=FACE_RECOGNITION_TOL
            )
            if True in matches:
                return known_names[matches.index(True)]
            return None


# =============================================================================
# FaceVerifier — quick single-frame mid-session identity check
# =============================================================================

class FaceVerifier:
    """
    Used by iZACH to gate sensitive commands.
    Does NOT require a nod — just a clean face match in the current frame.
    Intended to be called on a single frame, not looped.

    Example in iZACH command router:
        verifier = FaceVerifier(db_manager)

        # When "send file to friend" command is received:
        frame = camera_service.get_frame()
        result = verifier.verify(frame, expected_username=session.current_user)
        if result.verified:
            execute_command()
        else:
            izach.speak("I couldn't verify your identity. Command blocked.")
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def verify(
        self,
        rgb_frame: np.ndarray,
        expected_username: Optional[str] = None,
    ) -> VerifyResult:
        """
        rgb_frame: single RGB frame.
        expected_username: if provided, only verifies against this user.
                           if None, verifies against all users (any registered face).
        Returns VerifyResult with verified=True/False.
        """
        small = _resize(rgb_frame, 0.5)
        locations = face_recognition.face_locations(small)
        encodings = face_recognition.face_encodings(small, locations)

        if not encodings:
            return VerifyResult(
                verified=False,
                message="No face detected in frame.",
            )

        encoding = encodings[0]

        if expected_username:
            known = self.db_manager.get_encoding(expected_username)
            if known is None:
                return VerifyResult(
                    verified=False,
                    message=f"No registered face for user '{expected_username}'.",
                )
            distances = face_recognition.face_distance([known], encoding)
            match = distances[0] <= FACE_RECOGNITION_TOL
            confidence = round(1.0 - float(distances[0]), 3)
            return VerifyResult(
                verified=bool(match),
                username=expected_username if match else None,
                confidence=confidence,
                message="Verified." if match else "Face does not match session user.",
            )
        else:
            known_encodings, known_names = self.db_manager.get_all_encodings()
            if not known_encodings:
                return VerifyResult(verified=False, message="No registered users.")
            distances = face_recognition.face_distance(known_encodings, encoding)
            best_idx = int(np.argmin(distances))
            best_dist = distances[best_idx]
            if best_dist <= FACE_RECOGNITION_TOL:
                return VerifyResult(
                    verified=True,
                    username=known_names[best_idx],
                    confidence=round(1.0 - float(best_dist), 3),
                    message=f"Verified as {known_names[best_idx]}.",
                )
            return VerifyResult(
                verified=False,
                message="Unknown face.",
            )


# =============================================================================
# Private helpers
# =============================================================================

def _resize(rgb_frame: np.ndarray, scale: float) -> np.ndarray:
    import cv2
    return cv2.resize(rgb_frame, (0, 0), fx=scale, fy=scale)


def _scale_location(location: tuple, factor: int) -> tuple:
    """Scale a face location tuple back up after processing on a downscaled frame."""
    top, right, bottom, left = location
    return (top * factor, right * factor, bottom * factor, left * factor)