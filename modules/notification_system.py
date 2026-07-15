"""
Notification system — push categorized PC events to Android/Cortex/Forge.
Categories: system, downloads, transfers, automation, alerts

Phase 5 (2026-07-16): unified notification triage. Previously WhatsApp and
Calendar reminders bypassed this entirely (WhatsApp used a separate raw WS
broadcast, Calendar was voice-only) so /notifications/history only ever
showed email-agent and health-monitor alerts. Both now also push() here, and
`feed()` returns everything ranked by a simple, deterministic priority score
(VIP sender + category weight) rather than raw insertion order — no LLM
involved, this is just arithmetic over already-known signals.
"""
import json
import time

CATEGORIES = {"system", "downloads", "transfers", "automation", "alerts"}
_history: list[dict] = []
_MAX_HISTORY = 50

# Base priority weight per category — "alerts"/"system" are things a person
# usually wants to see promptly; "downloads"/"transfers"/"automation" are
# passive/background-status pings.
_CATEGORY_WEIGHT = {"alerts": 3, "system": 3, "automation": 1, "downloads": 1, "transfers": 1}
_VIP_BONUS = 5


def push(title: str, category: str = "system", body: str = "", source: str = ""):
    if category not in CATEGORIES:
        category = "system"
    entry = {
        "title": title, "category": category, "body": body,
        "source": source or category, "ts": int(time.time()),
    }
    _history.insert(0, entry)
    if len(_history) > _MAX_HISTORY:
        _history.pop()
    try:
        from modules.ws_bridge import emit
        emit("notification", category, {
            "title": title, "body": body, "category": category,
            "source": entry["source"], "ts": entry["ts"],
        })
    except Exception:
        pass


def history() -> list:
    return list(_history)


def _vip_contacts() -> set:
    try:
        with open("api_keys.json", encoding="utf-8") as f:
            return set(json.load(f).get("dnd_priority_contacts", []))
    except Exception:
        return set()


def _score(entry: dict, vips: set) -> int:
    score = _CATEGORY_WEIGHT.get(entry.get("category"), 1)
    hay = f"{entry.get('title', '')} {entry.get('body', '')}".lower()
    if any(v and v.lower() in hay for v in vips):
        score += _VIP_BONUS
    return score


def feed(limit: int = 20) -> list:
    """Same entries as history(), ranked by priority score (VIP + category
    weight) rather than plain insertion order, newest first within a tier."""
    vips = _vip_contacts()
    scored = [{**e, "priority": _score(e, vips)} for e in _history]
    scored.sort(key=lambda e: (e["priority"], e["ts"]), reverse=True)
    return scored[:limit]
