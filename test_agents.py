"""
Agent smoke-test suite.
Run: python test_agents.py
Tests each agent with a real GROQ call for intent parsing + mock speak.
External side-effects (camera, spotify, WhatsApp, file ops) are intercepted
so nothing actually fires.
"""

if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("script-style smoke test; run directly")

import os, sys, time, traceback, unittest.mock as mock
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
if not GROQ_KEY:
    print("[FATAL] No GROQ_API_KEY in .env — cannot run tests.")
    sys.exit(1)

# ── Real GROQ raw_ai ──────────────────────────────────────────────
from groq import Groq
_groq = Groq(api_key=GROQ_KEY)

def raw_ai(prompt: str) -> str:
    r = _groq.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=300,
    )
    return r.choices[0].message.content

# ── Speak capture ─────────────────────────────────────────────────
spoken: list[str] = []

def speak(text: str):
    spoken.append(text)
    print(f"    SPEAK: {text}")

# ── Test harness ──────────────────────────────────────────────────
PASS = 0
FAIL = 0
results: list[tuple] = []

def run(agent_name: str, cmd: str, agent, domain_ctx: dict,
        expect_handled=True, patch_map: dict | None = None):
    """Run one test case. patch_map = {module_path: mock_object}."""
    global PASS, FAIL
    spoken.clear()
    patches = []
    try:
        if patch_map:
            for target, obj in patch_map.items():
                p = mock.patch(target, obj)
                p.start()
                patches.append(p)

        t0 = time.time()
        handled = agent.handle(cmd, domain_ctx)
        elapsed = round((time.time() - t0) * 1000)

        status = "PASS" if handled == expect_handled else "FAIL"
        if status == "PASS":
            PASS += 1
        else:
            FAIL += 1

        results.append((status, agent_name, cmd, elapsed, spoken[:]))
        print(f"  [{status}] {agent_name} | '{cmd}' | {elapsed}ms")
    except Exception as e:
        FAIL += 1
        tb = traceback.format_exc(limit=3)
        results.append(("ERR", agent_name, cmd, 0, [str(e)]))
        print(f"  [ERR]  {agent_name} | '{cmd}'\n{tb}")
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  iZACH AGENT SMOKE TESTS")
print("="*60)

# ── 1. OrchestratorAgent ──────────────────────────────────────────
print("\n[1] OrchestratorAgent")
from Agents.orchestrator import OrchestratorAgent
orch = OrchestratorAgent(groq_key=GROQ_KEY)

classify_cases = [
    ("what's the weather in Mumbai",  "research"),
    ("send a message to Rahul",       "whatsapp"),
    ("play Arijit Singh on Spotify",  "spotify"),
    ("remind me at 6pm",              "calendar"),
    ("open Chrome",                   "system"),
    ("remember that I like coffee",   "memory"),
    ("what am I holding",             "vision"),
    ("open my downloads folder",      "file"),
]

for cmd, expected_domain in classify_cases:
    t0 = time.time()
    ctx = orch.classify(cmd)
    elapsed = round((time.time() - t0) * 1000)
    got = ctx["domain"]
    status = "PASS" if got == expected_domain else "FAIL"
    if status == "PASS": PASS += 1
    else: FAIL += 1
    results.append((status, "Orchestrator", cmd, elapsed, [f"domain={got} conf={ctx['confidence']:.2f}"]))
    print(f"  [{status}] '{cmd}' -> {got} (expected {expected_domain}) conf={ctx['confidence']:.2f} {elapsed}ms")


# ── 2. ResearchAgent ─────────────────────────────────────────────
print("\n[2] ResearchAgent")
from Agents.research_agent import ResearchAgent
res = ResearchAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_res = {"domain": "research", "confidence": 0.95, "summary": ""}

# Patch realtime_data calls so no real HTTP
_fake_weather = mock.MagicMock(return_value="Delhi is 32°C, partly cloudy.")
_fake_news    = mock.MagicMock(return_value="Top story: Budget session begins today.")
_fake_gold    = mock.MagicMock(return_value="Gold is ₹72,000 per 10 grams.")
_fake_crypto  = mock.MagicMock()

import requests as _requests_mod
_fake_crypto_resp = mock.MagicMock()
_fake_crypto_resp.json.return_value = {"bitcoin": {"usd": 67000, "inr": 5600000}}
_fake_requests_get = mock.MagicMock(return_value=_fake_crypto_resp)

run("ResearchAgent", "weather in Delhi", res, ctx_res,
    patch_map={"modules.realtime_data.get_weather": _fake_weather})

run("ResearchAgent", "what's the gold rate today", res, ctx_res,
    patch_map={"modules.realtime_data.get_gold_rate": _fake_gold})

run("ResearchAgent", "latest news", res, ctx_res,
    patch_map={"modules.realtime_data.get_news": _fake_news})

run("ResearchAgent", "bitcoin price", res, ctx_res,
    patch_map={"requests.get": _fake_requests_get})


# ── 3. CalendarAgent ─────────────────────────────────────────────
print("\n[3] CalendarAgent")
from Agents.calendar_agent import CalendarAgent

mock_scheduler = mock.MagicMock()
mock_scheduler.add_reminder.return_value = "Reminder set for 5 PM."
mock_scheduler.list_reminders.return_value = "You have 2 reminders."

cal = CalendarAgent(speak_fn=speak, raw_ai_fn=raw_ai, scheduler=mock_scheduler)
ctx_cal = {"domain": "calendar", "confidence": 0.95, "summary": ""}

_fake_events      = mock.MagicMock(return_value=[])
_fake_next_event  = mock.MagicMock(return_value=None)
_fake_set_alarm   = mock.MagicMock(return_value=(True, "Alarm set for 7:00 AM."))

run("CalendarAgent", "what's on my schedule today", cal, ctx_cal,
    patch_map={"modules.calendar_agent.get_upcoming_events": _fake_events})

run("CalendarAgent", "remind me to drink water at 3pm", cal, ctx_cal)

run("CalendarAgent", "list my reminders", cal, ctx_cal)

run("CalendarAgent", "set alarm for 7am", cal, ctx_cal,
    patch_map={"modules.system_control.set_alarm": _fake_set_alarm})

run("CalendarAgent", "what's my next event", cal, ctx_cal,
    patch_map={"modules.calendar_agent.get_next_event": _fake_next_event})


# ── 4. SystemAgent ───────────────────────────────────────────────
print("\n[4] SystemAgent")
from Agents.system_agent import SystemAgent
sys_agent = SystemAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_sys = {"domain": "system", "confidence": 0.95, "summary": ""}

_fake_battery   = mock.MagicMock(return_value=(True, "Battery is at 82%, not charging."))
_fake_ram       = mock.MagicMock(return_value=(True, "RAM usage is 4.2 GB of 16 GB."))
_fake_vol_set   = mock.MagicMock(return_value=(True, "Volume set to 50%."))
_fake_mute      = mock.MagicMock(return_value=(True, "Muted."))
_fake_unmute    = mock.MagicMock(return_value=(True, "Unmuted."))
_fake_wifi_on   = mock.MagicMock(return_value=(True, "WiFi enabled."))
_fake_theme     = mock.MagicMock(return_value=(True, "Switched to dark mode."))

run("SystemAgent", "what's my battery", sys_agent, ctx_sys,
    patch_map={"modules.system_control.get_battery": _fake_battery})

run("SystemAgent", "check ram usage", sys_agent, ctx_sys,
    patch_map={"modules.system_control.get_ram_usage": _fake_ram})

run("SystemAgent", "set volume to 50", sys_agent, ctx_sys,
    patch_map={"modules.system_control.set_volume": _fake_vol_set})

run("SystemAgent", "mute", sys_agent, ctx_sys,
    patch_map={"modules.system_control.mute": _fake_mute})

run("SystemAgent", "turn on wifi", sys_agent, ctx_sys,
    patch_map={"modules.system_control.set_wifi": _fake_wifi_on})

run("SystemAgent", "switch to dark mode", sys_agent, ctx_sys,
    patch_map={"modules.system_control.set_theme": _fake_theme})


# ── 5. WhatsAppAgent ─────────────────────────────────────────────
print("\n[5] WhatsAppAgent")
from Agents.whatsapp_agent import WhatsAppAgent
wa = WhatsAppAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_wa = {"domain": "whatsapp", "confidence": 0.95, "summary": ""}

_fake_read     = mock.MagicMock(return_value="You have 3 unread messages from Rahul.")
_fake_bridge   = mock.MagicMock(return_value=(True, "Bridge connected."))
_fake_unread   = mock.MagicMock(return_value="3 unread messages.")

run("WhatsAppAgent", "how many unread messages do I have", wa, ctx_wa,
    patch_map={"modules.whatsapp_context.get_unread_count": _fake_unread})

# _read_messages calls requests.get to bridge — mock the HTTP call
_fake_hist_resp = mock.MagicMock()
_fake_hist_resp.json.return_value = {"messages": [
    {"fromMe": False, "sender": "Rahul", "text": "Hey, are you coming tomorrow?"},
]}
run("WhatsAppAgent", "read my messages from Rahul", wa, ctx_wa,
    patch_map={
        "modules.whatsapp_handler.ensure_bridge_running": mock.MagicMock(),
        "Agents.whatsapp_agent.requests.get": mock.MagicMock(return_value=_fake_hist_resp),
    })

# Send message — should ask for confirmation (pending state)
run("WhatsAppAgent", "send a message to Priya", wa, ctx_wa)
# Simulate reply with message text (pending_send resolution)
if wa._pending_send:
    print("    [pending_send active — feeding message content]")
    spoken.clear()
    handled = wa.handle("tell her the meeting is at 5pm", ctx_wa)
    print(f"    [pending_send resolved] handled={handled} spoken={spoken}")


# ── 6. SpotifyAgent ──────────────────────────────────────────────
print("\n[6] SpotifyAgent")
from Agents.spotify_agent import SpotifyAgent

mock_spotify = mock.MagicMock()
mock_spotify.pause.return_value = "Music paused."
mock_spotify.resume.return_value = "Music resumed."
mock_spotify.next_track.return_value = "Skipped to next track."
mock_spotify.get_current_track.return_value = "Playing: Tum Hi Ho by Arijit Singh."
mock_spotify.get_recently_played.return_value = "Recently played: Kesariya, Raataan Lambiyan."

spo = SpotifyAgent(speak_fn=speak, raw_ai_fn=raw_ai, spotify_handler=mock_spotify)
ctx_spo = {"domain": "spotify", "confidence": 0.95, "summary": ""}

run("SpotifyAgent", "pause music", spo, ctx_spo)
run("SpotifyAgent", "what's currently playing", spo, ctx_spo)
run("SpotifyAgent", "skip to next song", spo, ctx_spo)
run("SpotifyAgent", "resume", spo, ctx_spo)


# ── 7. FileAgent ─────────────────────────────────────────────────
print("\n[7] FileAgent")
from Agents.file_agent import FileAgent
file_agent = FileAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_file = {"domain": "file", "confidence": 0.95, "summary": ""}

_fake_list    = mock.MagicMock(return_value=(True, "3 folders, 12 files in Downloads", ["file1.pdf", "file2.mp4", "notes.txt"]))
_fake_stats   = mock.MagicMock(return_value=(True, "Downloads has 45 files and 2 subfolders, using 2.3 GB."))
_fake_find    = mock.MagicMock(return_value=[])
_fake_navigate= mock.MagicMock(return_value=(True, "Now in Documents"))
_fake_where   = mock.MagicMock(return_value=os.path.expanduser("~"))

_fm_mock = mock.MagicMock()
_fm_mock.list_folder.return_value = (True, "3 folders, 12 files in Downloads", ["file1.pdf", "file2.mp4", "notes.txt"])
_fm_mock.folder_stats.return_value = (True, "Downloads has 45 files and 2 subfolders, using 2.3 GB.")
_fm_mock.find_file.return_value = []
_fm_mock.smart_find.return_value = []
_fm_mock.navigate.return_value = (True, "Now in Documents")
_fm_mock.where_am_i.return_value = os.path.expanduser("~")
_fm_mock.current_dir = os.path.expanduser("~")
_fm_mock.get_status.return_value = {
    "permission": "balanced", "sandbox": False, "password_set": False,
    "current_dir": os.path.expanduser("~"),
}
_fm_mock.get_recent_actions.return_value = ["OPEN | notes.txt | success"]
_fm_mock.sort_folder.return_value = (True, "Sorted 12 files by name.", ["a.txt", "b.pdf"])

run("FileAgent", "list files in downloads", file_agent, ctx_file,
    patch_map={"modules.file_manager.get_file_manager": mock.MagicMock(return_value=_fm_mock)})

run("FileAgent", "folder stats for downloads", file_agent, ctx_file,
    patch_map={"modules.file_manager.get_file_manager": mock.MagicMock(return_value=_fm_mock)})

run("FileAgent", "where am I", file_agent, ctx_file,
    patch_map={"modules.file_manager.get_file_manager": mock.MagicMock(return_value=_fm_mock)})

run("FileAgent", "recent file actions", file_agent, ctx_file,
    patch_map={"modules.file_manager.get_file_manager": mock.MagicMock(return_value=_fm_mock)})

run("FileAgent", "file system status", file_agent, ctx_file,
    patch_map={"modules.file_manager.get_file_manager": mock.MagicMock(return_value=_fm_mock)})


# ── 8. MemoryAgent ───────────────────────────────────────────────
print("\n[8] MemoryAgent")
from Agents.memory_agent import MemoryAgent
mem = MemoryAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_mem = {"domain": "memory", "confidence": 0.95, "summary": ""}

_fake_add     = mock.MagicMock()
_fake_list_m  = mock.MagicMock(return_value=[("coffee pref", "I like coffee in the morning", "2026-05-22 10:00")])
_fake_remove  = mock.MagicMock(return_value=True)
_fake_summary = mock.MagicMock(return_value="Divya is your college friend.")
_fake_people  = mock.MagicMock(return_value=["Divya", "Rahul", "Priya"])

run("MemoryAgent", "remember that I prefer tea over coffee", mem, ctx_mem,
    patch_map={
        "modules.memory.add_memory": _fake_add,
        "modules.obsidian_brain.log_learned_fact": mock.MagicMock(),
    })

run("MemoryAgent", "what do you remember about me", mem, ctx_mem,
    patch_map={"modules.memory.list_memory": _fake_list_m})

run("MemoryAgent", "who is Divya", mem, ctx_mem,
    patch_map={"modules.relationship_memory.get_summary": _fake_summary})

run("MemoryAgent", "who do you know", mem, ctx_mem,
    patch_map={"modules.relationship_memory.list_people": _fake_people})

run("MemoryAgent", "forget that I like coffee", mem, ctx_mem,
    patch_map={
        "modules.memory.list_memory": _fake_list_m,
        "modules.memory.remove_memory": _fake_remove,
    })


# ── 9. VisionAgent ───────────────────────────────────────────────
print("\n[9] VisionAgent")
from Agents.vision_agent import VisionAgent
vis = VisionAgent(speak_fn=speak, raw_ai_fn=raw_ai)
ctx_vis = {"domain": "vision", "confidence": 0.95, "summary": ""}

_fake_enrolled   = mock.MagicMock(return_value=True)
_fake_not_enroll = mock.MagicMock(return_value=False)
_fake_capture    = mock.MagicMock(return_value="That looks like a smartphone, specifically an iPhone 15.")
_fake_screenshot = mock.MagicMock(return_value="screen_1234.jpg")
_fake_broadcast  = mock.MagicMock()
_fake_delete_f   = mock.MagicMock(return_value=True)

run("VisionAgent", "face auth status", vis, ctx_vis,
    patch_map={"modules.face_auth.is_enrolled": _fake_enrolled})

run("VisionAgent", "is face enrolled", vis, ctx_vis,
    patch_map={"modules.face_auth.is_enrolled": _fake_not_enroll})

run("VisionAgent", "take a screenshot", vis, ctx_vis,
    patch_map={
        "modules.screenshot_engine.capture_sync": _fake_screenshot,
        "modules.ws_bridge.broadcast": _fake_broadcast,
    })

run("VisionAgent", "what am I holding", vis, ctx_vis,
    patch_map={"modules.camera_vision.capture_and_ask": _fake_capture})

run("VisionAgent", "delete my face data", vis, ctx_vis,
    patch_map={"modules.face_auth.delete_face_data": _fake_delete_f})


# ═══════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print(f"  RESULTS  PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
print("="*60)

if FAIL:
    print("\nFailed / Errored tests:")
    for status, agent, cmd, ms, spk in results:
        if status != "PASS":
            print(f"  [{status}] {agent} | '{cmd}'")
            for s in spk:
                print(f"           {s}")
