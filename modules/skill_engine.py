"""
modules/skill_engine.py
iZACH Skill Engine

Skills are .md files in the skills/ directory.
Activated via #skill-id prefix in user input.
Each skill injects a system-prompt extension + optional model preference.
Generated code files are saved to C:/iZACH-Projects/<ProjectName>/
"""

from __future__ import annotations
import os, re, json, shutil
from datetime import datetime
from pathlib import Path

ROOT         = os.path.dirname(os.path.dirname(__file__))
SKILLS_DIR   = os.path.join(ROOT, "skills")
PROJECTS_DIR = "C:/iZACH-Projects"
STATS_FILE   = os.path.join(SKILLS_DIR, ".stats.json")

os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)


# ── Frontmatter parser ────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from .md. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text.strip()
    fm_raw = text[3:end].strip()
    body   = text[end + 4:].strip()
    meta: dict = {}
    for line in fm_raw.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.lower() == "true":
            v = True
        elif v.lower() == "false":
            v = False
        meta[k] = v
    return meta, body


# ── Stats ─────────────────────────────────────────────────────────────────────

def _load_stats() -> dict:
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_stats(stats: dict):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


def _track_usage(skill_id: str):
    stats = _load_stats()
    e = stats.get(skill_id, {"use_count": 0, "last_used": ""})
    e["use_count"] += 1
    e["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats[skill_id] = e
    _save_stats(stats)


# ── Core skill operations ─────────────────────────────────────────────────────

def list_skills() -> list[dict]:
    """Return metadata for all installed skills."""
    skills = []
    stats  = _load_stats()
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(SKILLS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta, _ = _parse_frontmatter(text)
            sid = meta.get("id") or fname.replace(".md", "")
            s = stats.get(sid, {})
            skills.append({
                "id":           sid,
                "name":         meta.get("name", sid),
                "description":  meta.get("description", ""),
                "version":      meta.get("version", "1.0"),
                "author":       meta.get("author", "community"),
                "tags":         meta.get("tags", []),
                "icon":         meta.get("icon", "⚡"),
                "model":        meta.get("model", "auto"),
                "creates_files": bool(meta.get("creates_files", False)),
                "size_kb":      round(os.path.getsize(path) / 1024, 1),
                "use_count":    s.get("use_count", 0),
                "last_used":    s.get("last_used", ""),
                "file":         fname,
            })
        except Exception as e:
            print(f"[SkillEngine] Parse error {fname}: {e}")
    return skills


def get_skill(skill_id: str) -> dict | None:
    return next((s for s in list_skills() if s["id"] == skill_id), None)


def load_skill_content(skill_id: str) -> tuple[dict, str] | None:
    """Return (meta, body) for a skill id, or None."""
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".md"):
            continue
        try:
            with open(os.path.join(SKILLS_DIR, fname), encoding="utf-8") as f:
                text = f.read()
            meta, body = _parse_frontmatter(text)
            if (meta.get("id") or fname.replace(".md", "")) == skill_id:
                return meta, body
        except Exception:
            pass
    return None


def detect_skill(text: str) -> tuple[str | None, str]:
    """
    Detect #skill-id prefix in user input.
    Returns (skill_id, cleaned_text_without_prefix).
    """
    m = re.match(r'^#([\w\-]+)\s*(.*)', text.strip(), re.DOTALL)
    if not m:
        return None, text
    return m.group(1).lower(), m.group(2).strip()


def build_skill_context(skill_id: str, user_message: str) -> tuple[str, str, dict]:
    """
    Load skill, build system prompt addition, detect project name.
    Returns (system_addition, possibly_modified_user_message, skill_meta).
    """
    result = load_skill_content(skill_id)
    if not result:
        print(f"[SkillEngine] Skill not found: {skill_id}")
        return "", user_message, {}

    meta, body = result
    project_name = ""

    if meta.get("creates_files"):
        project_name = extract_project_name(user_message)
        project_ctx = (
            f"\n\n## File Output Instructions\n"
            f"When generating code files, start each file's code block with its filename on the opening fence line:\n"
            f"```html index.html\n(content)\n```\n"
            f"```css style.css\n(content)\n```\n"
            f"```js script.js\n(content)\n```\n"
            f"Project name: **{project_name}**\n"
            f"Output path: C:/iZACH-Projects/{project_name}/\n"
            f"Generate ALL necessary files — do not omit any."
        )
        body = body + project_ctx

    system_addition = (
        f"[ACTIVE SKILL: {meta.get('name', skill_id)} v{meta.get('version','1.0')}]\n\n"
        f"{body}"
    )

    _track_usage(skill_id)
    return system_addition, user_message, meta


# ── Project file saving ───────────────────────────────────────────────────────

def save_project_files(response_text: str, project_name: str) -> list[str]:
    """
    Parse fenced code blocks from AI response and save files.
    Detects:  ```html index.html   or   ```css style.css   etc.
    Falls back to lang-based default filenames.
    Returns list of absolute paths of saved files.
    """
    if not project_name:
        return []

    project_dir = os.path.join(PROJECTS_DIR, project_name)
    os.makedirs(project_dir, exist_ok=True)
    saved: list[str] = []

    # Primary: explicit filename on fence line → ```lang filename.ext
    primary_pat = re.compile(
        r'```[\w]*\s+([\w\-\.\/]+\.\w+)\s*\n(.*?)```',
        re.DOTALL
    )
    used_names: set[str] = set()

    for m in primary_pat.finditer(response_text):
        raw_fname = m.group(1).strip()
        content   = m.group(2).rstrip()
        # Safety — no directory traversal
        fname = os.path.basename(raw_fname)
        if not fname or ".." in fname:
            continue
        filepath = os.path.join(project_dir, fname)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            saved.append(filepath)
            used_names.add(fname)
        except Exception as e:
            print(f"[SkillEngine] Save error {fname}: {e}")

    # Fallback: ```lang\ncode``` → guess filename from language
    if not saved:
        _EXT = {
            "html": "index.html", "css": "style.css",
            "javascript": "script.js", "js": "script.js",
            "python": "main.py", "py": "main.py",
            "java": "Main.java", "c": "main.c",
            "cpp": "main.cpp", "ts": "main.ts",
            "sql": "query.sql", "bash": "run.sh",
            "json": "data.json", "xml": "data.xml",
        }
        fallback_pat = re.compile(r'```(\w+)\n(.*?)```', re.DOTALL)
        for m in fallback_pat.finditer(response_text):
            lang    = m.group(1).lower()
            content = m.group(2).rstrip()
            fname   = _EXT.get(lang, f"output.{lang}")
            if fname in used_names:
                continue
            filepath = os.path.join(project_dir, fname)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                saved.append(filepath)
                used_names.add(fname)
            except Exception as e:
                print(f"[SkillEngine] Save error {fname}: {e}")

    if saved:
        print(f"[SkillEngine] Saved {len(saved)} file(s) → {project_dir}")
    return saved


def extract_project_name(user_message: str) -> str:
    """Derive a clean project folder name from user message."""
    # Patterns: "make a calculator", "build todo app", "create snake game"
    m = re.search(
        r'(?:make|build|create|write|generate|develop)\s+(?:a|an|the)?\s+([\w\s]+?)(?:\s+(?:using|in|with|for)|$)',
        user_message.lower()
    )
    if m:
        name = m.group(1).strip()
        parts = name.split()[:4]
        return "-".join(w.capitalize() for w in parts)
    # Fallback: first 3 words
    words = re.findall(r'\w+', user_message)[:3]
    return "-".join(w.capitalize() for w in words) if words else "Project"


# ── Skill management ──────────────────────────────────────────────────────────

def import_skill(src_path: str) -> dict | None:
    """Copy .md skill file into skills/ directory."""
    try:
        fname = os.path.basename(src_path)
        if not fname.endswith(".md"):
            return {"error": "File must be a .md file"}
        dst = os.path.join(SKILLS_DIR, fname)
        shutil.copy2(src_path, dst)
        with open(dst, encoding="utf-8") as f:
            text = f.read()
        meta, _ = _parse_frontmatter(text)
        return meta
    except Exception as e:
        return {"error": str(e)}


def import_skill_from_text(name: str, content: str) -> bool:
    """Save skill content directly to skills/ directory."""
    try:
        # Generate safe filename from name
        safe = re.sub(r'[^\w\-]', '-', name.lower()).strip('-')
        fname = f"{safe}.md"
        with open(os.path.join(SKILLS_DIR, fname), "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"[SkillEngine] Import text error: {e}")
        return False


def delete_skill(skill_id: str) -> bool:
    """Remove skill file by id."""
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(SKILLS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta, _ = _parse_frontmatter(text)
            if (meta.get("id") or fname.replace(".md", "")) == skill_id:
                os.remove(path)
                return True
        except Exception:
            pass
    return False


def update_skill_model(skill_id: str, model: str) -> bool:
    """Update model preference in skill .md frontmatter."""
    valid_models = {"auto", "groq", "gemini", "deepseek"}
    if model not in valid_models:
        return False
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(SKILLS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta, body = _parse_frontmatter(text)
            if (meta.get("id") or fname.replace(".md", "")) != skill_id:
                continue
            # Update or insert model line in frontmatter
            if re.search(r'^model:', text, re.MULTILINE):
                new_text = re.sub(r'^model:\s*.+$', f'model: {model}', text, flags=re.MULTILINE)
            else:
                # Insert model before closing ---
                new_text = re.sub(r'(\n---\n)', f'\nmodel: {model}\\1', text, count=1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            return True
        except Exception as e:
            print(f"[SkillEngine] Model update error {fname}: {e}")
    return False


# ── Projects ──────────────────────────────────────────────────────────────────

def list_projects() -> list[dict]:
    """List all generated projects in C:/iZACH-Projects/"""
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        return []
    for name in sorted(os.listdir(PROJECTS_DIR)):
        full = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(full):
            continue
        try:
            files = [f for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))]
            size  = sum(os.path.getsize(os.path.join(full, f)) for f in files)
            projects.append({
                "name":       name,
                "path":       full,
                "files":      files,
                "file_count": len(files),
                "size_kb":    round(size / 1024, 1),
            })
        except Exception:
            pass
    return projects


def open_project_folder(project_name: str) -> bool:
    """Open project folder in Windows Explorer."""
    path = os.path.join(PROJECTS_DIR, project_name)
    if not os.path.exists(path):
        return False
    try:
        import subprocess
        subprocess.Popen(f'explorer "{path}"')
        return True
    except Exception:
        return False
