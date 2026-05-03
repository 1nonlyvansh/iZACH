import threading
import time
import dateparser
from datetime import datetime

class TaskScheduler:
    def __init__(self, speak_callback, orchestrator=None):
        self.reminders = []
        self.speak_callback = speak_callback
        self.orchestrator = orchestrator # Linked to central brain
        self.counter = 0
        self.running = True

    def add_reminder(self, task_text, time_str):
        target_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
        
        if not target_time:
            return "Vansh, that time format is invalid."
        
        if target_time < datetime.now():
            return "I can't remind you of something in the past, Vansh."

        self.counter += 1
        reminder = {"id": self.counter, "task": task_text, "time": target_time}
        self.reminders.append(reminder)
        return f"Reminder set: {task_text} at {target_time.strftime('%H:%M')}."

    def list_reminders(self):
        if not self.reminders: return "No pending reminders."
        lines = [f"- {r['task']} at {r['time'].strftime('%H:%M')}" for r in self.reminders]
        return "Pending tasks:\n" + "\n".join(lines)

    def _check_loop(self):
        while self.running:
            now = datetime.now()
            triggered = [r for r in self.reminders if r['time'] <= now]
            
            for r in triggered:
                # IMPORTANT: Submit to orchestrator so it waits for current speech to finish
                if self.orchestrator:
                    self.orchestrator.submit_task(self.speak_callback, f"Vansh, reminder: {r['task']}")
                else:
                    self.speak_callback(f"Vansh, reminder: {r['task']}")
                
                self.reminders.remove(r)
            
            time.sleep(1)

    def start(self):
        threading.Thread(target=self._check_loop, daemon=True).start()

    def stop(self):
        self.running = False