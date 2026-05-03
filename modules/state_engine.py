import time

class PersonalityState:
    def __init__(self):
        self.mode = "idle"  # work, focus, gym, idle
        self.energy_level = 80.0
        self.last_active_time = time.time()
        self.system_status = "normal"
        
    def transition(self, new_mode):
        modes = {
            "work": {"energy_mod": -5, "msg": "Switching to Work Mode. Productivity engaged."},
            "focus": {"energy_mod": -2, "msg": "Entering Focus Mode. Minimizing interruptions."},
            "gym": {"energy_mod": -10, "msg": "Gym Mode active. Let's get it, Vansh."},
            "idle": {"energy_mod": 5, "msg": "Returning to Idle."}
        }
        
        if new_mode in modes:
            self.mode = new_mode
            self.energy_level = max(0, min(100, self.energy_level + modes[new_mode]["energy_mod"]))
            self.last_active_time = time.time()
            return modes[new_mode]["msg"]
        return "Invalid mode transition."

    def get_persona_prefix(self):
        prefixes = {
            "work": "[Mode: Professional/Efficient] ",
            "focus": "[Mode: Minimalist/Brief] ",
            "gym": "[Mode: High-Energy/Aggressive] ",
            "idle": "[Mode: Sassy/Casual] "
        }
        return prefixes.get(self.mode, "")

state = PersonalityState()