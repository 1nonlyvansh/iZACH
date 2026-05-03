import csv
import os
from collections import defaultdict

LOG_FILE = "command_logs.csv"

def analyze_logs():
    if not os.path.exists(LOG_FILE):
        print("[LOG] No command log found yet.")
        return

    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("[LOG] Log file is empty.")
        return

    total      = len(rows)
    success    = sum(1 for r in rows if r.get("status") == "success")
    fail       = total - success
    print(f"  Failed commands    : {fail}")
    times = []
    for r in rows:
        try:
            times.append(float(r.get("time_taken") or 0))
        except:
            pass
    avg_time   = round(sum(times) / len(times), 3) if times else 0

    by_type    = defaultdict(lambda: {"total": 0, "success": 0})
    for r in rows:
        t = r.get("input_type", "unknown")
        by_type[t]["total"]   += 1
        by_type[t]["success"] += 1 if r.get("status") == "success" else 0

    print("\n" + "="*45)
    print("         iZACH COMMAND LOG REPORT")
    print("="*45)
    print(f"  Total commands     : {total}")
    print(f"  Success rate       : {round(success/total*100, 1)}%")
    print(f"  Avg response time  : {avg_time}s")
    print("-"*45)
    for t, data in by_type.items():
        sr = round(data['success'] / data['total'] * 100, 1) if data['total'] else 0
        print(f"  {t.upper():<6} — {data['total']} cmds, {sr}% success")
    print("="*45 + "\n")