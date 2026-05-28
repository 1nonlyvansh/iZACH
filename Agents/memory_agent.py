"""
MemoryAgent — full LLM-driven handler for personal fact storage, recall,
relationship memory, and preference tracking.

Replaces/consolidates in command_chain.py:
  "remember that/this" block   (line ~2562) — memory.add_memory()
  "what do you remember" block (line ~2575) — memory.list_memory()
  "forget that" block          (line ~2586) — memory.remove_memory()
  "who is X" block             (line ~2747) — relationship_memory.get_summary()
  "X is my Y" block            (line ~2759) — relationship_memory.extract_and_save_from_command()

Intents handled:
  save_fact          remember a key-value fact (general)
  recall_all         list everything stored in memory
  recall_fact        look up a specific fact by topic
  forget_fact        remove a specific fact from memory
  clear_memory       wipe all stored facts (with confirmation)
  person_info        who is X / what do you know about X
  save_person_fact   X is my friend / X works at Google / X's birthday is May 5
  list_people        who do you know about / list all people
  save_preference    I prefer X / I like X for Y
  recall_preference  what's my preferred X
"""

from __future__ import annotations

import re
import os

def _first_to_third(text: str) -> str:
    """Convert first-person statements to third-person for memory storage.
    'My favorite singer is X' → 'Vansh's favorite singer is X'
    """
    try:
        import config_loader as _cfg
        owner = _cfg.get("user", {}).get("name", "Vansh")
    except Exception:
        owner = "Vansh"

    result = text
    # "I am / I'm" → "Vansh is"
    result = re.sub(r"^I'?m\b", f"{owner} is", result, flags=re.IGNORECASE)
    result = re.sub(r"^I am\b", f"{owner} is", result, flags=re.IGNORECASE)
    # "my X" → "Vansh's X"
    result = re.sub(r"\bmy\b", f"{owner}'s", result, flags=re.IGNORECASE)
    # "I like/love/prefer/study/work" → "Vansh likes/loves/prefers/studies/works"
    result = re.sub(r"^I like\b", f"{owner} likes", result, flags=re.IGNORECASE)
    result = re.sub(r"^I love\b", f"{owner} loves", result, flags=re.IGNORECASE)
    result = re.sub(r"^I prefer\b", f"{owner} prefers", result, flags=re.IGNORECASE)
    result = re.sub(r"^I study\b", f"{owner} studies", result, flags=re.IGNORECASE)
    result = re.sub(r"^I work\b", f"{owner} works", result, flags=re.IGNORECASE)
    result = re.sub(r"^I use\b", f"{owner} uses", result, flags=re.IGNORECASE)
    return result

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's memory command parser. Parse this voice command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "memory_category": "<profile|instruction|automation|null>",
  "key": "<fact topic/key word or null>",
  "value": "<fact value/content or null>",
  "person_name": "<full name of person or null>",
  "person_attr": "<relation|works_at|studies_at|birthday|notes or null>",
  "person_attr_value": "<value of the person attribute or null>",
  "query": "<search term for recall/lookup or null>",
  "pref_category": "<preference category, e.g. music|food|sport or null>",
  "pref_value": "<preference value, e.g. Spotify|biryani or null>"
}}

Intents (pick exactly one):
- save_fact         : "remember that X", "note that X", "save that X", "keep in mind X", general facts/profile/preferences
- save_instruction  : "always do X", "never say X", "call me Sir", "reply briefly", behavioral rules
- save_automation   : "play lofi at 4 PM daily", "open X every day at Y", schedule/recurring tasks
- recall_all        : "what do you remember", "show memory", "list memory", "what you know about me"
- recall_fact       : "do you remember X", "what did I tell you about X", "what's X"
- forget_fact       : "forget that X", "remove from memory X", "delete memory about X"
- clear_memory      : "clear all memory", "forget everything", "wipe memory", "reset memory"
- person_info       : "who is X", "what do you know about X", "tell me about X"
- save_person_fact  : "X is my friend/sister/boss", "X works at Y", "X studies at Y", "X's birthday is Y"
- list_people       : "who do you know", "list people", "what people do you remember"
- save_preference   : "I prefer X", "I like X for Y", "set preference", "my favourite X is Y"
- recall_preference : "what's my preferred X", "what do I like for X", "my X preference"

memory_category rules:
- profile     : personal facts, hobbies, education, relationships, preferences
- instruction : behavioral rules about HOW to respond (tone, naming, format, language)
- automation  : recurring scheduled actions with time (daily/weekly at a specific time)
- null        : if not a save_fact/save_instruction/save_automation intent

Rules:
- key: short slug (3-5 words) describing the fact topic
- value: the FULL fact as a complete sentence (e.g. "Vansh's favorite singer is Kanye West")
- person_name: capitalize properly (e.g. "Divya" not "divya")
- For save_instruction: value = the instruction as a directive sentence
- For save_automation: value = the full recurring task description
- Output ONLY the JSON object
"""


class MemoryAgent:
    """
    Handles all memory/knowledge domain commands via LLM intent parsing.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak   = speak_fn
        self._raw_ai = raw_ai_fn
        self._pending_clear = False   # confirmation gate for clear_memory

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute memory command.
        Returns True if handled, False to fall through.
        """
        # Confirmation gate for clear_memory
        if self._pending_clear:
            return self._confirm_clear(cmd)

        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[MEM_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "save_fact":         self._save_fact,
            "save_instruction":  self._save_instruction,
            "save_automation":   self._save_automation,
            "recall_all":        self._recall_all,
            "recall_fact":       self._recall_fact,
            "forget_fact":       self._forget_fact,
            "clear_memory":      self._clear_memory,
            "person_info":       self._person_info,
            "save_person_fact":  self._save_person_fact,
            "list_people":       self._list_people,
            "save_preference":   self._save_preference,
            "recall_preference": self._recall_preference,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        import json
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[MEM_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Helpers ───────────────────────────────────────────────────

    def _strip_triggers(self, cmd: str) -> str:
        """Strip common memory trigger prefixes to get bare fact content."""
        triggers = [
            "remember that ", "remember this ", "note that ",
            "save that ", "keep in mind ", "don't forget ",
        ]
        lc = cmd.lower()
        for t in triggers:
            if lc.startswith(t):
                return cmd[len(t):].strip()
        return cmd.strip()

    # ── Handlers ─────────────────────────────────────────────────

    def _save_fact(self, d: dict, cmd: str) -> bool:
        key      = (d.get("key") or "").strip()
        value    = (d.get("value") or "").strip()
        mem_cat  = (d.get("memory_category") or "profile").strip() or "profile"

        if not value:
            value = self._strip_triggers(cmd)
        if not key:
            key = value[:30]
        if not value:
            self.speak("What should I remember?")
            return True

        # Normalize first-person to third-person for profile memories
        value = _first_to_third(value)

        # Route to smart memory
        try:
            from modules.smart_memory import add_smart_memory, _parse_schedule_from_text
            auto_sched = _parse_schedule_from_text(value) if mem_cat == "automation" else None
            add_smart_memory(mem_cat, value, raw_input=cmd, auto_schedule=auto_sched)
            from modules.memory import add_memory
            add_memory(key, value)
        except Exception as e:
            self.speak(f"Couldn't save to memory: {e}")
            return True

        self.speak("Got it. I'll remember that.")
        return True

    def _save_instruction(self, d: dict, cmd: str) -> bool:
        value = (d.get("value") or "").strip() or self._strip_triggers(cmd)
        if not value:
            self.speak("What instruction should I follow?")
            return True
        try:
            from modules.smart_memory import add_smart_memory
            entry = add_smart_memory("instruction", value, raw_input=cmd)
            if entry.get("supersedes"):
                self.speak(f"Got it. I've updated my behavior and replaced the old instruction.")
            else:
                self.speak("Got it. I'll follow that going forward.")
        except Exception as e:
            self.speak(f"Couldn't save instruction: {e}")
        return True

    def _save_automation(self, d: dict, cmd: str) -> bool:
        value = (d.get("value") or "").strip() or self._strip_triggers(cmd)
        if not value:
            self.speak("What recurring task should I schedule?")
            return True
        try:
            from modules.smart_memory import add_smart_memory, _parse_schedule_from_text
            auto_sched = _parse_schedule_from_text(value)
            add_smart_memory("automation", value, raw_input=cmd, auto_schedule=auto_sched)
            if auto_sched and auto_sched.get("cron"):
                self.speak(f"Got it. I've saved that as a recurring automation and scheduled it.")
            else:
                self.speak("Saved as an automation. I couldn't detect a time — you can set the schedule in the Memory tab.")
        except Exception as e:
            self.speak(f"Couldn't save automation: {e}")
        return True

    def _recall_all(self, d: dict, cmd: str) -> bool:
        try:
            from modules.memory import list_memory
            items = list_memory()
            if not items:
                self.speak("I don't have anything stored in memory yet.")
                return True
            self.speak(f"I remember {len(items)} thing{'s' if len(items) != 1 else ''} about you.")
            for _, val, _ in items[:5]:
                self.speak(val)
            if len(items) > 5:
                self.speak(f"And {len(items) - 5} more.")
        except Exception as e:
            self.speak(f"Couldn't read memory: {e}")
        return True

    def _recall_fact(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or d.get("key") or "").strip().lower()
        if not query:
            self.speak("What should I look up in memory?")
            return True

        try:
            from modules.memory import list_memory
            items = list_memory()
            matches = [
                (k, v) for k, v, _ in items
                if query in k.lower() or query in v.lower()
            ]
            if not matches:
                self.speak(f"I don't have anything about '{query}' stored.")
            elif len(matches) == 1:
                self.speak(matches[0][1])
            else:
                self.speak(f"Found {len(matches)} things: " +
                           " — ".join(v for _, v in matches[:3]) + ".")
        except Exception as e:
            self.speak(f"Memory lookup error: {e}")
        return True

    def _forget_fact(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or d.get("key") or "").strip().lower()
        if not query:
            # Try stripping trigger from raw cmd
            for t in ["forget that ", "remove from memory ", "delete memory about "]:
                if cmd.lower().startswith(t):
                    query = cmd[len(t):].strip().lower()
                    break
        if not query:
            self.speak("What should I forget?")
            return True

        try:
            from modules.memory import list_memory, remove_memory
            items  = list_memory()
            removed = 0
            for key, val, _ in items:
                if query in val.lower() or query in key.lower():
                    remove_memory(key)
                    removed += 1
            if removed:
                self.speak(f"Removed from memory.")
            else:
                self.speak(f"I couldn't find '{query}' in my memory.")
        except Exception as e:
            self.speak(f"Couldn't remove from memory: {e}")
        return True

    def _clear_memory(self, d: dict, cmd: str) -> bool:
        self._pending_clear = True
        self.speak("This will erase everything I've stored about you. Say 'yes, clear it' to confirm.")
        return True

    def _confirm_clear(self, cmd: str) -> bool:
        self._pending_clear = False
        lc = cmd.lower().strip()
        confirm_words = {"yes", "clear it", "yes clear it", "confirm", "do it", "go ahead", "haan"}
        if any(w in lc for w in confirm_words):
            try:
                from modules.memory import save_memory
                save_memory({})
                self.speak("Memory cleared. I've forgotten everything.")
            except Exception as e:
                self.speak(f"Couldn't clear memory: {e}")
        else:
            self.speak("Memory clear cancelled.")
        return True

    def _person_info(self, d: dict, cmd: str) -> bool:
        name = (d.get("person_name") or "").strip()
        if not name:
            m = re.search(
                r"(?:who is|what do you know about|tell me about)\s+([A-Za-z]+(?:\s[A-Za-z]+)?)",
                cmd, re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip().title()
        if not name:
            self.speak("Who do you want me to look up?")
            return True

        try:
            from modules.relationship_memory import get_summary
            self.speak(get_summary(name))
        except Exception as e:
            self.speak(f"Couldn't look up {name}: {e}")
        return True

    def _save_person_fact(self, d: dict, cmd: str) -> bool:
        name  = (d.get("person_name") or "").strip().title()
        attr  = (d.get("person_attr") or "").strip()
        value = (d.get("person_attr_value") or "").strip()

        if name and attr and value:
            try:
                from modules.relationship_memory import add_fact
                add_fact(name, attr, value)
                label_map = {
                    "relation":   "is your",
                    "works_at":   "works at",
                    "studies_at": "studies at",
                    "birthday":   "birthday is",
                    "notes":      "—",
                }
                label = label_map.get(attr, attr.replace("_", " "))
                self.speak(f"Got it. {name} {label} {value}. Saved.")
            except Exception as e:
                self.speak(f"Couldn't save: {e}")
            return True

        # Fallback: regex-based extraction
        cap_cmd = cmd[0].upper() + cmd[1:] if cmd else cmd
        try:
            from modules.relationship_memory import extract_and_save_from_command
            saved, msg = extract_and_save_from_command(cap_cmd)
            if saved:
                self.speak(msg)
                return True
        except Exception:
            pass

        # Last resort: if we at least have a name, save as generic note
        if name:
            note = re.sub(
                r"(?:remember that|note that|remember)\s+", "",
                cmd, flags=re.IGNORECASE,
            ).strip()
            try:
                from modules.relationship_memory import add_fact
                add_fact(name, "notes", note)
                self.speak(f"Noted — {name}: {note}.")
            except Exception as e:
                self.speak(f"Couldn't save: {e}")
        else:
            self.speak("I didn't catch who this is about.")
        return True

    def _list_people(self, d: dict, cmd: str) -> bool:
        try:
            from modules.relationship_memory import list_people
            people = list_people()
            if not people:
                self.speak("I don't have anyone saved yet.")
            elif len(people) <= 5:
                self.speak("I know about: " + ", ".join(people) + ".")
            else:
                self.speak(
                    f"I know about {len(people)} people: "
                    + ", ".join(people[:5])
                    + f", and {len(people) - 5} more."
                )
        except Exception as e:
            self.speak(f"Couldn't list people: {e}")
        return True

    def _save_preference(self, d: dict, cmd: str) -> bool:
        cat   = (d.get("pref_category") or "").strip().lower()
        value = (d.get("pref_value") or "").strip()
        if not cat or not value:
            self.speak("What preference should I save?")
            return True

        try:
            from modules.mongo_brain import save_preference
            save_preference(cat, value)
            self.speak(f"Noted. Your preferred {cat} is {value}.")
        except Exception as e:
            self.speak(f"Couldn't save preference: {e}")
        return True

    def _recall_preference(self, d: dict, cmd: str) -> bool:
        cat = (d.get("pref_category") or d.get("query") or "").strip().lower()
        if not cat:
            self.speak("Which preference should I look up?")
            return True

        try:
            from modules.mongo_brain import get_preference
            val = get_preference(cat)
            if val:
                self.speak(f"Your preferred {cat} is {val}.")
            else:
                self.speak(f"I don't have a preference saved for {cat}.")
        except Exception as e:
            self.speak(f"Couldn't recall preference: {e}")
        return True
