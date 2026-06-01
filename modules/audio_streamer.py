"""
audio_streamer.py
Streams PC system audio (loopback) to the Android app over HTTP.

Uses ffmpeg with WASAPI loopback — most reliable on Windows 10/11.
Falls back to virtual-audio-cable / Stereo Mix device if available.

Endpoint: GET /audio/stream
  → Content-Type: application/octet-stream
  → Raw PCM s16le, 22050 Hz, 1 channel (mono)
  → Client must request and then disconnect to stop streaming

Android AudioTrack config:
    sampleRate = 22050
    channelConfig = AudioFormat.CHANNEL_OUT_MONO
    audioFormat = AudioFormat.ENCODING_PCM_16BIT
"""

import logging
import subprocess
import threading
from typing import Generator

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 22050
_CHANNELS    = 1
_CHUNK_BYTES = 4096   # bytes per Flask chunk (~46ms of audio)

# Shared lock — only one stream at a time
_stream_lock = threading.Lock()
_active_proc: subprocess.Popen | None = None


def _ffmpeg_in_path() -> bool:
    """Quick check: ffmpeg exists in PATH."""
    import shutil
    return shutil.which("ffmpeg") is not None


def _get_ffmpeg_cmd() -> list[str]:
    """Build ffmpeg command for WASAPI loopback capture."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        # WASAPI loopback — captures whatever plays through default speakers
        "-f", "wasapi",
        "-loopback",
        "-i", "dummy",
        # Output: raw PCM s16le mono 22050Hz
        "-f",  "s16le",
        "-ar", str(_SAMPLE_RATE),
        "-ac", str(_CHANNELS),
        # Write to stdout
        "pipe:1",
    ]


def _get_sounddevice_cmd() -> list[str] | None:
    """
    Fallback: use sounddevice loopback via a tiny inline Python script.
    Only works if sounddevice + PyAudio with WASAPI support are installed.
    Returns None if sounddevice unavailable.
    """
    try:
        import sounddevice  # noqa: F401
        import sys
        script = (
            "import sounddevice as sd, sys, numpy as np;"
            "sd.default.samplerate=" + str(_SAMPLE_RATE) + ";"
            "sd.default.channels=" + str(_CHANNELS) + ";"
            "with sd.InputStream(samplerate=" + str(_SAMPLE_RATE) + ","
            "channels=" + str(_CHANNELS) + ",dtype='int16')as s:"
            "\n while True:\n  d,_=s.read(2048)\n  sys.stdout.buffer.write(d.tobytes())"
        )
        return [sys.executable, "-c", script]
    except ImportError:
        return None


def get_status() -> dict:
    """Return availability info for the /audio/info endpoint."""
    has_ffmpeg = _ffmpeg_in_path()
    has_sd     = _get_sounddevice_cmd() is not None
    return {
        "available":  has_ffmpeg or has_sd,
        "backend":    "ffmpeg" if has_ffmpeg else ("sounddevice" if has_sd else "none"),
        "ffmpeg":     has_ffmpeg,
        "sounddevice": has_sd,
        "sample_rate": _SAMPLE_RATE,
        "channels":    _CHANNELS,
        "encoding":    "pcm_s16le",
        "install_hint": (
            "" if (has_ffmpeg or has_sd)
            else "Install ffmpeg (winget install ffmpeg) or pip install sounddevice"
        ),
    }


def stream_generator() -> Generator[bytes, None, None]:
    """
    Generator that yields raw PCM chunks.
    Tries ffmpeg first, falls back to sounddevice.
    """
    global _active_proc

    if _ffmpeg_in_path():
        cmd = _get_ffmpeg_cmd()
    else:
        cmd = _get_sounddevice_cmd()

    if cmd is None:
        logger.error(
            "[AudioStream] No audio backend available. "
            "Install ffmpeg (winget install ffmpeg) or sounddevice (pip install sounddevice)."
        )
        return

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=_CHUNK_BYTES * 4,
        )
    except FileNotFoundError:
        logger.error("[AudioStream] Backend not found. Install ffmpeg and add to PATH.")
        return
    except Exception as e:
        logger.error(f"[AudioStream] Failed to start audio capture: {e}")
        return

    with _stream_lock:
        _active_proc = proc

    logger.info("[AudioStream] Streaming started")
    try:
        while True:
            chunk = proc.stdout.read(_CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
    except GeneratorExit:
        pass
    except Exception as e:
        logger.error(f"[AudioStream] Error during stream: {e}")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass
        with _stream_lock:
            if _active_proc is proc:
                _active_proc = None
        logger.info("[AudioStream] Streaming stopped")


def stop_stream():
    """Stop any active stream (called from /audio/stop endpoint)."""
    global _active_proc
    with _stream_lock:
        proc = _active_proc
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass


def get_stream_info() -> dict:
    return {
        "sample_rate": _SAMPLE_RATE,
        "channels": _CHANNELS,
        "encoding": "pcm_s16le",
        "chunk_bytes": _CHUNK_BYTES,
    }
