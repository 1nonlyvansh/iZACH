"""
Shared lock to serialize PyAudio/PortAudio initialization.
PortAudio on Windows cannot handle concurrent Pa_Initialize() calls —
two threads opening sr.Microphone() simultaneously causes an access violation.
Import PYAUDIO_INIT_LOCK wherever sr.Microphone() is created.
"""
import threading

PYAUDIO_INIT_LOCK = threading.Lock()
