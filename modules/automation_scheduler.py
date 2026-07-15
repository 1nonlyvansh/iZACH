"""
modules/automation_scheduler.py
APScheduler background scheduler for automation memories.
Restored from smart_memory.json on every startup.
"""

from __future__ import annotations
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler: BackgroundScheduler | None = None
_speak_fn = None


def init(speak_fn=None):
    """Call once on backend startup with the speak callback."""
    global _scheduler, _speak_fn
    _speak_fn = speak_fn
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.start()
    _restore_jobs()
    print("[AutoSched] Scheduler started.")


def _restore_jobs():
    try:
        from modules.smart_memory import list_smart_memories
        for m in list_smart_memories("automation"):
            if m.get("enabled") and m.get("auto_schedule", {}).get("cron"):
                _do_schedule(f"mem_{m['id']}", m["auto_schedule"]["cron"], m["auto_schedule"]["action"])
    except Exception as e:
        print(f"[AutoSched] Restore error: {e}")

    try:
        import os, json
        recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "browser_recordings")
        if os.path.isdir(recordings_dir):
            for fname in os.listdir(recordings_dir):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(recordings_dir, fname), encoding="utf-8") as f:
                        rec = json.load(f)
                    if rec.get("schedule_cron"):
                        schedule_recording_job(rec["name"], rec["schedule_cron"])
                except Exception:
                    continue
    except Exception as e:
        print(f"[AutoSched] Recording schedule restore error: {e}")


def schedule_memory_job(memory_id: str, cron_expr: str, action_text: str) -> str:
    job_id = f"mem_{memory_id}"
    _do_schedule(job_id, cron_expr, action_text)
    return job_id


def schedule_recording_job(name: str, cron_expr: str) -> str:
    """Recording feature's scheduling hook — 'run my X recording every morning
    at 9'. The action text is a sentinel command_chain.py matches directly (no
    trigger-phrase text needed) and routes to a replay_recording WS broadcast,
    since only the Electron renderer can decrypt any credential steps."""
    job_id = f"rec_{name}"
    _do_schedule(job_id, cron_expr, f"__replay_recording__::{name}")
    return job_id


def _do_schedule(job_id: str, cron_expr: str, action_text: str):
    global _scheduler, _speak_fn
    if not _scheduler:
        return

    # Drop existing
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass

    def _run_job(action=action_text):
        try:
            from modules.command_chain import _chain_ref
            if _chain_ref:
                import threading
                threading.Thread(target=_chain_ref.process, args=(action,), daemon=True).start()
            elif _speak_fn:
                _speak_fn(f"Automation: {action}")
        except Exception as e:
            print(f"[AutoSched] Job run error: {e}")

    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            print(f"[AutoSched] Bad cron: {cron_expr}")
            return
        minute, hour, dom, month, dow = parts
        _scheduler.add_job(
            _run_job,
            CronTrigger(
                minute=minute, hour=hour,
                day=dom, month=month, day_of_week=dow,
            ),
            id=job_id,
            replace_existing=True,
        )
        print(f"[AutoSched] Scheduled {job_id}: {cron_expr}")
    except Exception as e:
        print(f"[AutoSched] Schedule error: {e}")


def unschedule_memory_job(job_id: str):
    global _scheduler
    if _scheduler:
        try:
            _scheduler.remove_job(job_id)
            print(f"[AutoSched] Removed {job_id}")
        except Exception:
            pass


def list_jobs() -> list[dict]:
    global _scheduler
    if not _scheduler:
        return []
    return [
        {"id": j.id, "next_run": str(j.next_run_time) if j.next_run_time else "—"}
        for j in _scheduler.get_jobs()
    ]
