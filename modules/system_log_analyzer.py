"""
modules/system_log_analyzer.py
Reads last 10 days of Windows system data (Event Logs, Prefetch, recent apps),
sends compressed summary to Gemini for analysis, stores insight in MongoDB +
Obsidian. Runs once on startup in background — non-blocking.
"""

import logging
import subprocess
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_analyzed_this_session = False
_speak_func = None


def init(speak_fn=None):
    global _speak_func
    _speak_func = speak_fn


def start():
    """Fire analysis in background thread on startup."""
    threading.Thread(target=_run_analysis, daemon=True, name="SysLogAnalyzer").start()


# ── Data collectors ───────────────────────────────────────────


def _run_ps(script: str, timeout: int = 15) -> str:
    """Run a PowerShell snippet and return stdout. Returns '' on error."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"[SysLog] PS error: {e}")
        return ""


def _get_event_summary(days: int = 10) -> str:
    """Count errors and warnings per source from System + Application logs."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    script = f"""
$cutoff = [datetime]::Parse('{cutoff}')
$logs = @('System','Application')
$results = @()
foreach ($log in $logs) {{
    try {{
        $events = Get-WinEvent -LogName $log -ErrorAction SilentlyContinue |
                  Where-Object {{ $_.TimeCreated -gt $cutoff -and $_.LevelDisplayName -in @('Error','Critical','Warning') }}
        $grouped = $events | Group-Object -Property LevelDisplayName,ProviderName |
                   Select-Object -First 20 Count,Name
        foreach ($g in $grouped) {{ $results += "$log | $($g.Name) | Count: $($g.Count)" }}
    }} catch {{}}
}}
$results | Select-Object -First 40 | Out-String
"""
    return _run_ps(script, timeout=25)


def _get_prefetch_apps() -> str:
    """List recently-run executables from Prefetch (last 10 days)."""
    script = """
$pf = 'C:\\Windows\\Prefetch'
if (Test-Path $pf) {
    $cutoff = (Get-Date).AddDays(-10)
    Get-ChildItem $pf -Filter '*.pf' |
        Where-Object { $_.LastWriteTime -gt $cutoff } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 60 |
        ForEach-Object { $_.Name -replace '-[A-F0-9]+\.pf$','' } |
        Sort-Object -Unique
} else { 'Prefetch unavailable' }
"""
    return _run_ps(script, timeout=10)


def _get_startup_times() -> str:
    """Last 5 boot/shutdown events."""
    script = """
try {
    $boots = Get-WinEvent -FilterHashtable @{LogName='System';Id=6005,6006,6013} -ErrorAction SilentlyContinue |
             Select-Object -First 10 |
             ForEach-Object { "$($_.TimeCreated.ToString('yyyy-MM-dd HH:mm')) | ID $($_.Id) | $($_.Message.Split('.')[0])" }
    $boots | Out-String
} catch { 'Boot log unavailable' }
"""
    return _run_ps(script, timeout=15)


def _get_disk_health() -> str:
    """Quick disk + RAM snapshot."""
    script = """
$disks = Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free |
         ForEach-Object {
             $total = $_.Used + $_.Free
             if ($total -gt 0) { "$($_.Name): Used $([math]::Round($_.Used/1GB,1))GB / $([math]::Round($total/1GB,1))GB" }
         }
$ram = (Get-CimInstance Win32_OperatingSystem)
$ramUsed  = [math]::Round(($ram.TotalVisibleMemorySize - $ram.FreePhysicalMemory)/1MB, 1)
$ramTotal = [math]::Round($ram.TotalVisibleMemorySize/1MB, 1)
"RAM: ${ramUsed}GB used of ${ramTotal}GB"
$disks | Out-String
"""
    return _run_ps(script, timeout=10)


# ── Analysis ─────────────────────────────────────────────────


def _analyze_with_ai(raw_data: dict) -> str:
    """Send compressed system data to Gemini for personality-aware analysis."""
    try:
        from modules.ai_handler import AIProvider
        import json as _j
        with open("api_keys.json") as _f:
            cfg = _j.load(_f)
        keys = [cfg.get("gemini_key_1", ""), cfg.get("gemini_key_2", ""), cfg.get("gemini_key_3", "")]
        keys = [k for k in keys if k]
        if not keys:
            return ""

        prompt = f"""You are analyzing a user's Windows laptop system data from the last 10 days.
Write a concise, human personality-style profile — like you're describing how this person uses their computer.
Cover: app usage habits, system health, performance patterns, how well they maintain their machine.
Keep it under 200 words. Be specific. No bullet lists — write in natural flowing sentences.

=== EVENT LOG SUMMARY ===
{raw_data.get('events', 'N/A')[:1500]}

=== RECENTLY-RUN APPS (Prefetch) ===
{raw_data.get('apps', 'N/A')[:800]}

=== BOOT/SHUTDOWN HISTORY ===
{raw_data.get('boots', 'N/A')[:400]}

=== DISK & RAM ===
{raw_data.get('disk', 'N/A')[:300]}
"""
        ai = AIProvider(keys[0], keys)
        return ai.send_message(prompt)
    except Exception as e:
        logger.error(f"[SysLog] AI analysis failed: {e}")
        return ""


# ── Main runner ───────────────────────────────────────────────


def _run_analysis():
    global _analyzed_this_session
    if _analyzed_this_session:
        return
    _analyzed_this_session = True

    time.sleep(45)  # wait for startup to complete

    logger.info("[SysLog] Starting 10-day system analysis...")
    try:
        raw = {
            "events": _get_event_summary(),
            "apps":   _get_prefetch_apps(),
            "boots":  _get_startup_times(),
            "disk":   _get_disk_health(),
        }

        # Check if we actually got data
        if not any(raw.values()):
            logger.warning("[SysLog] No system data collected.")
            return

        summary = _analyze_with_ai(raw)
        if not summary:
            logger.warning("[SysLog] AI returned empty analysis.")
            return

        # Save to MongoDB
        try:
            from modules.mongo_brain import save_preference
            save_preference("system_profile.summary", summary)
            save_preference("system_profile.analyzed_at", datetime.now().isoformat())
            save_preference("system_profile.top_apps", raw["apps"][:500])
        except Exception as e:
            logger.warning(f"[SysLog] MongoDB save failed: {e}")

        # Save to Obsidian
        try:
            from modules.obsidian_brain import save_system_profile
            save_system_profile(summary, raw["apps"], raw["events"])
        except Exception as e:
            logger.warning(f"[SysLog] Obsidian save failed: {e}")

        logger.info("[SysLog] Analysis complete.")

        if _speak_func:
            _speak_func("I've finished analyzing your system. I now have a better idea of how you use your laptop.")

    except Exception as e:
        logger.error(f"[SysLog] Analysis error: {e}")


def get_system_profile() -> str:
    """Retrieve the stored system profile summary from MongoDB."""
    try:
        from modules.mongo_brain import get_preference
        return get_preference("system_profile.summary", "")
    except Exception:
        return ""
