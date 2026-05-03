"""
launch_izach.py  —  C:/Projects/launch_izach.py
iZACH System Launcher

Starts in order:
  1. N8N
  2. iZACH  (Python backend, port 5050)
  3. MMA    (Python remote agent, port 6060)
  4. WhatsApp Bridge  (Node.js, port 3000)
  5. Ngrok  (HTTP tunnel → port 5050)

Each service gets its own console window with a colour-coded header.
Health checks confirm each is alive before moving to the next.
Ngrok public URL is fetched and printed clearly once the tunnel is up.
"""

import subprocess
import time
import sys
import os
import requests

# ── Paths ────────────────────────────────────────────────────
BASE      = r"C:\Projects\iZACH"
N8N_CMD = [r"C:\Users\vansh\AppData\Roaming\npm\n8n.cmd"]
IZACH_CMD = [r"C:\Projects\iZACH\.venv\Scripts\python.exe", os.path.join(BASE, "main.py")]
MMA_CMD   = [r"C:\Projects\iZACHMMA\.venv\Scripts\python.exe", os.path.join(r"C:\Projects\iZACHMMA", "main.py")]
WA_CMD    = ["node", os.path.join(BASE, "whatsapp_bridge.js")]
NGROK_CMD = ["ngrok", "http", "5050"]

# ── Colours (Windows ANSI) ───────────────────────────────────
R  = "\033[91m"
G  = "\033[92m"
Y  = "\033[93m"
C  = "\033[96m"
M  = "\033[95m"
W  = "\033[97m"
DIM= "\033[2m"
RST= "\033[0m"
BOLD="\033[1m"

os.system("cls")

# Enable ANSI on Windows
import ctypes
kernel = ctypes.windll.kernel32
kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)

BANNER = f"""
{C}╔══════════════════════════════════════════════════════════════╗
║  {BOLD}iZACH  —  Neural System Launcher{RST}{C}                            ║
║  {DIM}Intelligent Zenith Adaptive Cognitive Handler{RST}{C}                ║
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


def wait_http(url, label, color, timeout=30, interval=1.5):
    """Poll url until 200 or timeout. Returns True if alive."""
    log(color, label, f"Waiting for {url} ...")
    for i in range(int(timeout / interval)):
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
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


def start(label, color, cmd, cwd=None, new_window=True):
    """Launch a process. Returns Popen handle."""
    log(color, label, f"Starting: {' '.join(cmd[:3])} ...")
    try:
        flags = subprocess.CREATE_NEW_CONSOLE if new_window else 0
        proc  = subprocess.Popen(
            cmd,
            cwd=cwd or BASE,
            creationflags=flags,
        )
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
print(f"\n{Y}━━━ Step 1 / 5 — N8N Workflow Engine ━━━{RST}")
p_n8n = start("N8N", Y, N8N_CMD, cwd=r"C:\Projects")
time.sleep(3)
n8n_ok = wait_http("http://localhost:5678", "N8N", Y, timeout=40)
if not n8n_ok:
    log(Y, "N8N", f"{Y}⚠ Continuing without N8N{RST}")

# ── 2. iZACH ────────────────────────────────────────────────
print(f"\n{C}━━━ Step 2 / 5 — iZACH Backend (port 5050) ━━━{RST}")
p_izach = start("iZACH", C, IZACH_CMD, cwd=BASE)
izach_ok = wait_http("http://localhost:5050/health", "iZACH", C, timeout=45)
if not izach_ok:
    log(C, "iZACH", f"{R}✗ iZACH failed to start. Check main.py.{RST}")
    input("Press Enter to exit...")
    sys.exit(1)

# ── 3. MMA ───────────────────────────────────────────────────
print(f"\n{M}━━━ Step 3 / 5 — MMA Remote Agent (port 6060) ━━━{RST}")
p_mma = start("MMA", M, MMA_CMD, cwd=r"C:\Projects\iZACHMMA")
time.sleep(2)
mma_ok = wait_http("http://localhost:6060/health", "MMA", M, timeout=20)
if not mma_ok:
    log(M, "MMA", f"{Y}⚠ MMA offline — continuing{RST}")

# ── 4. WhatsApp Bridge ───────────────────────────────────────
print(f"\n{G}━━━ Step 4 / 5 — WhatsApp Bridge (port 3000) ━━━{RST}")
p_wa = start("WhatsApp", G, WA_CMD, cwd=BASE)
time.sleep(5)
wa_ok = wait_http("http://localhost:3000/health", "WhatsApp", G, timeout=25)
if not wa_ok:
    log(G, "WhatsApp", f"{Y}⚠ Bridge not ready yet — scan QR in its window{RST}")

# ── 5. Ngrok ─────────────────────────────────────────────────
print(f"\n{R}━━━ Step 5 / 5 — Ngrok Tunnel → port 5050 ━━━{RST}")
p_ngrok = start("Ngrok", R, NGROK_CMD, cwd=BASE, new_window=True)
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
    log(R, "Ngrok", f"{Y}⚠ Could not fetch URL. Check ngrok window.{RST}")
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
        p_electron = subprocess.Popen(
            ["npm", "run", "electron:dev"],
            cwd=ELECTRON_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            shell=True,
        )
        log(C, "Electron", f"{G}✓ Electron window starting...{RST}")
    else:
        log(C, "Electron", f"{R}✗ Backend never came up — skipping UI launch{RST}")    

# ── Summary ──────────────────────────────────────────────────
print(f"\n{C}━━━ iZACH System Status ━━━{RST}\n")

services = [
    ("N8N",         Y,  "http://localhost:5678",        n8n_ok),
    ("iZACH",       C,  "http://localhost:5050/health", izach_ok),
    ("MMA Agent",   M,  "http://localhost:6060/health", mma_ok),
    ("WhatsApp",    G,  "http://localhost:3000/health", wa_ok),
    ("Ngrok",       R,  ngrok_url or "—",               bool(ngrok_url)),
    ("Electron UI", C,  "izach-ui (npm run electron:dev)", os.path.isdir(os.path.join(BASE, "izach-ui"))),
]

for name, color, url, ok in services:
    status = f"{G}● ONLINE {RST}" if ok else f"{R}● OFFLINE{RST}"
    print(f"  {status}  {color}{name:<14}{RST}  {DIM}{url}{RST}")

print(f"\n  {DIM}All windows are independent — close this to stop monitoring.{RST}")
print(f"  {DIM}Press Ctrl+C to exit launcher (services keep running).{RST}\n")

try:
    while True:
        time.sleep(60)
        # Periodic health check every 60s
        for name, color, url, _ in services[:4]:
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