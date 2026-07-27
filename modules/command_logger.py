import csv
import os
from datetime import datetime

LOG_FILE = "command_log.csv"
HEADERS  = ["timestamp", "input_type", "command", "response", "time_taken_s", "status"]

def _ensure_file():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADERS)

def log_command(input_type: str, command: str, response: str, time_taken: float, status: str):
    _ensure_file()
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                input_type,
                command[:200],
                response[:200],
                round(time_taken, 3),
                status,
            ])
    except Exception as e:
        print(f"[LOG ERROR] {e}")