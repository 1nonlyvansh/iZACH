"""
modules/wake_word.py
Wake word state machine — no separate audio stream.
Recognition runs inline in listen() via the existing pyaudio stream.
"""
import os
import json
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
    "i jack", "hijack",
    "eye zach", "eye sack",
}


def _load_custom_nickname() -> str:
    """User-set nickname (Settings → Nickname, both Cortex and Forge UI),
    stored in api_keys.json's "nickname" key. Loaded once at process start —
    same "restart required" convention as the wake_word_enabled setting."""
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api_keys.json")
        with open(path, encoding="utf-8") as f:
            return (json.load(f).get("nickname") or "").strip().lower()
    except Exception:
        return ""


# Added to _NAME_VARIANTS itself (not kept separate) so command_chain.py's
# leading-wake-word stripper — which imports _NAME_VARIANTS directly — picks
# the nickname up automatically with no changes needed on its side.
_custom_nickname = _load_custom_nickname()
if _custom_nickname:
    _NAME_VARIANTS.add(_custom_nickname)

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


# Matches a leading wake-word phrase ("hey izach", "izach", "isaac", ...) so
# a command said in the SAME breath ("hey izach open chrome") can be
# extracted and executed immediately instead of being discarded — mirrors
# command_chain.py's own leading-filler stripper (which handles the
# wake-word-disabled/always-listening path), reused here for the
# wake-word-enabled path in main.py's listen().
import re as _re
_PREFIX_ALT = "|".join(_re.escape(p) for p in sorted(_PREFIXES, key=len, reverse=True))
_NAME_ALT   = "|".join(_re.escape(n) for n in sorted(_NAME_VARIANTS, key=len, reverse=True))
_STRIP_RE = _re.compile(rf'^(?:(?:{_PREFIX_ALT})[,\s]+)*(?:{_NAME_ALT})\b[,\s]*', _re.IGNORECASE)


def strip_wake_word(text: str) -> str:
    """Remove a leading wake-word phrase from text, returning whatever
    command follows (empty string if the wake word was said alone)."""
    return _STRIP_RE.sub('', text, count=1).strip()


_detector: Optional[WakeWordDetector] = None


def init_wake_word(on_detected: Callable) -> WakeWordDetector:
    global _detector
    _detector = WakeWordDetector(on_detected)
    return _detector


def get_wake_detector() -> Optional[WakeWordDetector]:
    return _detector
