"""
modules/synonym_learner.py
Command failure learning — reduces future false negatives by recording
alternate phrasings that succeeded after an earlier phrasing failed.

Flow:
  1. command_chain routes cmd → domain="chat", confidence=low → record_failure()
  2. User rephrases (within FAILURE_WINDOW seconds)
  3. New phrasing routed to a real domain → record_success()
  4. synonym stored: domain → [phrase, ...]
  5. Future: match_synonym(query) → domain hint skips orchestrator for known phrases
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

SYNONYMS_FILE  = "intent_synonyms.json"
FAILURE_WINDOW = 120   # seconds — must succeed within this window

_synonyms: dict[str, list[str]] = {}      # domain → [phrases]
_pending: dict[str, dict]       = {}      # domain → {cmd, ts}
_loaded = False


# ── Public API ─────────────────────────────────────────────────

def record_failure(command: str, domain: str):
    """
    Call when a command routes to 'chat' with low confidence (fallback).
    Marks this domain as having a pending failure for this phrasing.
    """
    _load()
    cmd = command.lower().strip()
    _pending[domain] = {"cmd": cmd, "ts": time.time()}
    logger.debug(f"[SynonymLearner] Failure: domain={domain} cmd={cmd!r}")


def record_success(command: str, domain: str):
    """
    Call when a command is handled by a real agent (non-chat domain).
    If same domain failed recently with different phrasing → store synonym.
    """
    _load()
    failure = _pending.get(domain)
    if not failure:
        return
    if time.time() - failure["ts"] > FAILURE_WINDOW:
        _pending.pop(domain, None)
        return

    failed_cmd  = failure["cmd"]
    success_cmd = command.lower().strip()

    if failed_cmd == success_cmd:
        _pending.pop(domain, None)
        return

    if domain not in _synonyms:
        _synonyms[domain] = []
    if success_cmd not in _synonyms[domain]:
        _synonyms[domain].append(success_cmd)
        _save()
        logger.info(
            f"[SynonymLearner] Learned synonym: domain={domain!r} "
            f"new={success_cmd!r} (corrected from: {failed_cmd!r})"
        )

    _pending.pop(domain, None)


def match_synonym(command: str) -> str | None:
    """
    Returns domain if command closely matches a learned synonym, else None.
    Called at start of command_chain.process() to pre-route known phrasings.
    """
    _load()
    cmd = command.lower().strip()
    best_domain = None
    best_overlap = 0.0

    for domain, phrases in _synonyms.items():
        for phrase in phrases:
            if phrase == cmd:
                return domain  # exact match → immediate
            ov = _word_overlap(cmd, phrase)
            if ov > best_overlap and ov >= 0.65:
                best_overlap = ov
                best_domain  = domain

    return best_domain


def get_synonyms(domain: str) -> list[str]:
    _load()
    return list(_synonyms.get(domain, []))


def stats() -> dict:
    _load()
    return {
        "domains_learned": len(_synonyms),
        "total_synonyms":  sum(len(v) for v in _synonyms.values()),
        "pending_failures": len(_pending),
    }


# ── Internals ──────────────────────────────────────────────────

def _load():
    global _synonyms, _loaded
    if _loaded:
        return
    _loaded = True
    if not os.path.exists(SYNONYMS_FILE):
        _synonyms = {}
        return
    try:
        with open(SYNONYMS_FILE) as f:
            _synonyms = json.load(f)
        total = sum(len(v) for v in _synonyms.values())
        logger.info(f"[SynonymLearner] Loaded {total} synonyms across {len(_synonyms)} domains.")
    except Exception:
        _synonyms = {}


def _save():
    try:
        with open(SYNONYMS_FILE, "w") as f:
            json.dump(_synonyms, f, indent=2)
    except Exception as e:
        logger.error(f"[SynonymLearner] Save error: {e}")


def _word_overlap(a: str, b: str) -> float:
    """Jaccard coefficient of word sets."""
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
