"""
Standalone test for event_extractor — no WhatsApp needed.
Tests extraction + calendar add + cancellation flow.
"""
import sys, json, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from modules import event_extractor

# mock speak so we see output
def mock_speak(text):
    print(f"  [iZACH SPEAKS]: {text}")

event_extractor.init(speak_fn=mock_speak)

# patch _process to run synchronously for testing
import modules.event_extractor as _mod

def run_sync(text, sender, msg_id=None):
    print(f"\n--- Message from {sender}: \"{text}\"")
    extracted = _mod._extract(text, sender, timestamp=None)
    print(f"  Extracted: {json.dumps(extracted, indent=2)}")
    if extracted and extracted.get("confidence", 0) >= 0.80:
        if extracted.get("is_cancellation"):
            _mod._handle_cancellation(extracted, sender)
        elif extracted.get("is_event"):
            _mod._handle_new_event(extracted, sender, msg_id or "test_msg_1")
    else:
        print("  >> Low confidence or not an event. Skipped.")

print("=== EventExtractor Phase 2 Test ===")

# Test 1: Hinglish social event
run_sync("8 June ko golf khelne jana hai 10 baje", "Rahul", "msg_001")

# Test 2: English class with Meet link
run_sync(
    "Class will be at 3pm today, join on this link: https://meet.google.com/abc-xyz-def",
    "Teacher",
    "msg_002"
)

# Test 3: Casual social message (should not create event)
run_sync("bhai kaisa hai", "Priya", "msg_003")

# Test 4: Cancellation - Hinglish
run_sync("Aaj class cancel hai", "Teacher", "msg_004")

# Test 5: Meeting tomorrow
run_sync("kal 5pm pe meeting hai office mein", "Boss", "msg_005")

print("\n=== Test complete. Check calendar.google.com for added events. ===")
