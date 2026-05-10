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
        _client = MongoClient("mongodb://127.0.0.1:27017/", serverSelectionTimeoutMS=2000)
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

def log_important_command(command: str, response: str, intent: str = ""):
    """Store only meaningful commands — skip small talk."""
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