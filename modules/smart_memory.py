"""
modules/smart_memory.py
iZACH persistent smart memory engine.

Memory types:
  profile     — long-term user facts ("Vansh's favorite singer is Kanye West")
  instruction — behavioral directives ("Always reply briefly")
  automation  — recurring scheduled tasks ("Play lofi at 4 PM daily")

Features:
  - Conflict detection & supersede for instruction memories
  - APScheduler job creation for automation memories
  - Obsidian vault sync (one .md per memory)
  - ChatGPT/Claude import parser
  - Export to text
"""

from __future__ import annotations
import json, os, re, uuid
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
SMART_MEMORY_FILE = os.path.join(ROOT, "smart_memory.json")

try:
    import config_loader as _cfg
    OWNER = _cfg.get("user", {}).get("name", "Vansh")
except Exception:
    OWNER = "Vansh"

# ── I/O ───────────────────────────────────────────────────────────────────────

def _load() -> list:
    try:
        with open(SMART_MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f).get("memories", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[SmartMemory] Load error: {e}")
        return []


def _save(memories: list):
    with open(SMART_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"memories": memories, "version": 2}, f, indent=2, ensure_ascii=False)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _new_id() -> str:
    return "m_" + uuid.uuid4().hex[:8]


# ── Conflict detection ────────────────────────────────────────────────────────

_BEHAVIOR_KEYS = [
    "call me", "address me", "reply", "respond with", "always ", "never ",
    "don't ", "use formal", "use informal", "tone", "language style",
    "greeting", "briefly", "concise", "detailed", "formal", "informal",
    "stop using", "instead of", "prefix", "suffix", "punctuation",
]


def _find_conflict(memories: list, new_content: str) -> str | None:
    """Return id of first enabled instruction that shares behavior keywords."""
    lower = new_content.lower()
    matched_keys = [k for k in _BEHAVIOR_KEYS if k in lower]
    if not matched_keys:
        return None
    for m in memories:
        if m.get("category") != "instruction" or not m.get("enabled", True):
            continue
        existing = m.get("content", "").lower()
        if any(k in existing for k in matched_keys):
            return m["id"]
    return None


# ── CRUD ──────────────────────────────────────────────────────────────────────

def add_smart_memory(
    category: str,
    content: str,
    raw_input: str = "",
    auto_schedule: dict | None = None,
) -> dict:
    """
    Add a new smart memory.
    - instruction: auto-detect & supersede conflicting instructions
    - automation:  create APScheduler job if schedule found
    Returns the new memory entry dict.
    """
    memories = _load()

    entry: dict = {
        "id":           _new_id(),
        "category":     category,
        "content":      content,
        "raw_input":    raw_input,
        "enabled":      True,
        "created":      _now(),
        "updated":      _now(),
        "supersedes":   None,
        "superseded_by": None,
    }
    if auto_schedule:
        entry["auto_schedule"] = auto_schedule

    # Instruction conflict → mark old as superseded
    if category == "instruction":
        conflict_id = _find_conflict(memories, content)
        if conflict_id:
            for m in memories:
                if m["id"] == conflict_id:
                    m["superseded_by"] = entry["id"]
                    m["enabled"] = False
                    entry["supersedes"] = conflict_id
                    break

    memories.append(entry)
    _save(memories)

    # Side-effects (non-blocking, best-effort)
    _sync_to_obsidian(entry)
    if category == "automation" and auto_schedule and entry["enabled"]:
        _schedule_automation(entry)

    return entry


def list_smart_memories(
    category: str | None = None,
    include_disabled: bool = False,
    search: str = "",
) -> list:
    memories = _load()
    result = []
    sq = search.lower().strip()
    for m in memories:
        if not include_disabled and not m.get("enabled", True):
            continue
        if category and m.get("category") != category:
            continue
        if sq and sq not in m.get("content", "").lower():
            continue
        result.append(m)
    return sorted(result, key=lambda x: x.get("created", ""), reverse=True)


def get_smart_memory(mid: str) -> dict | None:
    return next((m for m in _load() if m["id"] == mid), None)


def update_smart_memory(
    mid: str,
    content: str | None = None,
    enabled: bool | None = None,
) -> bool:
    memories = _load()
    for m in memories:
        if m["id"] != mid:
            continue
        if content is not None:
            m["content"] = content
            m["updated"] = _now()
        if enabled is not None:
            m["enabled"] = enabled
            if m.get("category") == "automation":
                if enabled:
                    _schedule_automation(m)
                else:
                    _unschedule_automation(m)
        _save(memories)
        _sync_to_obsidian(m)
        return True
    return False


def delete_smart_memory(mid: str) -> bool:
    memories = _load()
    target = next((m for m in memories if m["id"] == mid), None)
    if not target:
        return False
    if target.get("category") == "automation":
        _unschedule_automation(target)
    _save([m for m in memories if m["id"] != mid])
    return True


# ── AI context injection ──────────────────────────────────────────────────────

def get_instruction_context() -> str:
    """Enabled instruction memories → prompt block injected into AI calls."""
    items = list_smart_memories("instruction")
    lines = [m["content"] for m in items if m.get("enabled")]
    if not lines:
        return ""
    return "User behavioral instructions (follow these always):\n" + "\n".join(f"- {l}" for l in lines)


def get_profile_context() -> str:
    """Enabled profile memories → prompt context block."""
    items = list_smart_memories("profile")
    lines = [m["content"] for m in items if m.get("enabled")]
    if not lines:
        return ""
    return f"What iZACH knows about {OWNER}:\n" + "\n".join(f"- {l}" for l in lines)


def get_full_context() -> str:
    """Combined profile + instruction context for AI."""
    parts = [get_profile_context(), get_instruction_context()]
    return "\n\n".join(p for p in parts if p)


# ── Import parser ─────────────────────────────────────────────────────────────

def import_from_text(raw_text: str) -> list[dict]:
    """
    Parse a ChatGPT / Claude memory export paste.
    Accepts bullet lists, numbered lists, section headers.
    Returns list of newly created memory entries.
    """
    imported: list[dict] = []
    lines = raw_text.strip().splitlines()
    current_cat: str = "profile"

    SECTION_MAP = {
        "profile":     "profile",
        "identity":    "profile",
        "about me":    "profile",
        "facts":       "profile",
        "preferences": "profile",
        "instruction": "instruction",
        "behavior":    "instruction",
        "rules":       "instruction",
        "automation":  "automation",
        "schedule":    "automation",
        "reminders":   "automation",
        "tasks":       "automation",
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Section header detection
        clean_header = re.sub(r'[#\-–—*_`]', '', stripped).strip().lower()
        matched_section = next(
            (v for k, v in SECTION_MAP.items() if k in clean_header),
            None
        )
        if matched_section and len(stripped) < 50:
            current_cat = matched_section
            continue

        # Strip bullet / numbering
        clean = re.sub(r'^[-•*▸►\d]+[.):]?\s*', '', stripped).strip()
        if len(clean) < 8:
            continue

        cat = _classify_memory(clean) if current_cat == "profile" else current_cat
        auto_sched = _parse_schedule_from_text(clean) if cat == "automation" else None

        entry = add_smart_memory(cat, clean, raw_input=stripped, auto_schedule=auto_sched)
        imported.append(entry)

    return imported


def _classify_memory(text: str) -> str:
    """Heuristic category classifier."""
    lower = text.lower()

    AUTO_KW = [
        "every day", "daily", "every morning", "every evening", "every week",
        "at \\d", " pm", " am", "schedule", "remind me every",
        "automatically", "recurring", "routine", "each day", "weekday",
    ]
    INST_KW = [
        "call me", "address me", "always ", "never ", "don't ",
        "reply ", "respond with", "use ", "avoid ", "prefer ",
        "stop ", "instead of", "tone", "formal", "informal",
        "briefly", "concise", "detailed", "language",
    ]
    if any(re.search(k, lower) for k in AUTO_KW):
        return "automation"
    if any(k in lower for k in INST_KW):
        return "instruction"
    return "profile"


def _parse_schedule_from_text(text: str) -> dict | None:
    """Extract cron schedule string from natural language automation text."""
    lower = text.lower()

    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', lower)
    if not m:
        return None

    hour   = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm   = m.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    dow = "*"
    if "monday"  in lower: dow = "1"
    elif "tuesday"  in lower: dow = "2"
    elif "wednesday" in lower: dow = "3"
    elif "thursday" in lower: dow = "4"
    elif "friday"   in lower: dow = "5"
    elif "weekend"  in lower: dow = "6,0"
    elif "weekday"  in lower: dow = "1-5"

    cron = f"{minute} {hour} * * {dow}"
    return {"cron": cron, "action": text, "job_id": None}


# ── Export ────────────────────────────────────────────────────────────────────

def export_to_text(include_disabled: bool = False) -> str:
    memories = _load()
    active = [m for m in memories if include_disabled or m.get("enabled")]
    if not active:
        return "No memories stored."

    sections: dict[str, list[str]] = {}
    for m in active:
        sections.setdefault(m.get("category", "profile"), []).append(m["content"])

    lines = [f"# iZACH Memory Export — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for cat, items in sections.items():
        lines.append(f"\n## {cat.title()}\n")
        for item in items:
            lines.append(f"- {item}")

    return "\n".join(lines)


# ── Obsidian sync ─────────────────────────────────────────────────────────────

_OBS_FOLDERS = {
    "profile":     "Identity",
    "instruction": "Instructions",
    "automation":  "Automations",
    "preference":  "Preferences",
    "project":     "Projects",
}


def _sync_to_obsidian(entry: dict):
    try:
        from modules.obsidian_brain import VAULT_PATH
        folder = _OBS_FOLDERS.get(entry.get("category", "profile"), "Identity")
        dir_path = os.path.join(VAULT_PATH, "Memory", folder)
        os.makedirs(dir_path, exist_ok=True)

        slug = re.sub(r'[^\w\s-]', '', entry["content"][:40]).strip().replace(' ', '-')
        filename = f"{entry['id']}_{slug}.md"
        filepath = os.path.join(dir_path, filename)

        cat  = entry.get("category", "profile")
        tags = [folder.lower(), cat, "izach-memory"]

        links = []
        if entry.get("supersedes"):
            links.append(f"- supersedes: [[{entry['supersedes']}]]")
        if entry.get("superseded_by"):
            links.append(f"- superseded_by: [[{entry['superseded_by']}]]")

        md = (
            f"---\n"
            f"id: {entry['id']}\n"
            f"category: {cat}\n"
            f"tags: {json.dumps(tags)}\n"
            f"created: {entry.get('created', '')}\n"
            f"updated: {entry.get('updated', '')}\n"
            f"enabled: {str(entry.get('enabled', True)).lower()}\n"
            f"---\n\n"
            f"# {entry['content'][:80]}\n\n"
            f"{entry['content']}\n\n"
            + ("\n".join(links) + "\n\n" if links else "")
            + f"---\n*Source: iZACH Smart Memory · {entry.get('created', '')}*\n"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)
    except Exception as e:
        print(f"[SmartMemory] Obsidian sync error: {e}")


def sync_all_to_obsidian() -> int:
    count = 0
    for m in _load():
        try:
            _sync_to_obsidian(m)
            count += 1
        except Exception:
            pass
    return count


# ── Scheduler integration ─────────────────────────────────────────────────────

def _schedule_automation(entry: dict):
    sched = entry.get("auto_schedule") or {}
    if not sched.get("cron"):
        return
    try:
        from modules.automation_scheduler import schedule_memory_job
        job_id = schedule_memory_job(entry["id"], sched["cron"], sched["action"])
        if job_id:
            memories = _load()
            for m in memories:
                if m["id"] == entry["id"]:
                    m.setdefault("auto_schedule", {})["job_id"] = job_id
                    break
            _save(memories)
    except Exception as e:
        print(f"[SmartMemory] Schedule error: {e}")


def _unschedule_automation(entry: dict):
    sched = entry.get("auto_schedule") or {}
    job_id = sched.get("job_id")
    if not job_id:
        return
    try:
        from modules.automation_scheduler import unschedule_memory_job
        unschedule_memory_job(job_id)
    except Exception as e:
        print(f"[SmartMemory] Unschedule error: {e}")
