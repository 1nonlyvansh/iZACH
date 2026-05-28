# =============================================================================
# modules/file_manager.py
# iZACH File Access and Control System — Phase 1 + 2 + 3
# =============================================================================

import os
import json
import time
import shutil
import logging
import hashlib
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "file_manager_config.json")
LOG_FILE    = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "file_actions.log")

DEFAULT_CONFIG = {
    "permission_level": "balanced",   # safe | balanced | admin
    "sandbox_enabled": False,
    "sandbox_folder": os.path.expanduser("~/Documents/iZACH_Sandbox"),
    "protected_paths": [
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
    ],
    "password_hash": "",              # sha256 hash, empty = no password set
    "search_roots": [                 # Phase 3: where to search by default
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Pictures"),
        os.path.expanduser("~/Videos"),
        os.path.expanduser("~/Music"),
        os.path.expanduser("~/OneDrive"),
    ],
}

PERMISSION_LEVELS = {
    "safe":     {"read": True,  "create": False, "delete": False, "execute": False},
    "balanced": {"read": True,  "create": True,  "delete": False, "execute": False},
    "admin":    {"read": True,  "create": True,  "delete": True,  "execute": True},
}

# File types iZACH knows how to handle
FILE_TYPE_MAP = {
    ".pdf":  "document",
    ".txt":  "text",
    ".md":   "text",
    ".py":   "script",
    ".exe":  "executable",
    ".docx": "document",
    ".xlsx": "spreadsheet",
    ".pptx": "presentation",
    ".mp3":  "audio",
    ".mp4":  "video",
    ".jpg":  "image",
    ".jpeg": "image",
    ".png":  "image",
    ".zip":  "archive",
    ".rar":  "archive",
}

# ─────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
_action_logger = logging.getLogger("iZACH.FileManager")
if not _action_logger.handlers:
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    _action_logger.addHandler(_fh)
    _action_logger.setLevel(logging.DEBUG)


# =============================================================================
# Phase 2 — Password Manager
# =============================================================================

class PasswordManager:
    """Handles password confirmation for dangerous actions."""

    def __init__(self, config: dict):
        self._config = config
        self._confirmed = False
        self._confirm_expiry = 0
        self._confirm_ttl = 120  # seconds password confirmation stays valid
        self._failed_attempts = 0
        self._lockout_until = 0

    def is_set(self) -> bool:
        return bool(self._config.get("password_hash", ""))

    def set_password(self, password: str, config_save_fn):
        h = hashlib.sha256(password.encode()).hexdigest()
        self._config["password_hash"] = h
        config_save_fn()

    def verify(self, password: str) -> bool:
        stored = self._config.get("password_hash", "")
        if not stored:
            return True  # no password set = always allowed
        if time.time() < self._lockout_until:
            return False  # locked out
        h = hashlib.sha256(password.encode()).hexdigest()
        result = h == stored
        if result:
            self._failed_attempts = 0
            self._confirmed = True
            self._confirm_expiry = time.time() + self._confirm_ttl
        else:
            self._failed_attempts += 1
            if self._failed_attempts >= 5:
                self._lockout_until = time.time() + 60  # 60s lockout after 5 fails
                self._failed_attempts = 0
        return result

    def is_confirmed(self) -> bool:
        """Returns True if password was confirmed recently."""
        if not self.is_set():
            return True
        if self._confirmed and time.time() < self._confirm_expiry:
            return True
        self._confirmed = False
        return False

    def revoke(self):
        self._confirmed = False
        self._confirm_expiry = 0


# =============================================================================
# FileManager
# =============================================================================

class FileManager:
    def __init__(self):
        self.config = self._load_config()
        self.current_dir = os.path.expanduser("~")
        self.pwd_manager = PasswordManager(self.config)
        self._pending_action = None  # Phase 2: stores action awaiting password
        self._speak_func = None      # set from command_chain for password prompts

    def set_speak(self, fn):
        self._speak_func = fn

    def _speak(self, text):
        if self._speak_func:
            self._speak_func(text)

    # ─────────────────────────────────────────
    # Config
    # ─────────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            self._save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()

    def _save_config(self, config: dict = None):
        cfg = config or self.config
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    def reload_config(self):
        self.config = self._load_config()

    # ─────────────────────────────────────────
    # Permission helpers
    # ─────────────────────────────────────────

    def _can(self, action: str) -> bool:
        level = self.config.get("permission_level", "balanced")
        return PERMISSION_LEVELS.get(level, {}).get(action, False)

    def _is_protected(self, path: str) -> bool:
        try:
            abs_path = os.path.abspath(path).lower()
            for p in self.config.get("protected_paths", []):
                p_lower = p.lower().rstrip(os.sep)
                if abs_path == p_lower or abs_path.startswith(p_lower + os.sep):
                    return True
        except Exception:
            pass
        return False

    def _is_in_sandbox(self, path: str) -> bool:
        if not self.config.get("sandbox_enabled", False):
            return True
        sandbox = os.path.abspath(self.config.get("sandbox_folder", ""))
        return os.path.abspath(path).startswith(sandbox)

    def _log(self, action: str, path: str, result: str):
        _action_logger.info(f"{action.upper()} | {path} | {result}")

    # ─────────────────────────────────────────
    # Phase 2 — Dangerous action gate
    # ─────────────────────────────────────────

    def _requires_password(self, action: str) -> bool:
        """Delete and execute require password confirmation."""
        dangerous = ["delete", "execute", "overwrite"]
        return action in dangerous and self.pwd_manager.is_set()

    def confirm_password(self, password: str) -> tuple[bool, str]:
        """
        Called when user types password in UI.
        If confirmed, executes the pending action.
        """
        if not self.pwd_manager.verify(password):
            self._pending_action = None
            self._log("password", "confirm", "failed")
            return False, "Wrong password. Action cancelled."

        if self._pending_action:
            action_fn, args = self._pending_action
            self._pending_action = None
            return action_fn(*args)

        return True, "Password confirmed."

    def _queue_dangerous(self, action_fn, args, action_name: str) -> tuple[bool, str]:
        """Queue a dangerous action for password confirmation."""
        if self.pwd_manager.is_confirmed():
            return action_fn(*args)
        self._pending_action = (action_fn, args)
        return False, f"PASSWORD_REQUIRED:{action_name}"

    # ─────────────────────────────────────────
    # PHASE 1 — Core Operations
    # ─────────────────────────────────────────

    def open_file(self, path: str) -> tuple[bool, str]:
        if not self._can("read"):
            return False, "Permission denied. Current level is safe."
        if self._is_protected(path):
            return False, "That path is protected."
        if not self._is_in_sandbox(path):
            return False, "Sandbox mode is on. File is outside sandbox."
        if not os.path.exists(path):
            return False, f"File not found."

        ext = Path(path).suffix.lower()
        ftype = FILE_TYPE_MAP.get(ext, "file")

        if ftype == "executable" and not self._can("execute"):
            return self._queue_dangerous(self._do_open, [path], "execute executable")

        try:
            os.startfile(path)
            self._log("open", path, "success")
            return True, f"Opened {os.path.basename(path)}."
        except Exception as e:
            self._log("open", path, f"error: {e}")
            return False, f"Could not open: {e}"

    def _do_open(self, path: str) -> tuple[bool, str]:
        try:
            os.startfile(path)
            self._log("execute", path, "success")
            return True, f"Executed {os.path.basename(path)}."
        except Exception as e:
            return False, f"Could not execute: {e}"

    def create_folder(self, path: str) -> tuple[bool, str]:
        if not self._can("create"):
            return False, "Permission denied. Need balanced or admin level."
        if self._is_protected(path):
            return False, "Cannot create folders in protected paths."
        if not self._is_in_sandbox(path):
            return False, "Sandbox mode on. Cannot create outside sandbox."
        try:
            os.makedirs(path, exist_ok=True)
            self._log("create_folder", path, "success")
            return True, f"Folder created: {os.path.basename(path)}"
        except Exception as e:
            self._log("create_folder", path, f"error: {e}")
            return False, f"Could not create folder: {e}"

    def delete_file(self, path: str) -> tuple[bool, str]:
        """Delete a file — requires admin + password."""
        if not self._can("delete"):
            return False, "Permission denied. Need admin level to delete files."
        if self._is_protected(path):
            return False, "Cannot delete from protected paths."
        if not self._is_in_sandbox(path):
            return False, "Sandbox mode on. Cannot delete outside sandbox."
        if not os.path.exists(path):
            return False, "File not found."
        return self._queue_dangerous(self._do_delete, [path], "delete")

    def delete_verified(self, path: str) -> tuple[bool, str]:
        """Delete after face verification has already passed — skips permission/password checks."""
        if self._is_protected(path):
            return False, "That path is protected and cannot be deleted."
        if not os.path.exists(path):
            return False, "File not found."
        return self._do_delete(path)

    def _do_delete(self, path: str) -> tuple[bool, str]:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self._log("delete", path, "success")
            return True, f"Deleted {os.path.basename(path)}."
        except Exception as e:
            self._log("delete", path, f"error: {e}")
            return False, f"Could not delete: {e}"

    def list_folder(self, path: str = None) -> tuple[bool, str, list]:
        target = path or self.current_dir
        if not self._can("read"):
            return False, "Permission denied.", []
        if self._is_protected(target):
            return False, "That path is protected.", []
        if not os.path.isdir(target):
            return False, f"Not a folder: {target}", []
        try:
            items = os.listdir(target)
            folders = sorted([i for i in items if os.path.isdir(os.path.join(target, i))])
            files   = sorted([i for i in items if os.path.isfile(os.path.join(target, i))])
            self.current_dir = target
            self._log("list", target, f"{len(items)} items")
            return True, f"{len(folders)} folders, {len(files)} files in {os.path.basename(target) or target}", folders + files
        except Exception as e:
            return False, f"Could not list folder: {e}", []

    def navigate(self, direction: str) -> tuple[bool, str]:
        if direction == "up":
            parent = str(Path(self.current_dir).parent)
            if parent == self.current_dir:
                return False, "Already at the root."
            self.current_dir = parent
            return True, f"Now in {os.path.basename(parent) or parent}"
        else:
            target = os.path.join(self.current_dir, direction)
            if os.path.isdir(target):
                self.current_dir = target
                return True, f"Navigated into {direction}"
            return False, f"Folder '{direction}' not found here."

    def read_text_file(self, path: str, max_chars: int = 600) -> tuple[bool, str]:
        if not self._can("read"):
            return False, "Permission denied."
        if self._is_protected(path):
            return False, "That path is protected."
        if not os.path.exists(path):
            return False, "File not found."
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(max_chars)
            self._log("read", path, "success")
            if len(content) == max_chars:
                content += "... (truncated)"
            return True, content
        except Exception as e:
            return False, f"Could not read file: {e}"

    def where_am_i(self) -> str:
        return self.current_dir

    # ─────────────────────────────────────────
    # PHASE 3 — Smart Search & Understanding
    # ─────────────────────────────────────────

    def smart_find(self, query: str, ai_func=None) -> list:
        """
        Phase 3 smart search.
        Uses AI to extract filename/type hints from natural language,
        then searches across configured search roots.
        Returns list of matching paths.
        """
        name_hint = query
        type_hint = None

        # Extract file type from query
        for ext, ftype in FILE_TYPE_MAP.items():
            if ftype in query.lower() or ext.strip(".") in query.lower():
                type_hint = ext.strip(".")
                break

        # Use AI to extract a cleaner filename if available
        if ai_func:
            try:
                prompt = f"""Extract the file name or topic the user is looking for from this query: "{query}"
Reply with ONLY the search term — 1-5 words, no punctuation, no explanation.
Example: "Time Series Analysis" or "assignment notes" or "handwritten notes"."""
                name_hint = ai_func(prompt).strip().strip('"').strip("'")
            except Exception:
                pass

        roots = self.config.get("search_roots", [os.path.expanduser("~")])
        results = []

        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for dirpath, dirs, files in os.walk(root):
                    if self._is_protected(dirpath):
                        dirs.clear()
                        continue
                    for fname in files:
                        name_lower = fname.lower()
                        query_lower = name_hint.lower()
                        words = [w for w in query_lower.split() if len(w) >= 3]
                        if words:
                            match = all(word in name_lower for word in words)
                        else:
                            match = query_lower in name_lower
                        if type_hint and not fname.lower().endswith(f".{type_hint}"):
                            match = False
                        if match:
                            full = os.path.join(dirpath, fname)
                            results.append(full)
                        if len(results) >= 15:
                            break
            except PermissionError:
                continue

        # If multiple results, re-rank using full-path semantic scoring against
        # the ORIGINAL query (includes folder hints like "Unit 3", "Time Series").
        # This resolves "Assignment.pdf" ambiguity across 15 different folders.
        if len(results) > 1 and query != name_hint:
            reranked = self.smart_find_file(query)
            if reranked:
                # Prefer path-scored results; append any filename-only matches not in it
                seen = set(reranked)
                reranked += [r for r in results if r not in seen]
                return reranked[:5]

        return results

    def find_file(self, name: str, search_dir: str = None, file_type: str = None) -> list:
        """Simple name-based search."""
        roots = [search_dir] if search_dir else self.config.get(
            "search_roots", [os.path.expanduser("~")]
        )
        results = []
        name_lower = name.lower()
        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for dirpath, dirs, files in os.walk(root):
                    if self._is_protected(dirpath):
                        dirs.clear()
                        continue
                    for fname in files:
                        match = name_lower in fname.lower()
                        if file_type and not fname.lower().endswith(f".{file_type.lower()}"):
                            match = False
                        if match:
                            results.append(os.path.join(dirpath, fname))
                        if len(results) >= 10:
                            return results
            except PermissionError:
                continue
        return results

    def smart_find_file(self, query: str, search_dir: str = None) -> list:
        """
        Semantic path resolver — tokenize query, score file paths by token matches.
        "Time Series Unit 3 Assignment" → best-matching file returned first.
        Falls back to find_file() if no tokens survive stop-word stripping.
        """
        import re as _re

        STOP = {
            "the", "a", "an", "in", "of", "for", "and", "or", "my", "me",
            "file", "open", "show", "find", "get", "please", "can", "you",
            "to", "is", "it", "this", "that", "from", "with", "send", "print",
        }
        raw = _re.findall(r'[a-zA-Z0-9]+', query.lower())
        tokens = [t for t in raw if t not in STOP]

        if not tokens:
            return self.find_file(query, search_dir)

        roots = [search_dir] if search_dir else self.config.get(
            "search_roots", [os.path.expanduser("~")]
        )
        scored: list[tuple[float, str]] = []

        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for dirpath, dirs, files in os.walk(root):
                    if self._is_protected(dirpath):
                        dirs.clear()
                        continue
                    for fname in files:
                        full_path = os.path.join(dirpath, fname)
                        path_lower = full_path.lower()

                        # Base score: fraction of tokens present anywhere in path
                        base_match = sum(1 for t in tokens if t in path_lower)
                        if base_match == 0:
                            continue

                        # Bonus: whole-word boundary matches (e.g. "unit" not inside "unitary")
                        word_bonus = sum(
                            0.2 for t in tokens
                            if _re.search(r'(?<![a-z0-9])' + _re.escape(t) + r'(?![a-z0-9])', path_lower)
                        )

                        score = (base_match + word_bonus) / len(tokens)
                        scored.append((score, full_path))
            except PermissionError:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)

        # Clear winner (≥80% tokens matched with bonuses) → return just top 1
        if scored and scored[0][0] >= 0.8:
            return [scored[0][1]]
        # Ambiguous → return top 5 for user to choose
        return [path for _, path in scored[:5]]

    def get_latest_file(self, folder: str = None, file_type: str = None) -> Optional[str]:
        base = folder or self.current_dir
        try:
            files = []
            for f in os.listdir(base):
                full = os.path.join(base, f)
                if not os.path.isfile(full):
                    continue
                if file_type and not f.lower().endswith(f".{file_type.lower()}"):
                    continue
                files.append((os.path.getmtime(full), full))
            if files:
                return sorted(files, reverse=True)[0][1]
        except Exception:
            pass
        return None

    def get_file_info(self, path: str) -> dict:
        """Return metadata about a file."""
        if not os.path.exists(path):
            return {}
        stat = os.stat(path)
        ext = Path(path).suffix.lower()
        return {
            "name": os.path.basename(path),
            "type": FILE_TYPE_MAP.get(ext, "unknown"),
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "path": path,
        }

    def handle_by_type(self, path: str) -> tuple[bool, str]:
        """
        Phase 3: Open/handle a file intelligently based on its type.
        txt/md → read and speak
        pdf/docx → open with default app
        py → execute if admin
        exe → queue with password
        """
        if not os.path.exists(path):
            return False, "File not found."

        ext = Path(path).suffix.lower()
        ftype = FILE_TYPE_MAP.get(ext, "file")

        if ftype == "text":
            ok, content = self.read_text_file(path)
            return ok, content

        elif ftype in ("document", "spreadsheet", "presentation", "image", "audio", "video"):
            return self.open_file(path)

        elif ftype == "script":
            if not self._can("execute"):
                return False, "Need admin permission to execute scripts."
            return self._queue_dangerous(self._do_run_script, [path], "execute script")

        elif ftype == "executable":
            if not self._can("execute"):
                return False, "Need admin permission to run executables."
            return self._queue_dangerous(self._do_open, [path], "execute")

        else:
            return self.open_file(path)

    def _do_run_script(self, path: str) -> tuple[bool, str]:
        import subprocess
        try:
            subprocess.Popen(["python", path])
            self._log("execute_script", path, "success")
            return True, f"Running {os.path.basename(path)}."
        except Exception as e:
            return False, f"Could not run script: {e}"

    # ─────────────────────────────────────────
    # PHASE 4 — Folder Management
    # ─────────────────────────────────────────

    _TYPE_FOLDERS = {
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pptx", ".xlsx", ".csv", ".xls"],
        "Images":    [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff", ".raw"],
        "Videos":    [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "Music":     [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
        "Archives":  [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        "Scripts":   [".py", ".js", ".ts", ".sh", ".bat", ".ps1", ".java", ".cpp", ".c", ".html", ".css"],
        "Executables": [".exe", ".msi", ".apk"],
    }

    def sort_folder(self, path: str, sort_by: str = "name") -> tuple[bool, str, list]:
        """Return files in a folder sorted by name/date/size/type."""
        if not self._can("read"):
            return False, "Permission denied.", []
        target = os.path.expandvars(os.path.expanduser(path))
        if not os.path.isdir(target):
            return False, f"Folder not found: {path}", []
        try:
            items = [os.path.join(target, f) for f in os.listdir(target)
                     if os.path.isfile(os.path.join(target, f))]
            if sort_by == "date":
                items.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            elif sort_by == "size":
                items.sort(key=lambda x: os.path.getsize(x), reverse=True)
            elif sort_by == "type":
                items.sort(key=lambda x: Path(x).suffix.lower())
            else:
                items.sort(key=lambda x: os.path.basename(x).lower())
            names = [os.path.basename(f) for f in items]
            self._log("sort", target, f"by {sort_by}, {len(items)} files")
            return True, f"Sorted {len(items)} files by {sort_by}.", names
        except Exception as e:
            return False, f"Could not sort folder: {e}", []

    def organize_by_type(self, path: str) -> tuple[bool, str]:
        """Move files in a folder into type-based subfolders (Documents, Images, etc.)."""
        if not self._can("create"):
            return False, "Permission denied. Need balanced or admin level."
        target = os.path.expandvars(os.path.expanduser(path))
        if not os.path.isdir(target):
            return False, f"Folder not found: {path}"
        moved, skipped, failed = 0, 0, []
        for fname in os.listdir(target):
            src = os.path.join(target, fname)
            if not os.path.isfile(src):
                continue
            ext = Path(src).suffix.lower()
            dest_cat = "Other"
            for cat, exts in self._TYPE_FOLDERS.items():
                if ext in exts:
                    dest_cat = cat
                    break
            dest_dir = os.path.join(target, dest_cat)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, fname)
            if os.path.exists(dest):
                skipped += 1
                continue
            try:
                shutil.move(src, dest)
                moved += 1
            except Exception:
                failed.append(fname)
        self._log("organize", target, f"moved={moved} skipped={skipped}")
        msg = f"Organized {moved} files into type folders."
        if skipped:
            msg += f" {skipped} already existed, skipped."
        if failed:
            msg += f" {len(failed)} failed to move."
        return True, msg

    def rename_file(self, path: str, new_name: str) -> tuple[bool, str]:
        """Rename a file or folder."""
        if not self._can("create"):
            return False, "Permission denied."
        if not os.path.exists(path):
            return False, "File not found."
        if self._is_protected(path):
            return False, "That path is protected."
        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            return False, f"A file named {new_name} already exists there."
        try:
            os.rename(path, new_path)
            self._log("rename", path, f"→ {new_name}")
            return True, f"Renamed to {new_name}."
        except Exception as e:
            return False, f"Could not rename: {e}"

    def move_file(self, src: str, dest_folder: str) -> tuple[bool, str]:
        """Move a file to a destination folder."""
        if not self._can("create"):
            return False, "Permission denied."
        if not os.path.exists(src):
            return False, "File not found."
        if self._is_protected(src):
            return False, "That path is protected."
        if not os.path.isdir(dest_folder):
            return False, f"Destination folder not found: {dest_folder}"
        dest = os.path.join(dest_folder, os.path.basename(src))
        if os.path.exists(dest):
            return False, f"A file with that name already exists in {os.path.basename(dest_folder)}."
        try:
            shutil.move(src, dest)
            self._log("move", src, f"→ {dest_folder}")
            return True, f"Moved {os.path.basename(src)} to {os.path.basename(dest_folder)}."
        except Exception as e:
            return False, f"Could not move: {e}"

    def copy_file(self, src: str, dest_folder: str) -> tuple[bool, str]:
        """Copy a file to a destination folder."""
        if not self._can("create"):
            return False, "Permission denied."
        if not os.path.exists(src):
            return False, "File not found."
        try:
            os.makedirs(dest_folder, exist_ok=True)
            dest = os.path.join(dest_folder, os.path.basename(src))
            shutil.copy2(src, dest)
            self._log("copy", src, f"→ {dest_folder}")
            return True, f"Copied {os.path.basename(src)} to {os.path.basename(dest_folder)}."
        except Exception as e:
            return False, f"Could not copy: {e}"

    def folder_stats(self, path: str = None) -> tuple[bool, str]:
        """Get file count and total size of a folder (non-recursive)."""
        target = os.path.expandvars(os.path.expanduser(path or self.current_dir))
        if not os.path.isdir(target):
            return False, "Folder not found."
        try:
            total_size, file_count, folder_count = 0, 0, 0
            for entry in os.scandir(target):
                if entry.is_file():
                    file_count += 1
                    total_size += entry.stat().st_size
                elif entry.is_dir():
                    folder_count += 1
            mb = total_size / 1024 / 1024
            size_str = f"{mb:.1f} MB" if mb >= 1 else f"{total_size / 1024:.1f} KB"
            name = os.path.basename(target) or target
            return True, f"{name} has {file_count} files and {folder_count} subfolders, using {size_str}."
        except Exception as e:
            return False, f"Could not read folder stats: {e}"

    # ─────────────────────────────────────────
    # Phase 2 — Logging helpers
    # ─────────────────────────────────────────

    def get_recent_actions(self, n: int = 10) -> list:
        """Return last n lines from the action log."""
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [l.strip() for l in lines[-n:]]
        except Exception:
            return []

    # ─────────────────────────────────────────
    # Settings helpers
    # ─────────────────────────────────────────

    def set_permission(self, level: str) -> bool:
        if level not in PERMISSION_LEVELS:
            return False
        self.config["permission_level"] = level
        self._save_config()
        return True

    def set_sandbox(self, enabled: bool, folder: str = None):
        self.config["sandbox_enabled"] = enabled
        if folder:
            self.config["sandbox_folder"] = folder
            os.makedirs(folder, exist_ok=True)
        self._save_config()

    def add_protected_path(self, path: str):
        if path not in self.config["protected_paths"]:
            self.config["protected_paths"].append(path)
            self._save_config()

    def remove_protected_path(self, path: str):
        if path in self.config["protected_paths"]:
            self.config["protected_paths"].remove(path)
            self._save_config()

    def add_search_root(self, path: str):
        if path not in self.config.get("search_roots", []):
            self.config.setdefault("search_roots", []).append(path)
            self._save_config()

    def get_status(self) -> dict:
        return {
            "permission": self.config.get("permission_level", "balanced"),
            "sandbox": self.config.get("sandbox_enabled", False),
            "sandbox_folder": self.config.get("sandbox_folder", ""),
            "current_dir": self.current_dir,
            "protected_count": len(self.config.get("protected_paths", [])),
            "password_set": self.pwd_manager.is_set(),
            "search_roots": self.config.get("search_roots", []),
        }


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────
_fm = None

def get_file_manager() -> FileManager:
    global _fm
    if _fm is None:
        _fm = FileManager()
    return _fm