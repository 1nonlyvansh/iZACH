"""
Bidirectional mirror between the real project files and ~/izach-shared-brain.

Why this exists: Syncthing cannot scan ~/Desktop/Projects/iZACH directly on
this Mac (root cause undetermined — ruled out TCC/FDA, Unix perms, .stignore,
Syncthing version, reboot; the directory just silently scans as empty). Every
test against a folder outside ~/Desktop works correctly, so Syncthing is
pointed at ~/izach-shared-brain instead, and this script keeps that mirror in
sync with the real files by content hash, in both directions.

Only runs on macOS. Windows syncs its real project folder directly — it never
hit this bug, so it needs no mirror.
"""
import hashlib
import os
import shutil
import time

from modules.platform_utils import IS_MAC

REAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR_ROOT = os.path.expanduser("~/izach-shared-brain")

FLAT_FILES = [
    "smart_memory.json",
    "memory.json",
    "contacts.json",
    "wa_processed_msgs.json",
    "custom_links.json",
    "browser_history.json",
]
DIRS = ["iZACH-Brain", "logs"]

POLL_INTERVAL_S = 5


def _hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def _sync_file(real_path, mirror_path):
    real_hash = _hash(real_path)
    mirror_hash = _hash(mirror_path)
    if real_hash == mirror_hash:
        return
    if real_hash is None:
        return
    if mirror_hash is None:
        shutil.copy2(real_path, mirror_path)
        return
    real_mtime = os.path.getmtime(real_path)
    mirror_mtime = os.path.getmtime(mirror_path)
    if real_mtime >= mirror_mtime:
        shutil.copy2(real_path, mirror_path)
    else:
        shutil.copy2(mirror_path, real_path)


def _sync_dir(real_dir, mirror_dir):
    os.makedirs(mirror_dir, exist_ok=True)
    real_names = set(os.listdir(real_dir)) if os.path.isdir(real_dir) else set()
    mirror_names = set(os.listdir(mirror_dir))
    for name in real_names | mirror_names:
        if name.startswith("."):
            continue
        real_path = os.path.join(real_dir, name)
        mirror_path = os.path.join(mirror_dir, name)
        if os.path.isdir(real_path) or os.path.isdir(mirror_path):
            _sync_dir(real_path, mirror_path)
        else:
            _sync_file(real_path, mirror_path)


def sync_once():
    os.makedirs(MIRROR_ROOT, exist_ok=True)
    for name in FLAT_FILES:
        _sync_file(os.path.join(REAL_ROOT, name), os.path.join(MIRROR_ROOT, name))
    for name in DIRS:
        _sync_dir(os.path.join(REAL_ROOT, name), os.path.join(MIRROR_ROOT, name))


def run_forever():
    if not IS_MAC:
        return
    while True:
        try:
            sync_once()
        except Exception as e:
            print(f"[shared_brain_mirror] sync error: {e}")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run_forever()
