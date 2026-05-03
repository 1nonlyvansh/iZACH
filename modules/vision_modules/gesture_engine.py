# =============================================================================
# vision/gesture_engine.py
# Gesture detection and action execution — no camera, no PyQt5.
#
# iZACH / AURA provides frames. This module processes them and fires callbacks.
#
# Callback-based design:
#   Instead of hardcoding what happens on each gesture, you register a callback.
#   iZACH provides its own callback. AURA provides its own callback.
#   The engine doesn't care — it just detects and calls.
#
# Usage (iZACH):
#   engine = GestureEngine(on_gesture=izach.handle_gesture)
#   engine.set_profile("desktop", mappings)
#   # per frame from camera service:
#   annotated_frame = engine.process_frame(rgb_frame)
#
# Usage (AURA standalone):
#   engine = GestureEngine(on_gesture=aura_action_executor)
#
# The on_gesture callback signature:
#   def on_gesture(gesture_name: str, action: str, metadata: dict): ...
#   gesture_name: e.g. "right_pinch", "left_fist"
#   action:       e.g. "volume_control", "none"
#   metadata:     {"lm_list": [...], "hand_label": "right", "frame": np.ndarray}
#                 frame is the annotated BGR frame — draw on it if you want overlays
# =============================================================================

import time
import math
from typing import Callable, Optional

import cv2
import mediapipe as mp
import numpy as np
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import screen_brightness_control as sbc
import pyautogui

from config.constants import (
    DEFAULT_DESKTOP_MAPPINGS,
    SWIPE_THRESHOLD_X,
    SWIPE_COOLDOWN,
    FIST_THRESHOLD,
)


# =============================================================================
# GestureEngine
# =============================================================================

class GestureEngine:
    """
    Stateful gesture processor. Feed it one BGR frame per call.
    Returns the frame with MediaPipe landmarks drawn on it (optional).

    Parameters
    ----------
    on_gesture : callable
        Called when a gesture is detected.
        Signature: on_gesture(gesture_name, action, metadata)
    draw_landmarks : bool
        Whether to draw hand landmarks on the returned frame.
    """

    def __init__(
        self,
        on_gesture: Optional[Callable] = None,
        draw_landmarks: bool = True,
    ):
        self.on_gesture = on_gesture or _default_gesture_callback
        self.draw_landmarks = draw_landmarks

        # MediaPipe
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            max_num_hands=2,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
        )
        self._mp_draw = mp.solutions.drawing_utils

        # Profile state
        self.active_profile: str = "desktop"
        self.gesture_mappings: dict = DEFAULT_DESKTOP_MAPPINGS.copy()

        # Gesture timing / tracking state
        self._fist_counter = 0
        self._swipe_start_pos = {"left": None, "right": None}
        self._last_swipe_time = 0.0
        self._last_hand_results = None
        self._frame_counter = 0

        # System control (volume)
        self._keyboard = KeyboardController()
        self._volume, self._min_vol, self._max_vol = _init_volume()

        # Last detected gesture (readable externally)
        self.last_gesture: Optional[str] = None

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def set_profile(self, profile_name: str, mappings: dict):
        """Switch the active gesture profile and its action mappings."""
        self.active_profile = profile_name
        self.gesture_mappings = mappings
        self._reset_gesture_state()

    def _reset_gesture_state(self):
        self._fist_counter = 0
        self._swipe_start_pos = {"left": None, "right": None}
        self._last_swipe_time = 0.0

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_frame(self, bgr_frame: np.ndarray) -> np.ndarray:
        """
        bgr_frame: HxWx3 BGR numpy array (standard OpenCV format).
        Returns the frame with optional landmark annotations.
        Flipping is NOT done here — the caller (camera service) should flip.
        """
        self._frame_counter += 1
        frame = bgr_frame.copy()

        # Run MediaPipe every other frame
        if self._frame_counter % 2 == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._last_hand_results = self._hands.process(rgb)

        if not (
            self._last_hand_results and
            self._last_hand_results.multi_hand_landmarks
        ):
            self.last_gesture = None
            return frame

        for hand_idx, hand_landmarks in enumerate(
            self._last_hand_results.multi_hand_landmarks
        ):
            handedness_label = (
                self._last_hand_results
                .multi_handedness[hand_idx]
                .classification[0]
                .label
            )
            # MediaPipe labels are mirrored when using a flipped frame
            is_right_on_screen = handedness_label == "Left"
            hand_label = "right" if is_right_on_screen else "left"

            lm_list = _extract_landmarks(hand_landmarks, frame.shape)
            if not lm_list:
                continue

            fingers = _detect_fingers(lm_list, handedness_label)
            gesture = self._classify_gesture(fingers, hand_label)
            self.last_gesture = gesture

            if gesture:
                action = self.gesture_mappings.get(gesture, "none")
                metadata = {
                    "lm_list":   lm_list,
                    "hand_label": hand_label,
                    "frame":     frame,
                    "fingers":   fingers,
                }
                # Execute built-in system actions
                self._execute_action(action, lm_list, hand_label, frame)
                # Fire the callback so iZACH / AURA can react too
                self.on_gesture(gesture, action, metadata)

            if self.draw_landmarks:
                self._mp_draw.draw_landmarks(
                    frame, hand_landmarks, self._mp_hands.HAND_CONNECTIONS
                )

        return frame

    # ------------------------------------------------------------------
    # Gesture classification
    # ------------------------------------------------------------------

    def _classify_gesture(self, fingers: list, hand_label: str) -> Optional[str]:
        """
        Maps a finger state list to a named gesture string.
        Returns None if no recognised gesture.
        """
        # Cursor and keyboard profiles are handled by their own engines.
        # Here we only classify the gestures used in desktop/music profiles.
        if fingers == [1, 1, 0, 0, 0]:
            self._fist_counter = 0
            return f"{hand_label}_pinch"

        if sum(fingers) == 5:
            self._fist_counter = 0
            return f"{hand_label}_five_swipe"

        if sum(fingers) == 0:
            self._fist_counter += 1
            if self._fist_counter > FIST_THRESHOLD:
                return f"{hand_label}_fist"
        else:
            self._fist_counter = 0
            self._swipe_start_pos[hand_label] = None

        return None

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def _execute_action(
        self,
        action: str,
        lm_list: list,
        hand_label: str,
        frame: np.ndarray,
    ):
        if action == "none" or not action:
            return

        if action == "volume_control":
            self._action_volume(lm_list, frame)

        elif action == "brightness_control":
            self._action_brightness(lm_list, frame)

        elif action in ("switch_desktops", "next_track", "prev_track"):
            self._action_swipe(action, lm_list, hand_label)

        elif action == "show_desktop":
            self._action_show_desktop()

        elif action == "play_pause":
            self._action_media(Key.media_play_pause)

        elif action == "mute_unmute":
            self._action_media(Key.media_volume_mute)

    def _action_volume(self, lm_list: list, frame: np.ndarray):
        x1, y1 = lm_list[4][1], lm_list[4][2]
        x2, y2 = lm_list[8][1], lm_list[8][2]
        length = math.hypot(x2 - x1, y2 - y1)
        cv2.line(frame, (x1, y1), (x2, y2), (255, 0, 255), 3)
        vol = np.interp(length, [25, 200], [self._min_vol, self._max_vol])
        vol_bar = np.interp(length, [25, 200], [400, 150])
        vol_percent = np.interp(length, [25, 200], [0, 100])
        if self._volume:
            self._volume.SetMasterVolumeLevel(vol, None)
        cv2.rectangle(frame, (1180, 150), (1215, 400), (0, 255, 0), 3)
        cv2.rectangle(frame, (1180, int(vol_bar)), (1215, 400), (0, 255, 0), cv2.FILLED)
        cv2.putText(frame, f"{int(vol_percent)} %", (1160, 450),
                    cv2.FONT_HERSHEY_COMPLEX, 1, (0, 255, 0), 3)

    def _action_brightness(self, lm_list: list, frame: np.ndarray):
        x1, y1 = lm_list[4][1], lm_list[4][2]
        x2, y2 = lm_list[8][1], lm_list[8][2]
        length = math.hypot(x2 - x1, y2 - y1)
        cv2.line(frame, (x1, y1), (x2, y2), (255, 0, 255), 3)
        brightness = np.interp(length, [25, 200], [0, 100])
        bright_bar = np.interp(length, [25, 200], [400, 150])
        try:
            sbc.set_brightness(int(brightness))
        except Exception:
            pass
        cv2.rectangle(frame, (50, 150), (85, 400), (255, 150, 0), 3)
        cv2.rectangle(frame, (50, int(bright_bar)), (85, 400), (255, 150, 0), cv2.FILLED)
        cv2.putText(frame, f"{int(brightness)} %", (40, 450),
                    cv2.FONT_HERSHEY_COMPLEX, 1, (255, 150, 0), 3)

    def _action_swipe(self, action: str, lm_list: list, hand_label: str):
        hand_center_x = lm_list[9][1]
        if self._swipe_start_pos[hand_label] is None:
            self._swipe_start_pos[hand_label] = hand_center_x
        delta_x = hand_center_x - self._swipe_start_pos[hand_label]
        if abs(delta_x) > SWIPE_THRESHOLD_X and \
                (time.time() - self._last_swipe_time) > SWIPE_COOLDOWN:
            if action == "switch_desktops":
                key = Key.right if delta_x > 0 else Key.left
                self._keyboard.press(Key.ctrl)
                self._keyboard.press(Key.meta)
                self._keyboard.press(key)
                self._keyboard.release(key)
                self._keyboard.release(Key.meta)
                self._keyboard.release(Key.ctrl)
            elif action == "next_track":
                self._keyboard.press(Key.media_next)
                self._keyboard.release(Key.media_next)
            elif action == "prev_track":
                self._keyboard.press(Key.media_previous)
                self._keyboard.release(Key.media_previous)
            self._last_swipe_time = time.time()
            self._swipe_start_pos[hand_label] = None

    def _action_show_desktop(self):
        if (time.time() - self._last_swipe_time) > SWIPE_COOLDOWN:
            self._keyboard.press(Key.meta)
            self._keyboard.press("d")
            self._keyboard.release("d")
            self._keyboard.release(Key.meta)
            self._last_swipe_time = time.time()

    def _action_media(self, key):
        if (time.time() - self._last_swipe_time) > SWIPE_COOLDOWN:
            self._keyboard.press(key)
            self._keyboard.release(key)
            self._last_swipe_time = time.time()

    def close(self):
        """Call when shutting down to release MediaPipe resources."""
        self._hands.close()


# =============================================================================
# Private helpers
# =============================================================================

def _extract_landmarks(hand_landmarks, frame_shape) -> list:
    h, w, _ = frame_shape
    lm_list = []
    for idx, lm in enumerate(hand_landmarks.landmark):
        cx, cy = int(lm.x * w), int(lm.y * h)
        lm_list.append([idx, cx, cy])
    return lm_list


def _detect_fingers(lm_list: list, handedness: str) -> list:
    """
    Returns a 5-element list [thumb, index, middle, ring, pinky].
    1 = extended, 0 = folded.
    handedness: "Right" or "Left" as reported by MediaPipe.
    """
    fingers = []
    tip_ids = [4, 8, 12, 16, 20]

    # Thumb — uses X axis (left/right) not Y
    if handedness == "Right":
        fingers.append(1 if lm_list[tip_ids[0]][1] < lm_list[tip_ids[0] - 2][1] else 0)
    else:
        fingers.append(1 if lm_list[tip_ids[0]][1] > lm_list[tip_ids[0] - 2][1] else 0)

    # Four fingers — use Y axis
    for i in range(1, 5):
        fingers.append(1 if lm_list[tip_ids[i]][2] < lm_list[tip_ids[i] - 2][2] else 0)

    return fingers


def _init_volume():
    """Initialise pycaw volume control. Returns (volume_obj, min_vol, max_vol)."""
    try:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        vol_range = volume.GetVolumeRange()
        return volume, vol_range[0], vol_range[1]
    except Exception:
        return None, -65.25, 0.0


def _default_gesture_callback(gesture_name: str, action: str, metadata: dict):
    """Fallback callback — just prints. Replace with your own."""
    print(f"[GestureEngine] {gesture_name} → {action}")