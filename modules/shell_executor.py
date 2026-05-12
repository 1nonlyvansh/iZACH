import re
import subprocess
import threading
import uuid
import logging
from modules.ws_bridge import broadcast

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 5000
TIMEOUT_SECONDS  = 30

# Patterns that are always blocked regardless of confirmation
_BLOCKED = [
    r'\bformat\s+[a-z]:\b',
    r'\bdel\s+/[sf]',
    r'\brmdir\s+/s',
    r'\bRemove-Item\b.{0,80}\b-Recurse\b.{0,40}\b-Force\b',
    r'\bRemove-Item\b.{0,80}\b-Force\b.{0,40}\b-Recurse\b',
    r'\brm\s+-[rf]{1,2}f?\b',
    r'\bnet\s+user\b.{0,60}\b/add\b',
    r'\bnet\s+user\b.{0,60}\bpassword\b',
    r'\breg\s+(delete|add)\b',
    r'\bbcdedit\b',
    r'\bdiskpart\b',
    r'\bcipher\s+/w\b',
    r'\bdd\s+if=\b',
    r'\bschtasks\b.{0,80}\b/create\b',
    r'\bSet-ExecutionPolicy\b.{0,40}\bUnrestricted\b',
    r'\bInvoke-Expression\b',
    r'\biex\b\s*[(\'"&]',
    r'\bDownloadString\b',
    r'\bStart-Process\b.{0,60}\bHidden\b',
]

_PENDING: dict[str, str] = {}  # id → command


def _is_dangerous(cmd: str) -> tuple[bool, str]:
    for pattern in _BLOCKED:
        if re.search(pattern, cmd, re.IGNORECASE | re.DOTALL):
            return True, pattern
    return False, ""


def request_confirmation(cmd: str) -> str:
    """Broadcast a shell_confirm_request and return the pending id."""
    exec_id = uuid.uuid4().hex[:8]
    _PENDING[exec_id] = cmd
    broadcast({"type": "shell_confirm", "state": "pending", "id": exec_id, "command": cmd})
    return exec_id


def run_confirmed(exec_id: str, speak_fn=None) -> tuple[bool, str]:
    """Execute a previously-confirmed pending command."""
    cmd = _PENDING.pop(exec_id, None)
    if cmd is None:
        return False, "No pending command with that id."
    return _execute(cmd, speak_fn=speak_fn)


def run_direct(cmd: str, speak_fn=None) -> tuple[bool, str]:
    """Execute without confirmation (voice already confirmed, or non-destructive)."""
    dangerous, pattern = _is_dangerous(cmd)
    if dangerous:
        msg = f"Blocked: command matches restricted pattern."
        broadcast({"type": "shell_confirm", "state": "blocked", "command": cmd})
        return False, msg
    return _execute(cmd, speak_fn=speak_fn)


def cancel_pending(exec_id: str):
    _PENDING.pop(exec_id, None)
    broadcast({"type": "shell_confirm", "state": "cancelled"})


def _execute(cmd: str, speak_fn=None) -> tuple[bool, str]:
    exec_id = uuid.uuid4().hex[:8]
    broadcast({"type": "shell_output", "id": exec_id, "command": cmd, "state": "running", "output": ""})

    output_buf = []

    def _run():
        total_chars = 0
        truncated   = False
        exit_code   = -1

        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )

            for line in proc.stdout:
                total_chars += len(line)
                if total_chars > MAX_OUTPUT_CHARS:
                    truncated = True
                    proc.kill()
                    break
                output_buf.append(line)
                broadcast({"type": "shell_output", "id": exec_id, "state": "streaming", "chunk": line})

            try:
                proc.wait(timeout=TIMEOUT_SECONDS)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                truncated = True
                exit_code = -1

        except Exception as e:
            output_buf.append(f"[error] {e}\n")
            broadcast({"type": "shell_output", "id": exec_id, "state": "streaming", "chunk": f"[error] {e}\n"})

        full_output = "".join(output_buf)
        if truncated:
            full_output += "\n[...output truncated — limit reached...]"

        broadcast({
            "type":      "shell_output",
            "id":        exec_id,
            "state":     "done",
            "exit_code": exit_code,
            "output":    full_output,
            "truncated": truncated,
        })

        if speak_fn:
            lines = [l.strip() for l in full_output.splitlines() if l.strip()]
            if not lines:
                speak_fn("Command finished with no output.")
            elif exit_code != 0 and not truncated:
                speak_fn(f"Command finished with exit code {exit_code}.")
            else:
                summary = " ".join(lines[:3])[:200]
                speak_fn(f"Done. {summary}")

    threading.Thread(target=_run, daemon=True).start()
    return True, f"Running command: {cmd}"
