"""
Lightweight task event system — broadcasts progress to WS clients.
Used by any backend module that runs async operations.
"""
import time
import uuid
import threading

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def _broadcast(event: dict):
    try:
        from modules.ws_bridge import broadcast
        broadcast(event)
    except Exception:
        pass


def start(name: str, total: int = 100) -> str:
    tid = str(uuid.uuid4())[:8]
    with _lock:
        _tasks[tid] = {"id": tid, "name": name, "progress": 0, "total": total, "status": "running"}
    _broadcast({"type": "task_started", "id": tid, "name": name,
                "total": total, "ts": time.strftime("%H:%M")})
    return tid


def progress(tid: str, value: int, message: str = ""):
    with _lock:
        if tid in _tasks:
            _tasks[tid]["progress"] = value
    _broadcast({"type": "task_progress", "id": tid, "progress": value, "message": message})


def complete(tid: str, message: str = "Done"):
    with _lock:
        if tid in _tasks:
            _tasks[tid]["status"] = "completed"
    _broadcast({"type": "task_completed", "id": tid, "message": message,
                "ts": time.strftime("%H:%M")})


def fail(tid: str, error: str = "Failed"):
    with _lock:
        if tid in _tasks:
            _tasks[tid]["status"] = "failed"
    _broadcast({"type": "task_failed", "id": tid, "error": error,
                "ts": time.strftime("%H:%M")})


def all_tasks() -> list:
    with _lock:
        return list(_tasks.values())
