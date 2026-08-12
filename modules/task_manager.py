import threading
import queue
import time

# A hung task (network call that never returns, a deadlocked lock, etc.) used
# to block this queue forever — func(*args) ran directly in the worker
# thread, so nothing after it could ever run either. Python can't force-kill
# a running thread, so this can't make the hung call itself stop — but it
# runs each task on its own daemon thread and only waits up to TASK_TIMEOUT_S
# before giving up and moving on to the next queued task. The abandoned
# thread finishes (or hangs) in the background, harmless since it's daemon.
TASK_TIMEOUT_S = 30

class TaskOrchestrator:
    def __init__(self):
        self.task_queue = queue.Queue()
        self.running = True
        self.worker_thread = None

    def submit_task(self, func, *args):
        """Adds a task to the centralized execution queue."""
        task = {"func": func, "args": args, "timestamp": time.time()}
        self.task_queue.put(task)
        print(f"[ORCHESTRATOR] Task submitted: {func.__name__}")

    def _worker_loop(self):
        """Sequentially executes tasks with timeout protection."""
        while self.running:
            try:
                task = self.task_queue.get(timeout=0.5)
                func = task["func"]
                args = task["args"]

                start_time = time.time()
                error_holder = {}

                def _run(_func=func, _args=args, _err=error_holder):
                    try:
                        _func(*_args)
                    except Exception as e:
                        _err["error"] = e

                t = threading.Thread(target=_run, daemon=True, name=f"Task-{func.__name__}")
                t.start()
                t.join(timeout=TASK_TIMEOUT_S)

                duration = time.time() - start_time
                if t.is_alive():
                    print(f"[ORCHESTRATOR WARNING] Task {func.__name__} exceeded "
                          f"{TASK_TIMEOUT_S}s — moving on to the next queued task "
                          f"(it'll keep running in the background; Python can't force-kill it).")
                elif "error" in error_holder:
                    print(f"[ORCHESTRATOR ERROR] Task {func.__name__} failed: {error_holder['error']}")
                elif duration > 15:
                    print(f"[ORCHESTRATOR WARNING] Task {func.__name__} took {duration:.2f}s (Over 15s limit)")

                self.task_queue.task_done()
            except queue.Empty:
                continue

    def start_task_worker(self):
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        print("[SYSTEM] Task Orchestrator Online.")

    def stop_task_worker(self):
        self.running = False

    def get_status(self):
        return f"Queue Depth: {self.task_queue.qsize()} tasks pending."