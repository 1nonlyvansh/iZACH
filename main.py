import os
import sys
os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # prevent DeepFace emoji crash on Windows

import subprocess
import threading
import time
import queue
import asyncio
import edge_tts
import pygame
import re
import speech_recognition as sr
import pyautogui
from dotenv import load_dotenv
from logging_config import setup_logging
setup_logging()


# --- 1. MODULE IMPORTS ---
from modules.automation import (
    get_current_time,
    get_current_date
)
from modules.ai_handler import AIProvider
from modules.spotify_controller import SpotifyController
import modules.context_engine as context_engine
import modules.scheduler as scheduler
import modules.command_chain as command_chain
import modules.performance_guard as performance_guard
import modules.task_manager as task_manager
from modules.context_manager import ContextManager
from modules.whatsapp_handler import init_whatsapp



# First-run onboarding
try:
    from setup.onboarding import needs_onboarding, run_onboarding  # type: ignore[import]
    if needs_onboarding():
        run_onboarding()
except (ImportError, ModuleNotFoundError):
    pass

# Load environment variables
load_dotenv()

# --- 2. CONFIGURATION ---
GROQ_KEY    = os.getenv("GROQ_API_KEY", "")
GEMINI_KEYS = [
    os.getenv("GEMINI_KEY_1", ""),
    os.getenv("GEMINI_KEY_2", ""),
    os.getenv("GEMINI_KEY_3", ""),
]

_AI_ENABLED = True
for _key_name, _key_val in [("GROQ_API_KEY", GROQ_KEY), ("GEMINI_KEY_1", GEMINI_KEYS[0])]:
    if not _key_val:
        print(f"[WARNING] Missing API key: {_key_name} — AI features will be disabled.")
        _AI_ENABLED = False
import uuid
VOICE       = "en-US-ChristopherNeural"
HINDI_VOICE = "hi-IN-MadhurNeural"
TEMP_AUDIO  = "speech.wav"  # fallback, overridden per call

# --- 3. GLOBAL OBJECTS ---
SPEECH_QUEUE = queue.Queue()
EXIT_SIGNAL  = False
app          = None
orchestrator = None
_speaking    = False

ai_manager  = AIProvider(os.getenv("GROQ_API_KEY", GROQ_KEY), GEMINI_KEYS)
spotify_api = SpotifyController()

try:
    pygame.mixer.init()
    print("[SYSTEM] Audio Mixer Initialized.")
except Exception as e:
    print(f"[CRITICAL] Mixer Init Failed: {e}")

# --- 4. NEURAL TTS WORKER ---

def _split_by_language(text, eng_voice=None):
    v = eng_voice or VOICE
    segments = []
    for chunk in re.split(r'([ऀ-ॿ]+)', text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.search(r'[ऀ-ॿ]', chunk):
            segments.append((chunk, HINDI_VOICE))
        else:
            segments.append((chunk, v))
    return segments


def _combined_rate(tone_rate: str, speed_offset: int) -> str:
    """Merge tone rate string ('+5%') with user speed offset (int) → final rate string."""
    m = re.match(r'([+-]?\d+)%', tone_rate.replace(' ', ''))
    base = int(m.group(1)) if m else 5
    total = base + speed_offset
    return f"+{total}%" if total >= 0 else f"{total}%"


async def generate_and_play(text):
    global _speaking
    try:
        from modules.interrupt_engine import get_interrupt_engine
        from modules.personality import extract_tone_rate
        ie = get_interrupt_engine()
        ie.reset()

        clean_text, rate = extract_tone_rate(text)

        try:
            import json as _j
            with open("api_keys.json") as _f:
                _spd = int(_j.load(_f).get("tts_speed", 0))
            rate = _combined_rate(rate, _spd)
        except Exception:
            pass

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

        _active_voice = VOICE
        try:
            import json as _jv
            with open("api_keys.json") as _fv:
                _active_voice = _jv.load(_fv).get("voice", VOICE) or VOICE
        except Exception:
            pass

        segments = _split_by_language(clean_text, _active_voice)

        _speaking = True
        ie.set_speaking(True)

        for seg_text, seg_voice in segments:
            if not seg_text.strip() or ie.is_interrupted():
                break

            audio_file = f"speech_{uuid.uuid4().hex[:8]}.mp3"
            try:
                communicate = edge_tts.Communicate(seg_text, seg_voice, rate=rate)
                await communicate.save(audio_file)
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()

                # Word-by-word live text — synced to audio duration
                words = seg_text.split()
                if words:
                    chars_total = max(len(seg_text), 1)
                    try:
                        duration = pygame.mixer.Sound(audio_file).get_length()
                    except Exception:
                        duration = max(len(seg_text) * 0.065, 1.5)

                    displayed = []
                    for word in words:
                        displayed.append(word)
                        partial = " ".join(displayed)
                        word_ratio = (len(word) + 1) / chars_total
                        word_time  = duration * word_ratio
                        if app and hasattr(app, 'root'):
                            try:
                                app.root.after(0, lambda t=partial: app.update_live_text(t))
                            except RuntimeError:
                                pass
                        try:
                            from modules.ws_bridge import broadcast
                            broadcast({"type": "live_text", "text": partial})
                        except Exception:
                            pass
                        await asyncio.sleep(word_time)

                while pygame.mixer.music.get_busy():
                    if ie.is_interrupted():
                        pygame.mixer.music.stop()
                        print("[INTERRUPT] Speech stopped.")
                        break
                    await asyncio.sleep(0.05)
                pygame.mixer.music.unload()
                await asyncio.sleep(0.1)
            finally:
                try:
                    if os.path.exists(audio_file):
                        os.remove(audio_file)
                except Exception:
                    pass

        if app and hasattr(app, 'root'):
            try:
                app.root.after(0, lambda: app.update_live_text(""))
            except RuntimeError:
                pass
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "live_text", "text": ""})
        except Exception:
            pass
        await asyncio.sleep(0.3)
    except Exception as e:
        print(f"[TTS ERROR] {e}")
    finally:
        _speaking = False
        try:
            from modules.interrupt_engine import get_interrupt_engine
            get_interrupt_engine().set_speaking(False)
        except Exception:
            pass


def tts_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while not EXIT_SIGNAL:
        try:
            text = SPEECH_QUEUE.get(timeout=0.5)
            if text is None:
                break
            loop.run_until_complete(generate_and_play(text))
            SPEECH_QUEUE.task_done()
            if app and hasattr(app, 'set_speaking'):
                app.set_speaking(False)
        except queue.Empty:
            continue
        except Exception as e:
            import traceback
            print(f"[TTS WORKER ERROR] {e}")
            traceback.print_exc()
            continue

def stop_speech():
    pygame.mixer.music.stop()
    while not SPEECH_QUEUE.empty():
        try:
            SPEECH_QUEUE.get_nowait()
            SPEECH_QUEUE.task_done()
        except Exception:
            break
    if app and hasattr(app, 'root'):
        try:
            app.root.after(0, lambda: app.update_live_text(""))
            app.root.after(0, lambda: app.set_speaking(False))
        except RuntimeError:
            pass
    print("[INTERRUPT] Queue cleared.")


# --- 5. CORE FUNCTIONS ---

def speak(text, tone: str = "casual"):
    if not text:
        return
    print(f"[SPEAK] {str(text)[:60]}")
    display_text = re.sub(r'<[^>]+>', '', text).strip()
    display_text = re.sub(r'^\[TONE:[^\]]+\]', '', display_text).strip()
    display_text = display_text.replace("iZACH:", "").strip()
    if not display_text:
        return
    if app and hasattr(app, 'write_log'):
        app.write_log(f"iZACH: {display_text}")
    if app and hasattr(app, 'set_speaking'):
        app.set_speaking(True)
    try:
        from modules.ws_bridge import broadcast
        _ts = time.strftime("%H:%M")
        broadcast({"type": "chat", "sender": "iZACH", "text": display_text, "ts": _ts})
    except Exception:
        pass
    try:
        from modules.personality import add_ssml_tone
        toned = add_ssml_tone(display_text, tone)
        SPEECH_QUEUE.put(toned)
    except Exception:
        SPEECH_QUEUE.put(display_text)


def get_ai_response(query):
    if not _AI_ENABLED:
        return "AI is unavailable — missing API keys. Check your .env file."
    from modules.memory import get_memory_as_context
    from modules.context_memory import get_context_memory
    from modules.personality import PERSONALITY_PROMPT, detect_sentiment, get_companion_response, get_tone_for_sentiment
    from modules.state_engine import state
    cm = get_context_memory()

    resolved    = cm.resolve_followup(query)
    parts       = []
    personal_mem = get_memory_as_context()
    if personal_mem:
        parts.append(personal_mem)

    history = cm.get_history_as_prompt(6)
    if history:
        parts.append(f"Recent conversation:\n{history}")

    persona_prefix = state.get_persona_prefix()
    parts.insert(0, persona_prefix + PERSONALITY_PROMPT)

    if parts:
        full_query = "\n\n".join(parts) + f"\n\nUser: {resolved}"
    else:
        full_query = resolved

    response = ai_manager.send_message(full_query)

    from modules.response_generator import _detect_language
    lang      = _detect_language(query)
    sentiment = detect_sentiment(query)
    if lang == "en":
        companion = get_companion_response(sentiment)
        if companion and response:
            response = f"{companion} {response}"

    cm.add_turn(query, response or "")
    cm.update_entities_from_input(query)
    return response


def get_ai_response_raw(query):
    if not _AI_ENABLED:
        return "AI is unavailable — missing API keys. Check your .env file."
    return ai_manager.send_message(query)


# --- 6. COMMAND LOOP ---

_recognizer = sr.Recognizer()
_recognizer.pause_threshold         = 2.5
_recognizer.phrase_threshold        = 0.2
_recognizer.non_speaking_duration   = 1.0
_recognizer.energy_threshold        = 250
_recognizer.dynamic_energy_threshold = False
_mic = None
_mic_device_index = None

def set_mic_device(index):
    global _mic, _mic_device_index
    _mic_device_index = index
    _mic = None

def _init_mic():
    global _mic
    _mic = sr.Microphone(device_index=_mic_device_index)
    with _mic as source:
        _recognizer.adjust_for_ambient_noise(source, duration=1.5)
    print(f"[MIC] Calibrated. Energy threshold: {_recognizer.energy_threshold:.0f}")


def listen():
    global _mic
    try:
        from modules.ui_api import is_mic_active
        if not is_mic_active():
            time.sleep(0.5)
            return "none"
    except Exception:
        pass
    if app and hasattr(app, 'is_mic_active') and not app.is_mic_active():
        time.sleep(0.5)
        return "none"
    if _mic is None:
        _init_mic()
    try:
        with _mic as source:
            print("[LISTENING...]")
            audio = _recognizer.listen(source, timeout=3, phrase_time_limit=15)
        # Check again after listening in case mic was turned off during capture
        try:
            from modules.ui_api import is_mic_active
            if not is_mic_active():
                return "none"
        except Exception:
            pass
        text = _recognizer.recognize_google(audio, language='en-in').lower()

        # Inline wake word check — single pyaudio stream, no conflict
        try:
            from modules.wake_word import get_wake_detector
            det = get_wake_detector()
            if det is not None:
                if det.check_text(text):
                    print(f"[WAKE WORD] Heard: {text}")
                    det.activate()
                    return "none"
                if not det.is_active():
                    return "none"
        except Exception:
            pass

        return text
    except sr.WaitTimeoutError:
        return "none"
    except Exception:
        return "none"


def safe_shutdown():
    global EXIT_SIGNAL
    EXIT_SIGNAL = True

    try:
        SPEECH_QUEUE.put(None)
    except:
        pass

    try:
        if orchestrator:
            orchestrator.stop_task_worker()
    except:
        pass

    try:
        pygame.mixer.quit()
    except:
        pass

    print("[SYSTEM] Shutting down cleanly...")

    sys.exit(0)


# ─────────────────────────────────────────────────────────────
# start_brain — works with ui=None (Electron/headless) OR
#               ui=JarvisUI instance (old tkinter mode)
# ─────────────────────────────────────────────────────────────
def start_brain(ui=None):
    global app, orchestrator, chain_engine
    app = ui  # None when Electron UI is used

    # 1. Background services
    orchestrator = task_manager.TaskOrchestrator()
    orchestrator.start_task_worker()

    # 2. Performance Guard & Scheduler
    def _proactive_speak(msg):
        from modules.personality import detect_sentiment, get_tone_for_sentiment
        tone = get_tone_for_sentiment(detect_sentiment(msg))
        speak(msg, tone=tone)

    guard = performance_guard.PerformanceGuard(_proactive_speak)
    guard.start()
    reminder_engine = scheduler.TaskScheduler(speak, orchestrator)
    reminder_engine.start()

    # 3. Memory & Chain
    ctx_mgr = ContextManager()
    chain_engine = command_chain.CommandChain(
        context_handler=context_engine,
        scheduler_handler=reminder_engine,
        ai_handler=get_ai_response,
        raw_ai_handler=get_ai_response_raw,
        speak_func=speak,
        orchestrator=orchestrator,
        context_manager=ctx_mgr,
        spotify_handler=spotify_api
    )
    command_chain._chain_ref = chain_engine  # expose to ws_bridge for fill_result + command messages

    # Start device watchers after speak and chain are ready
    from modules import system_control as _sc
    _sc.start_bluetooth_watcher(speak)
    _sc.start_drive_watcher(speak)

    # 4. WhatsApp callbacks — real ones if old UI, dummy lambdas if headless
    from modules.whatsapp_handler import set_ui_callbacks
    if ui is not None:
        set_ui_callbacks(ui.add_notification, ui.add_error_log)
        ui.set_chain(chain_engine)
    else:
        set_ui_callbacks(
            lambda title, msg: print(f"[NOTIFY] {title}: {msg}"),
            lambda msg:        print(f"[ERROR LOG] {msg}")
        )

    init_whatsapp(speak, chain_engine.process, get_ai_response)

    # 6. Interrupt engine
    from modules.interrupt_engine import get_interrupt_engine
    ie = get_interrupt_engine()
    ie.set_stop_fn(stop_speech)

    # 7. Mic calibration (in background so startup is not delayed)
    threading.Thread(target=_init_mic, daemon=True).start()

    # MongoDB brain — non-blocking init
    try:
        from modules.mongo_brain import get_db, save_user_profile
        if get_db() is not None:
            save_user_profile(os.getenv("OWNER_NAME", "User"), {
                "response_style": "casual",
                "language":       "hinglish",
                "tts_voice":      "Christopher"
            })
    except Exception:
        pass

    # 8. Response generator
    from modules.response_generator import init_response_generator
    init_response_generator(
        groq_key=os.getenv("GROQ_API_KEY", GROQ_KEY),
        gemini_keys=[
            os.getenv("GEMINI_KEY_1", GEMINI_KEYS[0]),
            os.getenv("GEMINI_KEY_2", GEMINI_KEYS[1]),
            os.getenv("GEMINI_KEY_3", GEMINI_KEYS[2]),
        ],
        speak_func=speak
    )

    # 9. MMA status check
    try:
        import requests as _req
        r = _req.get("http://localhost:6060/health", timeout=2)
        if r.status_code == 200:
            speak("MMA remote agent is online.")
        else:
            speak("MMA agent is offline.")
    except Exception:
        speak("MMA agent is offline.")

    # ── Startup status summary ────────────────────────────────
    from modules.mongo_brain import get_db as _get_db
    _mongo_ok = _get_db() is not None
    _tts_ok   = pygame.mixer.get_init() is not None
    _ok  = "OK"
    _no  = "MISSING"
    print("\n" + "─" * 38)
    print("  iZACH Startup Status")
    print("─" * 38)
    print(f"  GROQ_API_KEY   {'OK' if GROQ_KEY   else 'MISSING'}")
    print(f"  GEMINI_KEY_1   {'OK' if GEMINI_KEYS[0] else 'MISSING'}")
    print(f"  MongoDB        {'Connected' if _mongo_ok else 'Not Connected'}")
    print(f"  TTS Engine     {'Ready' if _tts_ok else 'Failed'}")
    print(f"  AI Features    {'Enabled' if _AI_ENABLED else 'Disabled'}")
    print("─" * 38)
    print("  Try saying:")
    print("    • play something chill on spotify")
    print("    • open my notes")
    print("    • what's on my screen")
    print("    • remind me to call mom at 6pm")
    print("    • fill my details  (on any form)")
    print("    • delete old files in downloads")
    print("    • what can you do")
    print("─" * 38 + "\n")
    # ─────────────────────────────────────────────────────────

    speak("Assistant System Online.")

    # Phase 3: SmartAlarm + WhatsApp 24h context engine
    try:
        from modules.smart_alarm import init as _init_alarm
        _init_alarm(speak_fn=speak)
        print("[SMART ALARM] Initialized — persistent alarm engine active.")
    except Exception as _ae:
        print(f"[SMART ALARM] Init failed: {_ae}")

    try:
        from modules.whatsapp_context import startup_sync
        startup_sync(speak_fn=speak, hours=24)
        print("[WA CONTEXT] 24h history sync started in background.")
    except Exception as _wce:
        print(f"[WA CONTEXT] Startup sync failed: {_wce}")

    try:
        from modules.proactive_agent import init as _init_proactive, start as _start_proactive
        _init_proactive(speak_fn=speak)
        _start_proactive()
        print("[PROACTIVE] Agent started.")
    except Exception as _pe:
        print(f"[PROACTIVE] Init failed: {_pe}")

    try:
        from modules.pattern_learner import init as _init_patterns, start as _start_patterns
        _init_patterns(speak_fn=speak, chain_fn=chain_engine.process)
        _start_patterns()
        print("[PATTERNS] Learner started.")
    except Exception as _ple:
        print(f"[PATTERNS] Init failed: {_ple}")

    print("[FACE AUTH] Lazy-loaded — activates on first face command.")

    # Prune old command history per retention setting
    try:
        from modules.mongo_brain import cleanup_old_logs
        cleanup_old_logs()
    except Exception:
        pass

    # 10. Wake word
    import json as _json
    _ww_enabled = False
    try:
        with open("api_keys.json") as _f:
            _ww_enabled = _json.load(_f).get("wake_word_enabled", False)
    except Exception:
        pass

    # Read clap_enabled from settings (default True)
    _clap_enabled = True
    try:
        with open("api_keys.json") as _f:
            _clap_enabled = _json.load(_f).get("clap_enabled", True)
    except Exception:
        pass

    def _on_single_clap():
        speak("Listening.")
        if _ww_enabled and _wake_detector is not None:
            _wake_detector.extend_active()

    def _on_double_clap():
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    _clap_det = None
    if _clap_enabled:
        try:
            from modules.clap_detector import init_clap_detector
            _clap_det = init_clap_detector(on_single=_on_single_clap, on_double=_on_double_clap)
            _clap_det.start()
        except Exception as _ce:
            print(f"[CLAP] Failed to start: {_ce}")
    else:
        print("[CLAP] Disabled in settings.")

    # Start wake word detector if enabled
    _wake_detector = None
    if _ww_enabled:
        try:
            from modules.wake_word import init_wake_word
            def _ww_activated():
                speak("Yes?")
            _wake_detector = init_wake_word(_ww_activated)
            _wake_detector.start()
            print("[WAKE WORD] Active — say 'Hey iZACH' to activate.")
        except Exception as _we:
            print(f"[WAKE WORD] Failed to start: {_we}")
            _ww_enabled = False
    else:
        print("[WAKE WORD] Disabled — always listening mode")

    # Kill any leftover process on port 5051
    import subprocess
    try:
        netstat = subprocess.run(["netstat", "-aon"], capture_output=True, text=True)
        for line in netstat.stdout.splitlines():
            if ":5051 " in line:
                parts = line.split()
                if parts:
                    subprocess.run(["taskkill", "/F", "/PID", parts[-1]], capture_output=True)
    except Exception:
        pass

    # Launch WebSocket bridge
    from modules.ws_bridge import start_ws_bridge
    start_ws_bridge()

    # Launch Electron UI
    import subprocess
    ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "izach-ui")
    subprocess.Popen(
        ["cmd", "/c", "npm", "run", "electron:dev"],
        cwd=ui_path,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    print("[UI] Electron UI launching...")

    # 11. Voice loop
    def voice_loop():
        # Wait for mic to finish calibrating before starting
        while _mic is None and not EXIT_SIGNAL:
            time.sleep(0.2)

        while not EXIT_SIGNAL:
            try:
                query = listen()
                if query == "none":
                    if _wake_detector and _wake_detector.is_active():
                        _wake_detector.extend_active()
                    continue
                print(f"[USER]: {query}")
                if app and hasattr(app, 'root'):
                    try:
                        app.root.after(0, lambda q=query: app._chat.add_message("USER", q))
                    except Exception:
                        pass
                try:
                    from modules.ws_bridge import broadcast
                    broadcast({
                        "type": "chat",
                        "sender": "YOU",
                        "text": query,
                        "ts": time.strftime("%H:%M")
                    })
                except Exception:
                    pass
                if any(w in query for w in ["shutdown", "exit izach", "stop izach"]):
                    speak("Systems offline.")
                    safe_shutdown()
                    break
                try:
                    from modules.proactive_agent import record_interaction
                    record_interaction()
                except Exception:
                    pass
                if _wake_detector:
                    _wake_detector.extend_active()
                _t0 = time.time()
                try:
                    chain_engine.process(query)
                    _status = "fail" if "unknown" in query.lower() else "success"
                except Exception as _e:
                    _status = "fail"
                    raise
                finally:
                    try:
                        from modules.command_logger import log_command
                        log_command("voice", query, "", round(time.time() - _t0, 3), _status)
                        if _status == "success":
                            from modules.mongo_brain import log_important_command
                            log_important_command(query, "", "voice")
                        if _status == "fail":
                            from modules.obsidian_brain import log_weakness
                            log_weakness(f"Failed voice command: {query[:60]}")
                    except Exception:
                        pass
            except Exception as e:
                import traceback
                print(f"[RUNTIME ERROR] {e}")
                traceback.print_exc()
                continue
    threading.Thread(target=voice_loop, daemon=True).start()

    try:
        while not EXIT_SIGNAL:
            time.sleep(1)
    except KeyboardInterrupt:
        safe_shutdown()
    except Exception as e:
        import traceback
        print(f"[MAIN LOOP CRASH] {e}")
        traceback.print_exc()
        input("Press Enter to exit...")

if __name__ == "__main__":
    from modules.mongo_brain import init_db
    db = init_db()
    if db is None:
        print("[MONGO] Warning: MongoDB not connected — memory features degraded.")

    try:
        from modules.log_analyzer import analyze_logs
        analyze_logs()
    except:
        pass

    threading.Thread(target=tts_worker, daemon=True).start()

    try:
        start_brain(ui=None)
    except Exception as e:
        import traceback
        print(f"\n[FATAL CRASH] {e}")
        traceback.print_exc()

    # Keep process alive until Ctrl+C
    try:
        while not EXIT_SIGNAL:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[SYSTEM] Shutting down.")
        safe_shutdown()