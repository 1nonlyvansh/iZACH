import sys; sys.path.insert(0, '.')
from unittest.mock import patch, MagicMock
if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("script-style face auth smoke test; run directly")
import numpy as np
import pickle, os, time, threading

spoken = []
def mock_speak(t): spoken.append(t); print(f"  [SPEAK] {t}")

import modules.face_auth as fa
fa.init(mock_speak)

PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: print(f"  PASS {name}"); PASS += 1
    else:    print(f"  FAIL {name}" + (f" | {detail}" if detail else "")); FAIL += 1

def wait_for(lst, expected_len=1, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(lst) >= expected_len:
            return True
        time.sleep(0.1)
    return False

print("="*50)
print("FACE AUTH TEST SUITE")
print("="*50)

fake_encoding = np.random.rand(128)
mock_rgb = np.zeros((480,640,3), dtype=np.uint8)

# T1: not enrolled by default
print("\n[T1] Not enrolled by default")
if os.path.exists(fa.FACE_DATA_FILE): os.remove(fa.FACE_DATA_FILE)
check("T1", not fa.is_enrolled())

# T2: verify with no enrollment
print("\n[T2] verify_owner no enrollment")
spoken.clear()
result = fa.verify_owner()
check("T2 returns False", result == False)
check("T2 speaks prompt", any("enroll" in s.lower() for s in spoken))

# T3: enroll success
print("\n[T3] Enroll owner (mocked)")
if os.path.exists(fa.FACE_DATA_FILE): os.remove(fa.FACE_DATA_FILE)
enroll_done = []
with patch('modules.face_auth._capture_rgb', return_value=mock_rgb), \
     patch('face_recognition.face_locations', return_value=[(10,100,90,10)]), \
     patch('face_recognition.face_encodings', return_value=[fake_encoding]), \
     patch('modules.face_auth._broadcast'):
    spoken.clear()
    fa.enroll_owner(callback=lambda ok: enroll_done.append(ok))
    # wait up to 12s for thread to finish (5*0.7s capture + 3s post-success + margin)
    got = wait_for(enroll_done, timeout=12)

check("T3 callback called", got, f"enroll_done={enroll_done}")
check("T3 callback True", enroll_done and enroll_done[0] == True, str(enroll_done))
check("T3 file exists", os.path.exists(fa.FACE_DATA_FILE))

# T4: verify success
print("\n[T4] verify_owner success path")
with open(fa.FACE_DATA_FILE, 'rb') as f:
    stored = pickle.load(f)
check("T4a encoding shape", stored.shape == (128,))

with patch('modules.face_auth._capture_rgb', return_value=mock_rgb), \
     patch('face_recognition.face_locations', return_value=[(10,100,90,10)]), \
     patch('face_recognition.face_encodings', return_value=[fake_encoding]), \
     patch('face_recognition.compare_faces', return_value=[True]), \
     patch('modules.face_auth._broadcast'), \
     patch('modules.face_auth.time') as mt:
    mt.time.side_effect = [0, 1, 999]
    mt.sleep = lambda x: None
    result = fa.verify_owner()
check("T4b verify True", result == True)

# T5: verify failure
print("\n[T5] verify_owner failure path")
with patch('modules.face_auth._capture_rgb', return_value=mock_rgb), \
     patch('face_recognition.face_locations', return_value=[(10,100,90,10)]), \
     patch('face_recognition.face_encodings', return_value=[fake_encoding]), \
     patch('face_recognition.compare_faces', return_value=[False]), \
     patch('modules.face_auth._broadcast'), \
     patch('modules.face_auth.time') as mt:
    mt.time.side_effect = [0, 1, 999]
    mt.sleep = lambda x: None
    result = fa.verify_owner()
check("T5 verify False", result == False)

# T6: verify timeout (no face in frame)
print("\n[T6] verify_owner timeout (no face)")
with patch('modules.face_auth._capture_rgb', return_value=mock_rgb), \
     patch('face_recognition.face_locations', return_value=[]), \
     patch('modules.face_auth._broadcast'), \
     patch('modules.face_auth.time') as mt:
    # simulate time exceeding VERIFY_TIMEOUT immediately
    mt.time.side_effect = [0, fa.VERIFY_TIMEOUT + 1]
    mt.sleep = lambda x: None
    result = fa.verify_owner()
check("T6 timeout returns False", result == False)

# T7: delete_face_data
print("\n[T7] delete_face_data")
check("T7a enrolled", fa.is_enrolled())
check("T7b delete True", fa.delete_face_data())
check("T7c file gone", not os.path.exists(fa.FACE_DATA_FILE))
check("T7d re-delete False", not fa.delete_face_data())

# T8: enroll fails — no face in any frame
print("\n[T8] Enroll fails — no detectable face")
# patch max_attempts to 3 so test doesn't take 14 seconds
enroll_done2 = []
orig_max = 20
with patch.object(fa, 'ENROLL_FRAMES', 3), \
     patch('modules.face_auth._capture_rgb', return_value=mock_rgb), \
     patch('face_recognition.face_locations', return_value=[]), \
     patch('modules.face_auth._broadcast'):
    # also patch time.sleep in face_auth to be instant
    orig_sleep = __import__('time').sleep
    fa_time = __import__('time')
    fa_time.sleep = lambda x: None
    spoken.clear()
    fa.enroll_owner(callback=lambda ok: enroll_done2.append(ok))
    got2 = wait_for(enroll_done2, timeout=10)
    fa_time.sleep = orig_sleep

check("T8 callback called", got2, f"enroll_done2={enroll_done2}")
check("T8 callback False", enroll_done2 and enroll_done2[0] == False, str(enroll_done2))
check("T8 no file", not os.path.exists(fa.FACE_DATA_FILE))
check("T8 speaks error", any("detect" in s.lower() or "lighting" in s.lower() for s in spoken))

# T9: _delete_with_face_auth no enrollment
print("\n[T9] _delete_with_face_auth no enrollment")
from modules.command_chain import CommandChain
spoken_cc = []
cc = MagicMock(); cc.speak = lambda t: spoken_cc.append(t)
CommandChain._delete_with_face_auth(cc, "test.txt")
time.sleep(0.3)
check("T9 speaks enroll prompt", any("enroll" in s.lower() for s in spoken_cc), str(spoken_cc))

# T10: _delete_with_face_auth deletes on verify success
print("\n[T10] _delete_with_face_auth deletes file on success")
# create dummy file
tmp_file = "test_delete_me.txt"
with open(tmp_file, "w") as f: f.write("test")

# save a fake encoding
with open(fa.FACE_DATA_FILE, "wb") as f: pickle.dump(fake_encoding, f)

spoken_cc2 = []
cc2 = MagicMock(); cc2.speak = lambda t: spoken_cc2.append(t)
with patch('modules.face_auth.verify_owner', return_value=True):
    CommandChain._delete_with_face_auth(cc2, tmp_file)
    time.sleep(0.5)

check("T10 file deleted", not os.path.exists(tmp_file))
check("T10 speaks confirmed", any("confirm" in s.lower() or "delet" in s.lower() for s in spoken_cc2), str(spoken_cc2))

# cleanup
if os.path.exists(fa.FACE_DATA_FILE): os.remove(fa.FACE_DATA_FILE)
if os.path.exists(tmp_file): os.remove(tmp_file)

print(f"\n{'='*50}")
print(f"FACE AUTH TESTS: {PASS} passed, {FAIL} failed")
print("="*50)
