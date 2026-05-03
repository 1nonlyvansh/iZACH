"""
modules/response_generator.py
Hybrid response system for iZACH.

Flow:
  Command received
  → speak instant feedback ("Opening...", "Playing...")
  → execute task
  → generate smart response via Groq/Gemini
  → speak final response

Rules:
  - Short, natural, human-like
  - No robotic phrases
  - Hindi supported when user speaks Hindi/Urdu
  - Groq primary, Gemini fallback
"""

import time
import threading
from groq import Groq

# ─────────────────────────────────────────────
# INSTANT FEEDBACK MAP
# Spoken immediately before execution starts
# ─────────────────────────────────────────────
INSTANT_FEEDBACK = {
    "open_file":      "Opening...",
    "play_music":     "Playing...",
    "pause":          "Pausing.",
    "resume":         "Resuming.",
    "next":           "Skipping.",
    "previous":       "Going back.",
    "open_app":       "Opening...",
    "search":         "Searching...",
    "send_file":      "Sending...",
    "send_message":   "Sending...",
    "delete_file":    "Deleting...",
    "create_folder":  "Creating...",
    "find_file":      "Searching...",
    "read_file":      "Reading...",
    "switch_device":  "Switching...",
    "mute":           "Muting.",
    "volume":         "Adjusting volume.",
    "remind":         "Setting reminder...",
    "memory_add":     "Got it.",
    "memory_list":    "Checking memory...",
    "whatsapp_reply": "Replying...",
    "system_stats":   "Checking system...",
    "default":        "On it.",
}

# ─────────────────────────────────────────────
# SYSTEM PROMPT for response generation
# ─────────────────────────────────────────────
RESPONSE_SYSTEM_PROMPT = """You are iZACH, a sharp AI assistant like JARVIS from Iron Man.
Generate ONE short spoken response after a task completes.

Hard rules:
- Maximum 8 words for simple tasks, 15 for complex
- NEVER say: "Sure", "Certainly", "I have", "I will", "I've successfully", "Of course"
- NEVER repeat the task name robotically
- Sound like a human, not a chatbot
- If status is failure: be direct, one line, no apology
- If language hint is "hi": respond in casual Hindi

Good examples:
"Playing Kanye now."
"Done — folder created."
"Couldn't find that file."
"Sent it to your phone."
"Sidhant's chat is open."

Respond with ONLY the spoken words. No quotes. Nothing else."""


# ─────────────────────────────────────────────
# Language detector (simple, no external libs)
# ─────────────────────────────────────────────
def _detect_language(text: str) -> str:
    """Returns 'hi' if Hindi/Urdu detected, else 'en'."""
    if not text:
        return "en"
    hindi_chars = set("अआइईउऊएऐओऔकखगघचछजझटठडढणतथदधनपफबभमयरलवशषसहक्षत्रज्ञ")
    urdu_words  = {"kya", "nahi", "haan", "theek", "acha", "bhai", "yaar",
                   "karo", "kar", "bolo", "sunao", "batao", "dekho", "chalao"}
    words = text.lower().split()
    if any(c in hindi_chars for c in text):
        return "hi"
    if sum(1 for w in words if w in urdu_words) >= 2:
        return "hi"
    return "en"


# ─────────────────────────────────────────────
# ResponseGenerator
# ─────────────────────────────────────────────
class ResponseGenerator:
    """
    Generates natural spoken responses after task execution.
    Uses Groq (primary) with Gemini fallback.
    """

    def __init__(self, groq_key: str, gemini_keys: list, speak_func):
        self._speak = speak_func
        self._groq  = Groq(api_key=groq_key)
        self._gemini_keys  = gemini_keys
        self._gem_idx      = 0
        self._gemini       = None
        self._init_gemini()

    def _init_gemini(self):
        try:
            from google import genai
            self._gemini = genai.Client(api_key=self._gemini_keys[self._gem_idx])
        except Exception:
            self._gemini = None

    def _rotate_gemini(self):
        self._gem_idx = (self._gem_idx + 1) % len(self._gemini_keys)
        self._init_gemini()

    # ─────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────

    def instant(self, task_name: str):
        """Speak immediate feedback before execution. Call this first."""
        msg = INSTANT_FEEDBACK.get(task_name, INSTANT_FEEDBACK["default"])
        self._speak(msg)

    def smart(self, context: dict, original_cmd: str = ""):
        """
        Generate and speak a smart response after execution.

        context example:
        {
            "task":   "open_file",
            "target": "DBMS_notes.pdf",
            "status": "success",
            "detail": ""           # optional extra info
        }
        """
        lang = _detect_language(original_cmd)
        threading.Thread(
            target=self._generate_and_speak,
            args=(context, lang),
            daemon=True
        ).start()

    def smart_sync(self, context: dict, original_cmd: str = "") -> str:
        """Blocking version — returns the response string."""
        lang = _detect_language(original_cmd)
        return self._generate(context, lang)

    # ─────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────

    def _generate_and_speak(self, context: dict, lang: str):
        response = self._generate(context, lang)
        if response:
            self._speak(response)

    def _build_prompt(self, context: dict, lang: str) -> str:
        task   = context.get("task", "unknown")
        target = context.get("target", "")
        status = context.get("status", "success")
        detail = context.get("detail", "")
        lang_note = "Respond in Hindi (romanized is fine)." if lang == "hi" else ""

        return (
            f"Task: {task}\n"
            f"Target: {target}\n"
            f"Status: {status}\n"
            f"Detail: {detail}\n"
            f"{lang_note}"
        ).strip()

    def _generate(self, context: dict, lang: str) -> str:
        prompt = self._build_prompt(context, lang)

        # Try Groq first
        try:
            resp = self._groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt}
                ],
                max_tokens=80,
                temperature=0.7
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(2)
            pass

        # Gemini fallback
        for _ in range(len(self._gemini_keys)):
            try:
                from google.genai import types
                resp = self._gemini.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=RESPONSE_SYSTEM_PROMPT,
                        max_output_tokens=80
                    )
                )
                return resp.text.strip()
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    self._rotate_gemini()
                else:
                    break

        # Hard fallback — static responses
        status = context.get("status", "success")
        task   = context.get("task", "")
        target = context.get("target", "")
        if status == "success":
            return f"Done." if not target else f"{target} — done."
        else:
            return f"That didn't work."


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────
_rg: ResponseGenerator = None

def init_response_generator(groq_key: str, gemini_keys: list, speak_func):
    global _rg
    _rg = ResponseGenerator(groq_key, gemini_keys, speak_func)
    print("[RESPONSE] Smart response generator online.")

def get_response_generator() -> ResponseGenerator:
    return _rg

def instant(task_name: str):
    if _rg: _rg.instant(task_name)

def smart(context: dict, original_cmd: str = ""):
    if _rg: _rg.smart(context, original_cmd)