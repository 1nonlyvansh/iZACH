# =============================================================================
# vision/cursor_engine.py
# Air mouse / cursor control — no camera, no PyQt5.
#
# Handles cursor mode gestures:
#   - 1 finger (index)     → move mouse
#   - 2 fingers (peace)    → click when fingers touch
#   - 3 fingers up         → scroll
#   - thumb + index pinch  → zoom (Ctrl +/-)
#
# Usage:
#   cursor = CursorEngine()
#   # per frame — pass the BGR frame and the lm_list from GestureEngine
#   annotated_frame = cursor.process(bgr_frame, lm_list, fingers)
# =============================================================================

import math
import time

import cv2
import numpy as np
import pyautogui
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

from config.constants import (
    CURSOR_SMOOTHENING,
    CLICK_COOLDOWN,
    SCROLL_DIVISOR,
    ZOOM_COOLDOWN,
    ZOOM_TRIGGER_DIST,
)


class CursorEngine:
    """
    Stateful cursor controller.
    Call process() once per frame when the active profile is 'cursor'.

    Only processes the RIGHT hand on screen (MediaPipe "Left" label when mirrored).
    """

    def __init__(self):
        self._keyboard = KeyboardController()
        self._mouse = MouseController()
        self._screen_w, self._screen_h = pyautogui.size()

        # Smoothing state
        self._prev_x: float = 0
        self._prev_y: float = 0
        self._curr_x: float = 0
        self._curr_y: float = 0

        # Timing state
        self._last_click_time: float = 0
        self._last_zoom_time: float = 0

        # Per-gesture state
        self._prev_scroll_y: int = 0
        self._zoom_start_dist: float = 0

        # Last action name — readable externally for overlays
        self.last_action: str = ""

    def reset(self):
        """Call when switching away from cursor mode."""
        self._prev_scroll_y = 0
        self._zoom_start_dist = 0
        self.last_action = ""

    def process(
        self,
        bgr_frame: np.ndarray,
        lm_list: list,
        fingers: list,
        is_right_hand: bool,
    ) -> np.ndarray:
        """
        bgr_frame   : current BGR frame (will be annotated and returned).
        lm_list     : landmark list from gesture_engine._extract_landmarks().
        fingers     : 5-element finger state list.
        is_right_hand: True if this is the right hand on screen.

        Returns annotated BGR frame.
        """
        frame = bgr_frame  # annotate in place

        if not is_right_hand:
            # Cursor mode only uses the right hand
            return frame

        # --- 1 finger: navigate ---
        if fingers == [0, 1, 0, 0, 0]:
            self.last_action = "Navigate"
            self._prev_scroll_y = 0
            self._zoom_start_dist = 0
            x1, y1 = lm_list[8][1], lm_list[8][2]
            x3 = np.interp(x1, (100, 1180), (0, self._screen_w))
            y3 = np.interp(y1, (100, 620), (0, self._screen_h))
            self._curr_x = self._prev_x + (x3 - self._prev_x) / CURSOR_SMOOTHENING
            self._curr_y = self._prev_y + (y3 - self._prev_y) / CURSOR_SMOOTHENING
            self._mouse.position = (self._curr_x, self._curr_y)
            self._prev_x, self._prev_y = self._curr_x, self._curr_y
            cv2.circle(frame, (x1, y1), 15, (255, 0, 255), cv2.FILLED)

        # --- 2 fingers: click when close together ---
        elif fingers == [0, 1, 1, 0, 0]:
            self.last_action = "Click"
            self._prev_scroll_y = 0
            self._zoom_start_dist = 0
            length = math.hypot(
                lm_list[12][1] - lm_list[8][1],
                lm_list[12][2] - lm_list[8][2],
            )
            if length < 40 and (time.time() - self._last_click_time) > CLICK_COOLDOWN:
                self._mouse.click(Button.left, 1)
                self._last_click_time = time.time()
                cv2.circle(frame, (lm_list[8][1], lm_list[8][2]), 15, (0, 255, 0), cv2.FILLED)

        # --- 3 fingers: scroll ---
        elif fingers == [0, 1, 1, 1, 0]:
            self.last_action = "Scroll"
            self._zoom_start_dist = 0
            current_y = lm_list[12][2]
            if self._prev_scroll_y != 0:
                delta_y = current_y - self._prev_scroll_y
                self._mouse.scroll(0, -delta_y // SCROLL_DIVISOR)
            self._prev_scroll_y = current_y

        # --- thumb + index: zoom ---
        elif fingers == [1, 1, 0, 0, 0]:
            self.last_action = "Zoom"
            self._prev_scroll_y = 0
            length = math.hypot(
                lm_list[8][1] - lm_list[4][1],
                lm_list[8][2] - lm_list[4][2],
            )
            if self._zoom_start_dist == 0:
                self._zoom_start_dist = length
            zoom_factor = length - self._zoom_start_dist
            if abs(zoom_factor) > ZOOM_TRIGGER_DIST and \
                    (time.time() - self._last_zoom_time) > ZOOM_COOLDOWN:
                key = "+" if zoom_factor > 0 else "-"
                self._keyboard.press(Key.ctrl)
                self._keyboard.press(key)
                self._keyboard.release(key)
                self._keyboard.release(Key.ctrl)
                self._last_zoom_time = time.time()
                self._zoom_start_dist = length

        else:
            self._prev_scroll_y = 0
            self._zoom_start_dist = 0
            self.last_action = ""

        return frame