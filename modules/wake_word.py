"""
modules/wake_word.py
Wake word detection for iZACH.

Two modes (configured via settings):
  1. always_on  — mic listens continuously (current behavior)
  2. wake_word  — listens only after hearing "Hey iZACH" or "iZACH"

Uses a lightweight keyword spotter before falling back to Google STT.
No Porcupine license needed — uses a simple energy + keyword approach
that works reliably for "iZACH" as a unique word.
"""

import threading
import time
import speech_recognition as sr
from typing import Callable, Optional

WAKE_WORDS = [
    "izach", "i zach", "isach", "i sach",
    "hey izach", "hey isach", "okay izach",
    "yo izach", "hello izach",
]

class WakeWordDetector:
    """
    Lightweight wake word detector.
    Calls on_detected() when wake word is heard.
    """

    def __init__(self, on_detected: Callable, sensitivity: float = 0.6):
        self.on_detected    = on_detected
        self.sensitivity    = sensitivity
        self._running       = False
        self._thread        = None
        self._rec           = sr.Recognizer()
        self._rec.energy_threshold         = 250
        self._rec.dynamic_energy_threshold = True
        self._rec.pause_threshold          = 0.5
        self._rec.phrase_threshold         = 0.1
        self._activated     = False   # True for 8s after wake word
        self._activated_at  = 0.0
        self.ACTIVE_WINDOW  = 8.0     # seconds to stay active after wake word

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[WAKE WORD] Detector started. Say 'iZACH' to activate.")

    def stop(self):
        self._running = False

    def is_active(self) -> bool:
        """Returns True if within the active window after wake word."""
        if self._activated:
            if time.time() - self._activated_at < self.ACTIVE_WINDOW:
                return True
            self._activated = False
        return False

    def extend_active(self):
        """Call after a successful command to keep the window open."""
        self._activated    = True
        self._activated_at = time.time()

    def _loop(self):
        mic = sr.Microphone()
        with mic as source:
            self._rec.adjust_for_ambient_noise(source, duration=1.0)

        while self._running:
            try:
                with mic as source:
                    audio = self._rec.listen(
                        source,
                        timeout=3,
                        phrase_time_limit=3
                    )
                text = self._rec.recognize_google(audio).lower()
                print(f"[WAKE WORD] Heard: {text}")

                if any(w in text for w in WAKE_WORDS):
                    print("[WAKE WORD] ✓ Activated")
                    self._activated    = True
                    self._activated_at = time.time()
                    self.on_detected()

            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                continue
            except Exception as e:
                print(f"[WAKE WORD] Error: {e}")
                time.sleep(1)


# Singleton
_detector: Optional[WakeWordDetector] = None

def init_wake_word(on_detected: Callable) -> WakeWordDetector:
    global _detector
    _detector = WakeWordDetector(on_detected)
    return _detector

def get_wake_detector() -> Optional[WakeWordDetector]:
    return _detector