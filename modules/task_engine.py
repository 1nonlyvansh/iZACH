class Task:
    def __init__(self, action, data=None):
        self.action = action
        self.data = data or {}
        self.status = "pending"

    def __repr__(self):
        return f"<Task {self.action} | {self.status}>"
    

class TaskEngine:

    def __init__(self, spotify_handler, speak):
        self.spotify = spotify_handler
        self.speak = speak
        self.queue = []

    def add_task(self, task):
        self.queue.append(task)

    def run(self):
        while self.queue:
            task = self.queue.pop(0)
            print(f"[TASK EXEC]: {task}")
            try:
                # Phase 3: instant feedback before execution
                from modules.response_generator import instant, smart, get_response_generator
                rg = get_response_generator()
                if rg:
                    rg.instant(task.action)

                result = self.execute(task)

                # Phase 2: smart natural response after execution
                if rg and isinstance(result, str):
                    target = task.data.get("song") or task.data.get("device") or ""
                    status = "success" if result and "error" not in result.lower() and "couldn't" not in result.lower() else "failure"
                    if task.action in ["play_music", "pause", "resume", "next", "previous", "switch_device"]:
                        rg.smart(
                            {"task": task.action, "target": target, "status": status, "detail": result},
                            original_cmd=""
                        )
                    else:
                        self.speak(result)
                elif isinstance(result, str):
                    self.speak(result)

                task.status = "done"
            except Exception as e:
                import traceback
                print(f"[TASK ENGINE ERROR] Task '{task.action}' failed: {e}")
                traceback.print_exc()
                task.status = "error"

    def execute(self, task):
        action = task.action
        data = task.data
        print("[TASK EXEC]", action, data)
        if action == "play_music":
            return self.spotify.play_track(data.get("song", ""))
        if action == "pause":
            return self.spotify.pause_music()
        if action == "resume":
            return self.spotify.resume_music()
        if action == "next":
            return self.spotify.next_track()
        if action == "previous":
            return self.spotify.previous_track()
        if action == "switch_device":
            return self.spotify.switch_device(data.get("device", ""))
        return None