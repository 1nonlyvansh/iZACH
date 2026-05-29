import os
import sys
os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # prevent DeepFace emoji crash on Windows

# ── Crash handler — MUST be first so it catches every later import/init crash.
# Persists everything (native crashes, uncaught exceptions, print output, signals)
# to logs/crash.log + logs/console.log. CMD window also stays open on crash.
try:
    from modules.crash_handler import install as _install_crash_handler
    _install_crash_handler()
except Exception as _ch_err:
    sys.stderr.write(f"[crash_handler] install failed: {_ch_err}\n")

# Suppress TensorFlow / oneDNN noise before any imports trigger TF load
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")        # hide C++ TF logs
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")       # disable oneDNN ops (eliminates the port.cc warning)
os.environ.setdefault("ABSL_MIN_LOG_LEVEL", "3")           # suppress absl::InitializeLog warnings
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")           # suppress gRPC noise

# ── Numba / LLVM safety — MUST be set before any numba/librosa import ─────
# SIGABRT root cause: numba JIT compiles on a thread while another thread
# does SSL/malloc (Spotify API) — LLVM's multi-threaded allocator conflicts.
# workqueue = single-threaded LLVM backend → no allocator race → no SIGABRT.
os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")
# Cache compiled bitcode to disk — skip full JIT recompile on subsequent starts.
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(os.getcwd(), ".numba_cache"))
# Limit numba to 1 thread — prevents parallel LLVM workers racing with CPython GIL.
os.environ.setdefault("NUMBA_NUM_THREADS", "1")
# Keep OMP/MKL single-threaded as well (same reason).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

# Suppress OpenCV VIDEOIO/DSHOW/MSMF/FFMPEG C++ backend warnings.
# Must be set BEFORE cv2 DLL loads — setting it inside camera_vision.py is too late
# if cv2 was already imported by another module.
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"      # suppress all OpenCV C++ logs
os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"       # extra safety for VIDEOIO backend noise
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"    # FFMPEG plugin ignores OPENCV_LOG_LEVEL — silence separately

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
from modules.audio_init_lock import PYAUDIO_INIT_LOCK
from dotenv import load_dotenv
from logging_config import setup_logging
setup_logging()
import logging as _logging
logger = _logging.getLogger(__name__)


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
from Agents.orchestrator import OrchestratorAgent



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
app              = None
orchestrator     = None
agent_orch       = None   # OrchestratorAgent — intent classifier
_speaking        = False

# ── Subprocess guard ───────────────────────────────────────────
# multiprocessing.spawn re-imports main.py inside child processes (face_auth
# subprocess workers). Heavy module-level init (audio device, Spotify auth,
# Flask app, etc.) MUST NOT run in the child — it conflicts with the parent
# and can take the backend offline.
import multiprocessing as _mp
_IS_SUBPROCESS = _mp.current_process().name != "MainProcess"

if _IS_SUBPROCESS:
    # Provide minimal stubs so any incidental references don't NameError;
    # subprocess workers never actually call these.
    ai_manager  = None
    spotify_api = None
else:
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
                _cfg = _j.load(_f)
            rate = _combined_rate(rate, int(_cfg.get("tts_speed", 0)))
            _active_voice = _cfg.get("voice", VOICE) or VOICE
        except Exception:
            _active_voice = VOICE

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
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
                # Retry up to 2 times — edge_tts occasionally returns "No audio
                # was received" on transient network hiccups.
                for _attempt in range(3):
                    try:
                        communicate = edge_tts.Communicate(seg_text, seg_voice, rate=rate)
                        await communicate.save(audio_file)
                        if os.path.getsize(audio_file) > 0:
                            break
                    except Exception as _tts_err:
                        if _attempt == 2:
                            raise
                        await asyncio.sleep(0.5 * (_attempt + 1))
                pygame.mixer.music.load(audio_file)
                pygame.mixer.music.play()

                # Word-by-word live text — synced to audio duration
                words = seg_text.split()
                if words:
                    chars_total = max(len(seg_text), 1)
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
        # Small cooldown so speaker reverb clears before mic re-opens.
        await asyncio.sleep(0.6)
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
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "tts_start", "word_count": len(str(text).split())})
            except Exception:
                pass
            loop.run_until_complete(generate_and_play(text))
            SPEECH_QUEUE.task_done()
            try:
                from modules.ws_bridge import broadcast
                broadcast({"type": "tts_end"})
            except Exception:
                pass
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

_last_izach_question: str = ""   # last spoken text if it ended with '?'
_question_expires_at: float = 0.0

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

    # ── DND gate: suppress audio when Do Not Disturb is active ──
    try:
        from modules import dnd_mode as _dnd
        if _dnd.is_active():
            logger.debug("[DND] speak() suppressed — DND active.")
            return   # text already broadcast to UI above; no audio
    except Exception:
        pass

    global _last_izach_question, _question_expires_at
    stripped = display_text.rstrip(" .!,")
    if stripped.endswith("?"):
        _last_izach_question = display_text
        _question_expires_at = time.time() + 120
    else:
        _last_izach_question = ""
    try:
        from modules.personality import add_ssml_tone
        toned = add_ssml_tone(display_text, tone)
        SPEECH_QUEUE.put(toned)
    except Exception:
        SPEECH_QUEUE.put(display_text)


def get_ai_response(query):
    if not _AI_ENABLED:
        return "AI is unavailable — missing API keys. Check your .env file."

    # ── Skill detection — #skill-id or #skill1 & #skill2 prefix ─────────────
    try:
        from modules.skill_engine import (
            detect_skills, build_multi_skill_context,
            save_project_files, extract_project_name
        )
        skill_ids, clean_query = detect_skills(query)
        if skill_ids:
            sys_add, clean_query, skill_meta = build_multi_skill_context(skill_ids, clean_query)
            if sys_add:
                model_pref = skill_meta.get("model", "auto")
                response = ai_manager.send_with_model(clean_query, model_pref, sys_add)
                # Save project files if any skill creates files
                if skill_meta.get("creates_files") and response:
                    proj_name = extract_project_name(clean_query)
                    saved = save_project_files(response, proj_name)
                    if saved:
                        file_list = " · ".join(os.path.basename(p) for p in saved)
                        response = (
                            f"Done! Built **{proj_name}** and saved to "
                            f"`C:/iZACH-Projects/{proj_name}/`\n"
                            f"Files: {file_list}\n\n"
                            f"Open the folder to view and run the project."
                        )
                return response
    except Exception as _se:
        print(f"[SkillEngine] Error: {_se}")

    from modules.memory import get_memory_as_context
    from modules.context_memory import get_context_memory
    from modules.personality import PERSONALITY_PROMPT, detect_sentiment, get_companion_response, get_tone_for_sentiment
    from modules.response_generator import _detect_language
    from modules.state_engine import state
    cm = get_context_memory()

    resolved    = cm.resolve_followup(query)
    lang        = _detect_language(query)

    # Hard per-query language directive — injected after the user message so the
    # model cannot override it with the general personality rule.
    if lang == "hi":
        lang_directive = (
            "\n[LANGUAGE RULE] User wrote in Hinglish. Reply in casual Hinglish — "
            "mix Hindi/Urdu words with English naturally, like Indian friends text. "
            "Example style: 'Bhai sorted hai', 'Chal theek hai', 'Acha nice'."
        )
    else:
        lang_directive = (
            "\n[LANGUAGE RULE] User wrote in English. Reply in English ONLY. "
            "Do NOT use any Hindi/Urdu words — no 'bhai', no 'yaar', no 'kya', nothing."
        )

    parts       = []
    personal_mem = get_memory_as_context()
    if personal_mem:
        parts.append(personal_mem)

    # Smart memory — profile facts + behavioral instructions
    try:
        from modules.smart_memory import get_full_context as _sm_ctx
        sm_ctx = _sm_ctx()
        if sm_ctx:
            parts.append(sm_ctx)
    except Exception:
        pass

    history = cm.get_history_as_prompt(6)
    if history:
        parts.append(f"Recent conversation:\n{history}")

    persona_prefix = state.get_persona_prefix()
    parts.insert(0, persona_prefix + PERSONALITY_PROMPT)

    # Active window + location context — gives JARVIS-level awareness
    try:
        from modules.window_watcher import get_active_window
        win = get_active_window()
        if win.get("title"):
            parts.append(f"[CONTEXT] User has '{win['title']}' open in {win['app']}.")
    except Exception:
        pass

    try:
        from modules.location_engine import get_location
        loc = get_location()
        loc_str = loc.get("label") or loc.get("city") or ""
        if loc_str:
            parts.append(f"[CONTEXT] User location: {loc_str}.")
    except Exception:
        pass

    if parts:
        full_query = "\n\n".join(parts) + f"\n\nUser: {resolved}{lang_directive}"
    else:
        full_query = resolved + lang_directive

    response = ai_manager.send_message(full_query)

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
    with PYAUDIO_INIT_LOCK:
        _mic = sr.Microphone(device_index=_mic_device_index)
        with _mic as source:
            _recognizer.adjust_for_ambient_noise(source, duration=1.5)
    print(f"[MIC] Calibrated. Energy threshold: {_recognizer.energy_threshold:.0f}")


def listen():
    global _mic

    # ── Barge-in command queue check ─────────────────────────
    # If user spoke during TTS playback, that command was captured by
    # interrupt_engine._voice_monitor_loop. Consume it here first.
    try:
        from modules.interrupt_engine import get_interrupt_engine
        _barge_cmd = get_interrupt_engine().get_barge_in_command()
        if _barge_cmd:
            print(f"[BARGE-IN] Executing queued command: {_barge_cmd!r}")
            return _barge_cmd
    except Exception:
        pass

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

    # Block mic while TTS is playing — prevents feedback loop where mic
    # picks up speaker output and processes it as a command.
    if _speaking:
        time.sleep(0.1)
        return "none"
    try:
        from modules.interrupt_engine import get_interrupt_engine
        if get_interrupt_engine().is_speaking():
            time.sleep(0.1)
            return "none"
    except Exception:
        pass

    if _mic is None:
        _init_mic()
    try:
        # Hold PYAUDIO_INIT_LOCK during BOTH __enter__ (Pa_Initialize) and
        # __exit__ (Pa_Terminate). Concurrent Pa_Initialize or Pa_Terminate
        # calls from interrupt_engine cause Windows access violations (C crash).
        try:
            with PYAUDIO_INIT_LOCK:
                source = _mic.__enter__()
        except Exception:
            return "none"
        try:
            print("[LISTENING...]")
            audio = _recognizer.listen(source, timeout=3, phrase_time_limit=15)
        finally:
            try:
                with PYAUDIO_INIT_LOCK:
                    _mic.__exit__(None, None, None)
            except Exception:
                pass
        # Check again after listening in case mic was turned off during capture
        try:
            from modules.ui_api import is_mic_active
            if not is_mic_active():
                return "none"
        except Exception:
            pass
        text = _recognizer.recognize_google(audio, language='en-in').lower()

        # ── Speaker diarization ───────────────────────────────
        # Filters background/TV audio and optionally tags non-owner speakers.
        try:
            from modules.speaker_diarization import identify_speaker, OWNER_KEY as _OWNER_KEY
            speaker = identify_speaker(audio)   # audio is sr.AudioData
            if speaker is None:
                # Too quiet / distant — background audio, ignore
                print(f"[LISTEN] Diarization dropped (low energy/background). Text was: {text!r}")
                return "none"
            if speaker not in (_OWNER_KEY, "unknown"):
                # Known non-owner speaker in the room
                print(f"[DIARIZATION] Speaker: {speaker}")
                text = f"[{speaker.title()}] {text}"
        except Exception as _dia_err:
            pass   # diarization is optional; errors don't block

        # Inline wake word check — single pyaudio stream, no conflict
        try:
            from modules.wake_word import get_wake_detector
            det = get_wake_detector()
            if det is not None:
                if det.check_text(text):
                    print(f"[WAKE WORD] Activated by: {text!r}")
                    det.activate()
                    return "none"
                if not det.is_active():
                    print(f"[WAKE WORD] Blocked (say 'Hey iZACH' first). Text: {text!r}")
                    return "none"
        except Exception:
            pass

        print(f"[HEARD] {text!r}")
        return text
    except sr.WaitTimeoutError:
        return "none"
    except sr.UnknownValueError:
        # Google could not understand audio (mumble, noise, etc.)
        return "none"
    except sr.RequestError as _req_err:
        print(f"[LISTEN] Google STT error: {_req_err}")
        return "none"
    except Exception as _listen_err:
        print(f"[LISTEN] Unexpected error: {_listen_err}")
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
    global app, orchestrator, agent_orch, chain_engine
    app = ui  # None when Electron UI is used

    # 0. Pre-warm ChromaDB / ONNX model in a BACKGROUND thread.
    #    The init lock inside rag_memory prevents concurrent downloads.
    #    Voice loop starts immediately; RAG calls block only if model isn't
    #    ready yet (usually cached after first run — < 1s wait).
    def _rag_warmup_bg():
        try:
            from modules import rag_memory as _rag
            _rag.warmup()
        except Exception as _rag_err:
            print(f"[RAG] Warmup skipped: {_rag_err}")
    import threading as _threading
    _threading.Thread(target=_rag_warmup_bg, daemon=True, name="RAG-Warmup").start()
    print("[RAG] ChromaDB warmup started in background.")

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

    # Automation memory scheduler (APScheduler for recurring memory jobs)
    try:
        from modules.automation_scheduler import init as _init_auto_sched
        _init_auto_sched(speak)
    except Exception as _ase:
        print(f"[Main] AutoScheduler init skipped: {_ase}")

    # 3. Memory & Chain
    ctx_mgr    = ContextManager()
    agent_orch = OrchestratorAgent(groq_key=GROQ_KEY) if GROQ_KEY else None
    chain_engine = command_chain.CommandChain(
        context_handler=context_engine,
        scheduler_handler=reminder_engine,
        ai_handler=get_ai_response,
        raw_ai_handler=get_ai_response_raw,
        speak_func=speak,
        orchestrator=orchestrator,
        context_manager=ctx_mgr,
        spotify_handler=spotify_api,
        agent_orch=agent_orch,
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

    # Defer startup greeting until Electron UI connects to WS bridge
    def _deferred_greeting():
        from modules.ws_bridge import _ui_ready_event
        connected = _ui_ready_event.wait(timeout=120)
        time.sleep(0.8)  # let React fully mount
        if connected:
            speak("Assistant System Online.")
        else:
            speak("Assistant System Online.")  # speak anyway after 2-min timeout

    threading.Thread(target=_deferred_greeting, daemon=True).start()

    # Startup briefing (if enabled in settings)
    try:
        import json as _bj
        with open("api_keys.json") as _bf:
            _bcfg = _bj.load(_bf)
        if _bcfg.get("briefing_enabled", False):
            def _startup_briefing():
                time.sleep(4)
                chain_engine._handle_briefing()
            threading.Thread(target=_startup_briefing, daemon=True).start()
    except Exception:
        pass

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
        from modules import subconsciousness as _subcon
        _subcon.init(speak_fn=speak, chain_fn=chain_engine.process)
        _subcon.start()
        print("[SUBCONSCIOUSNESS] Background agent started.")
    except Exception as _sce:
        print(f"[SUBCONSCIOUSNESS] Init failed: {_sce}")

    try:
        from modules.instagram_engine import init as _ig_init
        _ig_init(speak_fn=speak, ai_fn=get_ai_response_raw)
        print("[INSTAGRAM] Engine initialized.")
    except Exception as _ige:
        print(f"[INSTAGRAM] Init failed: {_ige}")

    try:
        from modules.news_engine import init as _news_init
        _news_init(speak_fn=speak, ai_fn=get_ai_response_raw)
        print("[NEWS] Engine initialized.")
    except Exception as _newse:
        print(f"[NEWS] Init failed: {_newse}")

    try:
        from modules.pattern_learner import init as _init_patterns, start as _start_patterns
        _init_patterns(speak_fn=speak, chain_fn=chain_engine.process)
        _start_patterns()
        print("[PATTERNS] Learner started.")
    except Exception as _ple:
        print(f"[PATTERNS] Init failed: {_ple}")

    try:
        from modules.curiosity_engine import init as _init_curiosity, start as _start_curiosity
        _init_curiosity(speak_fn=speak)
        _start_curiosity()
        print("[CURIOSITY] Engine started.")
    except Exception as _ce:
        print(f"[CURIOSITY] Init failed: {_ce}")

    try:
        from modules.system_log_analyzer import init as _init_syslog, start as _start_syslog
        _init_syslog(speak_fn=speak)
        _start_syslog()
        print("[SYSLOG] Analyzer started.")
    except Exception as _sle:
        print(f"[SYSLOG] Init failed: {_sle}")

    try:
        from modules.window_watcher import start as _start_window
        _start_window(speak_fn=speak)
    except Exception as _we:
        print(f"[WINDOW] Init failed: {_we}")

    # Location engine starts on-demand via UI toggle (not auto-started)
    print("[LOCATION] Engine ready — activate from Location widget in UI.")

    try:
        from modules.network_monitor import start as _start_network
        _start_network(speak_fn=speak)
    except Exception as _ne:
        print(f"[NETWORK] Init failed: {_ne}")

    # Init face_auth at startup so Settings UI face-enroll button works
    # without needing a voice command first. face_auth.py only imports stdlib
    # at module level — dlib stays in the subprocess workers.
    try:
        from modules import face_auth as _face_auth
        _face_auth.init(speak)
        print("[FACE AUTH] Initialized — speak handler bound.")
    except Exception as _fae:
        print(f"[FACE AUTH] Init failed: {_fae}")

    try:
        from modules.voice_id import init as _vi_init, warmup as _vi_warmup
        _vi_init(speak)
        # Warm up resemblyzer + librosa + numba on a dedicated thread spawned
        # from the main process. JIT compiles ~10-20 s on first run; must
        # NOT happen in a Flask worker thread or LLVM aborts the process.
        def _voice_warmup_bg():
            try:
                _vi_warmup()
            except Exception as _vwe:
                print(f"[VOICE ID] Warmup background error: {_vwe}")
        threading.Thread(target=_voice_warmup_bg, daemon=True, name="VoiceID-Warmup").start()
        print("[VOICE ID] Initialized — warmup running in background.")
    except Exception as _vie:
        print(f"[VOICE ID] Init failed: {_vie}")

    try:
        from modules.research_agent import init as _ri
        _ri(speak_fn=speak)
        print("[RESEARCH] Agent initialized.")
    except Exception as _rae:
        print(f"[RESEARCH] Init failed: {_rae}")

    try:
        from modules.wa_group_summarizer import init as _wgs_init
        _wgs_init(speak_fn=speak, ai_fn=get_ai_response)
        print("[GROUP SUM] Summarizer initialized.")
    except Exception as _wgse:
        print(f"[GROUP SUM] Init failed: {_wgse}")

    try:
        from modules.app_preloader import init as _apl_init, start as _apl_start
        _apl_init(speak_fn=speak)
        _apl_start()
        print("[PRELOADER] App pre-loader started.")
    except Exception as _aple:
        print(f"[PRELOADER] Init failed: {_aple}")

    try:
        from modules.clipboard_sync import init as _cs_init
        _cs_init(speak_fn=speak, chain_fn=chain_engine.process)
        print("[CLIPBOARD] Smart clipboard initialized.")
    except Exception as _cse:
        print(f"[CLIPBOARD] Smart init failed: {_cse}")

    try:
        from modules.download_monitor import start as _start_dlmon
        _start_dlmon()
        print("[DOWNLOAD MONITOR] Started.")
    except Exception as _dlme:
        print(f"[DOWNLOAD MONITOR] Init failed: {_dlme}")

    try:
        from modules.speaker_diarization import init as _sd_init
        _sd_init(speak_fn=speak)
        print("[DIARIZATION] Speaker diarization initialized.")
    except Exception as _sde:
        print(f"[DIARIZATION] Init failed: {_sde}")

    try:
        from modules import dnd_mode as _dnd_mod
        from modules.ws_bridge import broadcast as _ws_broadcast
        _dnd_mod.init(speak_fn=speak, broadcast_fn=_ws_broadcast)
        print("[DND] Do Not Disturb engine initialized.")
    except Exception as _dnde:
        print(f"[DND] Init failed: {_dnde}")

    try:
        from modules import busy_mode as _busy_mod
        from modules.ws_bridge import broadcast as _ws_broadcast2
        _busy_mod.init(speak_fn=speak, broadcast_fn=_ws_broadcast2)
        print("[BUSY] Busy mode engine initialized.")
    except Exception as _busye:
        print(f"[BUSY] Init failed: {_busye}")

    try:
        from modules.synonym_learner import stats as _sl_stats
        _sl = _sl_stats()
        print(f"[SYNONYM LEARNER] {_sl['total_synonyms']} synonyms across {_sl['domains_learned']} domains.")
    except Exception as _sle2:
        print(f"[SYNONYM LEARNER] Init failed: {_sle2}")

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

    # 11. Voice loop
    def voice_loop():
        global _last_izach_question, _question_expires_at
        # Wait for mic to finish calibrating before starting
        while _mic is None and not EXIT_SIGNAL:
            time.sleep(0.2)

        while not EXIT_SIGNAL:
            try:
                # Pause main voice loop while voice enrollment is recording —
                # otherwise the user's enrollment phrase gets captured by both
                # the enrollment recorder AND the voice loop, which then
                # routes it as a command. Includes a safety reset so a stuck
                # _enrolling flag never silently kills the voice loop.
                try:
                    from modules import voice_id as _vid
                    if getattr(_vid, "_enrolling", False):
                        # Track when enrollment flag first observed True so we
                        # can detect a stuck state and reset it.
                        if not hasattr(voice_loop, "_enroll_pause_start"):
                            voice_loop._enroll_pause_start = time.time()
                            print("[VOICE LOOP] Paused — voice enrollment in progress.")
                        elif time.time() - voice_loop._enroll_pause_start > 90:
                            print("[VOICE LOOP] Enrollment flag stuck > 90 s — forcing reset.")
                            _vid._enrolling = False
                            voice_loop._enroll_pause_start = None
                        time.sleep(0.5)
                        continue
                    elif hasattr(voice_loop, "_enroll_pause_start") and voice_loop._enroll_pause_start:
                        print("[VOICE LOOP] Resumed — voice enrollment cleared.")
                        voice_loop._enroll_pause_start = None
                except Exception:
                    pass
                # Also pause while face enrollment subprocess is using the camera/mic
                try:
                    from modules import face_auth as _fa
                    if getattr(_fa, "_enrolling", False):
                        if not hasattr(voice_loop, "_face_pause_start"):
                            voice_loop._face_pause_start = time.time()
                            print("[VOICE LOOP] Paused — face enrollment in progress.")
                        elif time.time() - voice_loop._face_pause_start > 120:
                            print("[VOICE LOOP] Face enroll flag stuck > 120 s — forcing reset.")
                            _fa._enrolling = False
                            voice_loop._face_pause_start = None
                        time.sleep(0.5)
                        continue
                    elif hasattr(voice_loop, "_face_pause_start") and voice_loop._face_pause_start:
                        voice_loop._face_pause_start = None
                except Exception:
                    pass

                # ── DND: pause mic while Do Not Disturb is active ──
                try:
                    from modules import dnd_mode as _dnd
                    if _dnd.is_active():
                        if not getattr(voice_loop, "_dnd_logged", False):
                            print("[VOICE LOOP] Paused — DND mode active.")
                            voice_loop._dnd_logged = True
                        time.sleep(0.5)
                        continue
                    elif getattr(voice_loop, "_dnd_logged", False):
                        print("[VOICE LOOP] Resumed — DND mode off.")
                        voice_loop._dnd_logged = False
                except Exception:
                    pass

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

                # Curiosity engine answer intercept — if iZACH just asked a
                # question, treat the next input as the answer, not a command.
                try:
                    from modules.curiosity_engine import is_waiting_for_answer, capture_answer, record_interaction as _ce_record
                    _ce_record()
                    if is_waiting_for_answer():
                        capture_answer(query)
                        _last_izach_question = ""  # clear any parallel question flag
                        continue
                except Exception:
                    pass

                # General conversational question intercept — if iZACH's last
                # spoken text ended with '?', route reply back to AI with context.
                if _last_izach_question and time.time() < _question_expires_at:
                    _ctx = _last_izach_question
                    _last_izach_question = ""
                    _question_expires_at = 0.0
                    try:
                        followup = get_ai_response(f"[Context: iZACH asked: \"{_ctx}\"]\nUser reply: {query}")
                        if followup:
                            speak(followup)
                    except Exception:
                        pass
                    continue

                # WhatsApp draft approval intercept — if iZACH just spoke a
                # draft reply, treat the next input as approve/reject/revise.
                try:
                    from modules.wa_draft_engine import is_waiting_for_approval, handle_approval
                    if is_waiting_for_approval():
                        handle_approval(query)
                        continue
                except Exception:
                    pass

                _t0 = time.time()
                try:
                    chain_engine.process(query)
                    _status = "success"
                except Exception as _e:
                    _status = "fail"
                    raise
                finally:
                    # ── Synonym learning hooks ────────────────────────────
                    try:
                        from modules.synonym_learner import record_failure, record_success
                        from modules.command_chain import _last_route_info
                        _domain   = _last_route_info.get("domain", "chat")
                        _handled  = _last_route_info.get("handled", False)
                        _conf     = _last_route_info.get("confidence", 0.0)
                        if _status == "success" and _handled and _domain != "chat":
                            record_success(query, _domain)
                        elif _domain == "chat" and _conf < 0.5:
                            record_failure(query, "chat")
                            _status = "fail"
                    except Exception:
                        pass
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