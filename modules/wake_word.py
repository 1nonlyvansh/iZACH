"""
modules/wake_word.py
Wake word state machine — no separate audio stream.
Recognition runs inline in listen() via the existing pyaudio stream.
"""
import time
from typing import Callable, Optional

_NAME_VARIANTS = {
    "izach", "i zach",
    "isach", "i sach",
    "isaac", "i sak",
    "isaak", "i saak",
    "isak",  "i zak",
    "izak",  "izaak",
    "i sack", "isack",
    "i jack",
    "eye zach", "eye sack",
}

_PREFIXES = {"hey", "hi", "okay", "ok", "yo", "hello", "aye"}

WAKE_WORDS = list(_NAME_VARIANTS) + [
    f"{p} {n}" for p in _PREFIXES for n in _NAME_VARIANTS
]


class WakeWordDetector:
    def __init__(self, on_detected: Callable):
        self.on_detected   = on_detected
        self._activated    = False
        self._activated_at = 0.0
        self.ACTIVE_WINDOW = 8.0

    def start(self):
        pass  # startup message printed by caller in main.py

    def stop(self):
        self._activated = False

    def is_active(self) -> bool:
        if self._activated:
            if time.time() - self._activated_at < self.ACTIVE_WINDOW:
                return True
            self._activated = False
        return False

    def activate(self):
        self._activated    = True
        self._activated_at = time.time()
        self.on_detected()

    def extend_active(self):
        self._activated    = True
        self._activated_at = time.time()

    def check_text(self, text: str) -> bool:
        return any(w in text for w in WAKE_WORDS)


_detector: Optional[WakeWordDetector] = None


def init_wake_word(on_detected: Callable) -> WakeWordDetector:
    global _detector
    _detector = WakeWordDetector(on_detected)
    return _detector


def get_wake_detector() -> Optional[WakeWordDetector]:
    return _detector
