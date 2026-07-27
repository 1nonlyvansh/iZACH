"""
modules/interrupt_engine.py
Handles interruption detection for iZACH.

Two modes:
1. Button interrupt — UI button stops speech immediately
2. Voice interrupt — background mic detects "okay stop", "iZACH", etc.
   while iZACH is speaking
"""

import threading
import speech_recognition as sr
from modules.audio_init_lock import PYAUDIO_INIT_LOCK

# ─────────────────────────────────────────────
# INTERRUPT KEYWORDS
# ─────────────────────────────────────────────
INTERRUPT_PHRASES = [
    "okay stop", "ok stop", "stop", "okay okay", "ok ok",
    "izach stop", "izach", "enough", "shut up", "cancel",
    "i got it", "got it", "alright", "that's enough", "okay wait",
    "bas", "ruk", "ruko", "band kar", "acha okay", "theek hai",  # Hindi
]

# Words that, if they appear alongside stop/cancel, mean pure interrupt (no command follows)
_PURE_STOP_WORDS = {"stop", "cancel", "enough", "bas", "ruk", "ruko", "shut up"}

# Minimum confidence to trigger interrupt from voice
INTERRUPT_THRESHOLD = 0.6


class InterruptEngine:
    """
    Monitors for interruption signals while iZACH is speaking.
    Two modes:
      - Pure interrupt: "stop", "cancel" → TTS stops, no follow-up command
      - Barge-in: "stop — open Chrome" → TTS stops, new command queued
    """

    def __init__(self):
        self._interrupted      = False
        self._is_speaking      = False
        self._stop_fn          = None   # injected from main.py
        self._listening        = False
        self._voice_thread     = None
        self._lock             = threading.Lock()
        self._start_lock       = threading.Lock()   # prevents overlapping thread starts
        self._barge_in_command = None   # queued command from barge-in

        # Lightweight recognizer for barge-in / interrupt detection
        self._rec = sr.Recognizer()
        self._rec.energy_threshold         = 300
        self._rec.dynamic_energy_threshold = True
        self._rec.pause_threshold          = 0.4
        self._rec.phrase_threshold         = 0.1

    def set_stop_fn(self, fn):
        self._stop_fn = fn

    def is_speaking(self) -> bool:
        with self._lock:
            return self._is_speaking

    def set_speaking(self, val: bool):
        """Called by main.py when TTS starts/stops."""
        with self._lock:
            self._is_speaking = val
            self._interrupted = False
        if val:
            # Never open the mic for barge-in detection if the user has
            # explicitly muted it via the UI toggle — this loop had no
            # awareness of that flag at all before, so muting during/before
            # a TTS response still left the mic listening for interruptions.
            try:
                from modules.ui_api import is_mic_active
                if not is_mic_active():
                    return
            except Exception:
                pass
            self._start_voice_monitor()
        else:
            self._stop_voice_monitor()

    def trigger(self):
        """Stops current TTS immediately."""
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

    # ── Barge-in command queue ────────────────────────────────

    def get_barge_in_command(self) -> str | None:
        """
        Returns and clears any command captured during barge-in.
        Called by main.py listen() before opening mic.
        """
        with self._lock:
            cmd = self._barge_in_command
            self._barge_in_command = None
        return cmd

    def _set_barge_in_command(self, text: str):
        with self._lock:
            self._barge_in_command = text

    # ── Voice monitor ─────────────────────────────────────────

    def _start_voice_monitor(self):
        # Non-blocking acquire — if another thread is already starting, skip
        if not self._start_lock.acquire(blocking=False):
            return
        try:
            if self._listening:
                return  # already running
            # Wait for previous thread to die before starting new one
            if self._voice_thread and self._voice_thread.is_alive():
                self._voice_thread.join(timeout=1.0)
            self._listening = True
            self._voice_thread = threading.Thread(
                target=self._voice_monitor_loop,
                daemon=True,
                name="interrupt-monitor",
            )
            self._voice_thread.start()
        finally:
            self._start_lock.release()

    def _stop_voice_monitor(self):
        self._listening = False

    def _voice_monitor_loop(self):
        """
        Keep mic context open for entire monitoring session.
        Single open/close avoids AssertionError from SpeechRecognition's
        'stream is already open' assertion on repeated __enter__ calls.
        """
        mic = None
        try:
            # Try device 0 first, fallback to system default
            # Serialize PyAudio init — concurrent Pa_Initialize() causes access violation on Windows
            for device_idx in (0, None):
                try:
                    with PYAUDIO_INIT_LOCK:
                        mic = sr.Microphone(device_index=device_idx)
                    break
                except (AssertionError, OSError, Exception):
                    mic = None

            if mic is None:
                return  # no mic available — silently skip

            # Open mic ONCE — hold PYAUDIO_INIT_LOCK during BOTH __enter__ (Pa_Initialize)
            # and __exit__ (Pa_Terminate). Pa_Initialize and Pa_Terminate are not
            # thread-safe on Windows — concurrent calls cause access violations (C crash).
            try:
                with PYAUDIO_INIT_LOCK:
                    source = mic.__enter__()
            except Exception:
                return  # device unavailable — skip silently
            try:
                try:
                    self._rec.adjust_for_ambient_noise(source, duration=0.2)
                except (AssertionError, Exception):
                    pass  # best-effort; non-fatal

                while self._listening and self._is_speaking:
                    try:
                        from modules.ui_api import is_mic_active
                        if not is_mic_active():
                            break
                    except Exception:
                        pass
                    try:
                        audio = self._rec.listen(
                            source,
                            timeout=1.5,
                            phrase_time_limit=6.0,
                        )
                        text = self._rec.recognize_google(audio, language="en-in").lower().strip()
                        if not text:
                            continue
                        print(f"[BARGE-IN MONITOR] Heard: {text!r}")

                        if any(phrase in text for phrase in INTERRUPT_PHRASES):
                            remainder = self._strip_interrupt_prefix(text)
                            if remainder and len(remainder.split()) >= 2:
                                print(f"[BARGE-IN] Command after interrupt: {remainder!r}")
                                self.trigger()
                                self._set_barge_in_command(remainder)
                            else:
                                print(f"[INTERRUPT] Pure stop: {text!r}")
                                self.trigger()
                            break

                    except sr.WaitTimeoutError:
                        continue
                    except sr.UnknownValueError:
                        continue
                    except (AssertionError, OSError):
                        # Mic stream went invalid (device disconnected, resource busy)
                        break
                    except Exception:
                        break
            finally:
                # Hold lock during Pa_Terminate() to avoid race with Pa_Initialize
                # in the main voice_loop — concurrent calls cause access violation.
                try:
                    with PYAUDIO_INIT_LOCK:
                        mic.__exit__(None, None, None)
                except Exception:
                    pass  # terminate() failed — ignore; process stays alive

        except (AssertionError, OSError):
            pass  # mic unavailable — normal when audio device is busy
        except Exception as e:
            if self._listening:
                print(f"[INTERRUPT ENGINE] Monitor error: {type(e).__name__}: {e or '(no msg)'}")
        finally:
            self._listening = False

    @staticmethod
    def _strip_interrupt_prefix(text: str) -> str:
        """Remove leading interrupt/stop words and connectors, return remainder."""
        import re
        # Remove leading interrupt phrases and connectors (actually / instead / rather)
        cleaned = re.sub(
            r'^(okay\s+stop|ok\s+stop|stop|cancel|enough|bas|ruk|ruko|izach|'
            r'actually|instead|no\s+wait|wait|hold\s+on|nevermind)[,\s\-–—]*',
            '',
            text,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned


# Singleton
_engine = InterruptEngine()

def get_interrupt_engine() -> InterruptEngine:
    return _engine