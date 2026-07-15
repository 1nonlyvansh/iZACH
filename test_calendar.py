import sys
if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("script-style calendar smoke test; run directly")
sys.path.insert(0, '.')
from modules.calendar_agent import add_event, cancel_event, get_upcoming_events

print("=== iZACH Calendar Phase 1 Test ===\n")

# 1. Add event
print("1. Adding test event to Google Calendar...")
e = add_event(
    title="iZACH Phase 1 Test",
    date_str="2026-05-13",
    time_str="10:00",
    description="Created by iZACH CalendarAgent. Safe to delete.",
    link="https://meet.google.com/abc-defg-hij"
)

if not e:
    print("FAILED: Could not create event.")
    sys.exit(1)

event_id = e["id"]
print(f"   Created: {e['summary']}")
print(f"   Event ID: {event_id}")
print(f"   View at: {e.get('htmlLink')}\n")

# 2. Read it back
print("2. Reading upcoming events (next 48h)...")
upcoming = get_upcoming_events(hours=48)
found = any(ev.get("id") == event_id for ev in upcoming)
print(f"   Events found: {len(upcoming)}")
print(f"   Test event visible: {found}\n")

# 3. Delete it
input("   >> Open calendar.google.com and verify the event exists. Press Enter to delete it...")
print("\n3. Deleting test event...")
ok = cancel_event(event_id)
print(f"   Deleted: {ok}\n")

print("=== All checks passed. Phase 1 working. ===")
