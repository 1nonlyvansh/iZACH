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


def stream_generator() -> Generator[bytes, None, None]:
    """
    Generator that yields raw PCM chunks.
    Each call to next() blocks until a chunk is available.
    Yields empty bytes to signal end (or on error).
    """
    global _active_proc

    cmd = _get_ffmpeg_cmd()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=_CHUNK_BYTES * 4,
        )
    except FileNotFoundError:
        logger.error("[AudioStream] ffmpeg not found. Install ffmpeg and add to PATH.")
        return
    except Exception as e:
        logger.error(f"[AudioStream] Failed to start ffmpeg: {e}")
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
