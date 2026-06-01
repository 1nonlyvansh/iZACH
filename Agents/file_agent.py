"""
FileAgent — full LLM-driven handler for file operations, folder management,
document access, and clipboard.

Replaces/consolidates in command_chain.py:
  _handle_file_command()              — lines 1374-1698
  _FILE_FAST_PATH triggers block      — keyword routing to file handler
  awaiting_disambiguation state       — multi-match open/delete resolution

Intents handled:
  open_file         open file by name/search (smart find + disambiguation)
  find_file         search for a file by name/type
  latest_file       newest file in a folder (optionally by extension)
  read_file         read text content of a file
  delete_file       delete file (admin + disambiguation guard)
  rename_file       rename a file to a new name
  move_file         move file to another folder
  copy_file         copy file to another folder
  list_files        list contents of current/named folder
  create_folder     create a new folder
  navigate_up       go up one directory level
  current_location  where is iZACH currently browsing
  organize_folder   organize by file type into subfolders
  sort_folder       sort files by name/date/size/type
  folder_stats      file count and total size of folder
  file_log          recent file action log
  file_status       permission level and sandbox status
"""

from __future__ import annotations

import os
import re

# ── Folder map ────────────────────────────────────────────────────
_HOME = os.path.expanduser("~")
_FOLDER_MAP = {
    "desktop":    os.path.join(_HOME, "Desktop"),
    "documents":  os.path.join(_HOME, "Documents"),
    "downloads":  os.path.join(_HOME, "Downloads"),
    "pictures":   os.path.join(_HOME, "Pictures"),
    "music":      os.path.join(_HOME, "Music"),
    "videos":     os.path.join(_HOME, "Videos"),
    "wallpapers": os.path.join(_HOME, "Pictures", "Wallpapers"),
    "onedrive":   os.path.join(_HOME, "OneDrive"),
}

# ── Apps that belong to SystemAgent, not FileAgent ───────────────
_APP_OPEN_EXCEPTIONS = frozenset({
    "file explorer", "explorer", "notepad", "notepad++", "paint",
    "calculator", "control panel", "task manager", "wordpad",
})

# ── Ordinal words → 0-based index ────────────────────────────────
_ORDINALS = {
    "first": 0, "1st": 0, "one": 0, "1": 0,
    "second": 1, "2nd": 1, "two": 1, "2": 1,
    "third": 2, "3rd": 2, "three": 2, "3": 2,
    "fourth": 3, "4th": 3, "four": 3, "4": 3,
    "fifth": 4, "5th": 4, "five": 4, "5": 4,
}

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's file and folder command parser. Parse this voice command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "file_name": "<file/folder name or search query or null>",
  "new_name": "<new name for rename, or null>",
  "folder_name": "<desktop|documents|downloads|pictures|music|videos|wallpapers|onedrive|current or null>",
  "dest_folder": "<destination folder keyword for move/copy, or null>",
  "sort_by": "<name|date|size|type — default name>",
  "file_type": "<extension without dot e.g. pdf mp3 mp4 docx py or null>",
  "subject_hint": "<topic or keyword for smart search or null>"
}}

Intents (pick exactly one):
- open_file        : open/show/launch a specific file (NOT system apps)
- find_file        : search/find/locate a file by name or type
- latest_file      : latest/newest/most recent file (optionally by type)
- read_file        : read/show contents of a text file
- delete_file      : delete/remove a file
- rename_file      : rename a file to a new name
- move_file        : move a file to another folder
- copy_file        : copy a file to another folder
- list_files       : list/show files in a folder or current location
- create_folder    : create/make a new folder or directory
- navigate_up      : go up / back / parent folder
- current_location : where am I / current folder / which directory
- organize_folder  : organize/sort folder by file type into subfolders
- sort_folder      : sort/list files sorted by name/date/size/type
- folder_stats     : how many files / folder size / stats of a folder
- file_log         : recent actions / history / what did iZACH do with files
- file_status      : permission level / sandbox / file system status

Rules:
- folder_name: only these keywords (desktop/documents/downloads/pictures/music/videos/wallpapers/onedrive/current). "current" = current dir.
- dest_folder: same set as folder_name — destination for move/copy
- file_type: bare extension (pdf not .pdf)
- sort_by: default "name" if not specified
- subject_hint: only when user describes content not exact filename ("the assignment I wrote last week")
- Output ONLY the JSON object
"""


class FileAgent:
    """
    Handles all file/folder domain commands via LLM intent parsing.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak   = speak_fn
        self._raw_ai = raw_ai_fn
        self._pending_disambiguation: dict | None = None

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Route file command. Returns True if handled, False to fall through.
        """
        # Resolve pending multi-match first
        if self._pending_disambiguation:
            return self._resolve_disambiguation(cmd)

        # Bail for system apps — SystemAgent handles those
        cmd_lower = cmd.lower()
        for exc in _APP_OPEN_EXCEPTIONS:
            if exc in cmd_lower:
                return False

        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[FILE_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "open_file":       self._open_file,
            "find_file":       self._find_file,
            "latest_file":     self._latest_file,
            "read_file":       self._read_file,
            "delete_file":     self._delete_file,
            "rename_file":     self._rename_file,
            "move_file":       self._move_file,
            "copy_file":       self._copy_file,
            "list_files":      self._list_files,
            "create_folder":   self._create_folder,
            "navigate_up":     self._navigate_up,
            "current_location":self._current_location,
            "organize_folder": self._organize_folder,
            "sort_folder":     self._sort_folder,
            "folder_stats":    self._folder_stats,
            "file_log":        self._file_log,
            "file_status":     self._file_status,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        import json
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[FILE_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Helpers ───────────────────────────────────────────────────

    def _fm(self):
        from modules.file_manager import get_file_manager
        fm = get_file_manager()
        fm.set_speak(self.speak)
        return fm

    def _resolve_folder(self, key: str | None) -> str | None:
        """Map folder keyword to absolute path, or None if unrecognised."""
        if not key:
            return None
        k = key.lower().strip()
        if k == "current":
            return self._fm().current_dir
        return _FOLDER_MAP.get(k)

    def _pick_index(self, cmd: str) -> int | None:
        """Extract 0-based index from ordinal phrase in cmd."""
        lc = cmd.lower()
        for word, idx in _ORDINALS.items():
            if re.search(rf'\b{re.escape(word)}\b', lc):
                return idx
        return None

    # ── Disambiguation ────────────────────────────────────────────

    def _start_disambiguation(self, action: str, matches: list, original_cmd: str):
        self._pending_disambiguation = {
            "action":  action,
            "matches": matches,
            "original_cmd": original_cmd,
        }
        names = [os.path.basename(p) for p in matches[:5]]
        parts = [f"{i+1}. {n}" for i, n in enumerate(names)]
        self.speak(f"Found {len(names)} files. Which one? " + ", ".join(parts))

    def _resolve_disambiguation(self, cmd: str) -> bool:
        state   = self._pending_disambiguation
        matches = state["matches"]
        action  = state["action"]

        idx = self._pick_index(cmd)
        if idx is None:
            # Try partial name match
            lc = cmd.lower()
            for i, path in enumerate(matches):
                if os.path.basename(path).lower() in lc or lc in os.path.basename(path).lower():
                    idx = i
                    break

        if idx is None or idx >= len(matches):
            self.speak("I didn't catch which one. Say 'first', 'second', or the file name.")
            return True

        self._pending_disambiguation = None
        chosen = matches[idx]
        fm = self._fm()

        if action == "open":
            ok, msg = fm.handle_by_type(chosen)
            self.speak(msg)
        elif action == "delete":
            self._delete_with_face_auth(chosen)
        elif action == "read":
            ok, content = fm.read_text_file(chosen)
            self.speak(content if ok else content)
        return True

    # ── Handlers ─────────────────────────────────────────────────

    def _open_file(self, d: dict, cmd: str) -> bool:
        query = (d.get("file_name") or d.get("subject_hint") or "").strip()
        if not query:
            self.speak("Which file should I open?")
            return True

        fm = self._fm()
        self.speak(f"Searching for {query}.")
        matches = fm.smart_find(query, ai_func=self._raw_ai)

        if not matches:
            self.speak(f"Couldn't find a file matching '{query}'.")
            return True
        if len(matches) == 1:
            ok, msg = fm.handle_by_type(matches[0])
            self.speak(msg)
            return True

        self._start_disambiguation("open", matches, cmd)
        return True

    def _find_file(self, d: dict, cmd: str) -> bool:
        query     = (d.get("file_name") or "").strip()
        file_type = (d.get("file_type") or "").strip()
        if not query and not file_type:
            self.speak("What file should I search for?")
            return True

        fm = self._fm()
        results = fm.find_file(query or file_type, file_type=file_type or None)
        if not results:
            self.speak(f"No files found matching '{query or file_type}'.")
        elif len(results) == 1:
            self.speak(f"Found: {os.path.basename(results[0])} in {os.path.dirname(results[0])}")
        else:
            names = [os.path.basename(p) for p in results[:5]]
            self.speak(f"Found {len(results)} matches: " + ", ".join(names) + ".")
        return True

    def _latest_file(self, d: dict, cmd: str) -> bool:
        folder_key = d.get("folder_name")
        file_type  = (d.get("file_type") or "").strip()
        folder     = self._resolve_folder(folder_key) or self._fm().current_dir

        fm = self._fm()
        path = fm.get_latest_file(folder=folder, file_type=file_type or None)
        if not path:
            loc = os.path.basename(folder) or folder
            self.speak(f"No files found in {loc}.")
            return True

        info = fm.get_file_info(path)
        self.speak(
            f"Latest file: {info['name']}, {info['size_kb']} KB, "
            f"modified {info['modified']}."
        )
        return True

    def _read_file(self, d: dict, cmd: str) -> bool:
        query = (d.get("file_name") or "").strip()
        if not query:
            self.speak("Which file should I read?")
            return True

        fm      = self._fm()
        matches = fm.smart_find(query, ai_func=self._raw_ai)
        if not matches:
            self.speak(f"Couldn't find '{query}'.")
            return True
        if len(matches) == 1:
            ok, content = fm.read_text_file(matches[0])
            self.speak(content)
            return True

        self._start_disambiguation("read", matches, cmd)
        return True

    def _delete_file(self, d: dict, cmd: str) -> bool:
        query = (d.get("file_name") or "").strip()
        if not query:
            self.speak("Which file should I delete?")
            return True

        fm      = self._fm()
        matches = fm.find_file(query)
        if not matches:
            matches = fm.smart_find(query, ai_func=self._raw_ai)

        if not matches:
            self.speak(f"Couldn't find '{query}' to delete.")
            return True

        if len(matches) == 1:
            self._delete_with_face_auth(matches[0])
            return True

        self._start_disambiguation("delete", matches, cmd)
        return True

    def _delete_with_face_auth(self, filepath: str):
        """Run face verification, then delete on success. Mirrors command_chain path."""
        import threading as _thr
        try:
            from modules import face_auth
        except ImportError:
            # face_auth unavailable — fall back to password-gated delete
            fm = self._fm()
            ok, msg = fm.delete_file(filepath)
            self.speak(msg)
            return

        if not face_auth.is_enrolled():
            self.speak("Face auth is not set up. Say 'enroll my face' first, then try deleting again.")
            return

        import os as _os
        name = _os.path.basename(filepath)
        self.speak(f"Look at the camera to confirm deletion of {name}.")

        def _run():
            verified = face_auth.verify_owner()
            if verified:
                try:
                    fm = self._fm()
                    ok, msg = fm.delete_verified(filepath)
                    self.speak(f"Identity confirmed. {msg}")
                except Exception as e:
                    self.speak(f"Verified but delete failed: {e}")
            else:
                self.speak("Face not recognized. Deletion cancelled.")

        _thr.Thread(target=_run, daemon=True).start()

    def _rename_file(self, d: dict, cmd: str) -> bool:
        query    = (d.get("file_name") or "").strip()
        new_name = (d.get("new_name") or "").strip()
        if not query:
            self.speak("Which file should I rename?")
            return True
        if not new_name:
            self.speak(f"What should I rename {query} to?")
            return True

        fm      = self._fm()
        matches = fm.find_file(query)
        if not matches:
            self.speak(f"Couldn't find '{query}'.")
            return True

        ok, msg = fm.rename_file(matches[0], new_name)
        self.speak(msg)
        return True

    def _move_file(self, d: dict, cmd: str) -> bool:
        query      = (d.get("file_name") or "").strip()
        dest_key   = d.get("dest_folder")
        dest_path  = self._resolve_folder(dest_key)

        if not query:
            self.speak("Which file should I move?")
            return True
        if not dest_path:
            self.speak("Where should I move it? Say a folder like downloads, documents, desktop.")
            return True

        fm      = self._fm()
        matches = fm.find_file(query)
        if not matches:
            matches = fm.smart_find(query, ai_func=self._raw_ai)
        if not matches:
            self.speak(f"Couldn't find '{query}'.")
            return True

        ok, msg = fm.move_file(matches[0], dest_path)
        self.speak(msg)
        return True

    def _copy_file(self, d: dict, cmd: str) -> bool:
        query     = (d.get("file_name") or "").strip()
        dest_key  = d.get("dest_folder")
        dest_path = self._resolve_folder(dest_key)

        if not query:
            self.speak("Which file should I copy?")
            return True
        if not dest_path:
            self.speak("Where should I copy it to?")
            return True

        fm      = self._fm()
        matches = fm.find_file(query)
        if not matches:
            matches = fm.smart_find(query, ai_func=self._raw_ai)
        if not matches:
            self.speak(f"Couldn't find '{query}'.")
            return True

        ok, msg = fm.copy_file(matches[0], dest_path)
        self.speak(msg)
        return True

    def _list_files(self, d: dict, cmd: str) -> bool:
        folder_key = d.get("folder_name")
        folder     = self._resolve_folder(folder_key)

        fm = self._fm()
        ok, msg, items = fm.list_folder(folder)
        if not ok:
            self.speak(msg)
            return True

        if not items:
            self.speak(msg + " It's empty.")
            return True

        sample = items[:8]
        self.speak(msg + ". " + ", ".join(sample) + ("…" if len(items) > 8 else "") + ".")
        return True

    def _create_folder(self, d: dict, cmd: str) -> bool:
        name       = (d.get("file_name") or "").strip()
        folder_key = d.get("folder_name")
        base       = self._resolve_folder(folder_key) or self._fm().current_dir

        if not name:
            self.speak("What should I name the new folder?")
            return True

        path = os.path.join(base, name)
        fm   = self._fm()
        ok, msg = fm.create_folder(path)
        self.speak(msg)
        return True

    def _navigate_up(self, d: dict, cmd: str) -> bool:
        fm      = self._fm()
        ok, msg = fm.navigate("up")
        self.speak(msg)
        return True

    def _current_location(self, d: dict, cmd: str) -> bool:
        fm  = self._fm()
        loc = fm.where_am_i()
        self.speak(f"Currently browsing: {loc}")
        return True

    def _organize_folder(self, d: dict, cmd: str) -> bool:
        folder_key = d.get("folder_name")
        folder     = self._resolve_folder(folder_key) or self._fm().current_dir

        fm      = self._fm()
        ok, msg = fm.organize_by_type(folder)
        self.speak(msg)
        return True

    def _sort_folder(self, d: dict, cmd: str) -> bool:
        folder_key = d.get("folder_name")
        sort_by    = (d.get("sort_by") or "name").strip().lower()
        folder     = self._resolve_folder(folder_key) or self._fm().current_dir

        fm = self._fm()
        ok, msg, names = fm.sort_folder(folder, sort_by=sort_by)
        if not ok:
            self.speak(msg)
            return True

        sample = names[:8]
        self.speak(msg + " " + ", ".join(sample) + ("…" if len(names) > 8 else "") + ".")
        return True

    def _folder_stats(self, d: dict, cmd: str) -> bool:
        folder_key = d.get("folder_name")
        folder     = self._resolve_folder(folder_key)

        fm      = self._fm()
        ok, msg = fm.folder_stats(folder)
        self.speak(msg)
        return True

    def _file_log(self, d: dict, cmd: str) -> bool:
        fm      = self._fm()
        entries = fm.get_recent_actions(10)
        if not entries:
            self.speak("No recent file actions recorded.")
            return True
        self.speak(f"Last {len(entries)} file actions: " + "; ".join(entries[-5:]) + ".")
        return True

    def _file_status(self, d: dict, cmd: str) -> bool:
        fm     = self._fm()
        status = fm.get_status()
        parts  = [
            f"Permission level: {status['permission']}",
            f"Sandbox: {'on' if status['sandbox'] else 'off'}",
            f"Password: {'set' if status['password_set'] else 'not set'}",
            f"Current folder: {os.path.basename(status['current_dir']) or status['current_dir']}",
        ]
        self.speak(". ".join(parts) + ".")
        return True
