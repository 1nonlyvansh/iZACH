"""
alias_engine.py — User-defined voice aliases for iZACH.

Stores trigger → command mappings in voice_aliases.json.
Example:
  {"fire it up": {"command": "play my gym playlist", "created": "2026-05-31 10:00"}}
"""

import json
import os
from datetime import datetime

_ALIAS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "voice_aliases.json")


def load_aliases() -> dict:
    """Load all aliases as {trigger: {command, created}} dict."""
    try:
        with open(_ALIAS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_aliases(d: dict):
    """Persist aliases dict to disk."""
    with open(_ALIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def add_alias(trigger: str, command: str):
    """Add or update an alias. trigger and command are stripped strings."""
    trigger  = trigger.strip().lower()
    command  = command.strip()
    if not trigger or not command:
        raise ValueError("trigger and command must be non-empty")
    aliases = load_aliases()
    aliases[trigger] = {
        "command": command,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_aliases(aliases)


def delete_alias(trigger: str):
    """Remove an alias by trigger. Silent if not found."""
    trigger = trigger.strip().lower()
    aliases = load_aliases()
    aliases.pop(trigger, None)
    save_aliases(aliases)


def list_aliases() -> list:
    """Return list of {trigger, command, created} dicts sorted by created desc."""
    aliases = load_aliases()
    result = []
    for trigger, meta in aliases.items():
        if isinstance(meta, dict):
            result.append({
                "trigger": trigger,
                "command": meta.get("command", ""),
                "created": meta.get("created", ""),
            })
        else:
            # Legacy flat string format
            result.append({"trigger": trigger, "command": str(meta), "created": ""})
    result.sort(key=lambda x: x["created"], reverse=True)
    return result


def resolve(text: str) -> str:
    """
    Check if text matches any alias trigger (case-insensitive exact match).
    If matched, return the aliased command. Otherwise return text unchanged.
    """
    if not text:
        return text
    normalized = text.strip().lower()
    aliases = load_aliases()
    if normalized in aliases:
        meta = aliases[normalized]
        return meta["command"] if isinstance(meta, dict) else str(meta)
    return text
