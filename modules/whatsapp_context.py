"""
whatsapp_context.py
Phase 3: On iZACH startup, fetch last 24h of WhatsApp messages and process
any events that were missed while iZACH was offline.

Deduplicates via wa_processed_msgs.json so messages aren't processed twice.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

WA_BRIDGE_URL = "http://localhost:3000"
PROCESSED_FILE = "wa_processed_msgs.json"
MAX_STORED_IDS = 2000  # cap file size


def startup_sync(speak_fn=None, hours: int = 24):
    """
    Call once at startup (non-blocking — runs in background thread).
    Waits for WA bridge to connect, then fetches + processes history.
    """
    threading.Thread(
        target=_sync_worker,
        args=(speak_fn, hours),
        daemon=True
    ).start()


def _sync_worker(speak_fn, hours: int):
    if not _wait_for_bridge(timeout=120):
        logger.warning("[WAContext] Bridge didn't connect in 2 min. Skipping history sync.")
        return

    logger.info(f"[WAContext] Fetching last {hours}h of WhatsApp messages...")
    try:
        r = requests.get(f"{WA_BRIDGE_URL}/messages/history", params={"hours": hours}, timeout=30)
        data = r.json()
    except Exception as e:
        logger.error(f"[WAContext] Failed to fetch history: {e}")
        return

    messages = data.get("messages", [])
    if not messages:
        logger.info("[WAContext] No messages in history.")
        return

    processed_ids = _load_processed_ids()
    new_msgs = [m for m in messages if m.get("id") not in processed_ids]

    if not new_msgs:
        logger.info("[WAContext] All messages already processed.")
        return

    logger.info(f"[WAContext] Processing {len(new_msgs)} unprocessed messages from history.")

    from modules.event_extractor import _extract, _handle_new_event, _handle_cancellation, _handle_reschedule
    from modules import event_extractor as _ee
    if speak_fn:
        _ee._speak_func = speak_fn

    events_found = []

    for msg in new_msgs:
        text      = msg.get("text", "").strip()
        sender    = msg.get("sender", "Unknown")
        msg_id    = msg.get("id")
        timestamp = str(msg.get("timestamp", ""))

        if not text:
            continue

        extracted = _extract(text, sender, timestamp)
        if not extracted:
            _mark_processed(msg_id)
            continue

        confidence = extracted.get("confidence", 0)
        if confidence < 0.80:
            _mark_processed(msg_id)
            continue

        is_event        = extracted.get("is_event", False)
        is_cancellation = extracted.get("is_cancellation", False)
        is_reschedule   = extracted.get("is_reschedule", False)

        if is_cancellation:
            _handle_cancellation(extracted, sender)
        elif is_reschedule:
            _handle_reschedule(extracted, sender)
        elif is_event:
            _handle_new_event(extracted, sender, msg_id)
            events_found.append(extracted)

        _mark_processed(msg_id)

    if events_found and speak_fn:
        count = len(events_found)
        if count == 1:
            e = events_found[0]
            title = e.get("title", "event")
            time_s = e.get("time", "")
            date_s = e.get("date", "")
            try:
                dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
                t_str = dt.strftime("%I:%M %p").lstrip("0")
                d_str = dt.strftime("%d %B")
                speak_fn(f"While I was offline, I found {title} at {t_str} on {d_str}. Added to your calendar.")
            except Exception:
                speak_fn(f"While I was offline, I found 1 new event. Added to your calendar.")
        else:
            speak_fn(f"While I was offline, I found {count} new events in your WhatsApp. Added to your calendar.")

    logger.info(f"[WAContext] Sync complete. {len(events_found)} events added from history.")


def _wait_for_bridge(timeout: int = 120) -> bool:
    """Poll WA bridge health until connected or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{WA_BRIDGE_URL}/health", timeout=3)
            if r.json().get("status") == "connected":
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


# ── Processed message ID store ────────────────────────────────

def _load_processed_ids() -> set:
    if not os.path.exists(PROCESSED_FILE):
        return set()
    try:
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _mark_processed(msg_id: str):
    if not msg_id:
        return
    ids = _load_processed_ids()
    ids.add(msg_id)
    # trim to cap
    if len(ids) > MAX_STORED_IDS:
        ids = set(list(ids)[-MAX_STORED_IDS:])
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(ids), f)
