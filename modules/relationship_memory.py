"""
modules/relationship_memory.py
iZACH relationship memory — stores and recalls facts about people.
Backed by MongoDB (fast lookup) + Obsidian (linked notes in graph).

Voice triggers handled in command_chain:
  "Divya is my college friend"     → save_fact("Divya", "relation", "college friend")
  "Remember that Rohan works at Google" → save_fact("Rohan", "works_at", "Google")
  "Who is Divya?"                  → get_summary("Divya") → speak
  "What do you know about Rohan?"  → same
"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_COLLECTION = "relationships"


# ── Public API ────────────────────────────────────────────────


def save_person(name: str, facts: dict) -> bool:
    """
    Upsert a person record. facts dict can have any keys:
    relation, works_at, studies_at, notes, whatsapp_number, etc.
    """
    name = _normalize(name)
    if not name:
        return False
    db = _db()
    if db is not None:
        db[_COLLECTION].update_one(
            {"_id": name},
            {"$set": {**facts, "updated_at": datetime.now()}},
            upsert=True
        )
    _write_obsidian(name, facts)
    logger.info(f"[RelMem] Saved person: {name} → {facts}")
    return True


def add_fact(name: str, key: str, value: str) -> bool:
    """Add or update a single fact about a person."""
    return save_person(name, {key: value})


def get_person(name: str) -> dict:
    """Return full record for a person, or {} if unknown."""
    name = _normalize(name)
    db = _db()
    if db is not None:
        doc = db[_COLLECTION].find_one({"_id": name})
        if doc:
            doc.pop("_id", None)
            doc.pop("updated_at", None)
            return doc
    return {}


def get_summary(name: str) -> str:
    """Human-readable summary of what iZACH knows about a person."""
    person = get_person(name)
    if not person:
        return f"I don't have anything saved about {name} yet."
    lines = [f"Here's what I know about {name}:"]
    label_map = {
        "relation":    "Relationship",
        "works_at":    "Works at",
        "studies_at":  "Studies at",
        "notes":       "Notes",
        "whatsapp_number": "WhatsApp",
        "last_topic":  "Last talked about",
        "birthday":    "Birthday",
    }
    for k, v in person.items():
        label = label_map.get(k, k.replace("_", " ").title())
        lines.append(f"  {label}: {v}")
    return "\n".join(lines)


def list_people() -> list[str]:
    """Return list of all known person names."""
    db = _db()
    if db is not None:
        return [doc["_id"] for doc in db[_COLLECTION].find({}, {"_id": 1})]
    return []


def find_person_by_number(wa_number: str) -> tuple[str, dict]:
    """
    Look up a person by WhatsApp number.
    Returns (name, facts) or ("", {}) if not found.
    """
    db = _db()
    if db is not None:
        doc = db[_COLLECTION].find_one({"whatsapp_number": wa_number})
        if doc:
            name = doc.pop("_id")
            doc.pop("updated_at", None)
            return name, doc
    return "", {}


def extract_and_save_from_command(text: str) -> tuple[bool, str]:
    """
    Attempt to extract a relationship fact from a voice command.
    Patterns:
      "[Name] is my [relation]"
      "remember that [Name] [verb] [detail]"
      "[Name]'s [attribute] is [value]"
    Returns (True, confirmation_msg) if extracted, else (False, "").
    """
    text = text.strip()

    # Pattern: "[Name] is my [relation]"
    m = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+is\s+my\s+(.+)$", text, re.IGNORECASE)
    if m:
        name, relation = m.group(1).strip(), m.group(2).strip()
        save_person(name, {"relation": relation})
        return True, f"Got it. {name} is your {relation}. Saved."

    # Pattern: "[Name] works at [place]"
    m = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+works\s+at\s+(.+)$", text, re.IGNORECASE)
    if m:
        name, place = m.group(1).strip(), m.group(2).strip()
        save_person(name, {"works_at": place})
        return True, f"Noted. {name} works at {place}."

    # Pattern: "[Name] studies at [place]"
    m = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:studies|goes to school|goes to college)\s+(?:at\s+)?(.+)$", text, re.IGNORECASE)
    if m:
        name, place = m.group(1).strip(), m.group(2).strip()
        save_person(name, {"studies_at": place})
        return True, f"Noted. {name} studies at {place}."

    # Pattern: "remember that [Name] [detail]"
    m = re.match(r"^(?:remember\s+that\s+|note\s+that\s+)([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(.+)$", text, re.IGNORECASE)
    if m:
        name, detail = m.group(1).strip(), m.group(2).strip()
        save_person(name, {"notes": detail})
        return True, f"Remembered — {name}: {detail}."

    return False, ""


# ── Obsidian ──────────────────────────────────────────────────


def _write_obsidian(name: str, facts: dict):
    try:
        from modules.obsidian_brain import save_person_profile
        save_person_profile(name, facts)
    except Exception as e:
        logger.warning(f"[RelMem] Obsidian write failed: {e}")


# ── Internal ──────────────────────────────────────────────────


def _normalize(name: str) -> str:
    return name.strip().title()


def _db():
    try:
        from modules.mongo_brain import init_db
        return init_db()
    except Exception:
        return None
