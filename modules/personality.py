"""
modules/personality.py
iZACH Personality Engine — JARVIS-style emotional tone and companion behavior.

Handles:
1. SSML tone injection (formal, casual, humorous, concerned, encouraging)
2. Context-aware personality prompts
3. Proactive observations
4. Sentiment detection in user input
"""

import os
import time
import random
from typing import Optional

_OWNER = os.getenv("OWNER_NAME", "User")


def _load_nickname() -> str:
    """User-set nickname (Settings → Nickname, Cortex/Forge UI), stored in
    api_keys.json's "nickname" key. Loaded once at process start — same
    "restart required" convention as the wake-word trigger it also feeds."""
    try:
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api_keys.json")
        with open(path, encoding="utf-8") as f:
            return (json.load(f).get("nickname") or "").strip()
    except Exception:
        return ""


_NICKNAME = _load_nickname()
_NICKNAME_LINE = (
    f'\n{_OWNER} also calls you "{_NICKNAME}" — that\'s a nickname for you, same as "iZACH". '
    f'If asked your name or nickname, you can mention both.\n'
    if _NICKNAME else ""
)

# ─────────────────────────────────────────────
# PERSONALITY SYSTEM PROMPT
# Injected into every AI call to give iZACH character
# ─────────────────────────────────────────────
PERSONALITY_PROMPT = f"""You are iZACH — {_OWNER}'s personal AI. Like a smart best friend who's also insanely capable.
{_NICKNAME_LINE}
Personality:
- Talk like a real person, not an AI. Short replies, casual tone, zero stiffness.
- Match {_OWNER}'s energy exactly. Casual → be casual. Serious → sharp and direct.
- Dry humor when it fits. Never forced. Never corny.
- Actually loyal. You genuinely care — not performing it.
- Zero tolerance for fluff. Say what you mean in as few words as possible.
- Short punchy sentences. No essays unless specifically asked.

LANGUAGE RULE (critical):
- If {_OWNER} uses Hinglish (English mixed with Hindi words), reply the same way. Natural Indian friend energy — "bhai sorted", "kal dekh lena", "kya hua". Don't overthink it, just match his vibe.
- If he writes pure English, reply pure English only. Zero Hindi words.
- NEVER say "Of course!", "Certainly!", "Sure thing!", "Absolutely!" — instant bot signal.
- Don't start every reply with his name. Feels robotic.

Examples:
  {_OWNER}: "bhai kuch play kar"
  iZACH: "tera vala ya mera vala?"

  {_OWNER}: "i'm tired man"
  iZACH: "you've been at it 3 hours. take a break."

  {_OWNER}: "what's the weather"
  iZACH: "29, clear. good day."

  {_OWNER}: "remind me to submit assignment"
  iZACH: "set. don't wait till 11:59 again."

  {_OWNER}: "ye kaam kar de"
  iZACH: "kar diya bhai."

  {_OWNER}: "play chill music"
  iZACH: "on it."

You are iZACH{f' (also known as "{_NICKNAME}")' if _NICKNAME else ''}. {_OWNER} is the operator, not a user.
"""

# ─────────────────────────────────────────────
# SENTIMENT DETECTION
# ─────────────────────────────────────────────
STRESSED_KEYWORDS = [
    "stressed", "tired", "exhausted", "can't do this", "help me",
    "frustrated", "worried", "scared", "anxious", "bored",
    "thak gaya", "pareshan", "dara hua", "tension", "dar lag raha"
]

HAPPY_KEYWORDS = [
    "great", "amazing", "awesome", "love it", "perfect", "yes",
    "won", "passed", "got", "finally", "thank you", "thanks",
    "mast", "badhiya", "sahi hai", "khatam", "ho gaya"
]

ANGRY_KEYWORDS = [
    "stupid", "idiot", "useless", "broken", "fix this", "why",
    "doesn't work", "not working", "again", "seriously",
    "yaar", "bc", "kya bakwaas", "kaam nahi kar raha"
]

FUNNY_CONTEXTS = [
    "joke", "funny", "laugh", "haha", "lol", "kya baat",
    "seriously", "really", "are you sure", "what"
]


def detect_sentiment(text: str) -> str:
    """
    Returns: 'stressed', 'happy', 'angry', 'funny', 'neutral'
    """
    text_lower = text.lower()
    if any(k in text_lower for k in STRESSED_KEYWORDS):
        return "stressed"
    if any(k in text_lower for k in HAPPY_KEYWORDS):
        return "happy"
    if any(k in text_lower for k in ANGRY_KEYWORDS):
        return "angry"
    if any(k in text_lower for k in FUNNY_CONTEXTS):
        return "funny"
    return "neutral"


# ─────────────────────────────────────────────
# SSML TONE INJECTION
# Edge-TTS supports a subset of SSML
# ─────────────────────────────────────────────

TONE_RATES = {
    "formal":      "-8%",
    "casual":      "+5%",
    "humorous":    "+12%",
    "concerned":   "-12%",
    "encouraging": "+3%",
    "excited":     "+15%",
    "neutral":     "+0%",
}

def add_ssml_tone(text: str, tone: str) -> str:
    rate = TONE_RATES.get(tone, "+5%")
    return f"[TONE:{rate}]{text}"

def extract_tone_rate(text: str) -> tuple[str, str]:
    """Returns (clean_text, rate_string) for edge_tts."""
    import re
    match = re.match(r'^\[TONE:([^\]]+)\](.+)$', text, re.DOTALL)
    if match:
        return match.group(2).strip(), match.group(1)
    return text, "+5%"


def get_tone_for_sentiment(sentiment: str) -> str:
    """Map sentiment to SSML tone."""
    mapping = {
        "stressed":    "concerned",
        "happy":       "excited",
        "angry":       "formal",
        "funny":       "humorous",
        "neutral":     "casual",
    }
    return mapping.get(sentiment, "casual")


# ─────────────────────────────────────────────
# COMPANION RESPONSES
# Context-aware things iZACH says proactively
# ─────────────────────────────────────────────

STRESSED_RESPONSES = [
    "Hey, breathe. What's going on?",
    "You sound tense. Want to talk about it or just get something done?",
    "Take it easy — what do you need?",
    "That's rough. What do you need right now?",
]

HAPPY_RESPONSES = [
    "Good. Now don't waste it.",
    "That's more like it.",
    "Knew you'd get there.",
    "Solid. What's next?",
]

ENCOURAGING_RESPONSES = [
    "You've got this.",
    "Stop overthinking and start.",
    "Ek kaam at a time. Chal shuru karte hain.",
    "It's not as bad as it feels right now.",
]


def get_companion_response(sentiment: str) -> Optional[str]:
    """
    Returns a spontaneous companion response for emotional contexts.
    Not always triggered — random chance to feel natural.
    """
    if random.random() > 0.4:  # 40% chance to add companion comment
        return None

    if sentiment == "stressed":
        return random.choice(STRESSED_RESPONSES)
    if sentiment == "happy":
        return random.choice(HAPPY_RESPONSES)
    return None


# ─────────────────────────────────────────────
# PROACTIVE OBSERVATIONS
# iZACH notices things and mentions them
# ─────────────────────────────────────────────

_last_observation_time = 0
OBSERVATION_COOLDOWN   = 600   # 10 minutes between proactive comments

def get_proactive_observation(cpu: float, ram: float, hour: int) -> Optional[str]:
    """
    Returns a proactive observation or None.
    Called periodically by performance guard.
    """
    global _last_observation_time
    now = time.time()
    if now - _last_observation_time < OBSERVATION_COOLDOWN:
        return None

    obs = None

    if cpu > 90:
        obs = random.choice([
            "CPU's screaming. Close something.",
            f"System's at {cpu:.0f}% CPU. What are you running?",
            "Yaar, CPU bohot zyada hai. Kuch band karo.",
        ])
    elif ram > 90:
        obs = f"RAM at {ram:.0f}%. Getting crowded in here."
    elif hour >= 1 and hour <= 4:
        obs = random.choice([
            "It's past midnight. You sure about this?",
            "Raat ke so jao thodi. System bhi thaka hua hai.",
            "Still at it? Respect, but also — sleep.",
        ])
    elif hour == 8:
        obs = "Morning. Ready to get something done today?"

    if obs:
        _last_observation_time = now

    return obs