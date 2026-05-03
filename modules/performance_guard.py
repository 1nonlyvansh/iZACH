import psutil
import threading
import time

class PerformanceGuard:
    def __init__(self, speak_callback):
        self.speak = speak_callback
        self.running = True
        self.cooldowns = {"cpu": False, "ram": False, "battery": False}
        self.cpu_high_count = 0 # Track consecutive high CPU hits

    def get_system_vitals(self):
        """Returns a formatted string of current hardware stats."""
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        battery = psutil.sensors_battery()
        
        bat_str = f"{battery.percent}%" if battery else "N/A"
        return f"CPU is at {cpu}%, Memory usage is at {ram}%, and Battery is at {bat_str}."

    def _monitor_loop(self):
        """Background thread to check thresholds."""
        while self.running:
            try:
                # 1. CPU Check (10-second logic)
                cpu = psutil.cpu_percent()
                if cpu > 85:
                    self.cpu_high_count += 1
                else:
                    self.cpu_high_count = 0
                    self.cooldowns["cpu"] = False

                if self.cpu_high_count >= 10 and not self.cooldowns["cpu"]:
                    self.speak("Warning: CPU load is critical. System performance may degrade.")
                    self.cooldowns["cpu"] = True

                # 2. RAM Check
                ram = psutil.virtual_memory().percent
                if ram > 90 and not self.cooldowns["ram"]:
                    self.speak("Memory usage is exceeding 90 percent. Consider closing some applications.")
                    self.cooldowns["ram"] = True
                elif ram < 85:
                    self.cooldowns["ram"] = False

                # 3. Battery Check
                battery = psutil.sensors_battery()
                if battery:
                    if battery.percent < 20 and not battery.power_plugged and not self.cooldowns["battery"]:
                        self.speak("System alert: Battery is below 20 percent. Please connect a power source.")
                        self.cooldowns["battery"] = True
                    elif battery.percent > 25:
                        self.cooldowns["battery"] = False

            except Exception as e:
                print(f"[PERF GUARD ERROR] {e}")
            
            time.sleep(1) # Poll every second

    def start(self):
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()
        print("[SYSTEM] Performance Guard Monitoring Active.")

    def stop(self):
        self.running = False