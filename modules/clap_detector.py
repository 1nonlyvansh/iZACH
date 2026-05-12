"""
modules/clap_detector.py
Clap detection via sounddevice amplitude analysis.
Single clap → on_single_clap()
Double clap (2 claps within 0.15–0.70s) → on_double_clap()
Uses threading.Timer for clean single/double discrimination.
"""
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

_RATE            = 44_100
_BLOCK           = 512       # ~11.6ms per chunk
_CLAP_RMS        = 0.18      # RMS threshold — clap is loud transient
_MAX_HIGH_CHUNKS = 9         # clap must be < ~100ms of high energy
_DOUBLE_MIN      = 0.15      # min gap between claps for double
_DOUBLE_MAX      = 0.70      # max gap for double
_COOLDOWN        = 0.9       # ignore re-triggers within this window


class ClapDetector:
    """
    Detects single and double claps from microphone input.
    Uses a threading.Timer to discriminate single from double:
    on_single_clap fires only if no second clap arrives within _DOUBLE_MAX.
    """

    def __init__(
        self,
        on_single_clap: Optional[Callable] = None,
        on_double_clap: Optional[Callable] = None,
        threshold: float = _CLAP_RMS,
    ):
        self.on_single_clap      = on_single_clap
        self.on_double_clap      = on_double_clap
        self.threshold           = threshold
        self._running            = False
        self._thread             = None
        self._audio_q: list      = []
        self._q_lock             = threading.Lock()
        self._state_lock         = threading.Lock()
        self._pending_timer: Optional[threading.Timer] = None
        self._last_clap_t        = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(
            f"[CLAP] Detector started (threshold={self.threshold:.2f}). "
            "Single clap = activate voice. Double clap = stop TTS."
        )

    def stop(self):
        self._running = False
        with self._state_lock:
            if self._pending_timer:
                self._pending_timer.cancel()
                self._pending_timer = None

    def _loop(self):
        def _cb(indata, frames, t, status):
            with self._q_lock:
                self._audio_q.append(indata.copy())

        high_cnt = 0
        was_high = False
        last_cd  = 0.0

        with sd.InputStream(
            channels=1,
            samplerate=_RATE,
            dtype='float32',
            blocksize=_BLOCK,
            callback=_cb,
        ):
            while self._running:
                chunk = None
                with self._q_lock:
                    if self._audio_q:
                        chunk = self._audio_q.pop(0)

                if chunk is None:
                    time.sleep(0.005)
                    continue

                rms = float(np.sqrt(np.mean(chunk ** 2)))
                now = time.time()

                if rms > self.threshold:
                    high_cnt += 1
                    was_high = True
                else:
                    if was_high and high_cnt <= _MAX_HIGH_CHUNKS:
                        if (now - last_cd) > _COOLDOWN:
                            last_cd = now
                            self._on_clap(now)
                    high_cnt = 0
                    was_high = False

    def _on_clap(self, t: float):
        with self._state_lock:
            gap = t - self._last_clap_t
            self._last_clap_t = t

            if _DOUBLE_MIN <= gap <= _DOUBLE_MAX:
                # Second clap arrived in window — double clap
                if self._pending_timer:
                    self._pending_timer.cancel()
                    self._pending_timer = None
                threading.Thread(target=self._fire_double, daemon=True).start()
            else:
                # First clap (or gap too large) — wait for possible second
                if self._pending_timer:
                    self._pending_timer.cancel()
                self._pending_timer = threading.Timer(_DOUBLE_MAX, self._fire_single)
                self._pending_timer.start()

    def _fire_single(self):
        with self._state_lock:
            self._pending_timer = None
        print("[CLAP] Single clap")
        if self.on_single_clap:
            self.on_single_clap()

    def _fire_double(self):
        print("[CLAP] Double clap")
        if self.on_double_clap:
            self.on_double_clap()


_clap_detector: Optional[ClapDetector] = None


def init_clap_detector(
    on_single: Optional[Callable] = None,
    on_double: Optional[Callable] = None,
    threshold: float = _CLAP_RMS,
) -> ClapDetector:
    global _clap_detector
    _clap_detector = ClapDetector(on_single, on_double, threshold)
    return _clap_detector


def get_clap_detector() -> Optional[ClapDetector]:
    return _clap_detector
