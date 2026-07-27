"""Shared platform-detection constants and helpers for Windows/macOS cross-platform code."""
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def run_applescript(script: str, timeout: int = 5) -> tuple[bool, str]:
    """Run an AppleScript snippet via osascript. Returns (success, stdout_or_error)."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    except Exception as e:
        return False, str(e)
