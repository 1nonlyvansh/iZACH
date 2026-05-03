import csv
import os
from collections import defaultdict
from datetime import datetime

LOG_FILE    = "command_log.csv"
REPORT_FILE = "performance_report.csv"

def run_analysis(mode: str = "overwrite"):
    import os
    from datetime import datetime as _dt
    global REPORT_FILE
    if mode == "new":
        date_str    = _dt.now().strftime("%Y-%m-%d_%H-%M")
        REPORT_FILE = f"performance_report_{date_str}.csv"
    else:
        REPORT_FILE = "performance_report.csv"
    if not os.path.exists(LOG_FILE):
        return False, "No log file found."

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return False, "Log file is empty."

    total        = len(rows)
    success      = sum(1 for r in rows if r.get("status") == "success")
    failures     = total - success
    times = []
    for r in rows:
        try:
            times.append(float(r.get("time_taken") or 0))
        except:
            pass
    avg_time     = round(sum(times) / len(times), 3) if times else 0
    min_time     = round(min(times), 3) if times else 0
    max_time     = round(max(times), 3) if times else 0

    # Intent accuracy
    commands     = [r.get("command", "").strip().lower() for r in rows]
    unknown = sum(1 for r in rows if r.get("fail_reason") == "unknown_intent")
    unknown_pct = round(unknown / total * 100, 1) if total else 0
    unknown_pct  = round(unknown / total * 100, 1) if total else 0

    # Failure reasons from status field
    fail_reasons = defaultdict(int)
    for r in rows:
        if r.get("status") != "success":
            reason = r.get("fail_reason", "unknown_intent").strip() or "unknown_intent"
            fail_reasons[reason] += 1

    # Most used command
    cmd_counts   = defaultdict(int)
    for c in commands:
        if c:
            cmd_counts[c] += 1
    most_used    = max(cmd_counts, key=cmd_counts.get) if cmd_counts else "N/A"

    # Voice vs text
    by_type      = defaultdict(lambda: {"total": 0, "success": 0, "times": []})
    for r in rows:
        t = r.get("input_type", "unknown")
        by_type[t]["total"] += 1
        if r.get("status") == "success":
            by_type[t]["success"] += 1
        try:
            by_type[t]["times"].append(float(r.get("time_taken") or 0))
        except Exception:
            pass

    # Write report CSV
    file_exists = os.path.exists(REPORT_FILE)

    with open(REPORT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)

        if not file_exists:
            w.writerow(["generated_at","total_commands","success","failures","success_rate","avg_time"])
    
    with open(REPORT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)

        w.writerow(["=== SESSION SUMMARY ==="])
        w.writerow(["generated_at",       datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        w.writerow(["total_commands",      total])
        w.writerow(["success_count",       success])
        w.writerow(["failure_count",       failures])
        w.writerow(["success_rate_%",      round(success / total * 100, 1) if total else 0])
        w.writerow(["most_used_command",   most_used])
        w.writerow([])

        w.writerow(["=== LATENCY BREAKDOWN ==="])
        w.writerow(["avg_response_time_s", avg_time])
        w.writerow(["min_response_time_s", min_time])
        w.writerow(["max_response_time_s", max_time])
        w.writerow([])

        w.writerow(["=== INTENT ACCURACY ==="])
        w.writerow(["total_intents",       total])
        w.writerow(["unknown_intents",     unknown])
        w.writerow(["unknown_intent_%",    unknown_pct])
        w.writerow([])

        w.writerow(["=== FAILURE REASONS ==="])
        w.writerow(["reason", "count"])
        for reason, count in fail_reasons.items():
            w.writerow([reason, count])
        w.writerow([])

        w.writerow(["=== VOICE VS TEXT ==="])
        w.writerow(["input_type", "total", "success", "success_%", "avg_time_s"])
        for t, data in by_type.items():
            sr  = round(data["success"] / data["total"] * 100, 1) if data["total"] else 0
            avg = round(sum(data["times"]) / len(data["times"]), 3) if data["times"] else 0
            w.writerow([t, data["total"], data["success"], sr, avg])

    return True, REPORT_FILE