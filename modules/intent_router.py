from modules.task_engine import Task



class IntentRouter:

    def __init__(self, spotify_handler, speak, ai, task_engine):
        self.spotify = spotify_handler
        self.speak = speak
        self.ai = ai
        self.task_engine = task_engine
    




    def _handle_play(self, data):
        song = data.get("song")
        device = data.get("device")

        if device:
            self.spotify.switch_device(device)

        if song:
            return self.spotify.play_track(song)

        return "What should I play?"


    def _handle_device(self, data):
        device = data.get("device")

        if device:
            return self.spotify.switch_device(device)

        return "Which device?"
    
    def route(self, parsed):
        intent = parsed.get("intent")

        if intent == "open_app":
            app = parsed.get("app", "")

            from modules.context_engine import handle_open_with_position

            apps = [a.strip() for a in app.split(" and ")] if " and " in app else [app]
            result = None
            for a in apps:
                result = handle_open_with_position(a, None)
                print("[OPEN APP RESULT]:", result)
            return result

        if intent == "play_music":
            return self._handle_play(parsed)

        if intent == "switch_device":
            return self._handle_device(parsed)

        return None