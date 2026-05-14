"""
modules/curiosity_engine.py
iZACH curiosity engine — asks the user one question per session during idle
moments to build a personal profile. Answers saved to MongoDB + Obsidian.
Intercepts the next voice input as the answer; clears itself if no answer in 30s.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# ── Questions iZACH will ask (progresses through list, skips answered) ──────
QUESTIONS = [
    {
        "key":      "top_contact",
        "category": "Social",
        "q":        "Hey, I was just wondering — who do you talk to or text the most? Like your go-to person?",
    },
    {
        "key":      "work_start_time",
        "category": "Routine",
        "q":        "What time do you usually sit down to start working or studying?",
    },
    {
        "key":      "music_while_working",
        "category": "Preferences",
        "q":        "Do you listen to music while working? And if yes, what kind?",
    },
    {
        "key":      "fav_browser",
        "category": "Tools",
        "q":        "What browser do you mostly use — Chrome, Edge, or something else?",
    },
    {
        "key":      "coding_language",
        "category": "Skills",
        "q":        "What programming language do you use the most these days?",
    },
    {
        "key":      "sleep_pattern",
        "category": "Routine",
        "q":        "Are you more of a night owl, or do you wake up early?",
    },
    {
        "key":      "laptop_overnight",
        "category": "Habits",
        "q":        "Do you usually shut your laptop down at night, or leave it running?",
    },
    {
        "key":      "most_used_app",
        "category": "Tools",
        "q":        "What app do you pretty much have open all day?",
    },
    {
        "key":      "stress_response",
        "category": "Wellbeing",
        "q":        "When you're stressed or stuck, do you push through or take a break first?",
    },
    {
        "key":      "current_project",
        "category": "Work",
        "q":        "What are you mainly working on these days? Like your main focus?",
    },
    {
        "key":      "fav_food",
        "category": "Personal",
        "q":        "Random one — what's your go-to food when you're hungry and lazy?",
    },
    {
        "key":      "productivity_peak",
        "category": "Routine",
        "q":        "When do you feel most productive — morning, afternoon, or late at night?",
    },
]

_MONGO_KEY      = "curiosity_asked_keys"
_IDLE_THRESHOLD = 180   # seconds idle before asking
_ANSWER_TIMEOUT = 30    # seconds to wait for answer before giving up

_speak_func:  object          = None
_running:     bool            = False
_asked_this_session: bool     = False
_pending:     dict | None     = None   # {"key", "category", "question", "expires_at"}
_pending_lock = threading.Lock()
_last_interaction: float      = time.time()

_ACK_PHRASES = [
    "Got it, I'll keep that in mind.",
    "Noted. Good to know.",
    "Alright, I'll remember that.",
    "Makes sense. Saved.",
    "Cool, I'll hold on to that.",
]


# ── Public API ────────────────────────────────────────────────


def init(speak_fn):
    global _speak_func
    _speak_func = speak_fn


def start():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, daemon=True, name="CuriosityEngine").start()
    logger.info("[Curiosity] Engine started.")


def stop():
    global _running
    _running = False


def record_interaction():
    """Call every time the user speaks — resets idle timer."""
    global _last_interaction
    _last_interaction = time.time()


def is_waiting_for_answer() -> bool:
    """Returns True if a question was just asked and we're waiting for the answer."""
    with _pending_lock:
        if _pending is None:
            return False
        if time.time() > _pending["expires_at"]:
            _clear_pending_unsafe()
            return False
        return True


def capture_answer(text: str) -> bool:
    """
    Call from voice loop when is_waiting_for_answer() is True.
    Saves the answer and speaks an acknowledgment. Returns True if captured.
    """
    import random
    with _pending_lock:
        if _pending is None:
            return False
        q = dict(_pending)
        _clear_pending_unsafe()

    _save_answer(q["key"], q["category"], q["question"], text)
    if _speak_func:
        _speak_func(random.choice(_ACK_PHRASES))
    return True


# ── Internal ──────────────────────────────────────────────────


def _clear_pending_unsafe():
    global _pending
    _pending = None


def _get_asked_keys() -> set:
    try:
        from modules.mongo_brain import get_preference
        return set(get_preference(_MONGO_KEY, []))
    except Exception:
        return set()


def _mark_asked(key: str):
    try:
        from modules.mongo_brain import get_preference, save_preference
        asked = list(get_preference(_MONGO_KEY, []))
        if key not in asked:
            asked.append(key)
            save_preference(_MONGO_KEY, asked)
    except Exception:
        pass


def _save_answer(key: str, category: str, question: str, answer: str):
    try:
        from modules.mongo_brain import save_preference
        save_preference(f"learned.{key}", answer)
    except Exception:
        pass
    try:
        from modules.obsidian_brain import log_learned_fact
        log_learned_fact(key, category, question, answer)
    except Exception as e:
        logger.warning(f"[Curiosity] Obsidian write failed: {e}")
    logger.info(f"[Curiosity] Saved '{key}': {answer[:80]}")


def _next_question() -> dict | None:
    asked = _get_asked_keys()
    for q in QUESTIONS:
        if q["key"] not in asked:
            return q
    return None


def _loop():
    global _asked_this_session, _pending
    time.sleep(90)  # wait for system to settle before first check
    while _running:
        time.sleep(20)
        if _asked_this_session:
            continue
        idle_secs = time.time() - _last_interaction
        if idle_secs < _IDLE_THRESHOLD:
            continue
        q = _next_question()
        if q is None:
            logger.info("[Curiosity] All questions answered. Engine idle.")
            break
        # Ask
        _mark_asked(q["key"])
        _asked_this_session = True
        with _pending_lock:
            _pending = {
                "key":        q["key"],
                "category":   q["category"],
                "question":   q["q"],
                "expires_at": time.time() + _ANSWER_TIMEOUT,
            }
        logger.info(f"[Curiosity] Asking: {q['key']}")
        if _speak_func:
            _speak_func(q["q"])
