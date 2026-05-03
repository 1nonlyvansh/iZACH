import threading
import queue
import time
import logging

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

                # Execution with logic to track duration
                start_time = time.time()
                
                # We use a sub-thread or a simple check for 15s timeout
                # Note: Python functions can't be easily killed, but we log warnings
                try:
                    func(*args)
                except Exception as e:
                    print(f"[ORCHESTRATOR ERROR] Task {func.__name__} failed: {e}")

                duration = time.time() - start_time
                if duration > 15:
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