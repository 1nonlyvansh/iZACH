USER_ID = "default_user"

"""
modules/mongo_brain.py
MongoDB integration for iZACH structured memory.
Local MongoDB only — no cloud.
"""

from datetime import datetime

from pymongo import MongoClient

_client = None
_db = None
_mongo_failed = False

def init_db():
    global _client, _db, _mongo_failed
    if _db is not None:
        return _db
    if _mongo_failed:
        return None
    try:
        _client = MongoClient("mongodb://127.0.0.1:27017/", serverSelectionTimeoutMS=2000, maxPoolSize=3)
        _client.server_info()
        _db = _client["izach"]
        print("[MONGO] Connected to MongoDB")
        return _db
    except Exception:
        _mongo_failed = True
        print("[MONGO] MongoDB not connected — memory disabled.")
        return None

def get_db():
    return init_db()


# ── COLLECTIONS ──────────────────────────────────────────────
# izach.profile    — user profile + preferences
# izach.context    — short-term context (entities, last_person etc.)
# izach.history    — important command history only


# ── USER PROFILE ─────────────────────────────────────────────

def save_preference(key: str, value):
    db = init_db()
    if db is None:
        return
    db.profile.update_one(
        {"_id": USER_ID},
        {"$set": {f"preferences.{key}": value, "updated_at": datetime.now()}},
        upsert=True
    )

store_preference = save_preference  # alias used by command_chain

def get_preference(key: str, default=None):
    db = init_db()
    if db is None:
        return default
    doc = db.profile.find_one({"_id": USER_ID})
    if not doc:
        return default
    return doc.get("preferences", {}).get(key, default)

def save_user_profile(name: str, preferences: dict = None):
    db = init_db()
    if db is None:
        return
    db.profile.update_one(
        {"_id": USER_ID},
        {"$set": {
            "name": name,
            "preferences": preferences or {},
            "updated_at": datetime.now()
        }},
        upsert=True
    )


# ── CONTEXT MEMORY ────────────────────────────────────────────

def store_context(key: str, value):
    """Store a context value (e.g., last_person, last_topic)."""
    db = init_db()
    if db is None:
        return
    db.context.update_one(
        {"_id": key},
        {"$set": {"value": value, "updated_at": datetime.now()}},
        upsert=True
    )

def retrieve_context(key: str, default=None):
    """Retrieve a context value by key."""
    db = init_db()
    if db is None:
        return default
    doc = db.context.find_one({"_id": key})
    return doc.get("value", default) if doc else default


# ── COMMAND HISTORY ───────────────────────────────────────────

def _history_enabled() -> bool:
    try:
        import json as _j
        with open("api_keys.json") as _f:
            return bool(_j.load(_f).get("command_history_enabled", True))
    except Exception:
        return True


def log_important_command(command: str, response: str, intent: str = ""):
    if not _history_enabled():
        return
    skip = ["hello", "hi", "okay", "thanks", "stop", "pause", "resume"]
    if len(command.strip()) < 5:
        return
    db = init_db()
    if db is None:
        return
    db.history.insert_one({
        "command":    command[:200],
        "response":   response[:200],
        "intent":     intent,
        "timestamp":  datetime.now()
    })


def cleanup_old_logs():
    try:
        import json as _j
        with open("api_keys.json") as _f:
            days = int(_j.load(_f).get("log_retention_days", 30))
    except Exception:
        days = 30
    if days == 0:
        return
    db = init_db()
    if db is None:
        return
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    result = db.history.delete_many({"timestamp": {"$lt": cutoff}})
    if result.deleted_count:
        print(f"[MONGO] Pruned {result.deleted_count} commands older than {days} days.")


def get_recent_history(limit: int = 10) -> list:
    db = init_db()
    if db is None:
        return []
    return list(db.history.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit))

def debug_insert():
    db = init_db()
    if db is None:
        print("[MONGO] Skipping debug insert — MongoDB not connected.")
        return
    db.history.insert_one({"msg": "Hello from iZACH!", "timestamp": datetime.now()})