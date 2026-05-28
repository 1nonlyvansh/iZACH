"""
modules/speaker_diarization.py
Multi-speaker voice fingerprinting for iZACH.

Supports owner + N guests (3+ speakers).
Filters distant audio (TV, background chatter) via RMS energy floor.

Enrollment:
  enroll_speaker("owner", audio_data)  — primary user
  enroll_speaker("Rohan", audio_data)  — guest
  list_enrolled()                      — all names
  delete_speaker("Rohan")

Identification (called from main.py listen()):
  identify_speaker(audio_data) -> name | "unknown" | None
    None      = too quiet/distant (TV, background) — caller should skip command
    "unknown" = heard but no match — process anyway for safety
    name      = matched profile — caller may inject speaker context
"""

import json
import logging
import os
import threading

import numpy as np

logger = logging.getLogger(__name__)

SPEAKER_DIR   = "speaker_profiles"
MANIFEST_FILE = os.path.join(SPEAKER_DIR, "manifest.json")
OWNER_KEY     = "owner"

MIN_ENERGY_RMS  = 0.003   # below → too distant/quiet → return None (lowered — was rejecting normal speech)
#  0.015 was too strict for laptop mics at normal speaking distance.
#  0.008 still filters genuine TV/background noise while passing real speech.
MATCH_THRESHOLD = 0.72    # cosine similarity for positive ID
NEAR_THRESHOLD  = 0.60    # above this but < MATCH → "unknown"

_profiles: dict[str, np.ndarray] = {}
_lock    = threading.Lock()
_loaded  = False
_speak_fn = None


# ── Public API ─────────────────────────────────────────────────

def init(speak_fn=None):
    global _speak_fn
    _speak_fn = speak_fn
    _load_profiles()


def identify_speaker(audio_data, sample_rate: int = 16000) -> str | None:
    """
    Identify who is speaking.

    audio_data: speech_recognition.AudioData, raw bytes, or np.ndarray float32.
    Returns speaker name, "unknown", or None (background audio — skip).

    RMS energy gate is only applied when voice profiles ARE enrolled.
    When no profiles exist, Google STT already confirmed real speech was heard —
    applying an additional energy filter here would drop legitimate commands.
    """
    audio_f32 = _to_float32(audio_data, sample_rate)
    if audio_f32 is None:
        logger.debug("[Diarization] _to_float32 returned None — unrecognised audio format, defaulting to owner")
        return OWNER_KEY  # can't decode — assume owner

    # Check profiles first — if none enrolled, skip all energy filtering
    with _lock:
        no_profiles = not _profiles
    if no_profiles:
        return OWNER_KEY  # no profiles → always treat as owner; STT already confirmed real speech

    # Profiles exist — apply energy gate to distinguish owner mic from TV/background
    rms = _rms(audio_f32)
    if rms < MIN_ENERGY_RMS:
        logger.debug(f"[Diarization] Dropped — low RMS {rms:.4f}")
        return None  # TV / distant speech

    emb = _embed(audio_f32, sample_rate)
    if emb is None:
        return OWNER_KEY  # resemblyzer unavailable — assume owner

    best_name, best_score = _best_match(emb)

    if best_score >= MATCH_THRESHOLD:
        logger.debug(f"[Diarization] {best_name} (score={best_score:.3f})")
        return best_name
    if best_score >= NEAR_THRESHOLD:
        logger.debug(f"[Diarization] unknown speaker (score={best_score:.3f})")
        return "unknown"
    # Below near-threshold → background noise / TV
    logger.debug(f"[Diarization] Background — ignored (score={best_score:.3f})")
    return None


def enroll_speaker(name: str, audio_data, sample_rate: int = 16000) -> tuple[bool, str]:
    """Compute embedding and persist a voice profile."""
    audio_f32 = _to_float32(audio_data, sample_rate)
    if audio_f32 is None:
        return False, "Could not decode audio data."
    if _rms(audio_f32) < MIN_ENERGY_RMS:
        return False, "Audio too quiet for enrollment. Speak closer to the mic."
    emb = _embed(audio_f32, sample_rate)
    if emb is None:
        return False, "resemblyzer not installed. Run: pip install resemblyzer"
    _save_profile(name.strip().lower(), emb)
    return True, f"Voice profile saved for {name}."


def list_enrolled() -> list[str]:
    with _lock:
        return list(_profiles.keys())


def delete_speaker(name: str) -> bool:
    name = name.strip().lower()
    with _lock:
        if name not in _profiles:
            return False
        del _profiles[name]
    try:
        m = _read_manifest()
        npy = m.pop(name, None)
        if npy:
            p = os.path.join(SPEAKER_DIR, npy)
            if os.path.exists(p):
                os.remove(p)
        _write_manifest(m)
    except Exception as e:
        logger.warning(f"[Diarization] Delete error: {e}")
    return True


# ── Internals ──────────────────────────────────────────────────

def _load_profiles():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
    try:
        m = _read_manifest()
        loaded = 0
        for name, npy_file in m.items():
            path = os.path.join(SPEAKER_DIR, npy_file)
            if os.path.exists(path):
                with _lock:
                    _profiles[name] = np.load(path)
                loaded += 1
        logger.info(f"[Diarization] Loaded {loaded} speaker profiles.")
    except Exception as e:
        logger.warning(f"[Diarization] Profile load error: {e}")


def _save_profile(name: str, emb: np.ndarray):
    os.makedirs(SPEAKER_DIR, exist_ok=True)
    safe = name.replace(" ", "_").replace("/", "_")
    npy_file = f"{safe}.npy"
    np.save(os.path.join(SPEAKER_DIR, npy_file), emb)
    m = _read_manifest()
    m[name] = npy_file
    _write_manifest(m)
    with _lock:
        _profiles[name] = emb


def _read_manifest() -> dict:
    if not os.path.exists(MANIFEST_FILE):
        return {}
    try:
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_manifest(data: dict):
    os.makedirs(SPEAKER_DIR, exist_ok=True)
    with open(MANIFEST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0.0


def _embed(audio_f32: np.ndarray, sample_rate: int) -> np.ndarray | None:
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
        encoder = VoiceEncoder()
        wav = preprocess_wav(audio_f32, source_sr=sample_rate)
        return encoder.embed_utterance(wav)
    except Exception as e:
        logger.debug(f"[Diarization] Embed error: {e}")
        return None


def _best_match(emb: np.ndarray) -> tuple[str, float]:
    best_name  = OWNER_KEY
    best_score = -1.0
    with _lock:
        for name, profile_emb in _profiles.items():
            score = _cosine(emb, profile_emb)
            if score > best_score:
                best_score = score
                best_name  = name
    return best_name, best_score


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _to_float32(audio_data, sample_rate: int) -> np.ndarray | None:
    """Convert sr.AudioData / bytes / ndarray to float32."""
    try:
        if isinstance(audio_data, np.ndarray):
            return audio_data.astype(np.float32)
        if hasattr(audio_data, "get_raw_data"):
            raw = audio_data.get_raw_data(convert_rate=sample_rate, convert_width=2)
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            return arr / 32768.0
        if isinstance(audio_data, (bytes, bytearray)):
            arr = np.frombuffer(bytes(audio_data), dtype=np.int16).astype(np.float32)
            return arr / 32768.0
    except Exception as e:
        logger.debug(f"[Diarization] Decode error: {e}")
    return None
