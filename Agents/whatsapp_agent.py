"""
WhatsAppAgent — full LLM-driven handler for all WhatsApp commands.

Replaces the scattered keyword-matching blocks in command_chain.py for the
"whatsapp" domain.  Called by CommandChain when OrchestratorAgent classifies
a query as domain="whatsapp".  Returns True when handled (command_chain skips
its own WA keyword blocks), False to fall through.

Intents handled:
  send_message       send a WhatsApp message to a contact
  read_messages      read recent messages (all or from one contact)
  summarize_history  summarise all WhatsApp activity
  summarize_group    summarise a specific group chat
  draft_reply        LLM-generated reply draft for approval
  reply_to           compose and send reply immediately
  last_message       read or elaborate on the last received message
  bridge_connect     start the WhatsApp bridge
  bridge_status      check if bridge is online
  bridge_disconnect  logout / stop bridge
  unread_count       how many unread messages
  relationship_info  who is a contact / what iZACH knows about them
  relationship_save  "X is my Y / works at Y / studies at Y"
  call_control       pick up / ignore / reject WhatsApp call
"""

from __future__ import annotations

import json
import os
import re
import requests
import threading
from collections import defaultdict

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's WhatsApp command parser. Parse the user command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "contact": "<name or null>",
  "message": "<text to send or null>",
  "group_name": "<group name or null>",
  "hours": <integer or null>,
  "action": "<bridge action: connect|status|disconnect or null>",
  "instruction": "<extra instruction for draft/reply or null>"
}}

Intents (pick exactly one):
- send_message      : user wants to send a WA message to a contact
- read_messages     : user wants to read received messages (all or from someone)
- summarize_history : user wants a summary of recent WA activity
- summarize_group   : user wants a summary of a group chat
- draft_reply       : user wants iZACH to suggest a reply draft (needs approval)
- reply_to          : user wants to compose and send a reply right now
- last_message      : user wants to know what the last received message said
- elaborate_message : user wants an elaboration/explanation of the last message
- bridge_connect    : start/connect the WhatsApp bridge
- bridge_status     : check if WhatsApp is connected
- bridge_disconnect : logout / disconnect WhatsApp
- unread_count      : how many unread messages
- relationship_info : who is X / what do you know about X
- relationship_save : remember that X is my Y / X works at Y
- call_control      : pick up / ignore / reject a WhatsApp call
- unknown           : cannot determine WhatsApp intent

Rules:
- Extract contact name without titles/fillers
- message: ONLY the text to send, strip "saying", "that", "tell him that", etc.
- hours: default 6 for group summaries, 12 for history, 24 for contact reads
- If unsure between draft_reply and reply_to: draft_reply needs approval, reply_to sends immediately
- Output ONLY the JSON object
"""

_BRIDGE_URL = "http://localhost:3000"


class WhatsAppAgent:
    """
    Handles all WhatsApp domain commands via LLM intent parsing + module calls.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak      = speak_fn
        self._raw_ai    = raw_ai_fn
        # Clarification state: waiting for message text after "send to X"
        self._pending_send: dict | None = None

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute WhatsApp command.
        Returns True if handled (stops command_chain fallback).
        """
        # If pending clarification (user said "send to X" without message text)
        if self._pending_send:
            return self._complete_pending_send(cmd)

        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[WA_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "send_message":      self._send_message,
            "read_messages":     self._read_messages,
            "summarize_history": self._summarize_history,
            "summarize_group":   self._summarize_group,
            "draft_reply":       self._draft_reply,
            "reply_to":          self._reply_to,
            "last_message":      self._last_message,
            "elaborate_message": self._elaborate_message,
            "bridge_connect":    self._bridge_connect,
            "bridge_status":     self._bridge_status,
            "bridge_disconnect": self._bridge_disconnect,
            "unread_count":      self._unread_count,
            "relationship_info": self._relationship_info,
            "relationship_save": self._relationship_save,
            "call_control":      self._call_control,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False  # unknown → fall through to command_chain

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            m        = re.search(r'\{.*\}', response, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            if "intent" not in data:
                return {"intent": "unknown"}
            return data
        except Exception as e:
            print(f"[WA_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Helpers ───────────────────────────────────────────────────

    def _ensure_bridge(self) -> None:
        from modules.whatsapp_handler import ensure_bridge_running
        ensure_bridge_running()

    def _resolve(self, name: str) -> str | None:
        from modules.whatsapp_handler import resolve_contact_by_name
        return resolve_contact_by_name(name)

    def _fetch_history(self, hours: int = 12) -> list:
        try:
            r = requests.get(f"{_BRIDGE_URL}/messages/history",
                             params={"hours": hours}, timeout=5)
            return r.json().get("messages", [])
        except Exception:
            return []

    def _send(self, number: str, text: str, contact: str) -> tuple[bool, str]:
        from modules.whatsapp_handler import _send_message
        return _send_message(number, text, contact)

    # ── Handlers ─────────────────────────────────────────────────

    def _send_message(self, d: dict, cmd: str) -> bool:
        contact = (d.get("contact") or "").strip()
        message = (d.get("message") or "").strip()
        self._ensure_bridge()

        if not contact:
            self.speak("Who should I send the message to?")
            return True

        if not message:
            # Enter clarification state
            number = self._resolve(contact)
            if not number:
                self.speak(f"I don't have {contact}'s number. Add them to contacts.json.")
                return True
            self._pending_send = {"contact": contact, "number": number}
            self.speak(f"What should I say to {contact}?")
            return True

        number = self._resolve(contact)
        if not number:
            self.speak(f"I don't have {contact}'s number. Add them to contacts.json.")
            return True

        ok, status = self._send(number, message, contact)
        self.speak(f"Message sent to {contact}." if ok else f"Couldn't send: {status}")
        return True

    def _complete_pending_send(self, message_text: str) -> bool:
        """User just spoke the message text for a pending send."""
        pending = self._pending_send
        self._pending_send = None
        if not message_text.strip():
            self.speak("Message cancelled.")
            return True
        ok, status = self._send(pending["number"], message_text, pending["contact"])
        self.speak(
            f"Sent to {pending['contact']}." if ok
            else f"Couldn't send: {status}"
        )
        return True

    def _read_messages(self, d: dict, cmd: str) -> bool:
        self._ensure_bridge()
        contact_filter = (d.get("contact") or "").strip().lower()
        hours          = int(d.get("hours") or 24)
        msgs           = self._fetch_history(hours)
        inbox          = [m for m in msgs if not m.get("fromMe", True) and m.get("text")]

        if contact_filter:
            inbox = [m for m in inbox if contact_filter in m.get("sender", "").lower()]

        if not inbox:
            who = f" from {contact_filter.title()}" if contact_filter else ""
            self.speak(f"No messages{who} in the last {hours} hours.")
            return True

        for m in inbox[-3:]:
            self.speak(f"{m.get('sender', 'Someone')} said: {m['text']}")
        return True

    def _summarize_history(self, d: dict, cmd: str) -> bool:
        self._ensure_bridge()
        hours = int(d.get("hours") or 12)
        msgs  = self._fetch_history(hours)
        inbox = [m for m in msgs if not m.get("fromMe", True) and m.get("text")]

        if not inbox:
            self.speak(f"No new WhatsApp messages in the last {hours} hours.")
            return True

        by_sender = defaultdict(list)
        for m in inbox:
            by_sender[m.get("sender", "Unknown")].append(m["text"])

        parts = []
        for sender, texts in by_sender.items():
            if len(texts) == 1:
                parts.append(f"{sender}: {texts[0]}")
            else:
                parts.append(f"{sender} sent {len(texts)} messages, latest: {texts[-1]}")

        summary = ". ".join(parts)
        if len(by_sender) > 2:
            owner  = os.getenv("OWNER_NAME", "the user")
            prompt = (
                f"Summarize these WhatsApp messages in 2-3 sentences like JARVIS briefing {owner}:\n"
                + summary
            )
            self.speak(self._raw_ai(prompt))
        else:
            self.speak(
                f"Messages from {len(by_sender)} contact{'s' if len(by_sender) > 1 else ''}. "
                + summary
            )
        return True

    def _summarize_group(self, d: dict, cmd: str) -> bool:
        group_name = (d.get("group_name") or "").strip()
        hours      = int(d.get("hours") or 6)

        if not group_name:
            self.speak("Which group should I summarize?")
            return True

        self._ensure_bridge()
        from modules.wa_group_summarizer import summarize_group_async, init as _init_sum
        _init_sum(self.speak, self._raw_ai)
        self.speak(f"Fetching {group_name} group. One moment.")
        threading.Thread(
            target=summarize_group_async,
            args=(group_name, hours),
            daemon=True
        ).start()
        return True

    def _draft_reply(self, d: dict, cmd: str) -> bool:
        self._ensure_bridge()
        from modules.whatsapp_handler import get_last_message, _send_message, _ai_func
        from modules.wa_draft_engine import draft_reply, init as _init_draft

        last = get_last_message()
        if not last or not last.get("number"):
            self.speak("No recent WhatsApp message to draft a reply for.")
            return True

        instruction = (d.get("instruction") or "").strip()
        _init_draft(self.speak, _ai_func, _send_message)
        draft_reply(last["number"], last.get("sender", "them"), instruction)
        return True

    def _reply_to(self, d: dict, cmd: str) -> bool:
        self._ensure_bridge()
        from modules.whatsapp_handler import get_last_message, _send_message, _ai_func

        last = get_last_message()
        if not last or not last.get("number"):
            self.speak("No recent WhatsApp message to reply to.")
            return True

        sender   = last.get("sender", "them")
        original = last.get("text", "")
        number   = last.get("number")
        instruction = (d.get("instruction") or d.get("message") or "").strip()

        if not instruction:
            self.speak("What should I say in the reply?")
            return True

        if _ai_func:
            owner  = os.getenv("OWNER_NAME", "User")
            prompt = f"""Write a WhatsApp reply message.
Original message from {sender}: "{original}"
{owner}'s instruction: "{instruction}"

Rules:
- Write ONLY the message text, nothing else
- If original is in Hindi/Hinglish → reply in Hinglish (Roman Hindi, casual)
- If original is in English → reply in English
- Match the tone of the original (casual if casual, formal if formal)
- Keep it short, natural, conversational
- Write from {owner}'s perspective"""
            reply_text = _ai_func(prompt)
        else:
            reply_text = instruction

        ok, status = _send_message(number, reply_text, sender)
        self.speak(f"Replied to {sender}." if ok else f"Couldn't send: {status}")
        return True

    def _last_message(self, d: dict, cmd: str) -> bool:
        from modules.whatsapp_handler import get_last_message, ensure_bridge_running
        ensure_bridge_running()
        last = get_last_message()
        if not last or not last.get("text"):
            self.speak("No recent WhatsApp message.")
            return True
        sender = last.get("sender", "They")
        text   = last.get("text", "")

        # If user asked about a specific contact, filter
        contact = (d.get("contact") or "").strip().lower()
        if contact and contact not in sender.lower():
            self.speak(f"The last message is from {sender}, not {contact.title()}. {sender} said: {text}")
            return True

        self.speak(f"{sender} said: {text}")
        return True

    def _elaborate_message(self, d: dict, cmd: str) -> bool:
        from modules.whatsapp_handler import get_last_message, ensure_bridge_running
        ensure_bridge_running()
        last = get_last_message()
        if not last or not last.get("text"):
            self.speak("No recent WhatsApp message to elaborate.")
            return True
        sender = last.get("sender", "They")
        text   = last.get("text", "")
        owner  = os.getenv("OWNER_NAME", "User")
        prompt = (
            f'A WhatsApp message was received from {sender}: "{text}"\n'
            f"Explain in one short sentence what they want or are saying, "
            f"as if briefing {owner}. Start with the sender's name. "
            f"Do not quote the message directly."
        )
        self.speak(self._raw_ai(prompt))
        return True

    def _bridge_connect(self, d: dict, cmd: str) -> bool:
        from modules.whatsapp_handler import ensure_bridge_running
        ensure_bridge_running()
        self.speak("Starting WhatsApp bridge. Give it a moment to connect.")
        return True

    def _bridge_status(self, d: dict, cmd: str) -> bool:
        try:
            r      = requests.get(f"{_BRIDGE_URL}/health", timeout=3)
            status = r.json().get("status")
            if status == "connected":
                self.speak("WhatsApp is connected and running.")
            else:
                self.speak("WhatsApp is connecting. Please wait.")
        except Exception:
            self.speak("WhatsApp bridge is offline.")
        return True

    def _bridge_disconnect(self, d: dict, cmd: str) -> bool:
        try:
            requests.post(f"{_BRIDGE_URL}/logout", timeout=5)
            self.speak("WhatsApp session logged out.")
        except Exception:
            self.speak("Could not reach WhatsApp bridge.")
        return True

    def _unread_count(self, d: dict, cmd: str) -> bool:
        from modules.whatsapp_context import get_unread_count
        count = get_unread_count()
        if count:
            self.speak(f"You have {count} unread WhatsApp message{'s' if count != 1 else ''}.")
        else:
            self.speak("No unread WhatsApp messages.")
        return True

    def _relationship_info(self, d: dict, cmd: str) -> bool:
        name = (d.get("contact") or "").strip().title()
        if not name:
            # Try extracting from cmd
            m = re.search(
                r"(?:who is|what do you know about|tell me about)\s+([A-Za-z]+(?:\s[A-Za-z]+)?)",
                cmd, re.IGNORECASE
            )
            name = m.group(1).strip().title() if m else ""
        if not name:
            self.speak("Who do you want me to look up?")
            return True
        from modules.relationship_memory import get_summary
        self.speak(get_summary(name))
        return True

    def _relationship_save(self, d: dict, cmd: str) -> bool:
        from modules.relationship_memory import extract_and_save_from_command
        cap_cmd = cmd[0].upper() + cmd[1:] if cmd else cmd
        saved, msg = extract_and_save_from_command(cap_cmd)
        if saved:
            self.speak(msg)
            return True
        # Pattern didn't match — fall through
        return False

    def _call_control(self, d: dict, cmd: str) -> bool:
        from modules.whatsapp_handler import handle_whatsapp_command
        handle_whatsapp_command(cmd, self.speak)
        return True
