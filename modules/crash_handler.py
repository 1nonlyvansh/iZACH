"""
modules/crash_handler.py
Comprehensive crash + console logger for iZACH.

Captures everything that normally vanishes when the backend CMD window closes:
  1. faulthandler   — native crashes (segfault/abort from dlib, OpenCV, ctypes)
  2. sys.excepthook — uncaught Python exceptions on main thread
  3. threading.excepthook — uncaught exceptions in worker threads (Py 3.8+)
  4. Tee'd stdout/stderr — every print() / traceback goes to console AND disk
  5. atexit hook    — final reason the process is exiting
  6. SIGTERM/SIGINT — OS-level termination requests

All output lands in: logs/crash.log and logs/console.log
Old logs auto-rotate at 5 MB, keeping 3 backups.

Call install() ONCE, as the very first line in main.py (before any other imports
that might fail). Idempotent — safe to call multiple times.
"""

import atexit
import faulthandler
import os
import signal
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler

_INSTALLED = False
_LOG_DIR   = "logs"
_CRASH_LOG = os.path.join(_LOG_DIR, "crash.log")
_CONSOLE_LOG = os.path.join(_LOG_DIR, "console.log")


class _Tee:
    """File-like object that writes to BOTH the original stream and a log file."""

    def __init__(self, stream, log_path: str):
        self._stream = stream
        try:
            # Append mode; line-buffered so crashes don't lose the last lines
            self._file = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
        except Exception:
            self._file = None

    def write(self, data):
        try:
            self._stream.write(data)
        except Exception:
            pass
        if self._file:
            try:
                self._file.write(data)
            except Exception:
                pass

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass
        if self._file:
            try:
                self._file.flush()
            except Exception:
                pass

    # Forward common attributes (encoding, isatty) for libraries that probe them
    def __getattr__(self, name):
        return getattr(self._stream, name)


def _global_excepthook(exc_type, exc_value, exc_tb):
    """Catches uncaught exceptions on the main thread."""
    ts  = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    banner = f"\n{'='*72}\n[{ts}] UNCAUGHT EXCEPTION (main thread)\n{'='*72}\n"
    sys.stderr.write(banner + msg)
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(banner + msg)
    except Exception:
        pass


def _thread_excepthook(args):
    """Catches uncaught exceptions in worker threads (Python 3.8+)."""
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    name = getattr(args.thread, "name", "<unknown>") if args.thread else "<unknown>"
    msg  = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    banner = f"\n{'='*72}\n[{ts}] UNCAUGHT EXCEPTION (thread: {name})\n{'='*72}\n"
    sys.stderr.write(banner + msg)
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(banner + msg)
    except Exception:
        pass


def _atexit_handler():
    """Logs the final shutdown reason — runs even on clean exit."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{ts}] Process exit — final.\n")
    except Exception:
        pass


def _signal_handler(signum, frame):
    """Logs OS-level termination signals."""
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    msg  = f"\n[{ts}] Received signal {name} ({signum}) — shutting down.\n"
    sys.stderr.write(msg)
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(msg)
            traceback.print_stack(frame, file=f)
    except Exception:
        pass
    # Re-raise default handler so process actually exits
    sys.exit(128 + signum)


def _rotate_if_large(path: str, max_bytes: int = 5 * 1024 * 1024):
    """Manual rotation — RotatingFileHandler doesn't apply to plain file writes."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            # Keep one backup
            backup = path + ".1"
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(path, backup)
    except Exception:
        pass


def install(also_pause_on_crash: bool = True):
    """
    Wire up every crash trap. Call as the first line of main.py.

    also_pause_on_crash: if True, sys.excepthook will pause with input() so
                        the CMD window stays open on crash — only set False
                        for headless / service deployments.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    # Skip inside multiprocessing subprocess workers — they have their own
    # stdout pipe back to parent and would conflict with parent's Tee.
    try:
        import multiprocessing as _mp
        if _mp.current_process().name != "MainProcess":
            return
    except Exception:
        pass

    _INSTALLED = True
    os.makedirs(_LOG_DIR, exist_ok=True)
    _rotate_if_large(_CRASH_LOG)
    _rotate_if_large(_CONSOLE_LOG)

    # 1. faulthandler — dumps Python stack to file on native crash (SIGSEGV, abort, etc.)
    # Periodic dump_traceback_later removed — it fired once after 5 min and
    # produced 200+ lines of healthy-thread stack noise that masked real crashes.
    try:
        _fh_file = open(_CRASH_LOG, "a", encoding="utf-8", buffering=1, errors="replace")
        _fh_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] faulthandler armed.\n")
        faulthandler.enable(file=_fh_file, all_threads=True)
    except Exception as e:
        sys.stderr.write(f"[crash_handler] faulthandler setup failed: {e}\n")

    # 2. sys.excepthook — uncaught exceptions on main thread
    def _hook(exc_type, exc_value, exc_tb):
        _global_excepthook(exc_type, exc_value, exc_tb)
        if also_pause_on_crash and sys.stdin and sys.stdin.isatty():
            try:
                input("\n[CRASH] Press Enter to close this window...")
            except Exception:
                pass
    sys.excepthook = _hook

    # 3. threading.excepthook — worker thread crashes (Python 3.8+)
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    # 4. Tee stdout + stderr so print() output survives the CMD window closing
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, _CONSOLE_LOG)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, _CONSOLE_LOG)

    # 5. atexit — final reason
    atexit.register(_atexit_handler)

    # 6. OS signals — SIGTERM (Windows: only on console close), SIGINT (Ctrl+C)
    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        pass
    # Windows-specific console-close signal
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
        except Exception:
            pass

    # Banner so crash.log clearly shows each startup
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'#'*72}\n")
            f.write(f"# iZACH startup — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# PID: {os.getpid()}  CWD: {os.getcwd()}\n")
            f.write(f"{'#'*72}\n")
    except Exception:
        pass

    print(f"[CRASH HANDLER] Armed. Logs → {_CRASH_LOG} & {_CONSOLE_LOG}")
