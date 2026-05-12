"""
pattern_learner.py
Phase 5: Behavioral pattern learning.

Reads command_log.csv, detects recurring time-based patterns,
suggests automations to the user, and executes confirmed routines.

Pattern types detected:
  - time-based: "weekdays ~9am → play Coding playlist" (3+ occurrences, 7+ day span)

Lifecycle:
  1. analyze()       — runs weekly, writes patterns.json
  2. ProactiveAgent  — offers unconfirmed patterns to user
  3. confirm(id)     — user says yes → routine saved to routines.json
  4. reject(id)      — user says no → marked rejected, never offered again
  5. RoutineRunner   — checks routines.json every 5 min, fires confirmed routines
"""

import csv
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

LOG_FILE      = "command_log.csv"
PATTERNS_FILE = "patterns.json"
ROUTINES_FILE = "routines.json"
LAST_ANALYSIS = "pattern_last_run.json"

MIN_OCCURRENCES = 3
MIN_DAY_SPAN    = 5   # pattern must span at least 5 days
ANALYSIS_INTERVAL_DAYS = 7

_speak_func   = None
_chain_fn     = None
_pending_suggestion: dict | None = None  # one at a time


def init(speak_fn, chain_fn=None):
    global _speak_func, _chain_fn
    _speak_func = speak_fn
    _chain_fn   = chain_fn


def start():
    """Start weekly analysis + routine runner in background threads."""
    threading.Thread(target=_analysis_loop, daemon=True).start()
    threading.Thread(target=_routine_runner, daemon=True).start()
    logger.info("[PatternLearner] Started.")


# ── Analysis ──────────────────────────────────────────────────

def _analysis_loop():
    import time
    time.sleep(60)  # wait for full boot
    while True:
        if _should_run_analysis():
            try:
                analyze()
            except Exception as e:
                logger.error(f"[PatternLearner] Analysis error: {e}")
        time.sleep(6 * 3600)  # check every 6h


def _should_run_analysis() -> bool:
    try:
        if not os.path.exists(LAST_ANALYSIS):
            return True
        with open(LAST_ANALYSIS) as f:
            last = datetime.fromisoformat(json.load(f).get("last_run", "2000-01-01"))
        return (datetime.now() - last).days >= ANALYSIS_INTERVAL_DAYS
    except Exception:
        return True


def analyze() -> list[dict]:
    """
    Full analysis pass. Reads CSV, detects patterns, updates patterns.json.
    Returns list of newly detected patterns.
    """
    logger.info("[PatternLearner] Starting analysis...")
    rows = _load_csv_rows(days=30)
    if len(rows) < MIN_OCCURRENCES:
        logger.info(f"[PatternLearner] Not enough data yet (need {MIN_OCCURRENCES}+ commands).")
        return []

    # Group by normalized command + time bucket
    buckets: dict[tuple, list] = defaultdict(list)
    for row in rows:
        try:
            ts   = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            cmd  = row.get("command", "").lower().strip()
            if not cmd or len(cmd) < 4:
                continue
            norm = _normalize_command(cmd)
            if not norm:
                continue
            hour_bucket = (ts.hour // 2) * 2   # 2h buckets: 0,2,4,...22
            day_type    = "weekend" if ts.weekday() >= 5 else "weekday"
            buckets[(norm, hour_bucket, day_type)].append(ts)
        except Exception:
            continue

    existing = _load_patterns()
    existing_keys = {(p["cmd_norm"], p["hour_bucket"], p["day_type"]) for p in existing}
    new_patterns = []

    for (norm, hour_bucket, day_type), timestamps in buckets.items():
        if len(timestamps) < MIN_OCCURRENCES:
            continue
        dates = sorted(set(t.date() for t in timestamps))
        if (dates[-1] - dates[0]).days < MIN_DAY_SPAN:
            continue

        key = (norm, hour_bucket, day_type)
        if key in existing_keys:
            # update count on existing
            for p in existing:
                if (p["cmd_norm"], p["hour_bucket"], p["day_type"]) == key:
                    p["count"] = len(timestamps)
                    p["last_seen"] = dates[-1].isoformat()
            continue

        pat_id = f"pat_{len(existing) + len(new_patterns) + 1:03d}"
        # pick most common example command
        example = _most_common_example(norm, [r["command"] for r in rows])
        new_patterns.append({
            "id":           pat_id,
            "cmd_norm":     norm,
            "example_cmd":  example,
            "day_type":     day_type,
            "hour_bucket":  hour_bucket,
            "count":        len(timestamps),
            "first_seen":   dates[0].isoformat(),
            "last_seen":    dates[-1].isoformat(),
            "status":       "pending",   # pending|offered|confirmed|rejected
            "offered_date": None,
            "routine_job_id": None,
        })

    all_patterns = existing + new_patterns
    with open(PATTERNS_FILE, "w") as f:
        json.dump(all_patterns, f, indent=2)

    with open(LAST_ANALYSIS, "w") as f:
        json.dump({"last_run": datetime.now().isoformat()}, f)

    logger.info(f"[PatternLearner] Analysis done. {len(new_patterns)} new patterns found.")
    return new_patterns


def _load_csv_rows(days: int = 30) -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rows = []
    try:
        with open(LOG_FILE, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff and row.get("status") == "success":
                        rows.append(row)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"[PatternLearner] CSV read error: {e}")
    return rows


_FILLER = re.compile(
    r'\b(hey|please|hi|okay|ok|yo|uh|um|can you|could you|would you|izach|will you|now|'
    r'the|a|an|my|me|i|to|for|on|in|at|and|or|is|are|was|were|be|been|being)\b'
)
_KNOWN_PREFIXES = [
    "play", "open", "check", "set", "turn", "show", "what",
    "search", "find", "get", "how", "tell", "start", "stop",
]

def _normalize_command(cmd: str) -> str | None:
    """Reduce command to a stable canonical form for pattern matching."""
    cmd = _FILLER.sub(" ", cmd).strip()
    cmd = re.sub(r'\s+', ' ', cmd).strip()
    if len(cmd) < 4:
        return None
    # keep first 6 words max
    words = cmd.split()[:6]
    return " ".join(words)


def _most_common_example(norm: str, all_commands: list[str]) -> str:
    """Return the most frequent raw command matching this normalized form."""
    candidates = [c for c in all_commands if _normalize_command(c.lower()) == norm]
    if not candidates:
        return norm
    return max(set(candidates), key=candidates.count)


# ── Suggestion (called by ProactiveAgent) ────────────────────

def get_pending_suggestion() -> dict | None:
    return _pending_suggestion


def offer_next_pattern() -> dict | None:
    """
    Returns next unoffered pattern (and marks it offered).
    ProactiveAgent calls this to get something to ask the user about.
    """
    global _pending_suggestion
    patterns = _load_patterns()
    today = datetime.now().date().isoformat()

    for p in patterns:
        if p.get("status") != "pending":
            continue
        if p.get("offered_date") == today:
            continue  # already offered today

        p["offered_date"] = today
        with open(PATTERNS_FILE, "w") as f:
            json.dump(patterns, f, indent=2)

        _pending_suggestion = p
        return p

    return None


def confirm_suggestion(pattern_id: str = None) -> bool:
    """User said yes. Save as confirmed routine."""
    global _pending_suggestion
    pid = pattern_id or (_pending_suggestion or {}).get("id")
    if not pid:
        return False

    patterns = _load_patterns()
    found = False
    for p in patterns:
        if p["id"] == pid:
            p["status"] = "confirmed"
            _save_routine(p)
            found = True
            break

    if not found:
        return False

    with open(PATTERNS_FILE, "w") as f:
        json.dump(patterns, f, indent=2)

    _pending_suggestion = None
    logger.info(f"[PatternLearner] Routine confirmed: {pid}")
    return True


def reject_suggestion(pattern_id: str = None) -> bool:
    """User said no. Mark rejected — never offer again."""
    global _pending_suggestion
    pid = pattern_id or (_pending_suggestion or {}).get("id")
    if not pid:
        return False

    patterns = _load_patterns()
    found = False
    for p in patterns:
        if p["id"] == pid:
            p["status"] = "rejected"
            found = True
            break

    if not found:
        return False

    with open(PATTERNS_FILE, "w") as f:
        json.dump(patterns, f, indent=2)

    _pending_suggestion = None
    logger.info(f"[PatternLearner] Pattern rejected: {pid}")
    return True


def _save_routine(pattern: dict):
    routines = _load_routines()
    routines = [r for r in routines if r["id"] != pattern["id"]]
    routines.append({
        "id":          pattern["id"],
        "cmd":         pattern["example_cmd"],
        "day_type":    pattern["day_type"],
        "hour_bucket": pattern["hour_bucket"],
        "last_fired":  None,
    })
    with open(ROUTINES_FILE, "w") as f:
        json.dump(routines, f, indent=2)


# ── Routine runner (called every 5 min by its own thread) ────

def _routine_runner():
    import time
    time.sleep(90)
    while True:
        try:
            _fire_due_routines()
        except Exception as e:
            logger.error(f"[PatternLearner] Routine runner error: {e}")
        time.sleep(300)  # check every 5 min


def _fire_due_routines():
    if not _chain_fn:
        return
    routines = _load_routines()
    now = datetime.now(tz=IST)
    hour_bucket = (now.hour // 2) * 2
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    today = now.date().isoformat()
    changed = False

    for r in routines:
        if r.get("day_type") != day_type:
            continue
        if r.get("hour_bucket") != hour_bucket:
            continue
        if r.get("last_fired") == today:
            continue  # already fired today

        # Fire only in first 5 min of bucket
        if now.minute > 5:
            continue

        r["last_fired"] = today
        changed = True
        cmd = r.get("cmd", "")
        logger.info(f"[PatternLearner] Firing routine: {cmd}")
        if _speak_func:
            _speak_func(f"Starting your usual {_friendly_name(cmd)}.")
        threading.Thread(target=_chain_fn, args=(cmd,), daemon=True).start()

    if changed:
        with open(ROUTINES_FILE, "w") as f:
            json.dump(routines, f, indent=2)


def _friendly_name(cmd: str) -> str:
    words = cmd.split()[:4]
    return " ".join(words)


# ── Persistence helpers ───────────────────────────────────────

def _load_patterns() -> list[dict]:
    if not os.path.exists(PATTERNS_FILE):
        return []
    try:
        with open(PATTERNS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _load_routines() -> list[dict]:
    if not os.path.exists(ROUTINES_FILE):
        return []
    try:
        with open(ROUTINES_FILE) as f:
            return json.load(f)
    except Exception:
        return []


# ── Public query helpers ──────────────────────────────────────

def list_routines() -> list[dict]:
    return _load_routines()


def list_patterns() -> list[dict]:
    return _load_patterns()


def delete_routine(routine_id: str) -> bool:
    routines = [r for r in _load_routines() if r["id"] != routine_id]
    with open(ROUTINES_FILE, "w") as f:
        json.dump(routines, f, indent=2)
    return True
