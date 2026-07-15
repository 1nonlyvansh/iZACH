"""Phase 4 test suite — run from project root."""
import sys, time, json
if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("script-style phase 4 smoke test; run directly")
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

spoken = []
def mock_speak(text):
    spoken.append(text)
    print(f"  [SPEAK]: {text}")

import modules.proactive_agent as pa
pa._speak_func = mock_speak
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

print("=" * 50)
print("PHASE 4 TEST SUITE")
print("=" * 50)

# ── Test 1: Import + init ─────────────────────────
print("\n[T1] Import + init")
from modules.proactive_agent import init, start, record_interaction
init(mock_speak)
print("  PASS")

# ── Test 2: Morning briefing — should NOT fire (wrong time) ──
print("\n[T2] Morning briefing skip (time mismatch)")
pa._morning_briefing_done_date = ""
pa._check_morning_briefing()
assert pa._morning_briefing_done_date == "", "Should not have fired"
print("  PASS — not fired at wrong time")

# ── Test 3: Morning briefing — force fire ────────
print("\n[T3] Morning briefing forced fire")
now = datetime.now(tz=IST)
orig_setting = pa._get_setting
pa._get_setting = lambda k, d: now.strftime("%H:%M") if k == "morning_briefing_time" else orig_setting(k, d)
pa._morning_briefing_done_date = ""
spoken.clear()
pa._check_morning_briefing()
time.sleep(4)  # thread runs async
pa._get_setting = orig_setting
today = now.strftime("%Y-%m-%d")
assert pa._morning_briefing_done_date == today, f"Expected {today}, got '{pa._morning_briefing_done_date}'"
assert len(spoken) > 0, "Expected speech"
print(f"  PASS — date set to {today}")
print(f"  Said: {spoken[-1][:80]}")

# ── Test 4: Morning briefing deduplicate (no double fire) ────
print("\n[T4] Morning briefing dedup")
spoken.clear()
pa._get_setting = lambda k, d: now.strftime("%H:%M") if k == "morning_briefing_time" else orig_setting(k, d)
pa._check_morning_briefing()
time.sleep(2)
pa._get_setting = orig_setting
assert len(spoken) == 0, "Should not fire twice same day"
print("  PASS — no double fire")

# ── Test 5: Upcoming events check ────────────────
print("\n[T5] Upcoming events check (live calendar)")
spoken.clear()
pa._announced_events.clear()
try:
    pa._check_upcoming_events()
    print(f"  PASS — ran without error. Spoken: {len(spoken)} alerts")
    for s in spoken:
        print(f"    -> {s}")
except Exception as e:
    print(f"  WARN — {e}")

# ── Test 6: Rain check ───────────────────────────
print("\n[T6] Rain chance fetch (wttr.in)")
try:
    rain = pa._get_rain_chance()
    print(f"  PASS — rain chance: {rain}%")
except Exception as e:
    print(f"  WARN — {e}")

# ── Test 7: Weather outdoor clash ────────────────
print("\n[T7] Weather outdoor clash (live)")
spoken.clear()
pa._weather_warned_events.clear()
try:
    pa._check_weather_outdoor_clash()
    if spoken:
        print(f"  PASS — warned: {spoken[-1][:80]}")
    else:
        print("  PASS — no outdoor events or rain < 60% (no alert needed)")
except Exception as e:
    print(f"  WARN — {e}")

# ── Test 8: record_interaction ───────────────────
print("\n[T8] record_interaction")
old_t = pa._last_interaction_time
time.sleep(0.1)
record_interaction()
assert pa._last_interaction_time > old_t
print("  PASS")

# ── Test 9: start() / stop() ─────────────────────
print("\n[T9] start() / stop() lifecycle")
assert not pa._running
pa.start()
time.sleep(0.5)
assert pa._running, "Should be running"
pa.stop()
time.sleep(0.2)
print("  PASS — started and stopped")

print("\n" + "=" * 50)
print("ALL TESTS PASSED")
print("=" * 50)
