import time

class ContextManager:
    def __init__(self):
        self.context = {
            "last_app_opened": None,
            "last_contact_target": None,
            "last_search_query": None,
            "last_window_position": None,
            "last_action_type": None,
            "timestamp": 0
        }
        self.EXPIRATION_LIMIT = 180  # 3 minutes in seconds

    def update_context(self, key, value):
        """Updates a specific context key and refreshes the timestamp."""
        if key in self.context:
            self.context[key] = value
            self.context["timestamp"] = time.time()

    def get_context(self, key):
        """Retrieves a value if the context is still valid."""
        if self.is_context_valid():
            return self.context.get(key)
        return None

    def is_context_valid(self):
        """Returns True if the last action was within the 3-minute limit."""
        return (time.time() - self.context["timestamp"]) < self.EXPIRATION_LIMIT

    def clear_context(self):
        """Manual reset of the memory."""
        for key in self.context:
            if key != "timestamp":
                self.context[key] = None
        self.context["timestamp"] = 0