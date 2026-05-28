"""
iZACH Node Receiver
Runs on AlliedNode 2 (low-spec secondary PC).
Listens for commands from AlliedNode, executes them locally.
Exposes system tray icon with quick actions.
"""

import os
import sys
import json
import base64
import threading
import subprocess
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import psutil
import pystray
from PIL import Image, ImageDraw, ImageFont

# ─── Config (edit these) ──────────────────────────────────────
RECEIVER_PORT   = 9797
SENDER_HOST     = "AlliedNode"   # main PC hostname or IP address
SENDER_UI_PORT  = 5173           # iZACH web UI port on AlliedNode
NODE_NAME       = "AlliedNode 2"
AUTH_TOKEN      = "izach-node-2026"  # must match remote_node.py on AlliedNode
# ──────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
ICON_PATH    = SCRIPT_DIR / "icon.png"
server_ref   = None
tray_icon    = None


# ─── Icon ─────────────────────────────────────────────────────

def _build_icon_image(status: str = "idle") -> Image.Image:
    """
    Load icon.png if present (user can drop iZACH logo there).
    Otherwise generate a simple coloured circle.
    status: 'connected' | 'idle' | 'error'
    """
    if ICON_PATH.exists():
        img = Image.open(ICON_PATH).convert("RGBA").resize((64, 64))
        return img

    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color_map = {
        "connected": (30, 160, 90, 255),
        "idle":      (30, 120, 255, 255),
        "error":     (200, 50, 50, 255),
    }
    bg = color_map.get(status, color_map["idle"])

    draw.ellipse([2, 2, size - 2, size - 2], fill=bg)

    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    draw.text((14, 19), "iZ", fill=(255, 255, 255, 255), font=font)

    # save once so user knows where to drop their logo
    if not ICON_PATH.exists():
        try:
            img.save(ICON_PATH)
        except Exception:
            pass

    return img


# ─── Vitals ───────────────────────────────────────────────────

def get_vitals() -> dict:
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")

    temps = {}
    try:
        sensor_data = psutil.sensors_temperatures()
        if sensor_data:
            for name, entries in sensor_data.items():
                if entries:
                    temps[name] = round(entries[0].current, 1)
    except Exception:
        pass

    return {
        "node":          NODE_NAME,
        "cpu_percent":   cpu,
        "ram_used_gb":   round(ram.used  / 1e9, 2),
        "ram_total_gb":  round(ram.total / 1e9, 2),
        "ram_percent":   ram.percent,
        "disk_used_gb":  round(disk.used  / 1e9, 1),
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_percent":  disk.percent,
        "temps_c":       temps,
    }


# ─── HTTP Handler ─────────────────────────────────────────────

class ReceiverHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence default access log

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-iZACH-Token")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        return self.headers.get("X-iZACH-Token", "") == AUTH_TOKEN

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── CORS preflight ────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-iZACH-Token")
        self.end_headers()

    # ── GET endpoints ─────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/ping":
            self._send_json({"status": "alive", "node": NODE_NAME})

        elif path == "/vitals":
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            self._send_json(get_vitals())

        elif path == "/ui":
            ui_file = SCRIPT_DIR / "node_ui.html"
            try:
                body = ui_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",   "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.send_header("Cache-Control",  "no-cache")
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self._send_json({"error": "node_ui.html not found"}, 404)

        elif path == "/processes":
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                from urllib.parse import parse_qs
                top = int(parse_qs(urlparse(self.path).query).get("top", [20])[0])
                procs = []
                for p in psutil.process_iter(['pid', 'name', 'memory_percent', 'status']):
                    try:
                        procs.append(p.info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                procs.sort(key=lambda x: x.get('memory_percent') or 0, reverse=True)
                self._send_json({"node": NODE_NAME, "processes": procs[:top]})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/screenshot":
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                from PIL import ImageGrab
                import io, base64 as _b64
                img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=75)
                b64 = _b64.b64encode(buf.getvalue()).decode()
                self._send_json({"node": NODE_NAME, "screenshot": b64,
                                 "width": img.width, "height": img.height})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/download/"):
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            file_path = path[len("/download/"):]
            try:
                data = Path(file_path).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",        "application/octet-stream")
                self.send_header("Content-Length",      len(data))
                self.send_header("Content-Disposition", f'attachment; filename="{Path(file_path).name}"')
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self._send_json({"error": "file not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/sysinfo":
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                import platform, socket, time as _t
                boot   = psutil.boot_time()
                up_s   = int(_t.time() - boot)
                h, rem = divmod(up_s, 3600)
                m, s   = divmod(rem, 60)
                # Network adapters
                addrs = {}
                for iface, snics in psutil.net_if_addrs().items():
                    addrs[iface] = [
                        {"family": str(snic.family), "address": snic.address,
                         "netmask": snic.netmask or ""}
                        for snic in snics
                    ]
                # Battery
                battery = None
                try:
                    b = psutil.sensors_battery()
                    if b:
                        battery = {"percent": round(b.percent, 1),
                                   "plugged": b.power_plugged}
                except Exception:
                    pass
                self._send_json({
                    "ok": True,
                    "os":              platform.system() + " " + platform.release(),
                    "version":         platform.version()[:80],
                    "hostname":        socket.gethostname(),
                    "cpu_name":        platform.processor()[:70],
                    "cpu_physical":    psutil.cpu_count(logical=False),
                    "cpu_logical":     psutil.cpu_count(logical=True),
                    "ram_total_gb":    round(psutil.virtual_memory().total / 1e9, 2),
                    "uptime":          f"{h}h {m}m {s}s",
                    "uptime_s":        up_s,
                    "net_interfaces":  addrs,
                    "battery":         battery,
                    "node":            NODE_NAME,
                })
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/net_stats":
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                net = psutil.net_io_counters()
                self._send_json({"ok": True,
                                 "bytes_sent": net.bytes_sent,
                                 "bytes_recv": net.bytes_recv})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path.startswith("/browse"):
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                from urllib.parse import parse_qs as _pqs
                qs       = _pqs(urlparse(self.path).query)
                dir_path = qs.get("path", ["C:\\"])[0]
                p        = Path(dir_path)
                entries  = []
                try:
                    items = sorted(p.iterdir(),
                                   key=lambda x: (not x.is_dir(), x.name.lower()))
                except PermissionError:
                    items = []
                for item in items:
                    try:
                        st = item.stat()
                        entries.append({
                            "name":     item.name,
                            "is_dir":   item.is_dir(),
                            "size":     st.st_size if not item.is_dir() else None,
                            "modified": int(st.st_mtime),
                        })
                    except (PermissionError, OSError):
                        entries.append({"name": item.name, "is_dir": item.is_dir(),
                                        "size": None, "modified": None, "locked": True})
                self._send_json({
                    "ok":      True,
                    "path":    str(p),
                    "parent":  str(p.parent),
                    "entries": entries,
                })
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path.startswith("/file_read"):
            if not self._auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                from urllib.parse import parse_qs as _pqs, unquote as _uq
                qs        = _pqs(urlparse(self.path).query)
                file_path = _uq(qs.get("path", [""])[0])
                p         = Path(file_path)
                if not p.is_file():
                    self._send_json({"ok": False, "error": "not a file"}, 400)
                    return
                if p.stat().st_size > 204800:   # 200 KB limit
                    self._send_json({"ok": False, "error": "File too large (>200 KB)"}, 400)
                    return
                content = p.read_text(encoding="utf-8", errors="replace")
                self._send_json({"ok": True, "path": str(p), "content": content})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/izach_bridge":
            try:
                import urllib.request as _ur
                req = _ur.Request(
                    f"http://{SENDER_HOST}:5050/status",
                    headers={"User-Agent": "iZACH-Node/1.0"}
                )
                with _ur.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                self._send_json({"ok": True, "online": True, "data": data})
            except Exception as e:
                self._send_json({"ok": True, "online": False, "error": str(e)})

        else:
            self._send_json({"error": "not found"}, 404)

    # ── POST endpoints ────────────────────────────────────────
    def do_POST(self):
        if not self._auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        path = urlparse(self.path).path
        body = self._body()

        if path == "/open_app":
            app = body.get("app", "")
            try:
                subprocess.Popen(app, shell=True)
                self._send_json({"status": "launched", "app": app})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/open_file":
            file_path = body.get("path", "")
            try:
                os.startfile(file_path)
                self._send_json({"status": "opened", "path": file_path})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/execute":
            cmd = body.get("command", "")
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=10
                )
                self._send_json({
                    "status":     "done",
                    "stdout":     result.stdout.strip(),
                    "stderr":     result.stderr.strip(),
                    "returncode": result.returncode,
                })
            except subprocess.TimeoutExpired:
                self._send_json({"error": "command timed out"}, 408)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/upload":
            file_path    = body.get("path", "")
            content_b64  = body.get("content", "")
            try:
                content = base64.b64decode(content_b64)
                dest = Path(file_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                self._send_json({"status": "saved", "path": file_path, "size": len(content)})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/system_control":
            action = body.get("action", "")
            try:
                if action == "shutdown":
                    self._send_json({"status": "shutting down in 5s"})
                    subprocess.Popen("shutdown /s /t 5", shell=True)
                elif action == "restart":
                    self._send_json({"status": "restarting in 5s"})
                    subprocess.Popen("shutdown /r /t 5", shell=True)
                elif action == "sleep":
                    self._send_json({"status": "sleeping"})
                    subprocess.Popen(
                        "rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True
                    )
                elif action == "lock":
                    self._send_json({"status": "locked"})
                    subprocess.Popen(
                        "rundll32.exe user32.dll,LockWorkStation", shell=True
                    )
                elif action == "kill_process":
                    proc_name = body.get("process", "").lower()
                    killed = 0
                    for proc in psutil.process_iter(["name"]):
                        if proc.info["name"].lower() == proc_name:
                            proc.kill()
                            killed += 1
                    self._send_json({"status": "killed", "process": proc_name, "count": killed})
                else:
                    self._send_json({"error": f"unknown action: {action}"}, 400)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/remote_input":
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                action = body.get("action", "type")
                if action == "type":
                    text = body.get("text", "")
                    # Use clipboard paste for reliability (handles unicode)
                    try:
                        import pyperclip
                        pyperclip.copy(text)
                        pyautogui.hotkey("ctrl", "v")
                        self._send_json({"status": "pasted", "chars": len(text)})
                    except ImportError:
                        pyautogui.write(text, interval=0.02)
                        self._send_json({"status": "typed", "chars": len(text)})
                elif action == "hotkey":
                    keys = body.get("keys", [])
                    pyautogui.hotkey(*keys)
                    self._send_json({"status": "hotkey", "keys": keys})
                elif action == "key":
                    key = body.get("key", "")
                    pyautogui.press(key)
                    self._send_json({"status": "key", "key": key})
                else:
                    self._send_json({"error": f"unknown action: {action}"}, 400)
            except ImportError:
                self._send_json(
                    {"error": "pyautogui not installed — run: pip install pyautogui"}, 500
                )
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/file_action":
            file_path = body.get("path", "")
            action    = body.get("action", "")
            try:
                p = Path(file_path)
                if action == "delete":
                    import shutil
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    self._send_json({"status": "deleted", "path": file_path})
                elif action == "rename":
                    new_name = body.get("new_name", "")
                    if not new_name:
                        self._send_json({"error": "new_name required"}, 400)
                        return
                    new_path = p.parent / new_name
                    p.rename(new_path)
                    self._send_json({"status": "renamed", "path": str(new_path)})
                elif action == "mkdir":
                    p.mkdir(parents=True, exist_ok=True)
                    self._send_json({"status": "created", "path": str(p)})
                else:
                    self._send_json({"error": f"unknown action: {action}"}, 400)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/notify":
            # Send Windows toast notification on this machine
            msg   = body.get("message", "")
            title = body.get("title", "iZACH")
            try:
                ps_cmd = (
                    f'Add-Type -AssemblyName System.Windows.Forms; '
                    f'$n = New-Object System.Windows.Forms.NotifyIcon; '
                    f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
                    f'$n.Visible = $true; '
                    f'$n.ShowBalloonTip(4000, \"{title}\", \"{msg}\", '
                    f'[System.Windows.Forms.ToolTipIcon]::Info); '
                    f'Start-Sleep -Milliseconds 4500; $n.Dispose()'
                )
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd]
                )
                self._send_json({"status": "sent", "message": msg})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        else:
            self._send_json({"error": "not found"}, 404)


# ─── Server ───────────────────────────────────────────────────

def _run_server():
    global server_ref
    server_ref = HTTPServer(("0.0.0.0", RECEIVER_PORT), ReceiverHandler)
    print(f"[iZACH Receiver] Listening on port {RECEIVER_PORT}")
    server_ref.serve_forever()


# ─── Tray actions ─────────────────────────────────────────────

def _open_web_ui(icon, item):
    webbrowser.open(f"http://localhost:{RECEIVER_PORT}/ui")


def _show_vitals(icon, item):
    v   = get_vitals()
    msg = (
        f"Node:  {v['node']}\n"
        f"CPU:   {v['cpu_percent']}%\n"
        f"RAM:   {v['ram_used_gb']} / {v['ram_total_gb']} GB  ({v['ram_percent']}%)\n"
        f"Disk:  {v['disk_used_gb']} / {v['disk_total_gb']} GB  ({v['disk_percent']}%)"
    )
    if v["temps_c"]:
        first_temp = next(iter(v["temps_c"].items()))
        msg += f"\nTemp:  {first_temp[1]} °C  ({first_temp[0]})"

    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("iZACH Node — System Status", msg)
    root.destroy()


def _ping_sender() -> bool:
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen(
            f"http://{SENDER_HOST}:{SENDER_UI_PORT}/status", timeout=2
        )
        return True
    except urllib.error.HTTPError:
        return True  # got HTTP response = server is up
    except Exception:
        return False


def _check_connection(icon):
    """Background thread: update tray tooltip based on AlliedNode reachability."""
    import time
    while True:
        reachable = _ping_sender()
        status    = "connected" if reachable else "idle"
        tooltip   = (
            f"iZACH Receiver — {NODE_NAME}\n"
            f"AlliedNode: {'Connected' if reachable else 'Not reachable'}"
        )
        try:
            icon.title = tooltip
            icon.icon  = _build_icon_image(status)
        except Exception:
            pass
        time.sleep(15)


def _restart_receiver(icon, item):
    global server_ref
    if server_ref:
        server_ref.shutdown()
    threading.Thread(target=_run_server, daemon=True).start()


def _quit_receiver(icon, item):
    global server_ref
    icon.stop()
    if server_ref:
        threading.Thread(target=server_ref.shutdown, daemon=True).start()
    sys.exit(0)


# ─── Main ─────────────────────────────────────────────────────

def main():
    threading.Thread(target=_run_server, daemon=True).start()

    img  = _build_icon_image("idle")
    menu = pystray.Menu(
        pystray.MenuItem(f"iZACH Receiver  —  {NODE_NAME}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open iZACH Web Interface", _open_web_ui),
        pystray.MenuItem("System Status",            _show_vitals),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Receiver",         _restart_receiver),
        pystray.MenuItem("Quit",                     _quit_receiver),
    )

    icon = pystray.Icon(
        "izach_node",
        img,
        f"iZACH Receiver — {NODE_NAME}",
        menu,
    )

    threading.Thread(target=_check_connection, args=(icon,), daemon=True).start()

    icon.run()


if __name__ == "__main__":
    main()
