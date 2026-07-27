import json
import os
import time

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory.json")

_mem_cache: dict | None = None
_cache_dirty = True


def load_memory() -> dict:
    global _mem_cache, _cache_dirty
    if not _cache_dirty and _mem_cache is not None:
        return _mem_cache
    try:
        with open(MEMORY_FILE, "r") as f:
            _mem_cache = json.load(f)
    except Exception:
        _mem_cache = {}
    _cache_dirty = False
    return _mem_cache


def save_memory(data: dict):
    global _mem_cache, _cache_dirty
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)
    _mem_cache = data
    _cache_dirty = False

def add_memory(key: str, value: str):
    data = load_memory()
    data[key] = {"value": value, "added": time.strftime("%Y-%m-%d %H:%M")}
    save_memory(data)

def remove_memory(key: str) -> bool:
    data = load_memory()
    if key in data:
        del data[key]
        save_memory(data)
        return True
    return False

def get_memory_as_context() -> str:
    data = load_memory()
    if not data:
        return ""
    lines = []
    for k, v in data.items():
        val = v["value"] if isinstance(v, dict) else str(v)
        lines.append(f"- {k}: {val}")
    owner = os.getenv("OWNER_NAME", "User")
    return f"Things iZACH remembers about {owner}:\n" + "\n".join(lines)

def list_memory() -> list:
    data = load_memory()
    result = []
    for k, v in data.items():
        if isinstance(v, dict):
            result.append((k, v.get("value", ""), v.get("added", "")))
        else:
            result.append((k, str(v), ""))
    return result