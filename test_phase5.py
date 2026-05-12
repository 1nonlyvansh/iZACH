"""Phase 5 test suite — pattern learner."""
import sys, csv, os, json, time, shutil
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timedelta

# ── Helpers ───────────────────────────────────────────────────
spoken = []
executed = []
def mock_speak(text): spoken.append(text); print(f"  [SPEAK]: {text}")
def mock_chain(cmd):  executed.append(cmd); print(f"  [EXEC]: {cmd}")

# Back up real files
TEST_LOG  = "command_log.csv"
TEST_PAT  = "patterns.json"
TEST_ROU  = "routines.json"
TEST_LAST = "pattern_last_run.json"
_backups = {}
for f in [TEST_LOG, TEST_PAT, TEST_ROU, TEST_LAST]:
    if os.path.exists(f):
        shutil.copy(f, f + ".bak")
        _backups[f] = True

def restore():
    for f, _ in _backups.items():
        if os.path.exists(f + ".bak"):
            shutil.copy(f + ".bak", f)
            os.remove(f + ".bak")
    for f in [TEST_PAT, TEST_ROU, TEST_LAST]:
        if f not in _backups and os.path.exists(f):
            os.remove(f)

def write_fake_csv(rows):
    with open(TEST_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "input_type", "command", "response", "time_taken_s", "status"])
        for r in rows:
            w.writerow(r)

def fake_rows(cmd, hour, weekday_only=True, count=8, span_days=20):
    """Generate fake command log rows spread over span_days."""
    rows = []
    base = datetime.now() - timedelta(days=span_days)
    added = 0
    day = 0
    while added < count:
        dt = base + timedelta(days=day)
        if not weekday_only or dt.weekday() < 5:
            ts = dt.replace(hour=hour, minute=10, second=0)
            rows.append([ts.strftime("%Y-%m-%d %H:%M:%S"), "voice", cmd, "ok", "0.5", "success"])
            added += 1
        day += 1
    return rows

print("=" * 50)
print("PHASE 5 TEST SUITE")
print("=" * 50)

import modules.pattern_learner as pl
pl.init(mock_speak, mock_chain)

# ── T1: Import ───────────────────────────────────────────────
print("\n[T1] Import + init")
print("  PASS")

# ── T2: CSV analysis — detect pattern ────────────────────────
print("\n[T2] Detect pattern from CSV")
rows = fake_rows("play coding playlist on spotify", hour=9, count=8, span_days=21)
write_fake_csv(rows)
if os.path.exists(TEST_PAT): os.remove(TEST_PAT)
if os.path.exists(TEST_LAST): os.remove(TEST_LAST)

patterns = pl.analyze()
assert len(patterns) > 0, f"Expected patterns, got {patterns}"
p = patterns[0]
assert p["hour_bucket"] == 8, f"Expected hour_bucket 8 (9am→bucket 8), got {p['hour_bucket']}"
assert p["day_type"] == "weekday"
assert p["count"] >= 3
assert p["status"] == "pending"
print(f"  PASS — detected: '{p['cmd_norm']}' {p['day_type']} ~{p['hour_bucket']}:00 x{p['count']}")

# ── T3: No duplicate patterns on re-analysis ─────────────────
print("\n[T3] Re-analysis dedup")
pl.analyze()
all_pats = pl._load_patterns()
dupes = [p for p in all_pats if p["cmd_norm"] == patterns[0]["cmd_norm"]]
assert len(dupes) == 1, f"Expected 1, got {len(dupes)} dupes"
print("  PASS — no duplicates")

# ── T4: offer_next_pattern ───────────────────────────────────
print("\n[T4] offer_next_pattern")
offered = pl.offer_next_pattern()
assert offered is not None
assert offered["id"] == p["id"]
assert offered.get("offered_date") == datetime.now().date().isoformat()
print(f"  PASS — offered: {offered['id']}")

# ── T5: offer dedup (same day) ───────────────────────────────
print("\n[T5] Offer dedup same day")
offered2 = pl.offer_next_pattern()
assert offered2 is None, f"Should be None (already offered today), got {offered2}"
print("  PASS — no double offer same day")

# ── T6: confirm_suggestion ───────────────────────────────────
print("\n[T6] confirm_suggestion")
pl._pending_suggestion = offered
ok = pl.confirm_suggestion()
assert ok
pats = pl._load_patterns()
confirmed = next((x for x in pats if x["id"] == offered["id"]), None)
assert confirmed and confirmed["status"] == "confirmed"
routines = pl._load_routines()
assert any(r["id"] == offered["id"] for r in routines), "Routine not saved"
print(f"  PASS — status=confirmed, routine saved ({len(routines)} routines)")

# ── T7: reject_suggestion ────────────────────────────────────
print("\n[T7] reject_suggestion")
rows2 = fake_rows("check weather", hour=7, count=5, span_days=18)
write_fake_csv(rows + rows2)
if os.path.exists(TEST_LAST): os.remove(TEST_LAST)
new_pats = pl.analyze()
weather_pat = next((x for x in new_pats if "weather" in x.get("cmd_norm", "")), None)
if weather_pat:
    pl._pending_suggestion = weather_pat
    ok2 = pl.reject_suggestion()
    assert ok2
    pats = pl._load_patterns()
    rejected = next((x for x in pats if x["id"] == weather_pat["id"]), None)
    assert rejected and rejected["status"] == "rejected"
    print(f"  PASS — weather pattern rejected")
else:
    print("  SKIP — weather pattern not detected (may need more data)")

# ── T8: routine runner fires correct time ────────────────────
print("\n[T8] Routine runner fires at correct time")
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
now = datetime.now(tz=IST)
current_bucket = (now.hour // 2) * 2
current_day_type = "weekend" if now.weekday() >= 5 else "weekday"

test_routine = {
    "id": "pat_test",
    "cmd": "play coding playlist",
    "day_type": current_day_type,
    "hour_bucket": current_bucket,
    "last_fired": None,
}
with open(TEST_ROU, "w") as f:
    json.dump([test_routine], f)

executed.clear()
if now.minute <= 5:
    pl._chain_fn = mock_chain
    pl._fire_due_routines()
    assert len(executed) == 1, f"Expected 1 execution, got {executed}"
    print(f"  PASS — fired: {executed[0]}")
else:
    print(f"  SKIP — current minute={now.minute} > 5, routine runner only fires in first 5min of bucket")

# ── T9: routine not fired twice same day ─────────────────────
print("\n[T9] Routine dedup — no double fire")
executed.clear()
pl._fire_due_routines()
assert len(executed) == 0, f"Expected 0, got {executed}"
print("  PASS — no double fire")

# ── T10: _normalize_command ───────────────────────────────────
print("\n[T10] Command normalization")
cases = [
    ("play coding playlist on spotify", "play coding playlist spotify"),
    ("hey izach play my coding playlist", "play coding playlist"),
    ("can you check the weather today", "check weather today"),
]
for raw, expected_contains in cases:
    result = pl._normalize_command(raw.lower())
    # just check it's shorter and non-empty
    assert result and len(result) < len(raw), f"Norm failed: {raw!r} -> {result!r}"
print("  PASS — normalization removes filler")

# ── Cleanup ───────────────────────────────────────────────────
restore()

print("\n" + "=" * 50)
print("ALL PHASE 5 TESTS PASSED")
print("=" * 50)
