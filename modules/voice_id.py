"""
modules/voice_id.py
Multi-profile speaker enrollment and verification using resemblyzer.

Enrollment flow (per profile):
  1. 5 sample phrases shown one at a time
  2. Each phrase recorded for PHRASE_SECONDS seconds
  3. Audio transcribed — if spoken text < 40 % word overlap with expected phrase,
     broadcast phrase_mismatch and re-record that phrase (1 retry per phrase)
  4. Duplicate check: new embedding vs all existing profiles (threshold 0.88)
     → broadcast duplicate event and abort if same voice already enrolled
  5. Embeddings averaged → normalized profile saved

WS events:
  {type:'voice_enroll', state:'start',           total:5, label:'...'}
  {type:'voice_enroll', state:'ready',            step:N, total:5, phrase:'...', prep:N}
  {type:'voice_enroll', state:'recording',        step:N, total:5, phrase:'...', seconds:4}
  {type:'voice_enroll', state:'step_done',        step:N, total:5}
  {type:'voice_enroll', state:'phrase_mismatch',  step:N, phrase:'...', reason:'Wrong words', retry:true}
  {type:'voice_enroll', state:'processing'}
  {type:'voice_enroll', state:'duplicate',        label:'Vansh\'s Voice'}
  {type:'voice_enroll', state:'done',             samples:N, profile_id:'...', label:'...'}
  {type:'voice_enroll', state:'failed',           reason:'...'}
"""

import json
import logging
import os
import threading
import time
import uuid

from modules.audio_init_lock import PYAUDIO_INIT_LOCK

import numpy as np

logger = logging.getLogger(__name__)

# ── Storage ───────────────────────────────────────────────────────────────────
VOICE_DIR      = "voice_profiles"
PROFILES_FILE  = os.path.join(VOICE_DIR, "profiles.json")

# ── Thresholds ────────────────────────────────────────────────────────────────
SIMILARITY_THRESHOLD  = 0.75   # verify_voice: must exceed to pass auth
DUPLICATE_THRESHOLD   = 0.88   # if new emb vs existing > this → same person
PHRASE_MATCH_MIN      = 0.40   # fraction of expected words that must appear in transcript

# ── Recording params ──────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000
PHRASE_SECONDS = 4
PREP_SECONDS   = 2

ENROLLMENT_PHRASES = [
    "Hey iZACH, open Spotify and play my favorite songs",
    "Set a reminder for tomorrow morning at eight o'clock",
    "What's the weather like today, and how's my schedule",
    "Send a message to my friend saying I will be late",
    "Turn off the lights and set the volume to fifty percent",
]

_speak_fn         = None
_enrolling        = False
_cancel_requested = False   # set True to abort in-progress enrollment cleanly


# ── Init ──────────────────────────────────────────────────────────────────────

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


# ── Profile I/O ───────────────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(VOICE_DIR, exist_ok=True)


def _read_profiles() -> list:
    try:
        with open(PROFILES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_profiles(profiles: list):
    _ensure_dir()
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)


def _emb_path(pid: str) -> str:
    return os.path.join(VOICE_DIR, f"{pid}.npy")


def _load_emb(pid: str) -> "np.ndarray | None":
    try:
        return np.load(_emb_path(pid))
    except Exception:
        return None


def _save_emb(pid: str, emb: np.ndarray):
    _ensure_dir()
    np.save(_emb_path(pid), emb)


# ── Public profile API ────────────────────────────────────────────────────────

def list_profiles() -> list:
    """Return list of profile dicts: [{id, label, enrolled_at, samples}]."""
    return _read_profiles()


def is_enrolled() -> bool:
    """True if at least one voice profile exists."""
    return bool(_read_profiles())


def get_meta() -> dict:
    """Legacy compat — returns first profile metadata or {}."""
    profiles = _read_profiles()
    return profiles[0] if profiles else {}


def rename_profile(pid: str, label: str) -> bool:
    profiles = _read_profiles()
    for p in profiles:
        if p["id"] == pid:
            p["label"] = label.strip()
            _write_profiles(profiles)
            return True
    return False


def delete_profile(pid: str) -> bool:
    profiles = _read_profiles()
    before   = len(profiles)
    profiles = [p for p in profiles if p["id"] != pid]
    if len(profiles) == before:
        return False
    _write_profiles(profiles)
    emb_file = _emb_path(pid)
    if os.path.exists(emb_file):
        os.remove(emb_file)
    # Also remove from diarization if present
    try:
        from modules.speaker_diarization import delete_speaker
        delete_speaker(pid)
    except Exception:
        pass
    return True


def delete_voice_data() -> bool:
    """Delete ALL profiles (legacy single-profile compat)."""
    profiles = _read_profiles()
    if not profiles:
        return False
    for p in profiles:
        delete_profile(p["id"])
    return True


# ── Encoder ───────────────────────────────────────────────────────────────────

_encoder        = None
_encoder_lock   = threading.Lock()
_warmup_done    = threading.Event()
_warmup_started = False


def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    with _encoder_lock:
        if _encoder is None:
            from resemblyzer import VoiceEncoder
            _encoder = VoiceEncoder()
            logger.info("[VOICE ID] VoiceEncoder loaded.")
    return _encoder


def warmup():
    global _warmup_started
    _warmup_started = True
    try:
        logger.info("[VOICE ID] Warmup — loading VoiceEncoder + JIT-compiling librosa...")
        try:
            import librosa                     # noqa
            import librosa.core.pitch          # noqa
            import librosa.feature.spectral    # noqa
            import librosa.core.constantq      # noqa
        except Exception as e:
            logger.warning(f"[VOICE ID] librosa pre-import warning (non-fatal): {e}")
        from resemblyzer import preprocess_wav
        enc = _get_encoder()
        rng   = np.random.default_rng(seed=42)
        dummy = (rng.standard_normal(SAMPLE_RATE * 2) * 0.01).astype(np.float32)
        wav   = preprocess_wav(dummy, source_sr=SAMPLE_RATE)
        _     = enc.embed_utterance(wav)
        logger.info("[VOICE ID] Warmup complete.")
        return True
    except Exception as e:
        logger.error(f"[VOICE ID] Warmup failed: {e}")
        return False
    finally:
        _warmup_done.set()


def is_warmed_up() -> bool:
    return _warmup_done.is_set()


def _compute_embedding(audio: np.ndarray,
                        sample_rate: int = SAMPLE_RATE) -> "np.ndarray | None":
    if not _warmup_done.is_set():
        if not _warmup_started:
            logger.warning("[VOICE ID] No warmup — running synchronously.")
            warmup()
        else:
            if not _warmup_done.wait(timeout=60):
                return None
    try:
        from resemblyzer import preprocess_wav
        wav = preprocess_wav(audio, source_sr=sample_rate)
        return _get_encoder().embed_utterance(wav)
    except Exception as e:
        logger.error(f"[VOICE ID] Embedding error: {e}")
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── Audio ─────────────────────────────────────────────────────────────────────

def _record_audio(seconds: int = PHRASE_SECONDS,
                  sample_rate: int = SAMPLE_RATE) -> "np.ndarray | None":
    try:
        import pyaudio
        # PortAudio isn't thread-safe for concurrent init/terminate across
        # threads — hold the same lock the main voice loop uses, so this
        # can't race main.py's own PyAudio open/terminate and crash the
        # process with a native access violation.
        with PYAUDIO_INIT_LOCK:
            pa     = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                             input=True, frames_per_buffer=1024)
            frames = []
            total  = int(sample_rate / 1024 * seconds)
            for _ in range(total):
                frames.append(stream.read(1024, exception_on_overflow=False))
            stream.stop_stream(); stream.close(); pa.terminate()
        raw = np.frombuffer(b"".join(frames), dtype=np.int16)
        return raw.astype(np.float32) / 32768.0
    except Exception as e:
        logger.error(f"[VOICE ID] Record error: {e}")
        return None


def _transcribe_audio(audio_f32: np.ndarray,
                      sample_rate: int = SAMPLE_RATE) -> "str | None":
    """Transcribe float32 audio using Google STT. Returns lowercased text or None."""
    try:
        import speech_recognition as sr_lib
        int16     = (np.clip(audio_f32, -1.0, 1.0) * 32767).astype(np.int16)
        raw_bytes = int16.tobytes()
        audio_obj = sr_lib.AudioData(raw_bytes, sample_rate, 2)
        r         = sr_lib.Recognizer()
        return r.recognize_google(audio_obj, language="en-in").lower()
    except Exception:
        return None


def _phrase_overlap(expected: str, spoken: "str | None") -> float:
    """Fraction of expected words that appear in spoken text (0–1)."""
    if not spoken:
        return 0.0
    exp_words    = set(expected.lower().split())
    spoken_words = set(spoken.lower().split())
    if not exp_words:
        return 1.0
    return len(exp_words & spoken_words) / len(exp_words)


# ── Duplicate check ───────────────────────────────────────────────────────────

def _is_duplicate(new_emb: np.ndarray) -> "tuple[bool, str | None]":
    """Check if new_emb matches any existing enrolled profile."""
    for profile in _read_profiles():
        existing = _load_emb(profile["id"])
        if existing is None:
            continue
        sim = _cosine(new_emb, existing)
        if sim >= DUPLICATE_THRESHOLD:
            return True, profile["label"]
    return False, None


# ── Guided enrollment ─────────────────────────────────────────────────────────

def cancel_enrollment():
    """Signal any running enrollment to abort cleanly."""
    global _enrolling, _cancel_requested
    _cancel_requested = True
    _enrolling        = False
    logger.info("[VOICE ID] Enrollment cancel requested.")


def enroll_voice_guided(label: str = "My Voice") -> "tuple[bool, str]":
    """
    Guided multi-phrase enrollment with phrase text verification.
    Blocking — call from a background thread via enroll_voice_async().
    """
    global _enrolling, _cancel_requested
    # NOTE: _enrolling is pre-set True by enroll_voice_async() so the voice
    # loop pauses early.  Do NOT check it here — that caused the stuck bug
    # where early-return happened BEFORE the try block so finally never ran.
    _cancel_requested = False
    label = label.strip() or "My Voice"
    total = len(ENROLLMENT_PHRASES)

    try:
        _broadcast("start", total=total, label=label)
        _speak(f"Starting voice enrollment for {label}. I'll guide you through five phrases.")
        time.sleep(1.5)

        embeddings: list[np.ndarray] = []

        for step, phrase in enumerate(ENROLLMENT_PHRASES, start=1):
            phrase_ok    = False
            retry_count  = 0
            audio        = None

            if _cancel_requested:
                _broadcast("failed", reason="Enrollment cancelled.")
                return False, "Enrollment cancelled."

            while not phrase_ok:
                if _cancel_requested:
                    _broadcast("failed", reason="Enrollment cancelled.")
                    return False, "Enrollment cancelled."
                # ── Show phrase ──────────────────────────────────
                _prep = PREP_SECONDS + 2 if (step == 1 and retry_count == 0) else PREP_SECONDS
                _broadcast("ready", step=step, total=total, phrase=phrase, prep=_prep)
                time.sleep(_prep)

                # ── Record ───────────────────────────────────────
                _broadcast("recording", step=step, total=total,
                           phrase=phrase, seconds=PHRASE_SECONDS)
                audio = _record_audio(PHRASE_SECONDS)

                if audio is None:
                    _broadcast("failed", reason=f"Microphone error on phrase {step}")
                    return False, "Microphone error. Check your mic and try again."

                # ── RMS check ────────────────────────────────────
                rms = float(np.sqrt(np.mean(audio ** 2)))
                if rms < 0.003:
                    _broadcast("phrase_mismatch", step=step, phrase=phrase,
                               reason="Too quiet — please speak louder", retry=True)
                    retry_count += 1
                    if retry_count >= 2:
                        _broadcast("failed", reason=f"Too quiet on phrase {step}. Check mic.")
                        return False, "Audio too quiet. Check your microphone."
                    continue

                # ── Phrase text verification ─────────────────────
                transcript = _transcribe_audio(audio)
                overlap    = _phrase_overlap(phrase, transcript)
                logger.info(f"[VOICE ID] Phrase {step} transcript: {transcript!r} "
                            f"overlap={overlap:.2f}")

                if overlap < PHRASE_MATCH_MIN and retry_count < 1:
                    reason = (f"You said: \"{transcript or '…'}\" — "
                              f"please read the phrase as shown")
                    _broadcast("phrase_mismatch", step=step, phrase=phrase,
                               reason=reason, retry=True)
                    retry_count += 1
                    time.sleep(0.5)
                    continue

                # ── Accepted ─────────────────────────────────────
                phrase_ok = True

            # Compute embedding
            emb = _compute_embedding(audio)
            if emb is not None:
                embeddings.append(emb)

            _broadcast("step_done", step=step, total=total)
            if step < total:
                time.sleep(0.8)

        # ── Build profile ─────────────────────────────────────────
        if len(embeddings) < 2:
            _broadcast("failed", reason="Could not compute voice embedding. Try again.")
            return False, "Voice processing failed. Please try again."

        _broadcast("processing")
        avg_emb = np.mean(np.stack(embeddings), axis=0)
        norm    = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm

        # ── Duplicate check ───────────────────────────────────────
        is_dup, dup_label = _is_duplicate(avg_emb)
        if is_dup:
            _broadcast("duplicate", label=dup_label)
            _speak(f"Voice already enrolled as {dup_label}.")
            return False, f"Voice already enrolled as \"{dup_label}\"."

        # ── Persist ───────────────────────────────────────────────
        pid      = "v_" + uuid.uuid4().hex[:8]
        profiles = _read_profiles()
        profiles.append({
            "id":          pid,
            "label":       label,
            "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "samples":     len(embeddings),
        })
        _save_emb(pid, avg_emb)
        _write_profiles(profiles)

        # ── Sync into diarization so the listen() gate works ──────
        try:
            from modules.speaker_diarization import _save_profile as _dia_save
            _dia_save(pid, avg_emb)
            logger.info(f"[VOICE ID] Synced profile {pid} into diarization.")
        except Exception as _de:
            logger.warning(f"[VOICE ID] Diarization sync skipped: {_de}")

        _broadcast("done", samples=len(embeddings),
                   profile_id=pid, label=label)
        return True, (f"Voice enrolled as \"{label}\" with {len(embeddings)} samples.")

    except Exception as e:
        logger.error(f"[VOICE ID] Enrollment error: {e}")
        _broadcast("failed", reason=str(e))
        return False, f"Enrollment error: {e}"
    finally:
        _enrolling        = False
        _cancel_requested = False


def enroll_voice_async(label: str = "My Voice"):
    global _enrolling, _cancel_requested
    # Guard: if a previous enrollment is genuinely still running, reject
    if _enrolling and not _cancel_requested:
        logger.warning("[VOICE ID] enroll_voice_async called while already enrolling — ignoring.")
        return
    # Set flag BEFORE spawning so voice loop pauses immediately (not a race)
    _cancel_requested = False
    _enrolling        = True
    def _run():
        ok, msg = enroll_voice_guided(label)
        _speak(msg)
    threading.Thread(target=_run, daemon=True, name="VoiceEnroll").start()


# ── Verification ─────────────────────────────────────────────────────────────

def verify_voice(audio: np.ndarray,
                 sample_rate: int = SAMPLE_RATE) -> "tuple[bool, float, str | None]":
    """
    Compare audio against all enrolled profiles.
    Returns (matched, best_similarity, matched_label | None).
    """
    profiles = _read_profiles()
    if not profiles:
        return True, 1.0, None   # no profiles → open access

    new_emb = _compute_embedding(audio, sample_rate)
    if new_emb is None:
        return False, 0.0, None

    best_sim   = 0.0
    best_label = None
    for p in profiles:
        stored = _load_emb(p["id"])
        if stored is None:
            continue
        sim = _cosine(new_emb, stored)
        if sim > best_sim:
            best_sim   = sim
            best_label = p["label"]

    matched = best_sim >= SIMILARITY_THRESHOLD
    return matched, round(best_sim, 3), best_label if matched else None


# ── Legacy aliases ────────────────────────────────────────────────────────────

def enroll_voice(label: str = "My Voice") -> "tuple[bool, str]":
    return enroll_voice_guided(label)


def _load_embedding() -> "np.ndarray | None":
    """Legacy: load first profile embedding."""
    profiles = _read_profiles()
    return _load_emb(profiles[0]["id"]) if profiles else None


def _save_embedding(emb: np.ndarray, label: str = "owner", samples: int = 1):
    """Legacy: save as single profile (replaces first profile)."""
    profiles = _read_profiles()
    pid      = profiles[0]["id"] if profiles else "v_" + uuid.uuid4().hex[:8]
    _save_emb(pid, emb)
    if not profiles:
        profiles = [{
            "id": pid, "label": label,
            "enrolled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "samples": samples,
        }]
    else:
        profiles[0]["label"]   = label
        profiles[0]["samples"] = samples
    _write_profiles(profiles)
