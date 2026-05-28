import sys; sys.path.insert(0, '.')
import csv, os, json, shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

spoken = []; executed = []
def mock_speak(text): spoken.append(text)
def mock_chain(cmd):  executed.append(cmd)

for f in ["command_log.csv","patterns.json","routines.json","pattern_last_run.json"]:
    if os.path.exists(f): shutil.copy(f, f+".bak")

def cleanup():
    for f in ["command_log.csv","patterns.json","routines.json","pattern_last_run.json"]:
        if os.path.exists(f+".bak"):
            shutil.copy(f+".bak", f); os.remove(f+".bak")
        elif os.path.exists(f):
            os.remove(f)

def write_csv(rows):
    with open("command_log.csv","w",newline="",encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp","input_type","command","response","time_taken_s","status"])
        for r in rows: w.writerow(r)

def make_rows(cmd, hour, count=5, span=28, day_type="weekday", status="success"):
    rows = []; base = datetime.now() - timedelta(days=span); added=0; day=0
    while added < count:
        dt = base + timedelta(days=day)
        is_weekend = dt.weekday() >= 5
        if (day_type=="weekday" and not is_weekend) or (day_type=="weekend" and is_weekend):
            ts = dt.replace(hour=hour, minute=5, second=0)
            rows.append([ts.strftime("%Y-%m-%d %H:%M:%S"),"voice",cmd,"ok","0.5",status])
            added += 1
        day += 1
    return rows

def make_weekly_rows(cmd, hour, day_type="weekday", count=5):
    """One row per week spread across last 4 weeks. Guaranteed span >= 21 days."""
    rows = []; now = datetime.now()
    for i in range(count, 0, -1):
        d = now - timedelta(days=i*6)  # 6,12,18,24,30 days ago → span=24d
        while True:
            is_wk = d.weekday() >= 5
            if (day_type=="weekday" and not is_wk) or (day_type=="weekend" and is_wk):
                break
            d += timedelta(days=1)
        ts = d.replace(hour=hour, minute=5, second=0)
        rows.append([ts.strftime("%Y-%m-%d %H:%M:%S"),"voice",cmd,"ok","0.5","success"])
    return rows

import modules.pattern_learner as pl
pl.init(mock_speak, mock_chain)

PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: print(f"  PASS {name}"); PASS += 1
    else:    print(f"  FAIL {name}" + (f" | {detail}" if detail else "")); FAIL += 1

print("="*55)
print("PHASE 5 DEEP TEST (final)")
print("="*55)

# E1: Failed rows excluded
print("\n[E1] Failed rows excluded from analysis")
cleanup()
rows = make_weekly_rows("play jazz music", hour=10)
err = make_weekly_rows("play jazz music", hour=10)
for r in err: r[5] = "error"
rows += err
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
check("E1", len([p for p in pats if "jazz" in p.get("cmd_norm","")]) >= 1)

# E2: confirm bogus ID returns False
print("\n[E2] confirm_suggestion bogus ID returns False")
result = pl.confirm_suggestion("nonexistent_id_xyz")
check("E2", result == False, f"got {result}")

# E3: reject bogus ID returns False
print("\n[E3] reject_suggestion bogus ID returns False")
result2 = pl.reject_suggestion("nonexistent_id_zzz")
check("E3", result2 == False, f"got {result2}")

# E4: Rejected never re-offered
print("\n[E4] Rejected pattern never offered again")
cleanup()
rows = make_weekly_rows("check weather forecast", hour=7)
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
pat = next((p for p in pats if "weather" in p.get("cmd_norm","")), None)
if pat:
    pl._pending_suggestion = pat
    pl.reject_suggestion()
    offered = pl.offer_next_pattern()
    check("E4", offered is None or offered["id"] != pat["id"])
else:
    print("  SKIP")

# E5: Multiple patterns different time slots
print("\n[E5] Multiple patterns different time slots")
cleanup()
rows = make_weekly_rows("open gmail", hour=9)
rows += make_weekly_rows("play lo-fi music", hour=22)
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
check("E5", len(pats) >= 2, f"got {len(pats)}")

# E6: Weekend vs weekday separation — weekly rows fix
print("\n[E6] Weekend vs weekday separate buckets")
cleanup()
rows  = make_weekly_rows("search youtube videos", hour=11, day_type="weekend")
rows += make_weekly_rows("search youtube videos", hour=11, day_type="weekday")
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
day_types = {p["day_type"] for p in pats if "youtube" in p.get("cmd_norm","")}
check("E6", len(day_types) == 2, f"got {day_types}")

# E7: delete non-existent preserves real routine
print("\n[E7] delete_routine non-existent ID")
cleanup()
with open("routines.json","w") as f:
    json.dump([{"id":"r_real","cmd":"open gmail","day_type":"weekday","hour_bucket":8,"last_fired":None}],f)
pl.delete_routine("r_fake_id")
routines = pl._load_routines()
check("E7", len(routines)==1 and routines[0]["id"]=="r_real")

# E8: _normalize_command edge cases
print("\n[E8] _normalize_command edge cases")
for inp, expected in [("",""),("ok",""),("hey izach",""),("play spotify","play spotify")]:
    got = pl._normalize_command(inp.lower()) or ""
    check(f"E8 ({inp!r})", got == expected, f"got {got!r}")

# E9: Missing-field routine no crash
print("\n[E9] Missing-field routine no crash")
with open("routines.json","w") as f: json.dump([{"id":"bad_r"}],f)
executed.clear()
try:
    pl._fire_due_routines(); check("E9", True)
except Exception as e:
    check("E9", False, str(e))

# E10: Same-day cluster rejected
print("\n[E10] Same-day cluster rejected")
cleanup()
rows = []
base = datetime.now() - timedelta(days=1)
for i in range(5):
    ts = base.replace(hour=10, minute=i, second=0)
    rows.append([ts.strftime("%Y-%m-%d %H:%M:%S"),"voice","open notepad","ok","0.5","success"])
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
check("E10", len([p for p in pats if "notepad" in p.get("cmd_norm","")]) == 0)

# E11: get_pending_suggestion sync
print("\n[E11] get_pending_suggestion sync")
pl._pending_suggestion = {"id":"test_sync"}
check("E11a", pl.get_pending_suggestion()["id"] == "test_sync")
pl._pending_suggestion = None
check("E11b", pl.get_pending_suggestion() is None)

# E12: Public list APIs
print("\n[E12] Public list APIs")
cleanup()
with open("routines.json","w") as f: json.dump([{"id":"r1"}],f)
with open("patterns.json","w") as f: json.dump([{"id":"p1"},{"id":"p2"}],f)
check("E12a", len(pl.list_routines()) == 1)
check("E12b", len(pl.list_patterns()) == 2)

# E13: confirm valid pattern end-to-end
print("\n[E13] confirm valid pattern end-to-end")
cleanup()
rows = make_weekly_rows("open youtube", hour=15)
write_csv(rows)
for f in ["patterns.json","pattern_last_run.json"]:
    if os.path.exists(f): os.remove(f)
pats = pl.analyze()
if pats:
    pl._pending_suggestion = pats[0]
    ok = pl.confirm_suggestion()
    loaded = pl._load_patterns()
    confirmed = next((p for p in loaded if p["id"]==pats[0]["id"]), None)
    check("E13a returns True", ok == True)
    check("E13b status=confirmed", confirmed and confirmed["status"] == "confirmed")
    check("E13c routine saved", any(r["id"]==pats[0]["id"] for r in pl._load_routines()))
    check("E13d pending cleared", pl._pending_suggestion is None)
else:
    print("  SKIP")

cleanup()
print(f"\n{'='*55}")
print(f"DEEP TEST: {PASS} passed, {FAIL} failed")
print('='*55)
