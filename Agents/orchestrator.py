"""
OrchestratorAgent — classifies every user query into a domain with a single
fast LLM call so downstream handlers can skip irrelevant keyword checks.

Uses llama-3.1-8b-instant (fastest Groq model, not the 70B used for chat)
because classification needs speed, not depth. Temperature=0 for determinism.

Phase 1: classify + log.
Phase 2 (future): each domain routes to a dedicated AgentHandler with its
own system prompt and tool set instead of the giant if/elif chain.
"""

import json
import re
import httpx
from groq import Groq

# ── Domain registry ───────────────────────────────────────────────
DOMAINS = frozenset({
    "whatsapp",   # send/read messages, contacts, group chat, reply drafts
    "spotify",    # play/pause/skip music, playlists, volume, Spotify
    "calendar",   # reminders, events, tasks, alarms, schedule
    "system",     # open apps, volume, brightness, shutdown, screenshot, reboot
    "research",   # web search, news, weather, stock, live data, current events
    "memory",     # remember/recall/forget facts, personal context
    "vision",     # camera, take photo, analyze screen, face recognition
    "file",       # open/move/delete files, documents, clipboard, downloads
    "chat",       # general conversation, jokes, help — anything else
})

_CONFIDENCE_THRESHOLD = 0.50   # below this → treat as "chat"
_MODEL                = "llama-3.1-8b-instant"
_MAX_TOKENS           = 64     # JSON output is tiny; cap tokens for speed

_SYSTEM_PROMPT = """You are iZACH's intent classifier. Given a user command, output ONLY valid JSON — no other text:
{"domain": "<domain>", "confidence": <0.0-1.0>, "summary": "<5 words max>"}

Domains (pick the SINGLE best match):
- whatsapp : send/read WhatsApp messages or texts, "message Rahul", "text someone", "WhatsApp Priya", "message to X", unread messages, group chat, contacts, reply drafts
- spotify  : play/pause/skip music, playlists, volume control, Spotify device switch
- calendar : reminders, events, tasks, alarms, schedule, "remind me", "set alarm"
- system   : open/launch apps, volume, brightness, shutdown, reboot, screenshot, window
- research : web search, news, weather, gold/petrol/stock price, live data, "what is X"
- memory   : remember this, what did I say, recall, forget, personal facts, context
- vision   : camera, take photo, analyze screenshot, face recognition, "what do you see"
- file     : open/save/move/delete files, documents, clipboard, downloads, folders
- chat     : general questions, conversation, jokes, anything that doesn't fit above

Rules:
- Output ONLY the JSON object, zero extra text
- Prefer a specific domain over chat when plausible
- Use confidence < 0.5 only when truly unclear
- CRITICAL: "open <app>" or "launch <app>" is ALWAYS system, even if the app name matches another domain (e.g. "open spotify" = system, "open camera" = system, "open whatsapp" = system)
- CRITICAL: "switch to <device/phone/TV/speaker>" when music context exists = spotify (transfer playback), NOT system. Examples: "switch to OnePlus", "switch to TV", "play on phone", "move to laptop" = spotify
- CRITICAL: "turn on/off <brand> AC/TV" or "turn off Samsung AC" = system (smart home), NOT open_app
- vision only when user wants to USE the camera to SEE something (describe, take photo, analyze) — NOT when launching the camera app"""


def _fallback(reason: str = "") -> dict:
    if reason:
        print(f"[ORCHESTRATOR] fallback → chat ({reason})")
    return {"domain": "chat", "confidence": 0.0, "summary": ""}


class OrchestratorAgent:
    """
    Single-call intent classifier.  Thread-safe; reuses one persistent HTTP
    connection to Groq to avoid per-request TLS handshake overhead.
    """

    def __init__(self, groq_key: str):
        self._client = Groq(
            api_key=groq_key,
            http_client=httpx.Client(
                limits=httpx.Limits(
                    max_connections=3,
                    max_keepalive_connections=1,
                )
            ),
        )

    def reload_key(self, groq_key: str):
        """Hot-swap Groq key at runtime. Rebuilds underlying HTTP client."""
        try:
            self._client = Groq(
                api_key=groq_key,
                http_client=httpx.Client(
                    limits=httpx.Limits(max_connections=3, max_keepalive_connections=1),
                ),
            )
            print(f"[OrchestratorAgent] Groq client rebuilt with new key ({groq_key[:8]}...).")
        except Exception as e:
            print(f"[OrchestratorAgent] Groq reload failed: {e}")

    def classify(self, query: str) -> dict:
        """
        Classify query into a domain.
        Returns {"domain": str, "confidence": float, "summary": str}.
        Never raises — falls back to domain="chat" on any error.
        """
        if not query or not query.strip():
            return _fallback("empty query")
        try:
            completion = self._client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": query},
                ],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            )
            raw = completion.choices[0].message.content.strip()

            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                return _fallback(f"no JSON in: {raw!r}")

            data    = json.loads(m.group())
            domain  = str(data.get("domain", "chat")).lower().strip()
            conf    = float(data.get("confidence", 0.0))
            summary = str(data.get("summary", ""))

            if domain not in DOMAINS:
                return _fallback(f"unknown domain {domain!r}")
            if conf < _CONFIDENCE_THRESHOLD:
                domain = "chat"

            result = {"domain": domain, "confidence": conf, "summary": summary}
            print(f"[ORCHESTRATOR] {domain} ({conf:.2f}) — {summary!r}")
            return result

        except Exception as e:
            return _fallback(str(e))
