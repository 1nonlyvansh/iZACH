"""
modules/context_memory.py
Session memory for iZACH — tracks conversation history,
entities, and WhatsApp message threads.

Separate from personal memory (memory.py).
This is short-term session memory only — clears on restart.
"""

import time
from collections import deque
from typing import Optional

# ─────────────────────────────────────────────
# SESSION MEMORY
# ─────────────────────────────────────────────

class ContextMemory:
    """
    Tracks the last N conversation turns and entity context.
    Used to resolve follow-up queries like "and his daughter?"
    """

    def __init__(self, max_turns: int = 10):
        self._history   = deque(maxlen=max_turns)
        self._entities  = {}          # person, topic, task
        self._whatsapp  = {}          # per-contact message thread
        self._last_task = None

    # ─────────────────────────────────────────
    # Conversation History
    # ─────────────────────────────────────────

    def add_turn(self, user_input: str, assistant_response: str):
        self._history.append({
            "role_user":      user_input,
            "role_assistant": assistant_response,
            "time":           time.strftime("%H:%M")
        })

    def get_history(self, n: int = 6) -> list:
        return list(self._history)[-n:]

    def get_history_as_prompt(self, n: int = 6) -> str:
        """Format last N turns as a string for AI context injection."""
        turns = self.get_history(n)
        if not turns:
            return ""
        lines = []
        for t in turns:
            lines.append(f"User: {t['role_user']}")
            lines.append(f"iZACH: {t['role_assistant']}")
        return "\n".join(lines)

    # ─────────────────────────────────────────
    # Entity Tracking
    # ─────────────────────────────────────────

    def set_entity(self, key: str, value: str):
        """Store a named entity (person, topic, task)."""
        self._entities[key] = value

    def get_entity(self, key: str) -> Optional[str]:
        return self._entities.get(key)

    def update_entities_from_input(self, text: str):
        """
        Simple entity extraction from user input.
        Stores 'last_topic' for follow-up resolution.
        """
        text_lower = text.lower()
        # If follow-up detected, don't overwrite entities
        followup_signals = ["and his", "and her", "and their", "what about",
                            "tell me more", "also", "what else", "and the"]
        if any(s in text_lower for s in followup_signals):
            return  # preserve existing entities
        self._entities["last_topic"] = text

    def resolve_followup(self, text: str) -> str:
        """
        Expand follow-up queries using entity memory.
        Example: "and his daughter?" → "Kanye West's daughter?"
        """
        followup_triggers = ["and his", "and her", "and their", "what about his",
                             "what about her", "also his", "also her"]
        text_lower = text.lower()
        if any(t in text_lower for t in followup_triggers):
            last_topic = self._entities.get("last_topic", "")
            last_person = self._entities.get("last_person", "")
            if last_person:
                return f"{last_person} — {text}"
            if last_topic:
                return f"{last_topic} — {text}"
        return text

    # ─────────────────────────────────────────
    # WhatsApp Thread Memory
    # ─────────────────────────────────────────

    def record_whatsapp_sent(self, contact: str, message: str, number: str = ""):
        if contact not in self._whatsapp:
            self._whatsapp[contact] = {"sent": [], "received": []}
        self._whatsapp[contact]["sent"].append({
            "message": message,
            "number":  number,
            "time":    time.strftime("%H:%M")
        })
        # Keep last 5 per contact
        self._whatsapp[contact]["sent"] = self._whatsapp[contact]["sent"][-5:]

    def record_whatsapp_received(self, contact: str, message: str, number: str = ""):
        if contact not in self._whatsapp:
            self._whatsapp[contact] = {"sent": [], "received": []}
        self._whatsapp[contact]["received"].append({
            "message": message,
            "number":  number,
            "time":    time.strftime("%H:%M")
        })
        self._whatsapp[contact]["received"] = self._whatsapp[contact]["received"][-5:]

    def get_whatsapp_context(self, contact: str) -> dict:
        return self._whatsapp.get(contact, {"sent": [], "received": []})

    def get_last_received(self, contact: str = None) -> Optional[dict]:
        """Get the last received message from any contact or a specific one."""
        if contact:
            thread = self._whatsapp.get(contact, {})
            received = thread.get("received", [])
            return received[-1] if received else None
        # Any contact — find most recent
        latest = None
        for thread in self._whatsapp.values():
            for msg in thread.get("received", []):
                if not latest or msg["time"] > latest["time"]:
                    latest = msg
        return latest

    def get_last_sent(self, contact: str = None) -> Optional[dict]:
        if contact:
            thread = self._whatsapp.get(contact, {})
            sent = thread.get("sent", [])
            return sent[-1] if sent else None
        return None

    # ─────────────────────────────────────────
    # Task Tracking
    # ─────────────────────────────────────────

    def set_last_task(self, task_name: str, details: dict = None):
        self._last_task = {"task": task_name, "details": details or {}}

    def get_last_task(self) -> Optional[dict]:
        return self._last_task

    def clear(self):
        self._history.clear()
        self._entities.clear()
        self._whatsapp.clear()
        self._last_task = None


# Singleton
_cm = ContextMemory()

def get_context_memory() -> ContextMemory:
    return _cm