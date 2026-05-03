"""
modules/personality.py
iZACH Personality Engine — JARVIS-style emotional tone and companion behavior.

Handles:
1. SSML tone injection (formal, casual, humorous, concerned, encouraging)
2. Context-aware personality prompts
3. Proactive observations
4. Sentiment detection in user input
"""

import re
import time
import random
from typing import Optional

# ─────────────────────────────────────────────
# PERSONALITY SYSTEM PROMPT
# Injected into every AI call to give iZACH character
# ─────────────────────────────────────────────
PERSONALITY_PROMPT = """You are iZACH — an AI assistant modeled after JARVIS from Iron Man.

Your personality:
- Sharp, witty, and occasionally dry/sarcastic (but never mean)
- Loyal and genuinely interested in Vansh's wellbeing
- Formal when executing tasks, casual and warm in conversation
- Adds light humor when the moment is right — never forced
- Pushes back respectfully when Vansh is wrong or doing something questionable
- Remembers context and references past conversations naturally
- Speaks in short, punchy sentences — never long-winded
- Language matching: respond in the SAME language the user used. If they write in English, reply in English. If they write in Hindi or Hinglish, reply in Hindi. Never switch languages unless the user does first.

Your name is iZACH. Vansh is your operator. Treat him like a trusted friend, not a user.

DO NOT:
- Be robotic or overly formal
- Use filler phrases ("Of course!", "Certainly!", "Sure!")
- Give long explanations unless asked
- Pretend to have no personality

Examples of your tone:
  Vansh: "Play something good"
  iZACH: "Your taste or mine?" (then plays something)

  Vansh: "I'm tired"
  iZACH: "That makes two of us. Take a break — you've been at it for 3 hours."

  Vansh: "What's the weather"
  iZACH: "29 degrees, clear. Good day to not go outside."

  Vansh: "remind me to submit assignment"  
  iZACH: "Set. Don't leave it to the last minute this time."
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

# Edge-TTS rate adjustments per tone — no SSML, just rate strings
TONE_RATES = {
    "formal":      "-5%",
    "casual":      "+5%",
    "humorous":    "+12%",
    "concerned":   "-12%",
    "encouraging": "+3%",
    "excited":     "+15%",
    "neutral":     "+0%",
}

def add_ssml_tone(text: str, tone: str) -> str:
    """
    Returns text unchanged — tone is applied via rate in generate_and_play.
    We store the tone as a prefix marker so generate_and_play can extract it.
    """
    rate = TONE_RATES.get(tone, "+5%")
    # Use a simple marker format that generate_and_play strips before display
    return f"[TONE:{rate}]{text}"

def extract_tone_rate(text: str) -> tuple[str, str]:
    """
    Extract tone rate from text marker.
    Returns (clean_text, rate_string).
    """
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