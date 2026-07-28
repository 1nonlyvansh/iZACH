"""
launch_izach.py — iZACH System Launcher

Starts in order:
  1. N8N
  2. iZACH  (Python backend, port 5050)
  3. MMA    (Python remote agent, port 6060 — optional, skipped if not found)
  4. WhatsApp Bridge  (Node.js, port 3000)
  5. Ngrok  (HTTP tunnel → port 5050)
  6. Electron UI

On Windows, each service gets its own console window (CREATE_NEW_CONSOLE).
On macOS there's no equivalent flag, so each service instead runs detached
and logs to its own file under logs/ — same pattern this file already used
for the MMA agent, just generalized to every service.

Health checks confirm each is alive before moving to the next. Ngrok public
URL is fetched and printed clearly once the tunnel is up.
"""

import subprocess
import time
import sys
import os
import requests

from modules.platform_utils import IS_WINDOWS, IS_MAC

# ── Paths ────────────────────────────────────────────────────
# Derived from this file's location (override with IZACH_BASE env var) instead
# of a hardcoded machine-specific path.
BASE = os.environ.get("IZACH_BASE", os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

if IS_WINDOWS:
    _VENV_PYTHON = os.path.join(BASE, ".venv", "Scripts", "python.exe")
    N8N_CMD = [os.environ.get("IZACH_N8N_CMD", r"C:\Users\vansh\AppData\Roaming\npm\n8n.cmd")]
else:
    _VENV_PYTHON = os.path.join(BASE, ".venv", "bin", "python3")
    N8N_CMD = ["n8n"]

IZACH_CMD = [_VENV_PYTHON, os.path.join(BASE, "main.py")]
WA_CMD = ["node", os.path.join(BASE, "whatsapp_bridge.js")]
# Explicit 127.0.0.1, not bare "5050"/"localhost:5050" — ngrok resolves
# "localhost" to the IPv6 loopback ([::1]) first on this Mac, and the Flask
# backend only binds IPv4 (host='0.0.0.0'), so ngrok's dial target had
# nothing listening on it at all (ERR_NGROK_8012, connection refused),
# even while the backend was genuinely healthy on IPv4.
NGROK_CMD = ["ngrok", "http", "127.0.0.1:5050"]

# MMA agent is a separate sibling project — optional, skipped entirely if not
# present (README: "Comment out MMA_CMD if you don't have the MMA agent repo").
_MMA_BASE = os.environ.get("IZACH_MMA_BASE", os.path.join(os.path.dirname(BASE), "iZACHMMA"))
_MMA_PYTHON = os.path.join(_MMA_BASE, ".venv", "Scripts" if IS_WINDOWS else "bin",
                            "python.exe" if IS_WINDOWS else "python3")
MMA_CMD = [_MMA_PYTHON, os.path.join(_MMA_BASE, "main.py")]
MMA_AVAILABLE = os.path.isfile(_MMA_PYTHON)

# n8n on macOS needs a Node LTS version — n8n's native deps (isolated-vm) don't
# build/run on the very newest Node majors yet. If a versioned Homebrew Node
# keg is present, prepend it to PATH just for the n8n subprocess.
_N8N_ENV = os.environ.copy()
if IS_MAC:
    for _node_ver in ("node@22", "node@20"):
        _node_bin = f"/opt/homebrew/opt/{_node_ver}/bin"
        if os.path.isdir(_node_bin):
            _N8N_ENV["PATH"] = _node_bin + os.pathsep + _N8N_ENV.get("PATH", "")
            break

# ── Colours (ANSI — native on macOS/Linux terminals, enabled below on Windows) ─
R  = "\033[91m"
G  = "\033[92m"
Y  = "\033[93m"
C  = "\033[96m"
M  = "\033[95m"
W  = "\033[97m"
DIM= "\033[2m"
RST= "\033[0m"
BOLD="\033[1m"

if IS_WINDOWS:
    os.system("cls")
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
else:
    os.system("clear")

BANNER = f"""
{C}╔══════════════════════════════════════════════════════════════╗
║  {BOLD}iZACH  —  Neural System Launcher{RST}{C}                            ║
║  {DIM}Intent Zenith Adaptive Cognitive Handler{RST}{C}                     ║
╚══════════════════════════════════════════════════════════════╝{RST}
"""
print(BANNER)


def tag(color, label):
    width = 16
    pad   = " " * (width - len(label))
    return f"{color}[{label}]{pad}{RST}"


def log(color, label, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  {DIM}{ts}{RST}  {tag(color, label)} {msg}")


# ── Boot Settings — which services/terminals to start ──────────
# Set from Cortex UI's Settings → BOOT SETTINGS tab, api_keys.json's
# "boot_terminals" key. Missing key or missing sub-key both default to True
# (on) so a fresh install / pre-upgrade settings file behaves exactly like
# before this feature existed — nothing skipped unless explicitly turned off.
def _load_boot_terminals() -> dict:
    import json
    defaults = {"boot_interface": True, "backend": True, "ngrok": True,
                "whatsapp_bridge": True, "n8n": True}
    try:
        with open(os.path.join(BASE, "api_keys.json"), encoding="utf-8") as f:
            cfg = json.load(f).get("boot_terminals") or {}
        return {**defaults, **cfg}
    except Exception:
        return defaults


BOOT = _load_boot_terminals()


def wait_http(url, label, color, timeout=30, interval=1.5):
    """Poll url until 200 or timeout. Returns True if alive."""
    log(color, label, f"Waiting for {url} ...")
    for i in range(int(timeout / interval)):
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                log(color, label, f"{G}✓ Online{RST}  ({url})")
                return True
        except Exception:
            pass
        time.sleep(interval)
        sys.stdout.write(f"\r  {DIM}{time.strftime('%H:%M:%S')}{RST}  {tag(color, label)} "
                         f"Waiting{'.' * ((i % 3) + 1)}   ")
        sys.stdout.flush()
    print()
    log(color, label, f"{R}✗ Did not respond within {timeout}s{RST}")
    return False


def _open_in_terminal_mac(cmd, cwd, env=None, filter_objc_noise=False):
    """macOS equivalent of Windows' CREATE_NEW_CONSOLE — tells Terminal.app to
    open a new window and run the command there, so it's visible just like the
    separate console windows on Windows. First run will prompt for Automation
    permission (System Settings > Privacy & Security > Automation) to let
    Python/Terminal control Terminal.app — approve it once, then it's silent."""
    import shlex
    parts = [f"cd {shlex.quote(cwd)}"]
    if env is not None:
        extra_path = env.get("PATH", "")
        if extra_path and extra_path != os.environ.get("PATH", ""):
            parts.append(f"export PATH={shlex.quote(extra_path)}")
    inner_cmd = " ".join(shlex.quote(c) for c in cmd)
    if filter_objc_noise:
        # pygame and opencv each bundle their own private SDL2 dylib on macOS;
        # the ObjC runtime logs a benign "Class X is implemented in both..."
        # warning per duplicate symbol at import time. Cosmetic only (no
        # crash, no behavior change) — filtered from the visible Terminal
        # window only. logs/console.log still gets the unfiltered stream via
        # crash_handler.py's Tee, since this only touches the raw fd the
        # shell sees before Python's own stderr object comes into play.
        inner_cmd += " 2> >(grep -v '^objc\\[' >&2)"
    parts.append(inner_cmd)
    shell_cmd = " && ".join(parts)
    # Escape for embedding inside an AppleScript double-quoted string literal.
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Terminal" to do script "{escaped}"'
    subprocess.Popen(["osascript", "-e", script])


def start(label, color, cmd, cwd=None, new_window=True, env=None, log_name=None, filter_objc_noise=False):
    """Launch a process. Windows: own console window (CREATE_NEW_CONSOLE).
    macOS: own Terminal.app window via AppleScript, for the same visible,
    per-service layout. Pass new_window=False for background/logged services
    (e.g. MMA) on either OS. filter_objc_noise: macOS only — strip the
    pygame/opencv duplicate-SDL2-class ObjC warnings from the visible window."""
    log(color, label, f"Starting: {' '.join(cmd[:3])} ...")
    try:
        if IS_WINDOWS and new_window:
            return subprocess.Popen(
                cmd, cwd=cwd or BASE, creationflags=subprocess.CREATE_NEW_CONSOLE, env=env,
            )
        if IS_MAC and new_window:
            _open_in_terminal_mac(cmd, cwd or BASE, env=env, filter_objc_noise=filter_objc_noise)
            log(color, label, f"{DIM}Opened in a new Terminal window{RST}")
            return None
        log_path = os.path.join(LOGS_DIR, f"{log_name or label.lower()}.log")
        fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
        proc = subprocess.Popen(
            cmd, cwd=cwd or BASE, stdout=fh, stderr=fh,
            start_new_session=not IS_WINDOWS,
            env=env,
        )
        log(color, label, f"{DIM}Logging to {log_path}{RST}")
        return proc
    except FileNotFoundError as e:
        log(color, label, f"{R}✗ Not found: {e}{RST}")
        return None


def get_ngrok_url(timeout=20):
    """Fetch public URL from ngrok local API."""
    for _ in range(int(timeout / 1.5)):
        try:
            data = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2).json()
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if "https" in t.get("public_url", ""):
                    return t["public_url"]
                if t.get("public_url"):
                    return t["public_url"]
        except Exception:
            pass
        time.sleep(1.5)
    return None


# ── 1. N8N ───────────────────────────────────────────────────
print(f"\n{Y}━━━ Step 1 / 6 — N8N Workflow Engine ━━━{RST}")
# N8N always runs — the Boot Settings toggle only controls whether it gets
# its own visible terminal window or runs headless, logging to logs/n8n.log.
# (Previously this toggle skipped starting N8N entirely, which was never the
# intent — the checkboxes are for reducing on-screen terminal clutter, not
# for disabling the service itself.)
p_n8n = start("N8N", Y, N8N_CMD, cwd=os.path.dirname(BASE), env=_N8N_ENV,
              new_window=BOOT["n8n"], log_name="n8n")
time.sleep(3)
n8n_ok = wait_http("http://localhost:5678", "N8N", Y, timeout=40)
if not n8n_ok:
    log(Y, "N8N", f"{Y}⚠ Continuing without N8N{RST}")

# ── 2. iZACH ────────────────────────────────────────────────
print(f"\n{C}━━━ Step 2 / 6 — iZACH Backend (port 5050) ━━━{RST}")
# Backend always runs (mandatory) — the toggle only controls whether it gets
# its own visible terminal window or runs headless, logging to logs/izach.log.
# If the auto-promotion watchdog is installed (Settings → auto-promote
# enabled), the OS scheduler (launchd on Mac, Task Scheduler on Windows)
# already owns this process's lifecycle — spawning our own copy here would
# double-launch it and fight over port 5050, so defer to the scheduler
# (kickstart) instead of Popen in that case.
from modules.instance_coordinator import is_watchdog_installed, kickstart_watchdog
if is_watchdog_installed():
    log(C, "iZACH", f"{DIM}Watchdog installed — restarting via the OS scheduler instead of a new process{RST}")
    kickstart_watchdog()
    p_izach = None
else:
    p_izach = start("iZACH", C, IZACH_CMD, cwd=BASE, filter_objc_noise=IS_MAC,
                     new_window=BOOT["backend"], log_name="izach")
# macOS first-run startup is slower than Windows here (heavier bytecode
# compilation + ML library init the first time — resemblyzer/torch/dlib),
# so give it more headroom than a tight 45s.
izach_ok = wait_http("http://localhost:5050/health", "iZACH", C, timeout=90 if IS_MAC else 45)
if not izach_ok:
    log(C, "iZACH", f"{R}✗ iZACH failed to start. Check main.py.{RST}")
    input("Press Enter to exit...")
    sys.exit(1)

# ── 3. MMA ───────────────────────────────────────────────────
print(f"\n{M}━━━ Step 3 / 6 — MMA Remote Agent (port 6060) ━━━{RST}")
mma_ok = False
if not MMA_AVAILABLE:
    log(M, "MMA", f"{DIM}Not found at {_MMA_BASE} — skipping (optional){RST}")
else:
    LOG_MMA = os.path.join(LOGS_DIR, "mma.log")
    _mma_log_fh = open(LOG_MMA, "a", encoding="utf-8", errors="replace", buffering=1)
    p_mma = subprocess.Popen(
        MMA_CMD,
        cwd=_MMA_BASE,
        stdout=_mma_log_fh,
        stderr=_mma_log_fh,
        creationflags=0 if IS_WINDOWS else 0,
        start_new_session=not IS_WINDOWS,
    )
    time.sleep(2)
    mma_ok = wait_http("http://localhost:6060/health", "MMA", M, timeout=20)
    if not mma_ok:
        log(M, "MMA", f"{Y}⚠ MMA offline — continuing{RST}")

# ── 4. WhatsApp Bridge ───────────────────────────────────────
print(f"\n{G}━━━ Step 4 / 6 — WhatsApp Bridge (port 3000) ━━━{RST}")
# Always runs — toggle only controls visible-window vs headless (see N8N above).
p_wa = start("WhatsApp", G, WA_CMD, cwd=BASE, new_window=BOOT["whatsapp_bridge"], log_name="whatsapp")
time.sleep(5)
wa_ok = wait_http("http://localhost:3000/health", "WhatsApp", G, timeout=25)
if not wa_ok:
    log(G, "WhatsApp", f"{Y}⚠ Bridge not ready yet{RST}" +
        (" — scan QR in its window" if (IS_WINDOWS and BOOT["whatsapp_bridge"]) else f" — check logs/whatsapp.log"))

# ── 5. Ngrok ─────────────────────────────────────────────────
print(f"\n{R}━━━ Step 5 / 6 — Ngrok Tunnel → port 5050 ━━━{RST}")
# Always runs — toggle only controls visible-window vs headless (see N8N above).
p_ngrok = start("Ngrok", R, NGROK_CMD, cwd=BASE, new_window=BOOT["ngrok"], log_name="ngrok")
time.sleep(3)

log(R, "Ngrok", "Fetching public URL from ngrok API ...")
ngrok_url = get_ngrok_url(timeout=25)

if ngrok_url:
    log(R, "Ngrok", f"{G}✓ Tunnel active{RST}")
    print(f"""
  {BOLD}{C}┌──────────────────────────────────────────────────────┐
  │  NGROK PUBLIC URL                                    │
  │  {RST}{BOLD}{W}{ngrok_url:<52}{RST}{BOLD}{C}  │
  │  {RST}{DIM}Forward this to MMA or external services           {RST}{BOLD}{C}  │
  └──────────────────────────────────────────────────────┘{RST}
""")
else:
    log(R, "Ngrok", f"{Y}⚠ Could not fetch URL. Check ngrok logs.{RST}")
    log(R, "Ngrok", f"  Run: {DIM}curl http://127.0.0.1:4040/api/tunnels{RST}")

# ── 6. Electron UI ───────────────────────────────────────────
print(f"\n{C}━━━ Step 6 / 6 — Electron UI (React) ━━━{RST}")

ELECTRON_DIR = os.path.join(BASE, "izach-ui")

if not os.path.isdir(ELECTRON_DIR):
    log(C, "Electron", f"{R}✗ izach-ui folder not found at {ELECTRON_DIR}{RST}")
else:
    # Wait for backend to be confirmed alive before opening UI
    if not izach_ok:
        log(C, "Electron", "Waiting for iZACH backend before launching UI ...")
        izach_ok = wait_http("http://localhost:5050/health", "iZACH", C, timeout=30)

    if izach_ok:
        log(C, "Electron", "Launching Electron UI ...")
        if IS_WINDOWS:
            p_electron = subprocess.Popen(
                ["cmd", "/c", "npm", "run", "electron:dev"],
                cwd=ELECTRON_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        elif IS_MAC:
            # Prefer the packaged app (correct "iZACH" Dock/menu-bar identity
            # instead of generic "Electron") — built via `npm run electron:build`
            # in izach-ui/. It still loads cortex-ui.html/api_keys.json live
            # from BASE via IZACH_PROJECT_ROOT, not a frozen snapshot, so UI
            # edits take effect on next launch with no rebuild needed. Falls
            # back to dev mode if the packaged app hasn't been built yet.
            _packaged_app = os.path.join(
                ELECTRON_DIR, "dist-electron", "mac-arm64", "iZACH.app",
                "Contents", "MacOS", "iZACH",
            )
            if os.path.isfile(_packaged_app):
                _electron_env = dict(os.environ)
                _electron_env["IZACH_PROJECT_ROOT"] = BASE
                subprocess.Popen([_packaged_app], env=_electron_env, start_new_session=True)
                log(C, "Electron", f"{DIM}Launched packaged iZACH.app{RST}")
            else:
                _open_in_terminal_mac(["npm", "run", "electron:dev"], ELECTRON_DIR)
                log(C, "Electron", f"{DIM}Packaged app not found — opened dev mode in a new "
                                    f"Terminal window (run 'npm run electron:build' in izach-ui/ "
                                    f"to build the packaged app for correct branding){RST}")
        else:
            _electron_log = open(os.path.join(LOGS_DIR, "electron.log"),
                                  "a", encoding="utf-8", errors="replace", buffering=1)
            p_electron = subprocess.Popen(
                ["npm", "run", "electron:dev"],
                cwd=ELECTRON_DIR,
                stdout=_electron_log, stderr=_electron_log,
                start_new_session=True,
            )
            log(C, "Electron", f"{DIM}Logging to logs/electron.log{RST}")
        log(C, "Electron", f"{G}✓ Electron window starting...{RST}")
    else:
        log(C, "Electron", f"{R}✗ Backend never came up — skipping UI launch{RST}")

# ── Summary ──────────────────────────────────────────────────
print(f"\n{C}━━━ iZACH System Status ━━━{RST}\n")

# "has_window" reflects whether this service's terminal is visible — every
# service in this list actually runs regardless of that Boot Settings
# checkbox, which only controls on-screen clutter (see Steps 1/4/5 above).
services = [
    ("N8N",         Y,  "http://localhost:5678",        n8n_ok,   BOOT["n8n"]),
    ("iZACH",       C,  "http://localhost:5050/health", izach_ok, BOOT["backend"]),
    ("MMA Agent",   M,  "http://localhost:6060/health", mma_ok,   True),
    ("WhatsApp",    G,  "http://localhost:3000/health", wa_ok,    BOOT["whatsapp_bridge"]),
    ("Ngrok",       R,  ngrok_url or "—",               bool(ngrok_url), BOOT["ngrok"]),
    ("Electron UI", C,  "izach-ui (npm run electron:dev)", os.path.isdir(os.path.join(BASE, "izach-ui")), True),
]

for name, color, url, ok, has_window in services:
    status = f"{G}● ONLINE {RST}" if ok else f"{R}● OFFLINE{RST}"
    window_note = "" if has_window else f" {DIM}(headless — no terminal window){RST}"
    print(f"  {status}  {color}{name:<14}{RST}  {DIM}{url}{RST}{window_note}")

if IS_WINDOWS:
    print(f"\n  {DIM}All windows are independent — close this to stop monitoring.{RST}")
else:
    print(f"\n  {DIM}Services run detached, logging to logs/*.log — closing this won't stop them.{RST}")
print(f"  {DIM}Press Ctrl+C to exit launcher (services keep running).{RST}\n")

try:
    while True:
        time.sleep(60)
        # Periodic health check every 60s — every service here actually runs
        # regardless of its terminal-window toggle, so all of them get
        # checked. Electron is excluded (no health URL, checked at boot only
        # via isdir()).
        for name, color, url, _, _has_window in services[:4]:
            try:
                r = requests.get(url, timeout=2)
                alive = r.status_code < 500
            except Exception:
                alive = False
            dot = f"{G}●{RST}" if alive else f"{R}●{RST}"
            sys.stdout.write(f"  {dot} {color}{name}{RST}  ")
        print(f"  {DIM}{time.strftime('%H:%M:%S')}{RST}")
except KeyboardInterrupt:
    print(f"\n{Y}[Launcher] Exiting monitor. Services continue in their own windows.{RST}\n")
