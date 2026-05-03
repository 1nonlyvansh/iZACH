"""
modules/interrupt_engine.py
Handles interruption detection for iZACH.

Two modes:
1. Button interrupt — UI button stops speech immediately
2. Voice interrupt — background mic detects "okay stop", "iZACH", etc.
   while iZACH is speaking
"""

import threading
import time
import queue
import speech_recognition as sr

# ─────────────────────────────────────────────
# INTERRUPT KEYWORDS
# ─────────────────────────────────────────────
INTERRUPT_PHRASES = [
    "okay stop", "ok stop", "stop", "okay okay", "ok ok",
    "izach stop", "izach", "enough", "shut up", "cancel",
    "i got it", "got it", "alright", "that's enough", "okay wait", 
    "bas", "ruk", "ruko", "band kar", "acha okay", "theek hai",  # Hindi
]

# Minimum confidence to trigger interrupt from voice
INTERRUPT_THRESHOLD = 0.6


class InterruptEngine:
    """
    Monitors for interruption signals while iZACH is speaking.
    Integrates with the speech queue to stop playback immediately.
    """

    def __init__(self):
        self._interrupted    = False
        self._is_speaking    = False
        self._stop_fn        = None   # injected from main.py
        self._listening      = False
        self._voice_thread   = None
        self._lock           = threading.Lock()

        # Lightweight recognizer for interrupt detection
        self._rec = sr.Recognizer()
        self._rec.energy_threshold        = 300
        self._rec.dynamic_energy_threshold = True
        self._rec.pause_threshold         = 0.4   # fast response
        self._rec.phrase_threshold        = 0.1

    def set_stop_fn(self, fn):
        """Inject the stop-speech function from main.py."""
        self._stop_fn = fn

    def set_speaking(self, val: bool):
        """Called by main.py when TTS starts/stops."""
        with self._lock:
            self._is_speaking = val
            self._interrupted = False
        if val:
            # Only start voice monitor if not already conflicting with main mic
            # The button interrupt always works regardless
            pass  # voice monitor disabled for now — use button interrupt
        else:
            self._stop_voice_monitor()

    def trigger(self):
        """
        Manually trigger interrupt — called by UI button or voice detection.
        Stops current speech immediately.
        """
        with self._lock:
            self._interrupted = True
        if self._stop_fn:
            self._stop_fn()

    def is_interrupted(self) -> bool:
        with self._lock:
            return self._interrupted

    def reset(self):
        with self._lock:
            self._interrupted = False

    # ─────────────────────────────────────────
    # Voice interrupt monitor
    # ─────────────────────────────────────────

    def _start_voice_monitor(self):
        if self._listening:
            return
        self._listening = True
        self._voice_thread = threading.Thread(
            target=self._voice_monitor_loop,
            daemon=True
        )
        self._voice_thread.start()

    def _stop_voice_monitor(self):
        self._listening = False

    def _voice_monitor_loop(self):
        try:
            # Use mic index 0 explicitly — avoids conflict with main mic
            try:
                mic = sr.Microphone(device_index=0)
            except Exception:
                mic = sr.Microphone()

            with mic as source:
                self._rec.adjust_for_ambient_noise(source, duration=0.2)

            while self._listening and self._is_speaking:
                try:
                    with mic as source:
                        audio = self._rec.listen(
                            source,
                            timeout=1.5,
                            phrase_time_limit=2.5
                        )
                    text = self._rec.recognize_google(audio).lower()
                    print(f"[INTERRUPT MONITOR] Heard: {text}")

                    if any(phrase in text for phrase in INTERRUPT_PHRASES):
                        print(f"[INTERRUPT] Triggered by voice: '{text}'")
                        self.trigger()
                        break

                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except Exception:
                    break
        except Exception as e:
            import traceback
            print(f"[INTERRUPT ENGINE] Monitor error: {type(e).__name__}: {e}")
            if str(e):
                traceback.print_exc()
        finally:
            self._listening = False


# Singleton
_engine = InterruptEngine()

def get_interrupt_engine() -> InterruptEngine:
    return _engine