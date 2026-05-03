import json
import os
import time

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory.json")

def load_memory() -> dict:
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_memory(data: dict):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

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
    return "Things iZACH remembers about Vansh:\n" + "\n".join(lines)

def list_memory() -> list:
    data = load_memory()
    result = []
    for k, v in data.items():
        if isinstance(v, dict):
            result.append((k, v.get("value", ""), v.get("added", "")))
        else:
            result.append((k, str(v), ""))
    return result