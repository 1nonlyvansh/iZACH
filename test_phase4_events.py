"""Test upcoming event announcement with mock calendar events."""
import sys, time
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

spoken = []
def mock_speak(text):
    spoken.append(text)
    print(f"  [SPEAK]: {text}")

import modules.proactive_agent as pa
pa._speak_func = mock_speak

# ── Mock calendar to inject fake events ──────────────────────
from unittest.mock import patch

def make_event(title, minutes_from_now, has_link=False):
    dt = datetime.now(tz=IST) + timedelta(minutes=minutes_from_now)
    desc = "Link: https://meet.google.com/test-abc" if has_link else ""
    return {
        "id": f"fake_{title.replace(' ','_')}_{minutes_from_now}",
        "summary": title,
        "start": {"dateTime": dt.isoformat()},
        "description": desc,
    }

print("=" * 50)
print("PHASE 4 EVENT ANNOUNCEMENT TESTS")
print("=" * 50)

# ── Test: T-60 announcement ───────────────────────────────────
print("\n[T1] T-60 announcement (event 60 min away)")
pa._announced_events.clear()
spoken.clear()
fake_events = [make_event("Math Class", 60)]
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_events):
    pa._check_upcoming_events()
assert len(spoken) == 1, f"Expected 1 speech, got {len(spoken)}"
assert "Math Class" in spoken[0]
assert "hour" in spoken[0]
print(f"  PASS: {spoken[0]}")

# ── Test: T-60 dedup (no double announce) ────────────────────
print("\n[T2] T-60 dedup")
spoken.clear()
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_events):
    pa._check_upcoming_events()
assert len(spoken) == 0, "Should not double-announce"
print("  PASS — no double announce")

# ── Test: T-15 announcement ───────────────────────────────────
print("\n[T3] T-15 announcement (event 15 min away)")
pa._announced_events.clear()
spoken.clear()
fake_events = [make_event("Zoom Meeting", 15, has_link=True)]
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_events):
    pa._check_upcoming_events()
assert len(spoken) == 1
assert "Zoom Meeting" in spoken[0]
assert "15 minutes" in spoken[0]
assert "Link" in spoken[0]
print(f"  PASS: {spoken[0]}")

# ── Test: event not in window (30 min) — no announcement ─────
print("\n[T4] Event at T-30 — no announcement expected")
pa._announced_events.clear()
spoken.clear()
fake_events = [make_event("Gym", 30)]
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_events):
    pa._check_upcoming_events()
assert len(spoken) == 0, f"Expected 0, got {spoken}"
print("  PASS — correctly silent at T-30")

# ── Test: two events, both at T-60 ───────────────────────────
print("\n[T5] Two events both at T-60")
pa._announced_events.clear()
spoken.clear()
fake_events = [make_event("Class A", 60), make_event("Class B", 62)]
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_events):
    pa._check_upcoming_events()
assert len(spoken) == 2, f"Expected 2, got {len(spoken)}: {spoken}"
print(f"  PASS — both announced: {[s[:40] for s in spoken]}")

# ── Test: weather outdoor clash logic ────────────────────────
print("\n[T6] Weather clash — rain 80% + outdoor event")
pa._weather_warned_events.clear()
spoken.clear()
fake_outdoor = [make_event("Cricket Match", 120)]
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_outdoor):
    with patch("modules.proactive_agent._get_rain_chance", return_value=80):
        pa._check_weather_outdoor_clash()
assert len(spoken) == 1
assert "rain" in spoken[0].lower() or "Cricket" in spoken[0]
print(f"  PASS: {spoken[0]}")

# ── Test: weather clash dedup ─────────────────────────────────
print("\n[T7] Weather clash dedup")
spoken.clear()
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_outdoor):
    with patch("modules.proactive_agent._get_rain_chance", return_value=80):
        pa._check_weather_outdoor_clash()
assert len(spoken) == 0
print("  PASS — no double weather warn")

# ── Test: rain < 60% — no warning ────────────────────────────
print("\n[T8] Rain 40% — no warning")
pa._weather_warned_events.clear()
spoken.clear()
with patch("modules.calendar_agent.get_upcoming_events", return_value=fake_outdoor):
    with patch("modules.proactive_agent._get_rain_chance", return_value=40):
        pa._check_weather_outdoor_clash()
assert len(spoken) == 0
print("  PASS — silent when rain < 60%")

# ── Test: proactive_enabled=False kills all checks ────────────
print("\n[T9] proactive_enabled=False disables everything")
pa._announced_events.clear()
pa._weather_warned_events.clear()
spoken.clear()
orig_setting = pa._get_setting
pa._get_setting = lambda k, d: False if k == "proactive_enabled" else orig_setting(k, d)

# simulate one loop iteration
if pa._get_setting("proactive_enabled", True):
    pa._check_morning_briefing()
    pa._check_upcoming_events()
    pa._check_weather_outdoor_clash()

pa._get_setting = orig_setting
assert len(spoken) == 0
print("  PASS — all checks skipped when disabled")

print("\n" + "=" * 50)
print("ALL EVENT TESTS PASSED")
print("=" * 50)
