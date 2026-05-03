# =============================================================================
# vision/virtual_keyboard.py
# Hand-hover virtual keyboard — renders onto a cv2 frame, no PyQt5.
#
# Usage:
#   kb = VirtualKeyboard()
#   # per frame (keyboard profile active):
#   kb.draw(frame)                        # renders keys onto BGR frame
#   kb.check_hover(index_x, index_y)     # updates highlighted key
#   kb.type_key()                         # types the hovered key if cooldown passed
#   kb.toggle_layout()                    # alpha ↔ symbols
# =============================================================================

import time
import math

import cv2
from pynput.keyboard import Key, Controller as KeyboardController

from config.constants import (
    KEY_WIDTH,
    KEY_HEIGHT,
    KEY_MARGIN,
    FRAME_WIDTH,
    PRESS_COOLDOWN,
    TOGGLE_COOLDOWN,
)


class VirtualKeyboard:
    """
    Draws a virtual keyboard onto a BGR frame using OpenCV.
    Typing is triggered by the caller checking proximity (thumb-to-middle pinch).
    Hover is updated by the caller passing index finger coordinates.

    Bug fix from original: click_dist calculation now uses middle_tip_X
    (not middle_tip_Y twice).
    """

    ALPHA_LAYOUT   = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
    SYMBOL_LAYOUT  = ["1234567890", "@#$_&-+()/*", ".,?!'%:;="]

    def __init__(self, frame_width: int = FRAME_WIDTH):
        self._frame_width = frame_width
        self._keyboard = KeyboardController()
        self.current_layout: str = "alpha"
        self.hovered_key: str | None = None
        self._last_press_time: float = 0
        self._last_toggle_time: float = 0
        self.keys: dict = {}
        self._generate_keys()

    # ------------------------------------------------------------------
    # Key layout generation
    # ------------------------------------------------------------------

    def _generate_keys(self):
        self.keys = {"alpha": [], "symbols": []}
        for mode, layout in [("alpha", self.ALPHA_LAYOUT), ("symbols", self.SYMBOL_LAYOUT)]:
            for row_idx, row in enumerate(layout):
                row_width = len(row) * (KEY_WIDTH + KEY_MARGIN) - KEY_MARGIN
                start_x = (self._frame_width - row_width) // 2
                for col_idx, char in enumerate(row):
                    x = start_x + col_idx * (KEY_WIDTH + KEY_MARGIN)
                    y = 100 + row_idx * (KEY_HEIGHT + KEY_MARGIN)
                    self.keys[mode].append({
                        "char": char, "x": x, "y": y,
                        "w": KEY_WIDTH, "h": KEY_HEIGHT,
                    })

            # Space + Backspace row
            space_w = 500
            bksp_w  = 150
            row_total = space_w + KEY_MARGIN + bksp_w
            space_x = (self._frame_width - row_total) // 2
            bksp_x  = space_x + space_w + KEY_MARGIN
            y = 100 + 3 * (KEY_HEIGHT + KEY_MARGIN)
            self.keys[mode].append({"char": "Space", "x": space_x, "y": y, "w": space_w,  "h": KEY_HEIGHT})
            self.keys[mode].append({"char": "Bksp",  "x": bksp_x,  "y": y, "w": bksp_w,   "h": KEY_HEIGHT})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draw(self, frame):
        """Render the keyboard overlay onto the BGR frame (in place)."""
        overlay = frame.copy()
        for key in self.keys[self.current_layout]:
            x, y, w, h = key["x"], key["y"], key["w"], key["h"]
            color = (255, 0, 0) if key["char"] == self.hovered_key else (128, 128, 128)
            cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
            text_size = cv2.getTextSize(key["char"], cv2.FONT_HERSHEY_SIMPLEX, 1.5, 2)[0]
            text_x = x + (w - text_size[0]) // 2
            text_y = y + (h + text_size[1]) // 2
            cv2.putText(overlay, key["char"], (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    def check_hover(self, x: int, y: int):
        """Update which key (if any) the finger is hovering over."""
        self.hovered_key = None
        for key in self.keys[self.current_layout]:
            if key["x"] < x < key["x"] + key["w"] and \
               key["y"] < y < key["y"] + key["h"]:
                self.hovered_key = key["char"]
                return

    def toggle_layout(self):
        """Switch between alpha and symbol layouts with cooldown."""
        if (time.time() - self._last_toggle_time) > TOGGLE_COOLDOWN:
            self.current_layout = "symbols" if self.current_layout == "alpha" else "alpha"
            self._last_toggle_time = time.time()

    def type_key(self):
        """
        Type the currently hovered key if cooldown has passed.
        Call this when the caller detects a click gesture (thumb-to-middle pinch).
        """
        if not self.hovered_key:
            return
        if (time.time() - self._last_press_time) <= PRESS_COOLDOWN:
            return

        char = self.hovered_key
        if char == "Space":
            self._keyboard.press(Key.space)
            self._keyboard.release(Key.space)
        elif char == "Bksp":
            self._keyboard.press(Key.backspace)
            self._keyboard.release(Key.backspace)
        else:
            self._keyboard.press(char.lower())
            self._keyboard.release(char.lower())

        self._last_press_time = time.time()

    @staticmethod
    def get_click_distance(lm_list: list) -> float:
        """
        Returns the distance between thumb tip and middle finger tip.
        Use this in your frame loop to decide when to call type_key().
        Fixed bug from original aura_app.py (middle_tip_Y used twice).
        """
        thumb_x,  thumb_y  = lm_list[4][1],  lm_list[4][2]
        middle_x, middle_y = lm_list[12][1], lm_list[12][2]
        return math.hypot(thumb_x - middle_x, thumb_y - middle_y)