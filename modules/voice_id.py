"""
modules/voice_id.py
Speaker enrollment (guided multi-sample) and verification using resemblyzer.

Enrollment flow:
  1. 5 sample phrases shown one at a time
  2. Each phrase recorded for PHRASE_SECONDS seconds
  3. Embeddings averaged → robust single profile saved

WS events emitted during enrollment:
  {type: 'voice_enroll', state: 'start',      total: 5}
  {type: 'voice_enroll', state: 'ready',      step: N, total: 5, phrase: '...'}
  {type: 'voice_enroll', state: 'recording',  step: N, total: 5, phrase: '...', seconds: 4}
  {type: 'voice_enroll', state: 'step_done',  step: N, total: 5}
  {type: 'voice_enroll', state: 'processing'}
  {type: 'voice_enroll', state: 'done',       samples: N}
  {type: 'voice_enroll', state: 'failed',     reason: '...'}
"""

import json
import logging
import os
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

VOICE_DATA_FILE      = "owner_voice.npy"
VOICE_META_FILE      = "owner_voice.json"
SIMILARITY_THRESHOLD = 0.75
SAMPLE_RATE          = 16000
PHRASE_SECONDS       = 4      # recording duration per phrase
PREP_SECONDS         = 2      # pause before recording starts (user reads phrase)

# ── Sample phrases ─────────────────────────────────────────────
# Diverse phoneme coverage — similar to Google/Alexa setup
ENROLLMENT_PHRASES = [
    "Hey iZACH, open Spotify and play my favorite songs",
    "Set a reminder for tomorrow morning at eight o'clock",
    "What's the weather like today, and how's my schedule",
    "Send a message to my friend saying I will be late",
    "Turn off the lights and set the volume to fifty percent",
]

_speak_fn  = None
_enrolling = False   # concurrent enrollment guard


# ── Init ──────────────────────────────────────────────────────

def init(speak_func):
    global _speak_fn
    _speak_fn = speak_func


def _speak(text: str):
    if _speak_fn:
        _speak_fn(text)


def _broadcast(state: str, **extra):
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "voice_enroll", "state": state, **extra})
    except Exception:
        pass


# ── File helpers ──────────────────────────────────────────────

def is_enrolled() -> bool:
    return os.path.exists(VOICE_DATA_FILE)


def _load_embedding() -> np.ndarray | None:
    try:
        return np.load(VOICE_DATA_FILE)
    except Exception:
        return None


def _save_embedding(emb: np.ndarray, label: str = "owner", samples: int = 1):
    np.save(VOICE_DATA_FILE, emb)
    with open(VOICE_META_FILE, "w") as f:
        json.dump({
            "label":       label,
            "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "samples":     samples,
        }, f)


def get_meta() -> dict:
    try:
        with open(VOICE_META_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def delete_voice_data() -> bool:
    removed = False
    for path in [VOICE_DATA_FILE, VOICE_META_FILE]:
        if os.path.exists(path):
            os.remove(path)
            removed = True
    return removed


# ── Audio recording ───────────────────────────────────────────

def _record_audio(seconds: int = PHRASE_SECONDS,
                  sample_rate: int = SAMPLE_RATE) -> np.ndarray | None:
    """Record mono float32 audio from default mic."""
    try:
        import pyaudio
        pa     = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            frames_per_buffer=1024,
        )
        frames = []
        total  = int(sample_rate / 1024 * seconds)
        for _ in range(total):
            frames.append(stream.read(1024, exception_on_overflow=False))
        stream.stop_stream()
        stream.close()
        pa.terminate()

        raw = np.frombuffer(b"".join(frames), dtype=np.int16)
        return raw.astype(np.float32) / 32768.0

    except Exception as e:
        logger.error(f"[VOICE ID] Record error: {e}")
        return None


# ── Embedding ─────────────────────────────────────────────────

# Cached VoiceEncoder — loading the model takes 1-2 s and ~600 MB on first call.
# Without caching, every enrollment phrase reloads it. Warmed at startup via warmup().
_encoder = None
_encoder_lock = threading.Lock()
_warmup_done = threading.Event()  # set when JIT compile + model load finished
_warmup_started = False


def _get_encoder():
    """Lazy-init + cache the VoiceEncoder. Thread-safe."""
    global _encoder
    if _encoder is not None:
        return _encoder
    with _encoder_lock:
        if _encoder is None:
            from resemblyzer import VoiceEncoder
            _encoder = VoiceEncoder()
            logger.info("[VOICE ID] VoiceEncoder loaded and cached.")
    return _encoder


def warmup():
    """
    Force-load resemblyzer + librosa + numba so JIT compile happens BEFORE
    any Flask request triggers embedding.

    Critical: librosa's first call triggers numba JIT compilation. When that
    happens inside a Flask worker thread (e.g. /voice/enroll handler), LLVM
    can abort the process with SIGABRT — taking the whole backend down.
    Pre-compiling here on a dedicated startup thread compiles once and caches
    the JIT result for subsequent calls.
    """
    global _warmup_started
    _warmup_started = True
    try:
        logger.info("[VOICE ID] Warmup — loading VoiceEncoder + JIT-compiling librosa...")

        # ── Step 1: force-import ALL librosa submodules that carry numba JIT
        # decorators at module level. These compile on first import.  Doing it
        # here (on a dedicated startup thread, before any Flask workers or
        # enrollment threads exist) prevents LLVM SIGABRT later.
        #   librosa.core.pitch   → @guvectorize pyin_* (the crash source)
        #   librosa.feature      → spectral features used by resemblyzer
        #   librosa.core.constantq → CQT transform
        # Import order matters: pitch depends on feature/spectral, so import
        # librosa top-level first which triggers the lazy loader chain.
        try:
            import librosa                     # noqa: F401 — triggers lazy imports
            import librosa.core.pitch          # noqa: F401 — @guvectorize at line 430
            import librosa.feature.spectral    # noqa: F401
            import librosa.core.constantq      # noqa: F401
            logger.info("[VOICE ID] librosa submodule JIT paths pre-compiled.")
        except Exception as _lib_e:
            logger.warning(f"[VOICE ID] librosa pre-import warning (non-fatal): {_lib_e}")

        # ── Step 2: load VoiceEncoder and run a full embed_utterance cycle
        # to force any remaining numba compilation paths in resemblyzer itself.
        from resemblyzer import preprocess_wav
        enc = _get_encoder()
        # Use small-amplitude random noise (NOT zeros) — preprocess_wav
        # normalises by RMS, and zero RMS causes log10(0) = -inf which skips
        # the JIT-heavy pitch/spectral code paths.
        rng = np.random.default_rng(seed=42)
        dummy = (rng.standard_normal(SAMPLE_RATE * 2) * 0.01).astype(np.float32)
        wav = preprocess_wav(dummy, source_sr=SAMPLE_RATE)
        _ = enc.embed_utterance(wav)

        logger.info("[VOICE ID] Warmup complete — full embedding pipeline ready.")
        return True
    except Exception as e:
        logger.error(f"[VOICE ID] Warmup failed: {e}")
        return False
    finally:
        _warmup_done.set()


def is_warmed_up() -> bool:
    return _warmup_done.is_set()


def _compute_embedding(audio: np.ndarray,
                       sample_rate: int = SAMPLE_RATE) -> np.ndarray | None:
    # Block until warmup finishes — prevents JIT compile racing inside a
    # Flask request thread (causes LLVM SIGABRT and full backend crash).
    if not _warmup_done.is_set():
        if not _warmup_started:
            # Warmup never started — fire it synchronously now (still on this
            # thread, but at least we'll know if it fails cleanly)
            logger.warning("[VOICE ID] No warmup detected — running synchronously.")
            warmup()
        else:
            logger.info("[VOICE ID] Waiting for warmup to finish before embedding...")
            if not _warmup_done.wait(timeout=60):
                logger.error("[VOICE ID] Warmup did not finish within 60 s — aborting embed.")
                return None
    try:
        from resemblyzer import preprocess_wav
        encoder = _get_encoder()
        wav     = preprocess_wav(audio, source_sr=sample_rate)
        return encoder.embed_utterance(wav)
    except Exception as e:
        logger.error(f"[VOICE ID] Embedding error: {e}")
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── Guided enrollment ─────────────────────────────────────────

def enroll_voice_guided(label: str = "owner") -> tuple[bool, str]:
    """
    Guided multi-phrase enrollment.
    Records ENROLLMENT_PHRASES one at a time, averages embeddings.
    Blocking — call from a background thread.
    """
    global _enrolling
    if _enrolling:
        return False, "Enrollment already in progress."

    _enrolling = True
    total      = len(ENROLLMENT_PHRASES)

    try:
        _broadcast("start", total=total)
        _speak("Voice enrollment starting. I'll guide you through five phrases.")
        # Give the UI wizard time to mount its WebSocket listener BEFORE
        # the first 'ready' broadcast fires — otherwise phrase 1 is lost.
        time.sleep(1.5)

        embeddings: list[np.ndarray] = []

        for step, phrase in enumerate(ENROLLMENT_PHRASES, start=1):
            # ── Show phrase, give user time to read ──────────────
            # First phrase gets extra read time so user can orient themselves
            _prep = PREP_SECONDS + 2 if step == 1 else PREP_SECONDS
            _broadcast("ready", step=step, total=total, phrase=phrase, prep=_prep)
            time.sleep(_prep)

            # ── Record ───────────────────────────────────────────
            _broadcast("recording", step=step, total=total, phrase=phrase, seconds=PHRASE_SECONDS)
            audio = _record_audio(PHRASE_SECONDS)

            if audio is None:
                _broadcast("failed", reason=f"Microphone error on phrase {step}")
                return False, "Microphone error. Check your mic and try again."

            # Quick RMS sanity — if near silence the phrase was skipped
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < 0.003:
                # Too quiet — re-record this phrase once
                _broadcast("ready", step=step, total=total,
                           phrase=phrase, prep=1,
                           hint="Too quiet — please speak louder")
                time.sleep(1)
                _broadcast("recording", step=step, total=total,
                           phrase=phrase, seconds=PHRASE_SECONDS)
                audio = _record_audio(PHRASE_SECONDS)
                if audio is None:
                    _broadcast("failed", reason="Microphone error")
                    return False, "Microphone error."

            # Compute embedding for this sample
            emb = _compute_embedding(audio)
            if emb is not None:
                embeddings.append(emb)

            _broadcast("step_done", step=step, total=total)

            # Brief gap between phrases (except after last)
            if step < total:
                time.sleep(0.8)

        # ── Average all collected embeddings ──────────────────────
        if len(embeddings) < 2:
            _broadcast("failed", reason="Could not compute voice embedding. Try again.")
            return False, "Voice processing failed. Please try again."

        _broadcast("processing")
        avg_emb = np.mean(np.stack(embeddings), axis=0)
        # Normalize to unit vector
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm

        _save_embedding(avg_emb, label, samples=len(embeddings))
        _broadcast("done", samples=len(embeddings))
        return True, f"Voice enrolled with {len(embeddings)} samples. I'll recognise you from now on."

    except Exception as e:
        logger.error(f"[VOICE ID] Enrollment error: {e}")
        _broadcast("failed", reason=str(e))
        return False, f"Enrollment error: {e}"

    finally:
        _enrolling = False


def enroll_voice_async(label: str = "owner"):
    """Non-blocking guided enrollment — speaks result when done."""
    def _run():
        ok, msg = enroll_voice_guided(label)
        _speak(msg)
    threading.Thread(target=_run, daemon=True, name="VoiceEnroll").start()


# ── Verification ──────────────────────────────────────────────

def verify_voice(audio: np.ndarray,
                 sample_rate: int = SAMPLE_RATE) -> tuple[bool, float]:
    """Compare audio against stored embedding. Returns (match, similarity)."""
    known = _load_embedding()
    if known is None:
        return False, 0.0

    emb = _compute_embedding(audio, sample_rate)
    if emb is None:
        return False, 0.0

    sim = _cosine(known, emb)
    return sim >= SIMILARITY_THRESHOLD, round(sim, 3)


# ── Legacy single-shot enroll (kept for voice command trigger) ─

def enroll_voice(label: str = "owner") -> tuple[bool, str]:
    """Alias to guided enrollment for backward compat."""
    return enroll_voice_guided(label)
