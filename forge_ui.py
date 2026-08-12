# Must run before anything else gets a chance to initialize COM in MTA mode —
# WebView2 requires the STA apartment, and Windows refuses to change a
# thread's apartment mode once set (RPC_E_CHANGED_MODE). Setting it through
# pythonnet's own CLR interop (rather than pywin32's pythoncom.CoInitialize,
# which corrupts unrelated background threading.Thread workers when combined
# with pythonnet in the same process) keeps plain background threads safe.
try:
    import clr
    clr.AddReference('System.Threading')
    from System.Threading import Thread as _NetThread, ApartmentState as _ApartmentState
    _NetThread.CurrentThread.SetApartmentState(_ApartmentState.STA)
except Exception:
    pass

import tkinter as tk
import threading
import os
import time
import math
import re
import json
import uuid
import psutil
import subprocess
import requests
from urllib.parse import quote, urlparse
from PIL import Image, ImageTk, ImageDraw
import cv2

from modules import password_vault


# ─────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────
BG_DEEP   = "#050d1a"
BG_PANEL  = "#071020"
BG_CARD   = "#0a1628"
CYAN      = "#00e5ff"
CYAN_DIM  = "#005060"
CYAN_DARK = "#002030"
GREEN     = "#1db954"
GREEN_DIM = "#0a4a22"
AMBER     = "#ffb300"
RED       = "#ff3d3d"
TEXT_PRI  = "#c8e8f0"
TEXT_SEC  = "#3a6070"
BORDER    = "#0d2a3a"
BORDER_HI = "#1a4a5a"


def _card(parent, **kw):
    return tk.Frame(parent, bg=BG_CARD,
                    highlightthickness=1,
                    highlightbackground=BORDER_HI, **kw)

def _label(parent, text, fg=CYAN, font_size=9, bold=False, **kw):
    weight = "bold" if bold else "normal"
    return tk.Label(parent, text=text, bg=BG_CARD, fg=fg,
                    font=("Consolas", font_size, weight), **kw)

_API = "http://127.0.0.1:5050"

_SHARED_PROFILE_PATCHED = False


def _electron_partition_dir():
    """Cortex UI's Electron session partition folder — WebView2 points its own
    profile here so cookies/logins are shared between Forge and Cortex."""
    appdata = os.environ.get("APPDATA", "")
    dev = os.path.join(appdata, "izach-ui", "Partitions", "izach-browser")
    packaged = os.path.join(appdata, "iZACH", "Partitions", "izach-browser")
    if os.path.isdir(packaged) and not os.path.isdir(dev):
        return packaged
    return dev


def _patch_shared_webview_profile():
    """tkwebview2 hardcodes cache_dir=None when constructing pywebview's
    EdgeChrome, with no public way to override it. Swap in a wrapper that
    always points WebView2 at Cortex's Chromium profile dir instead, so both
    browsers share the same live cookies/sessions."""
    global _SHARED_PROFILE_PATCHED
    if _SHARED_PROFILE_PATCHED:
        return
    import tkwebview2.tkwebview2 as _tkw2mod
    from webview.platforms.edgechromium import EdgeChrome as _RealEdgeChrome
    profile_dir = _electron_partition_dir()

    def _patched_edge_chrome(form, window, cache_dir):
        return _RealEdgeChrome(form, window, profile_dir)

    _tkw2mod.EdgeChrome = _patched_edge_chrome
    _SHARED_PROFILE_PATCHED = True


def _section_header(parent, text):
    f = tk.Frame(parent, bg=BG_CARD)
    f.pack(fill="x", padx=10, pady=(8, 6))
    tk.Label(f, text="* ", bg=BG_CARD, fg=CYAN,
             font=("Consolas", 9, "bold")).pack(side="left")
    tk.Label(f, text=text, bg=BG_CARD, fg=CYAN,
             font=("Consolas", 9, "bold")).pack(side="left")
    sep = tk.Frame(f, bg=BORDER_HI, height=1)
    sep.pack(side="left", fill="x", expand=True, padx=(8, 0))


# ─────────────────────────────────────────────
# NEURAL CORE
# ─────────────────────────────────────────────
class NeuralCore(tk.Canvas):
    def __init__(self, parent, size=300, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=BG_CARD, highlightthickness=0, **kw)
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.speaking = False
        self._t = 0
        self._nodes = self._gen_nodes()
        self._animate()

    def _gen_nodes(self):
        nodes = []
        for count, radius in [(6, 40), (9, 85), (7, 130)]:
            for i in range(count):
                angle = (2 * math.pi / count) * i
                nodes.append({
                    "x": self.cx + radius * math.cos(angle),
                    "y": self.cy + radius * math.sin(angle),
                    "phase": i * 0.5
                })
        return nodes

    def set_speaking(self, val):
        self.speaking = val

    def _animate(self):
        self._t += 0.04
        t = self._t
        self.delete("all")
        pulse = 1.0 + (0.3 * math.sin(t * 3.5) if self.speaking else 0.06 * math.sin(t))

        # Outer rings
        for i, col in enumerate([CYAN_DARK, CYAN_DIM, "#004a60"]):
            r = int(self.cx * 0.9 * pulse) + (3 - i) * 5
            self.create_oval(self.cx - r, self.cy - r,
                             self.cx + r, self.cy + r,
                             outline=col, width=1)

        # Edges
        for i, a in enumerate(self._nodes):
            for j, b in enumerate(self._nodes):
                if j <= i:
                    continue
                dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if dist < 100:
                    flicker = 0.25 + 0.5 * abs(math.sin(t + a["phase"] + b["phase"]))
                    if self.speaking:
                        flicker = min(1.0, flicker * 1.7)
                    col = self._lerp(CYAN_DARK, CYAN, flicker)
                    self.create_line(a["x"], a["y"], b["x"], b["y"],
                                     fill=col, width=1)

        # Nodes
        for nd in self._nodes:
            wave = math.sin(t * 1.6 + nd["phase"])
            nr = 3.5 * (1 + (0.3 * wave if self.speaking else 0.07 * wave))
            glow = (0.4 + 0.6 * abs(wave)) if self.speaking else (0.15 + 0.15 * abs(wave))
            col = self._lerp(CYAN_DIM, CYAN, glow)
            self.create_oval(nd["x"] - nr, nd["y"] - nr,
                             nd["x"] + nr, nd["y"] + nr,
                             fill=col, outline="")

        # Centre orb
        orb_r = int(16 * pulse)
        for layer in range(4, 0, -1):
            lr = orb_r + layer * 4
            self.create_oval(self.cx - lr, self.cy - lr,
                             self.cx + lr, self.cy + lr,
                             fill="", outline=CYAN_DIM, width=1)
        self.create_oval(self.cx - orb_r, self.cy - orb_r,
                         self.cx + orb_r, self.cy + orb_r,
                         fill=CYAN if self.speaking else CYAN_DIM, outline="")

        self.after(33, self._animate)

    @staticmethod
    def _lerp(c1, c2, t):
        t = max(0.0, min(1.0, t))
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


# ─────────────────────────────────────────────
# CHAT PANEL
# ─────────────────────────────────────────────
class ChatPanel(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._build()

    def _build(self):
        self._canvas = tk.Canvas(self, bg=BG_CARD, highlightthickness=0)
        sb = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview,
                          bg=BG_PANEL, troughcolor=BG_DEEP, activebackground=CYAN)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=BG_CARD)
        self._win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", lambda e: (
            self._canvas.configure(scrollregion=self._canvas.bbox("all")),
            self._canvas.yview_moveto(1.0)
        ))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._win, width=e.width))

    def add_message(self, sender, text):
        is_user = sender.upper() == "USER"
        row = tk.Frame(self._inner, bg=BG_CARD)
        row.pack(fill="x", padx=8, pady=3)
        bubble_bg = "#081828" if not is_user else "#081a10"
        bubble_fg = CYAN if not is_user else GREEN
        side = "w" if not is_user else "e"
        outer = tk.Frame(row, bg=BG_CARD)
        outer.pack(anchor=side)
        tk.Label(outer, text="iZACH" if not is_user else "YOU",
                 bg=BG_CARD, fg=bubble_fg,
                 font=("Consolas", 7, "bold")).pack(anchor=side, padx=4)
        bubble = tk.Frame(outer, bg=bubble_bg,
                          highlightthickness=1,
                          highlightbackground=bubble_fg if not is_user else GREEN_DIM)
        bubble.pack(anchor=side)
        tk.Label(bubble, text=text, bg=bubble_bg, fg=TEXT_PRI,
                 font=("Consolas", 10), wraplength=380,
                 justify="left" if not is_user else "right",
                 padx=10, pady=5).pack()


# ─────────────────────────────────────────────
# STATS PANEL
# ─────────────────────────────────────────────
class StatsPanel(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._bars = {}
        self._proc_bars = {}
        self._build()
        self.after(200, self._update)

    def _build(self):
        _section_header(self, "SYSTEM VITALS")
        for label in ["CPU", "RAM", "GPU"]:
            self._make_bar(label, CYAN, self._bars)
        tk.Frame(self, bg=BORDER_HI, height=1).pack(fill="x", padx=10, pady=4)
        f = tk.Frame(self, bg=BG_CARD)
        f.pack(anchor="w", padx=10, pady=(0, 4))
        tk.Label(f, text="iZ.ACH. PROCESS", bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8, "bold")).pack(side="left")
        for label in ["CPU", "MEM"]:
            self._make_bar(label, AMBER, self._proc_bars)

    def _make_bar(self, label, color, store):
        row = tk.Frame(self, bg=BG_CARD)
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text=f"{label:<4}", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8), width=4).pack(side="left")
        bg = tk.Frame(row, bg=BORDER, height=5)
        bg.pack(side="left", fill="x", expand=True, padx=(4, 8))
        fill = tk.Frame(bg, bg=color, height=5)
        fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)
        val = tk.Label(row, text="0%", bg=BG_CARD, fg=color,
                       font=("Consolas", 8), width=6)
        val.pack(side="right")
        store[label] = {"bg": bg, "fill": fill, "val": val}

    def _update(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        gpu = 0
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL).decode().strip()
            gpu = float(out.split("\n")[0])
        except Exception:
            pass
        for label, val in [("CPU", cpu), ("RAM", ram), ("GPU", gpu)]:
            b = self._bars[label]
            b["fill"].place(relwidth=val / 100)
            b["val"].config(text=f"{val:.0f}%")
            b["fill"].config(bg=RED if val > 85 else (AMBER if val > 65 else CYAN))
        try:
            proc = psutil.Process(os.getpid())
            p_cpu = proc.cpu_percent(interval=None)
            p_mem = proc.memory_percent()
        except Exception:
            p_cpu, p_mem = 0, 0
        for label, val in [("CPU", p_cpu), ("MEM", p_mem)]:
            b = self._proc_bars[label]
            b["fill"].place(relwidth=min(val / 100, 1.0))
            b["val"].config(text=f"{val:.1f}%")
        self.after(1500, self._update)


# ─────────────────────────────────────────────
# CAMERA PANEL
# ─────────────────────────────────────────────
class CameraPanel(tk.Frame):
    """
    Camera panel backed by AURA's VisionEngine.
    """
    CAM_W = 400   # was ~280, now bigger
    CAM_H = 300

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD,
                         highlightthickness=1,
                         highlightbackground=BORDER_HI, **kw)
        self._running      = False
        self._vision       = None
        self._pending      = False
        self._cam_label    = None
        self._status_var   = tk.StringVar(value="CAMERA OFFLINE")
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG_CARD)
        hdr.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(hdr, text="* ", bg=BG_CARD, fg=CYAN,
                 font=("Consolas", 9, "bold")).pack(side="left")
        tk.Label(hdr, text="VISION", bg=BG_CARD, fg=CYAN,
                 font=("Consolas", 9, "bold")).pack(side="left")

        # Camera switch button
        tk.Button(hdr, text="⟳ CAM", bg=BG_PANEL, fg=CYAN,
                  font=("Consolas", 8), relief="flat", cursor="hand2",
                  activebackground=CYAN_DARK,
                  command=self._switch_camera).pack(side="right", padx=4)

        # Start/stop toggle button
        self._start_btn = tk.Button(hdr, text="▶ START", bg=BG_PANEL, fg=GREEN,
                  font=("Consolas", 8), relief="flat", cursor="hand2",
                  activebackground=CYAN_DARK,
                  command=self._toggle_stream)
        self._start_btn.pack(side="right", padx=2)

        # Camera canvas
        self._canvas = tk.Canvas(self, width=self.CAM_W, height=self.CAM_H,
                                  bg="#000000", highlightthickness=0)
        self._canvas.pack(padx=8, pady=4)

        # Status line
        tk.Label(self, textvariable=self._status_var,
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 7)).pack(pady=2)

    def start(self, on_gesture=None):
        """Start camera stream using modules.camera_vision."""
        if self._running:
            return
        self._status_var.set("STARTING...")
        try:
            from modules import camera_vision as cv_mod
            cv_mod._start_stream_cam()
            self._running = True
            self._status_var.set("CAMERA ONLINE")
            self._cv_mod = cv_mod
            self._stream_loop()
        except Exception as e:
            self._status_var.set(f"CAM ERROR: {e}")
            print(f"[CAMERA] Vision start error: {e}")

    def _stream_loop(self):
        if not self._running:
            return
        try:
            frame = self._cv_mod._read_stream_frame()
            if frame is not None:
                self._update_canvas(frame, lambda: None)
        except Exception:
            pass
        self.after(60, self._stream_loop)  # ~16 FPS

    def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            from modules import camera_vision as cv_mod
            cv_mod._stop_stream_cam()
        except Exception:
            pass

    def _receive_frame(self, bgr_frame, done_callback):
        """Called by VisionEngine — push frame to tkinter on main thread."""
        if not self._running:
            done_callback()
            return
        self.after(0, lambda: self._update_canvas(bgr_frame, done_callback))

    def _update_canvas(self, bgr_frame, done_callback):
        try:
            from PIL import Image, ImageTk
            h, w = bgr_frame.shape[:2]
            scale = min(self.CAM_W / w, self.CAM_H / h)
            nw, nh = int(w * scale), int(h * scale)
            rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb).resize((nw, nh), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self._canvas.delete("all")
            x = (self.CAM_W - nw) // 2
            y = (self.CAM_H - nh) // 2
            self._canvas.create_image(x, y, anchor="nw", image=photo)
            self._canvas.image = photo  # keep reference
        except Exception:
            pass
        finally:
            done_callback()

    def _toggle_stream(self):
        if self._running:
            self.stop()
            self._start_btn.config(text="▶ START", fg=GREEN)
            self._status_var.set("CAMERA OFFLINE")
            self._canvas.delete("all")
        else:
            self.start()
            if self._running:
                self._start_btn.config(text="■ STOP", fg=RED)

    def _switch_camera(self):
        try:
            from modules import camera_vision as cv_mod
            cams = cv_mod.list_cameras()
            if not cams:
                self._status_var.set("No cameras detected")
                return
            cur = getattr(cv_mod, "_cam_device_index", 0)
            try:
                nxt = cams[(cams.index(cur) + 1) % len(cams)]
            except ValueError:
                nxt = cams[0]
            was_running = self._running
            if was_running:
                self.stop()
            cv_mod.set_camera_device(nxt)
            self._status_var.set(f"Camera {nxt}")
            if was_running:
                self.start()
        except Exception as e:
            self._status_var.set(f"Switch err: {e}")





# ─────────────────────────────────────────────
# SPOTIFY PANEL
# ─────────────────────────────────────────────
class SpotifyPanel(tk.Frame):
    def __init__(self, parent, spotify_handler=None, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self.sp = spotify_handler
        self._build()
        self.after(500, self._poll)

    def _build(self):
        _section_header(self, "SPOTIFY")

        # Art + info row
        top = tk.Frame(self, bg=BG_CARD)
        top.pack(fill="x", padx=10, pady=(0, 6))

        self._art_lbl = tk.Label(top, bg=BG_CARD)
        self._art_lbl.pack(side="left", padx=(0, 10))
        self._set_default_art()

        info = tk.Frame(top, bg=BG_CARD)
        info.pack(side="left", fill="both", expand=True)

        self._track_var = tk.StringVar(value="[ SONG TITLE HERE ]")
        self._artist_var = tk.StringVar(value="[ ARTIST NAME HERE ]")

        tk.Label(info, textvariable=self._track_var, bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9, "bold"), wraplength=150, justify="left").pack(anchor="w")
        tk.Label(info, textvariable=self._artist_var, bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(anchor="w")

        # Controls
        ctrl = tk.Frame(self, bg=BG_CARD)
        ctrl.pack(fill="x", padx=10, pady=(0, 8))

        btn_cfg = dict(bg=BG_PANEL, fg=CYAN, font=("Consolas", 11),
                       relief="flat", cursor="hand2",
                       activebackground=CYAN_DARK, activeforeground=CYAN,
                       padx=6, pady=2)

        tk.Button(ctrl, text="|◀", command=self._prev, **btn_cfg).pack(side="left", padx=2)
        self._play_btn = tk.Button(ctrl, text="▶", command=self._play_pause, **btn_cfg)
        self._play_btn.pack(side="left", padx=2)
        tk.Button(ctrl, text="▶|", command=self._next, **btn_cfg).pack(side="left", padx=2)
        tk.Button(ctrl, text="◁◁", bg=BG_PANEL, fg=TEXT_SEC,
                  font=("Consolas", 9), relief="flat",
                  padx=6, pady=2).pack(side="left", padx=2)

        tk.Frame(self, bg=BORDER_HI, height=1).pack(fill="x", padx=10, pady=4)

        # Device section
        _section_header(self, "DEVICE")

        dev_row = tk.Frame(self, bg=BG_CARD)
        dev_row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Label(dev_row, text="DEVICE", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 7)).pack(side="left")

        self._device_var = tk.StringVar(value="[ DEVICE NAME HERE ]")
        self._device_menu = tk.OptionMenu(dev_row, self._device_var, "─",
                                          command=self._switch_device)
        self._device_menu.config(bg=BG_PANEL, fg=CYAN, font=("Consolas", 8),
                                 relief="flat", borderwidth=0,
                                 highlightthickness=1, highlightbackground=BORDER,
                                 activebackground=CYAN_DARK, activeforeground=CYAN)
        self._device_menu["menu"].config(bg=BG_PANEL, fg=CYAN, font=("Consolas", 8))
        self._device_menu.pack(side="left", padx=4, fill="x", expand=True)

        tk.Button(dev_row, text="↺", bg=BG_PANEL, fg=TEXT_SEC,
                  font=("Consolas", 10), relief="flat",
                  command=self._refresh_devices, cursor="hand2").pack(side="right")

        # Progress bar placeholder
        prog_row = tk.Frame(self, bg=BG_CARD)
        prog_row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(prog_row, text="◀◀", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")
        bar_bg = tk.Frame(prog_row, bg=BORDER, height=3)
        bar_bg.pack(side="left", fill="x", expand=True, padx=6)
        self._prog_fill = tk.Frame(bar_bg, bg=CYAN, height=3)
        self._prog_fill.place(x=0, y=0, relheight=1.0, relwidth=0.4)
        tk.Button(prog_row, text="↺", bg=BG_CARD, fg=TEXT_SEC,
                  font=("Consolas", 8), relief="flat").pack(side="right")

    def _set_default_art(self):
        img = Image.new("RGB", (52, 52), color="#0a1628")
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 44, 44], outline=CYAN_DIM, width=2)
        draw.ellipse([20, 20, 32, 32], fill=CYAN_DIM)
        self._art_photo = ImageTk.PhotoImage(img)
        self._art_lbl.config(image=self._art_photo)

    def _poll(self):
        if self.sp:
            try:
                cur = self.sp.sp.current_playback()
                if cur and cur.get("item"):
                    item = cur["item"]
                    track = item["name"]
                    artist = ", ".join(a["name"] for a in item["artists"])
                    self._track_var.set(track[:22] + "…" if len(track) > 22 else track)
                    self._artist_var.set(artist[:22] + "…" if len(artist) > 22 else artist)
                    # Play/pause button glyph
                    self._play_btn.config(text="❚❚" if cur.get("is_playing") else "▶")
                    # Progress
                    duration = item.get("duration_ms") or 1
                    progress = cur.get("progress_ms", 0) or 0
                    self._prog_fill.place(relwidth=min(progress / duration, 1.0))
                    # Art
                    try:
                        imgs = item.get("album", {}).get("images", [])
                        if imgs:
                            resp = requests.get(imgs[-1]["url"], timeout=3)
                            img = Image.open(__import__("io").BytesIO(resp.content))
                            img = img.resize((52, 52), Image.Resampling.LANCZOS)
                            self._art_photo = ImageTk.PhotoImage(img)
                            self._art_lbl.config(image=self._art_photo)
                    except Exception:
                        pass
                    # Device
                    dev = cur.get("device", {})
                    if dev.get("name"):
                        self._device_var.set(dev["name"])
                else:
                    self._track_var.set("[ SONG TITLE HERE ]")
                    self._artist_var.set("[ ARTIST NAME HERE ]")
                    self._set_default_art()
            except Exception:
                pass
        self.after(5000, self._poll)

    def _refresh_devices(self):
        if not self.sp:
            return
        try:
            devices = self.sp.sp.devices().get("devices", [])
            menu = self._device_menu["menu"]
            menu.delete(0, "end")
            for d in devices:
                name = d["name"]
                menu.add_command(label=name,
                                 command=lambda n=name: self._device_var.set(n))
        except Exception:
            pass

    def _switch_device(self, name):
        if self.sp and name not in ("─", "[ DEVICE NAME HERE ]"):
            threading.Thread(target=self.sp.switch_device, args=(name,), daemon=True).start()

    def _prev(self):
        if self.sp:
            threading.Thread(target=self.sp.previous_track, daemon=True).start()

    def _next(self):
        if self.sp:
            threading.Thread(target=self.sp.next_track, daemon=True).start()

    def _play_pause(self):
        if not self.sp:
            return
        try:
            cur = self.sp.sp.current_playback()
            if cur and cur.get("is_playing"):
                threading.Thread(target=self.sp.pause_music, daemon=True).start()
            else:
                threading.Thread(target=self.sp.resume_music, daemon=True).start()
        except Exception:
            pass


# ─────────────────────────────────────────────
# OCR PANEL
# ─────────────────────────────────────────────
class OCRPanel(tk.Frame):
    """Camera OCR widget — toggle scanning, show extracted text, copy/save."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._enabled = False
        self._poll_id = None
        self._build()

    def _build(self):
        _section_header(self, "DOCUMENT OCR")

        # Status row + toggle
        top = tk.Frame(self, bg=BG_CARD)
        top.pack(fill="x", padx=10, pady=(0, 4))

        self._status_lbl = tk.Label(top, text="IDLE", bg=BG_CARD, fg=CYAN_DIM,
                                     font=("Consolas", 9, "bold"))
        self._status_lbl.pack(side="left")

        self._toggle_btn = tk.Button(top, text="[ START SCAN ]",
                                      bg=BG_CARD, fg=CYAN_DIM,
                                      font=("Consolas", 8), relief="flat",
                                      cursor="hand2",
                                      activebackground=CYAN_DARK,
                                      command=self._toggle_ocr,
                                      padx=6, pady=2)
        self._toggle_btn.pack(side="right")

        # Upload image button
        upload_row = tk.Frame(self, bg=BG_CARD)
        upload_row.pack(fill="x", padx=10, pady=(0, 4))

        tk.Button(upload_row, text="⊡ UPLOAD IMAGE",
                  bg=BG_CARD, fg=TEXT_SEC,
                  font=("Consolas", 8), relief="flat", cursor="hand2",
                  activebackground=CYAN_DARK,
                  command=self._upload_image,
                  padx=6, pady=2).pack(side="left")

        tk.Frame(self, bg=BORDER_HI, height=1).pack(fill="x", padx=10, pady=4)

        # Extracted text
        tk.Label(self, text="EXTRACTED TEXT", bg=BG_CARD, fg=CYAN_DIM,
                 font=("Consolas", 7)).pack(anchor="w", padx=10)

        txt_frame = tk.Frame(self, bg=BG_CARD)
        txt_frame.pack(fill="both", expand=True, padx=10, pady=(4, 4))

        sb = tk.Scrollbar(txt_frame, bg=BG_CARD, troughcolor=BORDER)
        sb.pack(side="right", fill="y")
        self._text_out = tk.Text(txt_frame, height=6,
                                  bg="#010814", fg="#60b8d0",
                                  font=("Consolas", 8), relief="flat",
                                  wrap="word",
                                  highlightthickness=1,
                                  highlightbackground=BORDER_HI,
                                  state="disabled",
                                  yscrollcommand=sb.set)
        self._text_out.pack(side="left", fill="both", expand=True)
        sb.config(command=self._text_out.yview)

        # Action buttons
        btn_row = tk.Frame(self, bg=BG_CARD)
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        for label, cmd in [("COPY", self._copy), ("SAVE", self._save), ("CLEAR", self._clear)]:
            tk.Button(btn_row, text=label,
                      bg=BG_CARD, fg=CYAN_DIM,
                      font=("Consolas", 7), relief="flat", cursor="hand2",
                      activebackground=CYAN_DARK,
                      command=cmd,
                      padx=6, pady=2).pack(side="left", padx=(0, 4))

    def _toggle_ocr(self):
        import threading, requests as _req
        self._enabled = not self._enabled
        self._toggle_btn.config(
            text="[ STOP SCAN ]" if self._enabled else "[ START SCAN ]",
            fg=CYAN if self._enabled else CYAN_DIM,
        )
        self._status_lbl.config(text="SCANNING…" if self._enabled else "IDLE",
                                 fg=CYAN if self._enabled else CYAN_DIM)
        try:
            _req.post("http://127.0.0.1:5050/ocr/toggle",
                      json={"enabled": self._enabled}, timeout=3)
        except Exception:
            pass
        if self._enabled:
            self._poll_id = self.after(1500, self._poll_result)
        else:
            if self._poll_id:
                self.after_cancel(self._poll_id)
                self._poll_id = None

    def _poll_result(self):
        try:
            import requests as _req
            r = _req.get("http://127.0.0.1:5050/ocr/status", timeout=2).json()
            if r.get("mode") == "done":
                self._set_text(r.get("last_text", ""))
                self._enabled = False
                self._toggle_btn.config(text="[ START SCAN ]", fg=CYAN_DIM)
                self._status_lbl.config(text="DONE", fg=GREEN)
                return
        except Exception:
            pass
        if self._enabled:
            self._poll_id = self.after(1500, self._poll_result)

    def _upload_image(self):
        import tkinter.filedialog as fd
        import base64, threading, requests as _req
        path = fd.askopenfilename(
            title="Select Image for OCR",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All", "*.*")]
        )
        if not path:
            return
        self._status_lbl.config(text="PROCESSING…", fg=CYAN)
        def _run():
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                import mimetypes
                mime = mimetypes.guess_type(path)[0] or "image/jpeg"
                r = _req.post("http://127.0.0.1:5050/ocr/scan-image",
                              json={"image": b64, "mime": mime}, timeout=30).json()
                self.after(0, lambda: self._set_text(r.get("text", "")))
                self.after(0, lambda: self._status_lbl.config(text="DONE", fg=GREEN))
            except Exception as e:
                self.after(0, lambda: self._status_lbl.config(text="ERROR", fg=RED))
        threading.Thread(target=_run, daemon=True).start()

    def _set_text(self, text):
        self._text_out.config(state="normal")
        self._text_out.delete("1.0", "end")
        self._text_out.insert("end", text or "")
        self._text_out.config(state="disabled")

    def _copy(self):
        text = self._text_out.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _save(self):
        import requests as _req, threading
        text = self._text_out.get("1.0", "end").strip()
        if not text:
            return
        try:
            _req.post("http://127.0.0.1:5050/ocr/save", json={"text": text}, timeout=5)
            self._status_lbl.config(text="SAVED ✓", fg=GREEN)
            self.after(2000, lambda: self._status_lbl.config(text="DONE", fg=GREEN))
        except Exception:
            pass

    def _clear(self):
        self._set_text("")
        self._status_lbl.config(text="IDLE", fg=CYAN_DIM)
        self._enabled = False
        self._toggle_btn.config(text="[ START SCAN ]", fg=CYAN_DIM)


# ─────────────────────────────────────────────
# PRINTER PANEL
# ─────────────────────────────────────────────
class PrinterPanel(tk.Frame):
    """Printer widget — status, default settings, file queue, print."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._queue = []   # list of absolute file paths
        self._prefs = {}
        self._build()
        self.after(500, self._refresh_status)

    def _build(self):
        _section_header(self, "PRINTER")

        # Status row
        status_row = tk.Frame(self, bg=BG_CARD)
        status_row.pack(fill="x", padx=10, pady=(0, 4))

        self._dot = tk.Label(status_row, text="●", bg=BG_CARD, fg=RED,
                              font=("Consolas", 10))
        self._dot.pack(side="left")

        self._name_lbl = tk.Label(status_row, text="SCANNING...", bg=BG_CARD, fg=TEXT_SEC,
                                   font=("Consolas", 8))
        self._name_lbl.pack(side="left", padx=(4, 0))

        self._status_lbl = tk.Label(status_row, text="—", bg=BG_CARD, fg=TEXT_SEC,
                                     font=("Consolas", 7))
        self._status_lbl.pack(side="right")

        self._queue_lbl = tk.Label(self, text="QUEUE: 0 JOBS", bg=BG_CARD, fg=CYAN_DIM,
                                    font=("Consolas", 7))
        self._queue_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        tk.Frame(self, bg=BORDER_HI, height=1).pack(fill="x", padx=10, pady=4)

        # Default settings
        tk.Label(self, text="DEFAULT SETTINGS", bg=BG_CARD, fg=CYAN_DIM,
                 font=("Consolas", 7)).pack(anchor="w", padx=10)

        cfg = tk.Frame(self, bg=BG_CARD)
        cfg.pack(fill="x", padx=10, pady=(4, 4))

        # Color mode
        r1 = tk.Frame(cfg, bg=BG_CARD); r1.pack(fill="x", pady=2)
        tk.Label(r1, text="COLOR MODE", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 7), width=14, anchor="w").pack(side="left")
        self._color_var = tk.StringVar(value="color")
        for val, lbl in [("color", "COLOR"), ("bw", "B&W")]:
            tk.Radiobutton(r1, text=lbl, variable=self._color_var, value=val,
                           bg=BG_CARD, fg=CYAN_DIM, selectcolor=CYAN_DARK,
                           activebackground=BG_CARD,
                           font=("Consolas", 7),
                           command=lambda: self._save_pref("color_mode", self._color_var.get())
                           ).pack(side="left", padx=4)

        # DPI
        r2 = tk.Frame(cfg, bg=BG_CARD); r2.pack(fill="x", pady=2)
        tk.Label(r2, text="DPI", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 7), width=14, anchor="w").pack(side="left")
        self._dpi_var = tk.StringVar(value="600")
        dpi_opt = tk.OptionMenu(r2, self._dpi_var, "120", "300", "600",
                                command=lambda v: self._save_pref("dpi", int(v)))
        dpi_opt.config(bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7),
                       relief="flat", highlightthickness=0, activebackground=CYAN_DARK)
        dpi_opt["menu"].config(bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7))
        dpi_opt.pack(side="left")

        # Pages
        r3 = tk.Frame(cfg, bg=BG_CARD); r3.pack(fill="x", pady=2)
        tk.Label(r3, text="PAGES", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 7), width=14, anchor="w").pack(side="left")
        self._pages_var = tk.StringVar(value="all")
        pg_opt = tk.OptionMenu(r3, self._pages_var, "all", "odd", "even",
                               command=lambda v: self._save_pref("pages", v))
        pg_opt.config(bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7),
                      relief="flat", highlightthickness=0, activebackground=CYAN_DARK)
        pg_opt["menu"].config(bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7))
        pg_opt.pack(side="left")

        tk.Frame(self, bg=BORDER_HI, height=1).pack(fill="x", padx=10, pady=4)

        # File queue
        queue_hdr = tk.Frame(self, bg=BG_CARD)
        queue_hdr.pack(fill="x", padx=10)
        tk.Label(queue_hdr, text="PRINT QUEUE", bg=BG_CARD, fg=CYAN_DIM,
                 font=("Consolas", 7)).pack(side="left")
        tk.Button(queue_hdr, text="+ ADD", bg=BG_CARD, fg=CYAN_DIM,
                  font=("Consolas", 7), relief="flat", cursor="hand2",
                  activebackground=CYAN_DARK,
                  command=self._add_files, padx=4).pack(side="right")

        # Listbox for files
        lb_frame = tk.Frame(self, bg=BG_CARD)
        lb_frame.pack(fill="x", padx=10, pady=(4, 4))
        self._file_lb = tk.Listbox(lb_frame, height=4,
                                    bg="#010814", fg="#60b8d0",
                                    font=("Consolas", 7), relief="flat",
                                    highlightthickness=1,
                                    highlightbackground=BORDER_HI,
                                    selectbackground=CYAN_DARK,
                                    selectforeground=CYAN)
        self._file_lb.pack(fill="x")

        # Preview label
        self._preview_lbl = tk.Label(self, text="", bg=BG_CARD, fg=TEXT_SEC,
                                      font=("Consolas", 7), justify="center")
        self._preview_lbl.pack(pady=(0, 4))
        self._file_lb.bind("<<ListboxSelect>>", self._on_select)

        # Print + clear buttons
        btn_row = tk.Frame(self, bg=BG_CARD)
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        self._print_btn = tk.Button(btn_row, text="⎙ PRINT ALL",
                                     bg=BG_PANEL, fg=CYAN,
                                     font=("Consolas", 9, "bold"),
                                     relief="flat", cursor="hand2",
                                     activebackground=CYAN_DARK,
                                     command=self._print_now,
                                     padx=8, pady=4)
        self._print_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        tk.Button(btn_row, text="✕",
                  bg=BG_PANEL, fg=RED,
                  font=("Consolas", 9), relief="flat", cursor="hand2",
                  activebackground="#2a0000",
                  command=self._clear_queue,
                  padx=8, pady=4).pack(side="right")

    # ── API helpers ────────────────────────────────
    def _save_pref(self, key, value):
        import requests as _req, threading
        self._prefs[key] = value
        def _run():
            try:
                _req.post("http://127.0.0.1:5050/print/settings",
                          json={key: value}, timeout=3)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_status(self):
        import requests as _req, threading
        def _run():
            try:
                r = _req.get("http://127.0.0.1:5050/print/status", timeout=3).json()
                if r.get("ok"):
                    online = r.get("is_online", False)
                    name   = r.get("name", "No printer")
                    status = (r.get("status") or "—").upper()
                    jobs   = r.get("jobs_count", 0)
                    self.after(0, lambda: self._apply_status(online, name, status, jobs))
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()
        self.after(30000, self._refresh_status)

    def _apply_status(self, online, name, status, jobs):
        color = GREEN if online else RED
        self._dot.config(fg=color)
        self._name_lbl.config(text=name[:28])
        self._status_lbl.config(text=status, fg=color)
        self._queue_lbl.config(text=f"QUEUE: {jobs} JOB{'S' if jobs != 1 else ''}")

    def _add_files(self):
        import tkinter.filedialog as fd
        paths = fd.askopenfilenames(
            title="Select Files to Print",
            filetypes=[
                ("Printable", "*.pdf *.docx *.doc *.txt *.jpg *.jpeg *.png"),
                ("All", "*.*"),
            ]
        )
        for p in paths:
            if p not in self._queue:
                self._queue.append(p)
                self._file_lb.insert("end", os.path.basename(p))
        self._queue_lbl.config(text=f"QUEUE: {len(self._queue)} FILE{'S' if len(self._queue) != 1 else ''}")

    def _on_select(self, _event):
        sel = self._file_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._queue):
            path = self._queue[idx]
            ext  = os.path.splitext(path)[1].lower()
            size = os.path.getsize(path) // 1024
            self._preview_lbl.config(
                text=f"{os.path.basename(path)}\n{ext.upper()[1:]} · {size} KB",
                fg=TEXT_SEC
            )

    def _clear_queue(self):
        self._queue.clear()
        self._file_lb.delete(0, "end")
        self._preview_lbl.config(text="")
        self._queue_lbl.config(text="QUEUE: 0 JOBS")

    def _print_now(self):
        import requests as _req, threading
        if not self._queue:
            self._preview_lbl.config(text="No files queued", fg=AMBER)
            return
        self._print_btn.config(text="⎙ PRINTING…", state="disabled")
        paths = list(self._queue)
        def _run():
            try:
                r = _req.post("http://127.0.0.1:5050/print/job",
                              json={"files": paths, "overrides": self._prefs},
                              timeout=60).json()
                if r.get("ok"):
                    self.after(0, lambda: self._preview_lbl.config(
                        text=f"✓ Sent {len(paths)} file(s) to printer", fg=GREEN))
                    self.after(0, self._clear_queue)
                else:
                    self.after(0, lambda: self._preview_lbl.config(
                        text="Print failed — check printer", fg=RED))
            except Exception as e:
                err = str(e)
                self.after(0, lambda err=err: self._preview_lbl.config(text=f"Error: {err}", fg=RED))
            self.after(0, lambda: self._print_btn.config(text="⎙ PRINT ALL", state="normal"))
        threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────
# BROWSER WINDOW — standalone multi-tab Chromium (Edge WebView2) via tkwebview2
# Shares Cortex UI's live cookies/session (same Chromium profile dir) and its
# saved-password vault (same browser_passwords.json, same DPAPI-based
# encryption as Electron's safeStorage).
# ─────────────────────────────────────────────
class BrowserWindow(tk.Toplevel):
    def __init__(self, master, on_close=None):
        super().__init__(master, bg=BG_DEEP)
        self.title("iZACH Browser")
        self.geometry("1180x800")
        self.configure(bg=BG_DEEP)
        self.on_close = on_close
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.tabs = []
        self.active_id = None
        self._find_open = False
        self._autofill_entry = None
        self._webview_ok = True

        _patch_shared_webview_profile()
        try:
            from tkwebview2.tkwebview2 import have_runtime
            self._webview_ok = have_runtime()
        except Exception:
            self._webview_ok = False

        self._build()
        if self._webview_ok:
            self.new_tab("https://www.google.com")
        else:
            self._show_runtime_missing()

        self.bind("<Control-t>", lambda e: self.new_tab())
        self.bind("<Control-w>", lambda e: self._close_active_tab())
        self.bind("<Control-Tab>", lambda e: self._cycle_tab(1))
        self.bind("<Control-Shift-Tab>", lambda e: self._cycle_tab(-1))
        self.bind("<Control-l>", lambda e: self._focus_address())
        self.bind("<Control-f>", lambda e: self._toggle_find())
        self.bind("<Alt-Left>", lambda e: self._nav_back())
        self.bind("<Alt-Right>", lambda e: self._nav_forward())
        self.bind("<Control-plus>", lambda e: self._zoom(0.1))
        self.bind("<Control-equal>", lambda e: self._zoom(0.1))
        self.bind("<Control-minus>", lambda e: self._zoom(-0.1))
        self.bind("<Control-0>", lambda e: self._zoom_reset())
        self.bind("<F12>", lambda e: self._toggle_devtools())

        self._poll_active_tab()

    # ── Layout ──────────────────────────────────────────────
    def _build(self):
        tabbar_outer = tk.Frame(self, bg=BG_PANEL, height=34)
        tabbar_outer.pack(fill="x")
        tabbar_outer.pack_propagate(False)
        self._tabbar = tk.Frame(tabbar_outer, bg=BG_PANEL)
        self._tabbar.pack(side="left", fill="both", expand=True)
        tk.Button(tabbar_outer, text="+", command=lambda: self.new_tab(),
                  bg=BG_PANEL, fg=CYAN, font=("Consolas", 12, "bold"), relief="flat",
                  cursor="hand2", activebackground=CYAN_DARK, activeforeground=CYAN,
                  padx=10).pack(side="left", pady=2)

        bar = tk.Frame(self, bg=BG_PANEL, height=42)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        nav_cfg = dict(bg=BG_PANEL, fg=CYAN, font=("Consolas", 11, "bold"),
                       relief="flat", cursor="hand2", activebackground=CYAN_DARK,
                       activeforeground=CYAN, padx=8, pady=4)
        tk.Button(bar, text="‹", command=self._nav_back, **nav_cfg).pack(side="left", padx=(8, 2), pady=6)
        tk.Button(bar, text="›", command=self._nav_forward, **nav_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="↻", command=self._nav_reload, **nav_cfg).pack(side="left", padx=(2, 8), pady=6)

        self._star_btn = tk.Button(bar, text="☆", command=self._toggle_bookmark,
                                   bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 12),
                                   relief="flat", cursor="hand2", activebackground=CYAN_DARK, padx=6)
        self._star_btn.pack(side="left", padx=2, pady=6)

        self._addr = tk.Entry(bar, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                              font=("Consolas", 10), relief="flat",
                              highlightthickness=1, highlightbackground=BORDER_HI)
        self._addr.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8), pady=6)
        self._addr.bind("<Return>", lambda _e: self._go(self._addr.get()))

        self._autofill_btn = tk.Button(bar, text="🔑", command=self._autofill,
                                       bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 10, "bold"),
                                       relief="flat", cursor="hand2", state="disabled",
                                       activebackground=CYAN_DARK, padx=6)
        self._autofill_btn.pack(side="left", padx=2, pady=6)

        small_cfg = dict(bg=BG_PANEL, fg=CYAN, font=("Consolas", 9, "bold"),
                         relief="flat", cursor="hand2", activebackground=CYAN_DARK,
                         activeforeground=CYAN, padx=6, pady=4)
        tk.Button(bar, text="−", command=lambda: self._zoom(-0.1), **small_cfg).pack(side="left", padx=(6, 0), pady=6)
        self._zoom_lbl = tk.Label(bar, text="100%", bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 9))
        self._zoom_lbl.pack(side="left", padx=4)
        tk.Button(bar, text="+", command=lambda: self._zoom(0.1), **small_cfg).pack(side="left", padx=(0, 6), pady=6)

        tk.Button(bar, text="🔍", command=self._toggle_find, **small_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="🛠", command=self._toggle_devtools, **small_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="🕐 HISTORY", command=self._show_history, **small_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="★ BOOKMARKS", command=self._show_bookmarks, **small_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="💾 SAVE LOGIN", command=self._show_save_login, **small_cfg).pack(side="left", padx=2, pady=6)
        tk.Button(bar, text="📱 SEND TO PHONE", command=self._send_to_phone, **small_cfg).pack(side="left", padx=2, pady=6)

        tk.Button(bar, text="✕ CLOSE", command=self._close,
                 bg=BG_PANEL, fg=RED, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", activebackground="#2a0000",
                 activeforeground=RED, padx=10, pady=4).pack(side="right", padx=8, pady=6)

        tk.Button(bar, text="📲 PHONE TABS", command=self._show_phone_tabs,
                 bg=BG_PANEL, fg=CYAN, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", activebackground=CYAN_DARK,
                 activeforeground=CYAN, padx=8, pady=4).pack(side="right", padx=(0, 4), pady=6)

        self._findbar = tk.Frame(self, bg=BG_CARD, height=36)
        self._find_input = tk.Entry(self._findbar, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                    font=("Consolas", 10), relief="flat",
                                    highlightthickness=1, highlightbackground=BORDER_HI)
        self._find_input.pack(side="left", fill="x", expand=True, ipady=4, padx=(10, 6), pady=6)
        self._find_input.bind("<Return>", lambda e: self._find_next())
        self._find_input.bind("<KeyRelease>", lambda e: self._find_live())
        self._find_count = tk.Label(self._findbar, text="0/0", bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 9))
        self._find_count.pack(side="left", padx=6)
        tk.Button(self._findbar, text="▲", command=lambda: self._find_next(back=True), **small_cfg).pack(side="left", padx=2)
        tk.Button(self._findbar, text="▼", command=lambda: self._find_next(back=False), **small_cfg).pack(side="left", padx=2)
        tk.Button(self._findbar, text="✕", command=self._toggle_find, **small_cfg).pack(side="left", padx=(2, 10))

        self._body = tk.Frame(self, bg=BG_DEEP)
        self._body.pack(fill="both", expand=True)

    def _show_runtime_missing(self, extra=""):
        tk.Label(self._body, text="Microsoft Edge WebView2 Runtime not found.\n\n"
                 "Install it from https://developer.microsoft.com/microsoft-edge/webview2/\n"
                 "then reopen the browser.\n" + extra,
                bg=BG_DEEP, fg=AMBER, font=("Consolas", 10), justify="center", wraplength=700).pack(expand=True)

    def _close(self):
        for tab in self.tabs:
            try:
                tab["webview"].destroy()
            except Exception:
                pass
        self.destroy()
        if self.on_close:
            self.on_close()

    # ── Non-modal dialogs. tkinter's built-in messagebox/simpledialog use a
    # blocking wait_window() loop, which crashes the interpreter once
    # pythonnet/WebView2 is active in the process (GIL corruption on nested
    # Tcl event loops) — these plain-Toplevel + callback versions avoid that
    # blocking loop entirely. ──
    def _notify(self, title, text):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=BG_PANEL)
        win.geometry("340x150")
        tk.Label(win, text=text, bg=BG_PANEL, fg=TEXT_PRI, font=("Consolas", 9),
                wraplength=300, justify="left").pack(padx=16, pady=16, expand=True)
        tk.Button(win, text="OK", command=win.destroy,
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"), relief="flat",
                 cursor="hand2", padx=14, pady=5).pack(pady=(0, 14))

    def _prompt_text(self, title, label, default, on_result):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=BG_PANEL)
        win.geometry("300x150")
        tk.Label(win, text=label, bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 9)).pack(
            anchor="w", padx=14, pady=(14, 4))
        e = tk.Entry(win, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN, font=("Consolas", 10),
                    relief="flat", highlightthickness=1, highlightbackground=BORDER_HI)
        e.pack(fill="x", padx=14, ipady=5)
        e.insert(0, default)
        e.focus_set()
        e.select_range(0, "end")

        state = {"done": False}

        def _finish(value):
            if state["done"]:
                return
            state["done"] = True
            win.destroy()
            on_result(value)

        btn_row = tk.Frame(win, bg=BG_PANEL)
        btn_row.pack(pady=14)
        tk.Button(btn_row, text="OK", command=lambda: _finish(e.get()),
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"), relief="flat",
                 cursor="hand2", padx=12, pady=4).pack(side="left", padx=4)
        tk.Button(btn_row, text="CANCEL", command=lambda: _finish(None),
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 9, "bold"), relief="flat",
                 cursor="hand2", padx=12, pady=4).pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: _finish(e.get()))
        win.protocol("WM_DELETE_WINDOW", lambda: _finish(None))

    # ── Tabs ────────────────────────────────────────────────
    # Each tab is a full separate native WebView2 process that stays alive at
    # full memory cost until its tab is explicitly closed — switching tabs
    # only hides them, it never frees anything. Capping the tab count is a
    # simple guardrail against unbounded RAM growth over a long session.
    MAX_TABS = 6

    def new_tab(self, url=None):
        if not self._webview_ok:
            return
        if len(self.tabs) >= self.MAX_TABS:
            self._notify("Browser", f"Tab limit reached ({self.MAX_TABS}) — close a tab before opening another.")
            return
        url = url or "https://www.google.com"
        tab_id = uuid.uuid4().hex[:10]
        from tkwebview2.tkwebview2 import WebView2
        try:
            wv = WebView2(self._body, width=1100, height=700, url=url)
        except Exception as e:
            self._show_runtime_missing(str(e))
            return
        tab = {"id": tab_id, "webview": wv, "url": url, "title": url,
               "history": [url], "hist_idx": 0}
        self.tabs.append(tab)
        self._switch_tab(tab_id)

    def _render_tabbar(self):
        for w in self._tabbar.winfo_children():
            w.destroy()
        for tab in self.tabs:
            active = tab["id"] == self.active_id
            bg = CYAN_DARK if active else BG_PANEL
            f = tk.Frame(self._tabbar, bg=bg, highlightthickness=1,
                        highlightbackground=BORDER_HI if active else bg)
            f.pack(side="left", padx=(0, 1), pady=2, fill="y")
            label = (tab["title"] or tab["url"])[:22]
            lbl = tk.Label(f, text=label, bg=bg, fg=CYAN if active else TEXT_SEC,
                          font=("Consolas", 9), padx=8, pady=4, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, tid=tab["id"]: self._switch_tab(tid))
            close_btn = tk.Label(f, text="✕", bg=bg, fg=TEXT_SEC, font=("Consolas", 8), padx=6, cursor="hand2")
            close_btn.pack(side="left")
            close_btn.bind("<Button-1>", lambda e, tid=tab["id"]: self._close_tab(tid))

    def _switch_tab(self, tab_id):
        self.active_id = tab_id
        for tab in self.tabs:
            if tab["id"] == tab_id:
                tab["webview"].place(x=0, y=0, relwidth=1, relheight=1)
                tab["webview"].lift()
                self._addr.delete(0, "end")
                self._addr.insert(0, tab["url"])
                try:
                    self._zoom_lbl.config(text=f'{round(tab["webview"].web.ZoomFactor * 100)}%')
                except Exception:
                    self._zoom_lbl.config(text="100%")
            else:
                tab["webview"].place_forget()
        self._render_tabbar()
        self._sync_bookmark_btn()
        self._sync_autofill_btn()
        if self._find_open:
            self._toggle_find(force_close=True)

    def _close_tab(self, tab_id):
        idx = next((i for i, t in enumerate(self.tabs) if t["id"] == tab_id), None)
        if idx is None:
            return
        tab = self.tabs.pop(idx)
        try:
            tab["webview"].destroy()
        except Exception:
            pass
        if not self.tabs:
            self._close()
            return
        if self.active_id == tab_id:
            new_idx = min(idx, len(self.tabs) - 1)
            self._switch_tab(self.tabs[new_idx]["id"])
        else:
            self._render_tabbar()

    def _close_active_tab(self):
        if self.active_id:
            self._close_tab(self.active_id)

    def _cycle_tab(self, direction):
        if len(self.tabs) < 2:
            return
        idx = next((i for i, t in enumerate(self.tabs) if t["id"] == self.active_id), 0)
        nxt = (idx + direction) % len(self.tabs)
        self._switch_tab(self.tabs[nxt]["id"])

    def _active_tab(self):
        return next((t for t in self.tabs if t["id"] == self.active_id), None)

    def _go_in_active_or_new(self, url):
        if self.active_id:
            self._go(url)
        else:
            self.new_tab(url)

    # ── Navigation ──────────────────────────────────────────
    def _go(self, value):
        tab = self._active_tab()
        value = (value or "").strip()
        if not value or not tab:
            return
        looks_like_url = bool(re.match(r'^https?://', value, re.IGNORECASE)) or (
            bool(re.match(r'^[\w.-]+\.[a-z]{2,}(/.*)?$', value, re.IGNORECASE)) and ' ' not in value
        )
        if looks_like_url:
            url = value if value.lower().startswith(("http://", "https://")) else f"https://{value}"
        else:
            url = f"https://www.google.com/search?q={quote(value)}"

        tab["webview"].load_url(url)
        tab["url"] = url
        self._addr.delete(0, "end")
        self._addr.insert(0, url)
        tab["history"] = tab["history"][:tab["hist_idx"] + 1]
        tab["history"].append(url)
        tab["hist_idx"] = len(tab["history"]) - 1
        self._sync_bookmark_btn()
        self._sync_autofill_btn()

    def _nav_back(self):
        tab = self._active_tab()
        if tab and tab["hist_idx"] > 0:
            tab["hist_idx"] -= 1
            url = tab["history"][tab["hist_idx"]]
            tab["webview"].load_url(url)
            tab["url"] = url
            self._addr.delete(0, "end"); self._addr.insert(0, url)

    def _nav_forward(self):
        tab = self._active_tab()
        if tab and tab["hist_idx"] < len(tab["history"]) - 1:
            tab["hist_idx"] += 1
            url = tab["history"][tab["hist_idx"]]
            tab["webview"].load_url(url)
            tab["url"] = url
            self._addr.delete(0, "end"); self._addr.insert(0, url)

    def _nav_reload(self):
        tab = self._active_tab()
        if tab:
            tab["webview"].reload()

    def _focus_address(self):
        self._addr.focus_set()
        self._addr.select_range(0, "end")

    # ── Title/URL sync + history logging ───────────────────
    def _poll_active_tab(self):
        if not self.winfo_exists():
            return
        tab = self._active_tab()
        if tab:
            try:
                url = tab["webview"].get_url()
            except Exception:
                url = None
            if url and url != tab["url"]:
                tab["url"] = url
                if tab["id"] == self.active_id:
                    self._addr.delete(0, "end"); self._addr.insert(0, url)
                self._sync_bookmark_btn()
                self._sync_autofill_btn()

            def _cb(title, tab=tab):
                if title and title != tab["title"]:
                    tab["title"] = title
                    self._render_tabbar()
                    self._log_history(tab["url"], title)
            try:
                tab["webview"].evaluate_js("document.title", _cb)
            except Exception:
                pass
        self.after(1500, self._poll_active_tab)

    # ── Zoom ────────────────────────────────────────────────
    def _zoom(self, delta):
        tab = self._active_tab()
        if not tab:
            return
        try:
            newz = max(0.25, min(5.0, tab["webview"].web.ZoomFactor + delta))
            tab["webview"].web.ZoomFactor = newz
            self._zoom_lbl.config(text=f"{round(newz * 100)}%")
        except Exception:
            pass

    def _zoom_reset(self):
        tab = self._active_tab()
        if not tab:
            return
        try:
            tab["webview"].web.ZoomFactor = 1.0
            self._zoom_lbl.config(text="100%")
        except Exception:
            pass

    # ── DevTools ────────────────────────────────────────────
    def _toggle_devtools(self):
        tab = self._active_tab()
        if tab and getattr(tab["webview"], "core", None):
            try:
                tab["webview"].core.OpenDevToolsWindow()
            except Exception:
                pass

    # ── Find in page ────────────────────────────────────────
    def _toggle_find(self, force_close=False):
        if self._find_open or force_close:
            self._findbar.pack_forget()
            self._find_open = False
            tab = self._active_tab()
            if tab:
                self._find_js(tab, "")
        else:
            self._findbar.pack(fill="x", before=self._body)
            self._find_open = True
            self._find_input.focus_set()

    def _find_js(self, tab, term, direction=0):
        script = f"""
        (function(term, direction){{
          document.querySelectorAll('mark[data-izach-find]').forEach(function(m){{
            var t = document.createTextNode(m.textContent);
            m.replaceWith(t);
          }});
          if(!term){{ return JSON.stringify({{count:0, idx:0}}); }}
          var re = new RegExp(term.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&'), 'gi');
          var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          var nodes = [];
          var n;
          while(n = walker.nextNode()) {{
            if(n.parentElement && ['SCRIPT','STYLE'].indexOf(n.parentElement.tagName) !== -1) continue;
            if(re.test(n.textContent)) nodes.push(n);
            re.lastIndex = 0;
          }}
          nodes.forEach(function(node){{
            var span = document.createElement('span');
            span.innerHTML = node.textContent.replace(re, function(m){{ return '<mark data-izach-find style="background:#ffb300;color:#000">' + m + '</mark>'; }});
            node.replaceWith(span);
          }});
          var marks = document.querySelectorAll('mark[data-izach-find]');
          if(!marks.length) return JSON.stringify({{count:0, idx:0}});
          var idx = window.__izachFindIdx || 0;
          idx = ((idx + direction) % marks.length + marks.length) % marks.length;
          window.__izachFindIdx = idx;
          marks[idx].scrollIntoView({{block:'center'}});
          marks[idx].style.background = '#ff3d3d';
          return JSON.stringify({{count: marks.length, idx: idx + 1}});
        }})({json.dumps(term)}, {direction})
        """
        def _cb(res):
            try:
                data = json.loads(res) if res else {"count": 0, "idx": 0}
                self._find_count.config(text=f'{data["idx"]}/{data["count"]}')
            except Exception:
                pass
        try:
            tab["webview"].evaluate_js(script, _cb)
        except Exception:
            pass

    def _find_live(self):
        tab = self._active_tab()
        term = self._find_input.get().strip()
        if tab:
            self._find_js(tab, term, 0)

    def _find_next(self, back=False):
        tab = self._active_tab()
        term = self._find_input.get().strip()
        if not tab or not term:
            return
        self._find_js(tab, term, -1 if back else 1)

    # ── Bookmarks ───────────────────────────────────────────
    # NOTE: all HTTP calls below run synchronously on the Tk main thread
    # rather than on background threading.Thread workers. Once WebView2 (via
    # pythonnet/CLR) is active in this process, background Python threads
    # racing against WebView2's own native callback threads reliably crash
    # the interpreter (PyEval_RestoreThread/GIL corruption — a pythonnet
    # + concurrent-Python-threads incompatibility, not a bug in this code).
    # These are all localhost calls to the Flask backend, so a synchronous
    # call is a sub-second blip in the success case; on failure it blocks for
    # up to the given timeout rather than crashing.
    def _sync_bookmark_btn(self):
        tab = self._active_tab()
        if not tab:
            return
        url = tab["url"]
        try:
            links = requests.get(f"{_API}/api/custom_links", timeout=4).json()
            starred = any(b.get("url") == url for b in links)
        except Exception:
            starred = False
        self._star_btn.config(text="★" if starred else "☆", fg=AMBER if starred else TEXT_SEC)

    def _toggle_bookmark(self):
        tab = self._active_tab()
        if not tab:
            return
        url, title = tab["url"], tab["title"] or tab["url"]
        try:
            links = requests.get(f"{_API}/api/custom_links", timeout=4).json()
        except Exception:
            self._notify("Bookmarks", "Couldn't reach iZACH backend.")
            return
        existing = any(b.get("url") == url for b in links)
        self._finish_bookmark_toggle(links, url, title, existing)

    def _finish_bookmark_toggle(self, links, url, title, existing):
        if existing:
            new_links = [b for b in links if b.get("url") != url]
            self._save_bookmarks(new_links)
        else:
            def _on_folder(folder):
                if folder is None:
                    return
                new_links = links + [{"title": title, "url": url, "folder": (folder or "General").strip() or "General"}]
                self._save_bookmarks(new_links)
            self._prompt_text("Bookmark folder", "Folder (optional):", "General", _on_folder)

    def _save_bookmarks(self, new_links):
        try:
            requests.post(f"{_API}/api/custom_links", json=new_links, timeout=5)
        except Exception:
            pass
        self._sync_bookmark_btn()

    def _show_bookmarks(self):
        win = tk.Toplevel(self)
        win.title("Bookmarks")
        win.configure(bg=BG_PANEL)
        win.geometry("460x420")
        tk.Label(win, text="BOOKMARKS", bg=BG_PANEL, fg=CYAN,
                font=("Consolas", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 6))

        container = tk.Frame(win, bg=BG_PANEL)
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        def _load():
            try:
                links = requests.get(f"{_API}/api/custom_links", timeout=5).json()
            except Exception:
                links = None
            _render(links)

        def _render(links):
            for w in container.winfo_children():
                w.destroy()
            if links is None:
                tk.Label(container, text="Couldn't reach the backend.", bg=BG_PANEL, fg=AMBER,
                        font=("Consolas", 9)).pack(pady=20)
                return
            if not links:
                tk.Label(container, text="No bookmarks yet.", bg=BG_PANEL, fg=TEXT_SEC,
                        font=("Consolas", 9)).pack(pady=20)
                return
            groups = {}
            for b in links:
                groups.setdefault(b.get("folder") or "General", []).append(b)
            for folder in sorted(groups.keys()):
                tk.Label(container, text=folder.upper(), bg=BG_PANEL, fg=CYAN,
                        font=("Consolas", 9, "bold")).pack(anchor="w", pady=(8, 2))
                for b in groups[folder]:
                    row = tk.Frame(container, bg=BG_CARD)
                    row.pack(fill="x", pady=1)
                    lbl = tk.Label(row, text=b.get("title") or b.get("url"), bg=BG_CARD, fg=TEXT_PRI,
                                  font=("Consolas", 9), anchor="w", cursor="hand2")
                    lbl.pack(side="left", fill="x", expand=True, padx=6, pady=3)
                    lbl.bind("<Button-1>", lambda e, u=b.get("url"): (win.destroy(), self._go_in_active_or_new(u)))
                    rm = tk.Label(row, text="✕", bg=BG_CARD, fg=RED, font=("Consolas", 8), cursor="hand2", padx=6)
                    rm.pack(side="right")
                    rm.bind("<Button-1>", lambda e, u=b.get("url"): _remove(u))

        def _remove(url):
            try:
                links = requests.get(f"{_API}/api/custom_links", timeout=5).json()
                links = [b for b in links if b.get("url") != url]
                requests.post(f"{_API}/api/custom_links", json=links, timeout=5)
            except Exception:
                pass
            _load()

        _load()

    # ── History ─────────────────────────────────────────────
    def _log_history(self, url, title):
        if not url or url.startswith("data:"):
            return
        try:
            requests.post(f"{_API}/browser/history", json={"url": url, "title": title, "device": "pc"}, timeout=4)
        except Exception:
            pass

    def _show_history(self):
        win = tk.Toplevel(self)
        win.title("Browser History")
        win.configure(bg=BG_PANEL)
        win.geometry("520x420")

        top = tk.Frame(win, bg=BG_PANEL)
        top.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(top, text="HISTORY", bg=BG_PANEL, fg=CYAN, font=("Consolas", 10, "bold")).pack(side="left")
        tk.Button(top, text="CLEAR ALL", command=lambda: self._history_clear_all(win),
                 bg=BG_PANEL, fg=RED, font=("Consolas", 8, "bold"), relief="flat",
                 cursor="hand2", padx=6).pack(side="right")

        search = tk.Entry(win, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN, font=("Consolas", 9),
                          relief="flat", highlightthickness=1, highlightbackground=BORDER_HI)
        search.pack(fill="x", padx=12, pady=(0, 8), ipady=4)

        lb = tk.Listbox(win, bg="#010814", fg="#60b8d0", font=("Consolas", 9),
                        relief="flat", highlightthickness=1, highlightbackground=BORDER_HI,
                        selectbackground=CYAN_DARK, selectforeground=CYAN)
        lb.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        rows_ref = {"rows": []}

        def _apply(entries):
            lb.delete(0, "end")
            rows_ref["rows"] = entries or []
            if entries is None:
                lb.insert("end", "  Couldn't reach the backend.")
                return
            if not entries:
                lb.insert("end", "  No history yet.")
                return
            for e in entries:
                lb.insert("end", f'{e.get("title") or e.get("url")}  —  {e.get("url")}')

        def _load(q=""):
            try:
                r = requests.get(f"{_API}/browser/history", params={"q": q, "limit": 300}, timeout=5).json()
                entries = r.get("entries", [])
            except Exception:
                entries = None
            _apply(entries)

        def _delete_selected():
            sel = lb.curselection()
            if not sel or sel[0] >= len(rows_ref["rows"]):
                return
            entry_id = rows_ref["rows"][sel[0]].get("id")
            try:
                requests.delete(f"{_API}/browser/history/{entry_id}", timeout=5)
            except Exception:
                pass
            _load(search.get().strip())

        def _open_selected(_e=None):
            sel = lb.curselection()
            if not sel or sel[0] >= len(rows_ref["rows"]):
                return
            url = rows_ref["rows"][sel[0]].get("url")
            win.destroy()
            if url:
                self._go_in_active_or_new(url)

        lb.bind("<Double-Button-1>", _open_selected)
        search.bind("<KeyRelease>", lambda e: _load(search.get().strip()))

        btn_row = tk.Frame(win, bg=BG_PANEL)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btn_row, text="OPEN", command=_open_selected,
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left")
        tk.Button(btn_row, text="DELETE", command=_delete_selected,
                 bg="#2a0000", fg=RED, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=(6, 0))

        _load()

    def _history_clear_all(self, win):
        try:
            requests.delete(f"{_API}/browser/history", timeout=5)
        except Exception:
            pass
        win.destroy()

    # ── Send to Phone ───────────────────────────────────────
    def _send_to_phone(self):
        tab = self._active_tab()
        if not tab:
            return
        url, title = tab["url"], tab["title"] or tab["url"]
        try:
            requests.post(f"{_API}/browser/handoff", json={"url": url, "title": title}, timeout=5)
            ok = True
        except Exception:
            ok = False
        self._notify("Send to Phone", "Sent." if ok else "Couldn't reach the backend.")

    # ── Continue a tab from the phone (mirrors Cortex UI's "Tabs from Phone") ──
    def _show_phone_tabs(self):
        rows = None
        try:
            r = requests.get(f"{_API}/browser/tabs?exclude=pc", timeout=5).json()
            rows = []
            for device, info in (r.get("devices") or {}).items():
                for t in info.get("tabs", []):
                    rows.append((device, t.get("title") or t.get("url", ""), t.get("url", "")))
        except Exception as e:
            print(f"[BROWSER] Phone tabs fetch error: {e}")
        self._render_phone_tabs_popup(rows)

    def _render_phone_tabs_popup(self, rows):
        win = tk.Toplevel(self)
        win.title("Tabs from Phone")
        win.configure(bg=BG_PANEL)
        win.geometry("420x320")

        tk.Label(win, text="CONTINUE A TAB FROM PHONE", bg=BG_PANEL, fg=CYAN,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 8))

        if rows is None:
            tk.Label(win, text="Couldn't reach the phone tabs list.",
                     bg=BG_PANEL, fg=AMBER, font=("Consolas", 9)).pack(padx=12, pady=20)
            return
        if not rows:
            tk.Label(win, text="No open tabs on the phone right now.",
                     bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 9)).pack(padx=12, pady=20)
            return

        lb = tk.Listbox(win, bg="#010814", fg="#60b8d0", font=("Consolas", 9),
                        relief="flat", highlightthickness=1, highlightbackground=BORDER_HI,
                        selectbackground=CYAN_DARK, selectforeground=CYAN)
        lb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for device, title, _url in rows:
            lb.insert("end", f"[{device.upper()}] {title}")

        def _open_selected():
            sel = lb.curselection()
            if not sel:
                return
            url = rows[sel[0]][2]
            win.destroy()
            if url:
                self._go_in_active_or_new(url)

        lb.bind("<Double-Button-1>", lambda _e: _open_selected())
        tk.Button(win, text="OPEN", command=_open_selected,
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=4).pack(pady=(0, 12))

    # ── Save a new login ────────────────────────────────────
    def _show_save_login(self):
        tab = self._active_tab()
        default_site = ""
        if tab:
            try:
                default_site = urlparse(tab["url"]).hostname or ""
            except Exception:
                default_site = ""

        win = tk.Toplevel(self)
        win.title("Save Login")
        win.configure(bg=BG_PANEL)
        win.geometry("340x260")

        def _field(label, show=None, default=""):
            tk.Label(win, text=label, bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 9)).pack(
                anchor="w", padx=16, pady=(10, 2))
            e = tk.Entry(win, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN, font=("Consolas", 10),
                        relief="flat", highlightthickness=1, highlightbackground=BORDER_HI, show=show)
            e.pack(fill="x", padx=16, ipady=5)
            if default:
                e.insert(0, default)
            return e

        site_e = _field("Site", default=default_site)
        user_e = _field("Username")
        pass_e = _field("Password", show="•")

        status = tk.Label(win, text="", bg=BG_PANEL, fg=AMBER, font=("Consolas", 8), wraplength=300)
        status.pack(pady=(4, 0))

        def _save():
            site, user, pw = site_e.get().strip(), user_e.get().strip(), pass_e.get()
            if not site or not user or not pw:
                status.config(text="All fields are required.")
                return
            try:
                password_vault.add(site, user, pw)
                win.destroy()
                self._sync_autofill_btn()
            except Exception as e:
                status.config(text=str(e)[:120])

        tk.Button(win, text="SAVE", command=_save,
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", padx=12, pady=6).pack(pady=14)

    # ── Autofill (gated behind the same Windows Hello enrollment Cortex uses) ──
    def _sync_autofill_btn(self):
        tab = self._active_tab()
        if not tab:
            return
        try:
            hostname = urlparse(tab["url"]).hostname or ""
        except Exception:
            hostname = ""
        entry = password_vault.find_for_site(hostname)
        self._autofill_entry = entry
        self._autofill_btn.config(state=("normal" if entry else "disabled"),
                                  fg=(CYAN if entry else TEXT_SEC))

    def _autofill(self):
        entry = self._autofill_entry
        tab = self._active_tab()
        if not entry or not tab:
            return
        credential_id = password_vault.is_webauthn_enrolled()
        if not credential_id:
            self._notify("Autofill",
                "Set up Windows Hello for autofill in Cortex UI's Browser Settings first.")
            return
        self._run_webauthn_verify(credential_id, lambda ok: self._finish_autofill(ok, entry, tab))

    def _finish_autofill(self, ok, entry, tab):
        if not ok:
            return
        try:
            username, password = password_vault.reveal(entry["id"])
        except Exception as e:
            self._notify("Autofill", f"Couldn't read saved password: {e}")
            return
        script = f"""
        (function(u, p){{
          function setNativeValue(el, value){{
            var proto = Object.getPrototypeOf(el);
            var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', {{bubbles:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
          }}
          var pwd = document.querySelector('input[type=password]');
          if(pwd) setNativeValue(pwd, p);
          var userEl = document.querySelector('input[type=email]') ||
                       document.querySelector('input[autocomplete=username]') ||
                       document.querySelector('input[type=text]');
          if(userEl) setNativeValue(userEl, u);
        }})({json.dumps(username)}, {json.dumps(password)})
        """
        try:
            tab["webview"].evaluate_js(script)
        except Exception as e:
            self._notify("Autofill", f"Injection failed: {e}")

    def _run_webauthn_verify(self, credential_id, on_done):
        gate = tk.Toplevel(self)
        gate.title("Windows Hello")
        gate.geometry("360x220")
        gate.configure(bg=BG_DEEP)
        from tkwebview2.tkwebview2 import WebView2
        url = f"{_API}/browser/webauthn-gate?mode=verify&credential_id={quote(credential_id)}"
        wv = WebView2(gate, width=360, height=220, url=url)
        wv.pack(fill="both", expand=True)

        state = {"done": False, "ticks": 0}

        def _poll():
            if state["done"] or not gate.winfo_exists():
                return
            state["ticks"] += 1

            def _cb(res):
                if state["done"]:
                    return
                text = (res or "").strip().strip('"')
                if text in ("Verified", "Not supported") or text.startswith("Cancelled"):
                    state["done"] = True
                    ok = (text == "Verified")
                    try:
                        gate.destroy()
                    except Exception:
                        pass
                    on_done(ok)
            try:
                wv.evaluate_js(
                    "document.getElementById('status') ? document.getElementById('status').textContent : ''",
                    _cb)
            except Exception:
                pass
            if state["ticks"] > 160:  # ~64s timeout
                state["done"] = True
                try:
                    gate.destroy()
                except Exception:
                    pass
                on_done(False)
                return
            gate.after(400, _poll)

        def _on_gate_close():
            state["done"] = True
            gate.destroy()
            on_done(False)

        gate.protocol("WM_DELETE_WINDOW", _on_gate_close)
        gate.after(600, _poll)


# ─────────────────────────────────────────────
# SETTINGS PAGE
# ─────────────────────────────────────────────
class SettingsPage(tk.Frame):
    # Tab key -> (label, builder-method-name(s) run in order to populate self._body)
    _TABS = [
        ("memory",     "MEMORY",                          ["_build_memory_section"]),
        ("personal",   "PERSONALISATION",                 ["_build_voice_section", "_build_proactive_section"]),
        ("appearance", "APPEARANCE",                       ["_build_appearance_section"]),
        ("device",     "DEVICE CONNECTION",                ["_build_device_connection_section", "_build_phone_pairing_section"]),
        ("notif",      "NOTIFICATIONS AND ANNOUNCEMENTS",  ["_build_meetings_section", "_build_notifications_section"]),
        ("services",   "CONNECTED SERVICES",               ["_build_email_agent_section", "_build_connected_services_section"]),
        ("boot",       "BOOT SETTINGS",                    ["_build_boot_settings_section"]),
        ("keys",       "KEYS & ID",                        ["_build_api_section"]),
        ("contacts",   "CONTACTS",                         ["_build_contacts_section"]),
        ("security",   "SECURITY",                         ["_build_security_section"]),
        ("commands",   "COMMANDS",                         ["_build_commands_section"]),
        ("links",      "CUSTOM LINKS",                     ["_build_custom_websites_section"]),
        ("others",     "OTHERS",                           ["_build_others_section"]),
        ("advanced",   "ADVANCED",                         ["_build_advanced_section"]),
        ("about",      "ABOUT iZACH",                      ["_build_dashboard_section", "_build_about_section"]),
    ]

    def __init__(self, parent, on_close, **kw):
        super().__init__(parent, bg=BG_DEEP, **kw)
        self.on_close = on_close
        self._memory_rows = []
        self._active_tab = self._TABS[0][0]
        self._build()
        self._switch_settings_tab(self._active_tab)

    def _build(self):
        # Header
        header = tk.Frame(self, bg=BG_PANEL, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="⚙  iZACH FORGE SETTINGS",
                 bg=BG_PANEL, fg=CYAN,
                 font=("Consolas", 13, "bold")).pack(side="left", padx=16, pady=10)

        tk.Button(header, text="✕  BACK",
                  bg=BG_PANEL, fg=RED,
                  font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2",
                  activebackground="#1a0000",
                  command=self._close,
                  padx=12, pady=4).pack(side="right", padx=16, pady=8)

        # Horizontally-scrollable tab strip
        tabstrip_outer = tk.Frame(self, bg=BG_PANEL, height=34)
        tabstrip_outer.pack(fill="x")
        tabstrip_outer.pack_propagate(False)

        self._tab_canvas = tk.Canvas(tabstrip_outer, bg=BG_PANEL, highlightthickness=0, height=34)
        self._tab_canvas.pack(fill="both", expand=True)

        self._tab_bar = tk.Frame(self._tab_canvas, bg=BG_PANEL)
        self._tab_bar_win = self._tab_canvas.create_window((0, 0), window=self._tab_bar, anchor="nw")
        self._tab_bar.bind("<Configure>", lambda e: self._tab_canvas.configure(
            scrollregion=self._tab_canvas.bbox("all")))

        def _tab_wheel(e):
            step = int(-1 * (e.delta / 120))
            self._tab_canvas.xview_scroll(step, "units")
        # Windows sends vertical deltas on <MouseWheel> for both plain and
        # shift-scroll — bind both so either scroll gesture moves the tab strip.
        self._tab_canvas.bind("<MouseWheel>", _tab_wheel)
        self._tab_canvas.bind("<Shift-MouseWheel>", _tab_wheel)

        self._tab_drag_x = None
        def _tab_drag_start(e):
            self._tab_drag_x = e.x
        def _tab_drag_move(e):
            if self._tab_drag_x is None:
                return
            dx = e.x - self._tab_drag_x
            self._tab_canvas.xview_scroll(int(-dx / 4), "units")
            self._tab_drag_x = e.x
        self._tab_canvas.bind("<ButtonPress-1>", _tab_drag_start)
        self._tab_canvas.bind("<B1-Motion>", _tab_drag_move)

        self._tab_buttons = {}
        for key, label, _builders in self._TABS:
            f = tk.Frame(self._tab_bar, bg=BG_PANEL)
            f.pack(side="left", padx=(0, 1), pady=2, fill="y")
            lbl = tk.Label(f, text=label, bg=BG_PANEL, fg=TEXT_SEC,
                          font=("Consolas", 8, "bold"), padx=10, pady=6, cursor="hand2")
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, k=key: self._switch_settings_tab(k))
            lbl.bind("<MouseWheel>", _tab_wheel)
            lbl.bind("<Shift-MouseWheel>", _tab_wheel)
            self._tab_buttons[key] = (f, lbl)

        # Scrollable body
        body_outer = tk.Frame(self, bg=BG_DEEP)
        body_outer.pack(fill="both", expand=True, padx=16, pady=10)

        canvas = tk.Canvas(body_outer, bg=BG_DEEP, highlightthickness=0)
        scrollbar = tk.Scrollbar(body_outer, orient="vertical",
                                  command=canvas.yview,
                                  bg=BG_PANEL, troughcolor=BG_DEEP)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._body_canvas = canvas
        self._body = tk.Frame(canvas, bg=BG_DEEP)
        self._body_win = canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._body_win, width=e.width))

        def _body_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _body_wheel)
        self._body.bind("<MouseWheel>", _body_wheel)

    def _switch_settings_tab(self, key):
        self._active_tab = key
        for k, (f, lbl) in self._tab_buttons.items():
            active = (k == key)
            bg = CYAN_DARK if active else BG_PANEL
            f.configure(bg=bg)
            lbl.configure(bg=bg, fg=CYAN if active else TEXT_SEC)

        for w in self._body.winfo_children():
            w.destroy()

        builders = next(b for k2, _lbl, b in self._TABS if k2 == key)
        for name in builders:
            getattr(self, name)()

        self._body_canvas.yview_moveto(0)

    def _section(self, title):
        card = _card(self._body)
        card.pack(fill="x", pady=(0, 12))
        _section_header(card, title)
        return card

    # ── Phone Pairing Section (mirrors Cortex UI's phone-connection QR panel) ──
    def _build_phone_pairing_section(self):
        card = self._section("PHONE PAIRING")

        tk.Label(card,
                 text="Scan this QR with the iZACH Android app (Settings → Scan QR Code) to pair.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8),
                 wraplength=520, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        body = tk.Frame(card, bg=BG_CARD)
        body.pack(fill="x", padx=12, pady=(0, 10))

        self._qr_label = tk.Label(body, bg=BG_CARD, text="loading…", fg=TEXT_SEC,
                                   font=("Consolas", 8), width=18, height=9)
        self._qr_label.pack(side="left", padx=(0, 16))

        right = tk.Frame(body, bg=BG_CARD)
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="PAIRING SECRET (manual entry)", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(anchor="w")
        self._pairing_secret_label = tk.Label(right, text="—", bg=BG_CARD, fg=CYAN,
                                               font=("Consolas", 9), wraplength=320, justify="left")
        self._pairing_secret_label.pack(anchor="w", pady=(2, 8))

        btn_row = tk.Frame(right, bg=BG_CARD)
        btn_row.pack(anchor="w")
        tk.Button(btn_row, text="COPY SECRET", bg=CYAN_DARK, fg=CYAN,
                  font=("Consolas", 8, "bold"), relief="flat", cursor="hand2",
                  command=self._copy_pairing_secret, padx=8, pady=3).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="↻ REFRESH", bg=BG_PANEL, fg=TEXT_SEC,
                  font=("Consolas", 8, "bold"), relief="flat", cursor="hand2",
                  command=self._load_phone_pairing_ui, padx=8, pady=3).pack(side="left")

        self._load_phone_pairing_ui()

    def _load_phone_pairing_ui(self):
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/connect/qr", timeout=8).json()
                qr_b64 = r.get("qr_base64", "")
                secret = r.get("pairing_secret", "")
                photo = None
                if qr_b64:
                    import base64, io
                    img = Image.open(io.BytesIO(base64.b64decode(qr_b64))).resize((140, 140))
                    photo = ImageTk.PhotoImage(img)

                def _apply():
                    if photo is not None:
                        self._qr_label.config(image=photo, text="")
                        self._qr_label.image = photo  # keep a reference, Tk drops it otherwise
                    self._pairing_secret_label.config(text=secret or "—")
                self._safe_after(0, _apply)
            except Exception as e:
                print(f"[SETTINGS] Phone pairing load error: {e}")
                self._safe_after(0, lambda: self._qr_label.config(text="unavailable", fg=AMBER))
        threading.Thread(target=_work, daemon=True).start()

    def _copy_pairing_secret(self):
        secret = self._pairing_secret_label.cget("text")
        if secret and secret != "—":
            self.clipboard_clear()
            self.clipboard_append(secret)

    # ── "What's Running" dashboard (mirrors Cortex UI's STATUS DASHBOARD panel) ──
    def _build_dashboard_section(self):
        card = self._section("WHAT'S RUNNING")
        self._dash_rows = {}
        for label in ["RECORDINGS", "AUTOMATIONS", "DO NOT DISTURB", "DOWNLOADS", "PHONE"]:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=f"{label:<16}", bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8), width=18, anchor="w").pack(side="left")
            val = tk.Label(row, text="loading…", bg=BG_CARD, fg=TEXT_PRI, font=("Consolas", 8, "bold"))
            val.pack(side="left", padx=8)
            self._dash_rows[label] = val
        tk.Button(card, text="↻ REFRESH", bg=BG_PANEL, fg=TEXT_SEC,
                  font=("Consolas", 8, "bold"), relief="flat", cursor="hand2",
                  command=self._load_dashboard_ui, padx=8, pady=3).pack(anchor="w", padx=12, pady=(6, 10))

        self._load_dashboard_ui()

    def _load_dashboard_ui(self):
        def _work():
            results = {}
            try:
                d = requests.get("http://127.0.0.1:5050/browser/recordings", timeout=5).json()
                recs = d.get("recordings", [])
                scheduled = sum(1 for r in recs if r.get("schedule_cron"))
                results["RECORDINGS"] = (f"{len(recs)} saved" + (f" · {scheduled} scheduled" if scheduled else ""), TEXT_PRI)
            except Exception:
                results["RECORDINGS"] = ("unavailable", AMBER)
            try:
                d = requests.get("http://127.0.0.1:5050/smart-memory?category=automation", timeout=5).json()
                items = d.get("data", [])
                active = sum(1 for i in items if i.get("enabled", True) is not False)
                results["AUTOMATIONS"] = (f"{active}/{len(items)} active", TEXT_PRI)
            except Exception:
                results["AUTOMATIONS"] = ("unavailable", AMBER)
            try:
                d = requests.get("http://127.0.0.1:5050/dnd", timeout=5).json()
                active = bool(d.get("active"))
                results["DO NOT DISTURB"] = ("ON" if active else "OFF", AMBER if active else TEXT_PRI)
            except Exception:
                results["DO NOT DISTURB"] = ("unavailable", AMBER)
            try:
                d = requests.get("http://127.0.0.1:5050/downloads/active", timeout=5).json()
                active = len(d.get("downloads") or d.get("active") or [])
                results["DOWNLOADS"] = (f"{active} in progress" if active else "idle", CYAN if active else TEXT_PRI)
            except Exception:
                results["DOWNLOADS"] = ("unavailable", AMBER)
            try:
                d = requests.get("http://127.0.0.1:5050/phone/status", timeout=5).json()
                connected = bool(d.get("connected"))
                label = f"paired · {d.get('device_name') or 'device'}" if connected else "not connected"
                results["PHONE"] = (label, GREEN if connected else TEXT_PRI)
            except Exception:
                results["PHONE"] = ("unavailable", AMBER)

            def _apply():
                for label, (text, color) in results.items():
                    if label in self._dash_rows:
                        self._dash_rows[label].config(text=text, fg=color)
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    # ── Memory Section ──
    def _build_memory_section(self):
        card = self._section("PERSONAL MEMORY")

        info = tk.Label(card,
                        text="iZACH uses this to understand you. Add facts about yourself.",
                        bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        info.pack(anchor="w", padx=12, pady=(0, 8))

        self._memory_frame = tk.Frame(card, bg=BG_CARD)
        self._memory_frame.pack(fill="x", padx=12, pady=(0, 6))

        # Add new memory row
        add_row = tk.Frame(card, bg=BG_CARD)
        add_row.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(add_row, text="KEY", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")

        self._mem_key_entry = tk.Entry(add_row, bg=BG_DEEP, fg=CYAN,
                                       insertbackground=CYAN,
                                       font=("Consolas", 9), relief="flat",
                                       highlightthickness=1,
                                       highlightbackground=BORDER_HI,
                                       width=18)
        self._mem_key_entry.pack(side="left", padx=(4, 8), ipady=4)

        tk.Label(add_row, text="VALUE", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")

        self._mem_val_entry = tk.Entry(add_row, bg=BG_DEEP, fg=CYAN,
                                       insertbackground=CYAN,
                                       font=("Consolas", 9), relief="flat",
                                       highlightthickness=1,
                                       highlightbackground=BORDER_HI,
                                       width=30)
        self._mem_val_entry.pack(side="left", padx=(4, 8), ipady=4)

        tk.Button(add_row, text="ADD",
                  bg=GREEN_DIM, fg=GREEN,
                  font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2",
                  command=self._add_memory,
                  padx=10, pady=3).pack(side="left")

        self._load_memory_ui()

    def _load_memory_ui(self):
        for w in self._memory_frame.winfo_children():
            w.destroy()
        from modules.memory import list_memory
        items = list_memory()
        if not items:
            tk.Label(self._memory_frame, text="No memory entries yet.",
                     bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8)).pack(anchor="w")
            return
        for key, val, added in items:
            row = tk.Frame(self._memory_frame, bg="#0a1e10",
                           highlightthickness=1, highlightbackground=GREEN_DIM)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{key}:", bg="#0a1e10", fg=GREEN,
                     font=("Consolas", 8, "bold"), width=20,
                     anchor="w").pack(side="left", padx=(8, 4), pady=4)
            tk.Label(row, text=val, bg="#0a1e10", fg=TEXT_PRI,
                     font=("Consolas", 8), anchor="w").pack(side="left",
                                                             fill="x", expand=True)
            tk.Label(row, text=added, bg="#0a1e10", fg=TEXT_SEC,
                     font=("Consolas", 7)).pack(side="left", padx=8)
            tk.Button(row, text="✕",
                      bg="#0a1e10", fg=RED,
                      font=("Consolas", 9), relief="flat",
                      cursor="hand2",
                      command=lambda k=key: self._delete_memory(k),
                      padx=6).pack(side="right", padx=4)

    def _add_memory(self):
        from modules.memory import add_memory
        key = self._mem_key_entry.get().strip()
        val = self._mem_val_entry.get().strip()
        if key and val:
            add_memory(key, val)
            self._mem_key_entry.delete(0, "end")
            self._mem_val_entry.delete(0, "end")
            self._load_memory_ui()

    def _delete_memory(self, key):
        from modules.memory import remove_memory
        remove_memory(key)
        self._load_memory_ui()

    # ── API Keys Section ──
    def _build_api_section(self):
        card = self._section("API KEYS")

        # Was reading/writing api_keys.json under keys like "GROQ_KEY" —
        # every real consumer (main.py, spotify_controller.py, etc.) only
        # ever reads these from .env via os.getenv(), so nothing here ever
        # actually took effect, "restart to apply" or not. Now goes through
        # the same GET/POST /api-keys endpoint modules/ui_api.py already
        # exposes (writes .env, hot-reloads live clients where it can).
        info = tk.Label(card,
                        text="Most keys hot-reload immediately. A few (marked below) need a restart.",
                        bg=BG_CARD, fg=AMBER, font=("Consolas", 8))
        info.pack(anchor="w", padx=12, pady=(0, 8))

        self._api_entries = {}
        self._api_loaded_values = {}

        for label, key in [("Groq API Key", "GROQ_API_KEY"),
                            ("Gemini Key 1", "GEMINI_KEY_1"),
                            ("Gemini Key 2", "GEMINI_KEY_2"),
                            ("Gemini Key 3", "GEMINI_KEY_3"),
                            ("Spotify Client ID", "SPOTIPY_CLIENT_ID"),
                            ("Spotify Client Secret", "SPOTIPY_CLIENT_SECRET"),
                            ("Dual-Instance Peer Token", "IZACH_PEER_TOKEN"),
                            ("AlliedNode2 Token", "ALLIEDNODE2_TOKEN")]:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=f"{label:<24}", bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8), width=24,
                     anchor="w").pack(side="left")
            entry = tk.Entry(row, bg=BG_DEEP, fg=CYAN,
                             insertbackground=CYAN,
                             font=("Consolas", 9), relief="flat",
                             highlightthickness=1,
                             highlightbackground=BORDER_HI,
                             show="*", width=40)
            entry.pack(side="left", padx=(8, 4), ipady=4)
            tk.Button(row, text="SHOW",
                      bg=BG_PANEL, fg=TEXT_SEC,
                      font=("Consolas", 7), relief="flat",
                      cursor="hand2",
                      command=lambda e=entry: e.config(
                          show="" if e.cget("show") == "*" else "*"),
                      padx=4).pack(side="left")
            self._api_entries[key] = entry

        self._api_keys_msg_lbl = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        tk.Button(card, text="SAVE API KEYS",
                  bg=CYAN_DARK, fg=CYAN,
                  font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2",
                  command=self._save_api_keys,
                  padx=14, pady=4).pack(anchor="w", padx=12, pady=(6, 4))
        self._api_keys_msg_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        self._load_api_keys()

    def _load_api_keys(self):
        def _work():
            try:
                d = requests.get(f"{_API}/api-keys", timeout=5).json()
                keys = d.get("keys", {}) if d.get("ok") else {}
            except Exception:
                keys = {}
            def _apply():
                for k, entry in self._api_entries.items():
                    # GET returns masked values ("abcd••••••") — shown so the
                    # user can see a key is set, but NOT resubmitted on save
                    # unless actually edited (see _save_api_keys).
                    val = keys.get(k, "")
                    self._api_loaded_values[k] = val
                    entry.delete(0, "end")
                    entry.insert(0, val)
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_api_keys(self):
        # Only send keys the user actually changed — resubmitting an
        # untouched masked value ("abcd••••••") would overwrite the real
        # secret with literal bullet characters.
        payload = {k: e.get() for k, e in self._api_entries.items()
                   if e.get() != self._api_loaded_values.get(k, "")}
        if not payload:
            self._api_keys_msg_lbl.config(text="No changes to save.", fg=TEXT_SEC)
            return
        self._api_keys_msg_lbl.config(text="Saving…", fg=TEXT_SEC)
        def _work():
            try:
                r = requests.post(f"{_API}/api-keys", json=payload, timeout=8)
                ok = r.status_code == 200
            except Exception:
                ok = False
            def _apply():
                if ok:
                    self._api_keys_msg_lbl.config(text="✓ Saved.", fg=GREEN)
                    self._load_api_keys()
                else:
                    self._api_keys_msg_lbl.config(text="Save failed — connection error.", fg=RED)
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    # ── Voice Section ──
    def _build_voice_section(self):
        card = self._section("VOICE & RESPONSE")

        # Wake word toggle
        ww_row = tk.Frame(card, bg=BG_CARD)
        ww_row.pack(fill="x", padx=12, pady=6)
        tk.Label(ww_row, text="Wake Word Mode", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")

        self._ww_var = tk.BooleanVar(value=self._load_ww_setting())
        tk.Checkbutton(
            ww_row,
            text="Say 'iZACH' to activate (restart required)",
            variable=self._ww_var,
            bg=BG_CARD, fg=TEXT_SEC,
            selectcolor=BG_DEEP,
            activebackground=BG_CARD,
            font=("Consolas", 8),
            command=self._save_ww_setting
        ).pack(side="left", padx=8)

        # Nickname
        nick_row = tk.Frame(card, bg=BG_CARD)
        nick_row.pack(fill="x", padx=12, pady=6)
        tk.Label(nick_row, text="Nickname", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._nickname_entry = tk.Entry(
            nick_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=20)
        self._nickname_entry.pack(side="left", padx=8, ipady=3)
        self._nickname_entry.insert(0, self._load_nickname_setting())
        tk.Button(nick_row, text="SAVE", command=self._save_nickname_setting,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="left", padx=(4, 0))
        tk.Label(card, text='e.g. "Neo" — also works as a wake word alongside "iZACH" (restart required)',
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 4))

        # TTS info
        for label, note in [
            ("Response style", "Short, natural, JARVIS-style"),
            ("TTS voice",      "en-US-ChristopherNeural"),
            ("Interrupt",      "Say 'stop' or press ⏹ button"),
        ]:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, bg=BG_CARD, fg=TEXT_PRI,
                     font=("Consolas", 9), width=20,
                     anchor="w").pack(side="left")
            tk.Label(row, text=note, bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8)).pack(side="left", padx=8)

        tk.Frame(card, bg=BG_CARD, height=8).pack()

    # ── Meetings Section (calendar-driven auto-DND) ──
    def _build_meetings_section(self):
        card = self._section("MEETINGS")

        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="Auto-DND Before Meetings", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._auto_dnd_var = tk.BooleanVar(value=self._load_auto_dnd_setting())
        tk.Checkbutton(
            row,
            text="Auto-enable DND before calendar meetings",
            variable=self._auto_dnd_var,
            bg=BG_CARD, fg=TEXT_SEC,
            selectcolor=BG_DEEP,
            activebackground=BG_CARD,
            font=("Consolas", 8),
            command=self._save_auto_dnd_setting
        ).pack(side="left", padx=8)

        lead_row = tk.Frame(card, bg=BG_CARD)
        lead_row.pack(fill="x", padx=12, pady=6)
        tk.Label(lead_row, text="Lead Time (minutes)", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._auto_dnd_lead_entry = tk.Entry(
            lead_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=6)
        self._auto_dnd_lead_entry.pack(side="left", padx=8, ipady=3)
        self._auto_dnd_lead_entry.insert(0, str(self._load_auto_dnd_lead_setting()))
        tk.Button(lead_row, text="SAVE", command=self._save_auto_dnd_lead_setting,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="left", padx=(4, 0))

        tk.Label(card, text="Automatically enables Do Not Disturb a few minutes before a calendar\n"
                            "meeting starts, and disables it when the meeting ends.",
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 8))

    def _load_auto_dnd_setting(self) -> bool:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("auto_dnd_before_meetings", False)
        except Exception:
            pass
        return False

    def _save_auto_dnd_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["auto_dnd_before_meetings"] = self._auto_dnd_var.get()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Auto-DND save error: {e}")

    def _load_auto_dnd_lead_setting(self) -> int:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return int(json.load(f).get("auto_dnd_lead_minutes", 5) or 5)
        except Exception:
            pass
        return 5

    def _save_auto_dnd_lead_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            val = self._auto_dnd_lead_entry.get().strip()
            data["auto_dnd_lead_minutes"] = int(val) if val.isdigit() else 5
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Auto-DND lead save error: {e}")

    # ── Proactive Agent Section ──
    def _build_proactive_section(self):
        card = self._section("PROACTIVE AGENT")

        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="Proactive Agent", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._proactive_var = tk.BooleanVar(value=self._load_proactive_setting())
        tk.Checkbutton(
            row, text="Morning briefing, event alerts, idle nudges",
            variable=self._proactive_var,
            bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
            font=("Consolas", 8), command=self._save_proactive_setting
        ).pack(side="left", padx=8)

        row2 = tk.Frame(card, bg=BG_CARD)
        row2.pack(fill="x", padx=12, pady=6)
        tk.Label(row2, text="Pattern Suggestions", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._pattern_suggest_var = tk.BooleanVar(value=self._load_pattern_suggest_setting())
        tk.Checkbutton(
            row2, text="Offer to automate things you do on a schedule",
            variable=self._pattern_suggest_var,
            bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
            font=("Consolas", 8), command=self._save_pattern_suggest_setting
        ).pack(side="left", padx=8)

        row3 = tk.Frame(card, bg=BG_CARD)
        row3.pack(fill="x", padx=12, pady=6)
        tk.Label(row3, text="Screen-Aware Assist", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._screen_aware_var = tk.BooleanVar(value=self._load_screen_aware_setting())
        tk.Checkbutton(
            row3, text="Reads active window text — off by default",
            variable=self._screen_aware_var,
            bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
            font=("Consolas", 8), command=self._save_screen_aware_setting
        ).pack(side="left", padx=8)

        excl_row = tk.Frame(card, bg=BG_CARD)
        excl_row.pack(fill="x", padx=12, pady=6)
        tk.Label(excl_row, text="Excluded Apps", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._screen_aware_excl_entry = tk.Entry(
            excl_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=36)
        self._screen_aware_excl_entry.pack(side="left", padx=8, ipady=3)
        self._screen_aware_excl_entry.insert(0, self._load_screen_aware_excl_setting())
        tk.Button(excl_row, text="SAVE", command=self._save_screen_aware_excl_setting,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="left", padx=(4, 0))
        tk.Label(card, text="Comma-separated process names, checked before any OCR happens.",
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 4))

        tk.Frame(card, bg=BG_CARD, height=8).pack()

    def _load_proactive_setting(self) -> bool:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("proactive_enabled", True)
        except Exception:
            pass
        return True

    def _save_proactive_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["proactive_enabled"] = self._proactive_var.get()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Proactive agent save error: {e}")

    def _load_pattern_suggest_setting(self) -> bool:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("pattern_automation_suggestions_enabled", True)
        except Exception:
            pass
        return True

    def _save_pattern_suggest_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["pattern_automation_suggestions_enabled"] = self._pattern_suggest_var.get()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Pattern suggestions save error: {e}")

    _SCREEN_AWARE_DEFAULT_EXCL = "keepass, keepassxc, 1password, bitwarden, lastpass"

    def _load_screen_aware_setting(self) -> bool:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("screen_aware_enabled", False)
        except Exception:
            pass
        return False

    def _save_screen_aware_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["screen_aware_enabled"] = self._screen_aware_var.get()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Screen-aware save error: {e}")

    def _load_screen_aware_excl_setting(self) -> str:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    apps = json.load(f).get("screen_aware_excluded_apps")
                    if apps is not None:
                        return ", ".join(apps)
        except Exception:
            pass
        return self._SCREEN_AWARE_DEFAULT_EXCL

    def _save_screen_aware_excl_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            raw = self._screen_aware_excl_entry.get()
            data["screen_aware_excluded_apps"] = [a.strip().lower() for a in raw.split(",") if a.strip()]
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Screen-aware exclusions save error: {e}")

    # ── Email Agent Section ──
    def _build_email_agent_section(self):
        card = self._section("EMAIL AGENT")

        status_row = tk.Frame(card, bg=BG_CARD)
        status_row.pack(fill="x", padx=12, pady=(0, 6))
        self._email_status_lbl = tk.Label(status_row, text="● NOT CONNECTED", bg=BG_CARD, fg=TEXT_SEC,
                                          font=("Consolas", 9, "bold"))
        self._email_status_lbl.pack(side="left")

        btn_row = tk.Frame(card, bg=BG_CARD)
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        self._email_connect_btn = tk.Button(btn_row, text="⊕ CONNECT GMAIL (read-only)", command=self._email_connect_start,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)
        self._email_connect_btn.pack(side="left")
        self._email_disconnect_btn = tk.Button(btn_row, text="DISCONNECT", command=self._email_disconnect,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)

        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=4)
        tk.Label(row, text="Email Agent", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._email_agent_var = tk.BooleanVar(value=self._load_email_setting("email_agent_enabled", False))
        tk.Checkbutton(row, text="Master switch — off by default", variable=self._email_agent_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8), command=lambda: self._save_email_setting("email_agent_enabled", self._email_agent_var.get())
                      ).pack(side="left", padx=8)

        for key, label, default in [
            ("email_watch_otp", "Watch for OTPs", True),
            ("email_watch_replies", "Watch for Replies", True),
            ("email_watch_keywords", "Watch Keywords/Senders", True),
            ("email_track_orders", "Track Orders/Shipments", True),
        ]:
            r = tk.Frame(card, bg=BG_CARD)
            r.pack(fill="x", padx=12, pady=2)
            tk.Label(r, text="", bg=BG_CARD, width=20).pack(side="left")
            var = tk.BooleanVar(value=self._load_email_setting(key, default))
            setattr(self, f"_{key}_var", var)
            tk.Checkbutton(r, text=label, variable=var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8), command=lambda k=key, v=var: self._save_email_setting(k, v.get())
                          ).pack(side="left", padx=8)

        wl_row = tk.Frame(card, bg=BG_CARD)
        wl_row.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(wl_row, text="Watchlist", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=20, anchor="w").pack(side="left")
        self._email_watchlist_entry = tk.Entry(
            wl_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=36)
        self._email_watchlist_entry.pack(side="left", padx=8, ipady=3)
        tk.Button(wl_row, text="SAVE", command=self._save_email_watchlist,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="left", padx=(4, 0))
        tk.Label(card, text='Comma-separated senders/subjects, e.g. "Dell Support Assist, Amazon Delivery"',
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 8))

        tk.Label(card, text="TRACKED ORDERS", bg=BG_CARD, fg=CYAN, font=("Consolas", 8, "bold")).pack(
            anchor="w", padx=12, pady=(0, 2))
        self._email_orders_lbl = tk.Label(card, text="No tracked orders yet.", bg=BG_CARD, fg=TEXT_SEC,
                                          font=("Consolas", 8), justify="left", wraplength=520, anchor="w")
        self._email_orders_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        tk.Frame(card, bg=BG_CARD, height=8).pack()

        self._email_refresh_status()
        self._load_email_watchlist_ui()
        self._load_email_orders_ui()

    def _load_email_setting(self, key, default):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get(key, default)
        except Exception:
            pass
        return default

    def _save_email_setting(self, key, value):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data[key] = value
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Email agent save error ({key}): {e}")

    def _load_email_watchlist_ui(self):
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/email/watchlist", timeout=5).json()
                items = r.get("watchlist", [])
            except Exception:
                items = []
            self._safe_after(0, lambda: (self._email_watchlist_entry.delete(0, "end"),
                                    self._email_watchlist_entry.insert(0, ", ".join(items))))
        threading.Thread(target=_work, daemon=True).start()

    def _save_email_watchlist(self):
        raw = self._email_watchlist_entry.get()
        watchlist = [w.strip() for w in raw.split(",") if w.strip()]
        def _work():
            try:
                requests.post("http://127.0.0.1:5050/email/watchlist", json={"watchlist": watchlist}, timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Watchlist save error: {e}")
        threading.Thread(target=_work, daemon=True).start()

    def _load_email_orders_ui(self):
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/email/orders", timeout=5).json()
                orders = r.get("orders", [])
            except Exception:
                orders = []
            def _apply():
                if not orders:
                    self._email_orders_lbl.config(text="No tracked orders yet.")
                    return
                lines = []
                for o in orders[:5]:
                    eta = f", ETA {o['delivery_date']}" if o.get("delivery_date") else ""
                    lines.append(f"{o.get('description') or 'Package'} via {o.get('carrier') or '?'} — "
                                 f"{(o.get('status') or '').replace('_', ' ')}{eta}")
                self._email_orders_lbl.config(text="\n".join(lines))
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _email_refresh_status(self):
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/email/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False, "status": "idle"}
            self._safe_after(0, lambda: self._email_apply_status(r))
        threading.Thread(target=_work, daemon=True).start()

    def _email_apply_status(self, status):
        connected = status.get("connected", False)
        if status.get("status") == "waiting_for_browser":
            self._email_status_lbl.config(text="● CONNECTING…", fg=AMBER)
        elif connected:
            user = status.get("user") or ""
            self._email_status_lbl.config(text=f"● CONNECTED — {user}", fg=GREEN)
        else:
            self._email_status_lbl.config(text="● NOT CONNECTED", fg=TEXT_SEC)
        if connected:
            self._email_connect_btn.pack_forget()
            self._email_disconnect_btn.pack(side="left")
        else:
            self._email_disconnect_btn.pack_forget()
            self._email_connect_btn.pack(side="left")

    def _email_connect_start(self):
        def _work():
            try:
                requests.post("http://127.0.0.1:5050/email/auth/connect", timeout=5).json()
            except Exception as e:
                print(f"[SETTINGS] Email connect error: {e}")
                return
            self._safe_after(0, self._email_poll_connect)
        threading.Thread(target=_work, daemon=True).start()

    def _email_poll_connect(self, attempt=0):
        self._email_apply_status({"connected": False, "status": "waiting_for_browser"})
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/email/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False, "status": "idle"}
            def _apply():
                if r.get("status") in ("connected", "error") or attempt > 60:
                    self._email_apply_status(r)
                else:
                    self._safe_after(2000, lambda: self._email_poll_connect(attempt + 1))
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _email_disconnect(self):
        def _work():
            try:
                requests.post("http://127.0.0.1:5050/email/auth/disconnect", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Email disconnect error: {e}")
            self._safe_after(0, self._email_refresh_status)
        threading.Thread(target=_work, daemon=True).start()

    # ── Unified Notifications Section (Phase 5) ──
    _NOTIF_SOURCE_ICON = {"whatsapp": "💬", "calendar": "📅", "system": "⚠", "email": "✉", "alerts": "✉"}

    def _build_notifications_section(self):
        card = self._section("NOTIFICATIONS")
        tk.Label(card, text="WhatsApp + Calendar + System + Email, ranked by priority",
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 6))

        self._notif_feed_lbl = tk.Label(card, text="Loading…", bg=BG_CARD, fg=TEXT_SEC,
                                        font=("Consolas", 8), justify="left", wraplength=520, anchor="w")
        self._notif_feed_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        tk.Button(card, text="↻ REFRESH", command=self._load_notification_feed,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(anchor="w", padx=12, pady=(0, 8))

        self._load_notification_feed()

    def _load_notification_feed(self):
        def _work():
            try:
                r = requests.get("http://127.0.0.1:5050/notifications/feed", params={"limit": 8}, timeout=5).json()
                items = r.get("notifications", [])
            except Exception:
                items = None
            def _apply():
                if items is None:
                    self._notif_feed_lbl.config(text="Could not load notifications.")
                    return
                if not items:
                    self._notif_feed_lbl.config(text="No notifications yet.")
                    return
                lines = []
                for n in items:
                    icon = self._NOTIF_SOURCE_ICON.get(n.get("source"), "•")
                    import time as _time
                    when = _time.strftime("%H:%M", _time.localtime(n.get("ts", 0)))
                    body = (n.get("body") or "")[:70]
                    lines.append(f"{icon} {n.get('title', '')}  [{when}]\n    {body}")
                self._notif_feed_lbl.config(text="\n".join(lines))
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    # ── Custom Websites Section ──
    def _build_custom_websites_section(self):
        card = self._section("CUSTOM WEBSITES")

        tk.Label(card, text='Say "open <name>" to open any site below.',
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(
                     anchor="w", padx=12, pady=(0, 8))

        self._websites_frame = tk.Frame(card, bg=BG_CARD)
        self._websites_frame.pack(fill="x", padx=12, pady=(0, 6))

        add_row = tk.Frame(card, bg=BG_CARD)
        add_row.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(add_row, text="NAME", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")
        self._ws_name_entry = tk.Entry(
            add_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=20)
        self._ws_name_entry.pack(side="left", padx=(4, 8), ipady=4)

        tk.Label(add_row, text="→", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 10)).pack(side="left", padx=(0, 4))

        tk.Label(add_row, text="URL", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")
        self._ws_url_entry = tk.Entry(
            add_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
            font=("Consolas", 9), relief="flat",
            highlightthickness=1, highlightbackground=BORDER_HI, width=28)
        self._ws_url_entry.pack(side="left", padx=(4, 8), ipady=4)

        self._ws_msg_var = tk.StringVar()
        tk.Button(add_row, text="ADD",
                  bg=GREEN_DIM, fg=GREEN,
                  font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2",
                  command=self._add_custom_website,
                  padx=10, pady=3).pack(side="left")

        tk.Label(card, textvariable=self._ws_msg_var,
                 bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(anchor="w", padx=12)

        tk.Frame(card, bg=BG_CARD, height=8).pack()
        self._load_custom_websites_ui()

    def _load_custom_websites_ui(self):
        for w in self._websites_frame.winfo_children():
            w.destroy()
        try:
            import json
            with open("custom_websites.json") as f:
                sites = json.load(f)
        except Exception:
            sites = []
        if not sites:
            tk.Label(self._websites_frame, text="No custom websites yet.",
                     bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8)).pack(anchor="w")
            return
        for site in sites:
            row = tk.Frame(self._websites_frame, bg="#071020",
                           highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=site["name"], bg="#071020", fg=CYAN,
                     font=("Consolas", 9, "bold"), width=22,
                     anchor="w").pack(side="left", padx=(8, 4), pady=4)
            tk.Label(row, text="→", bg="#071020", fg=TEXT_SEC,
                     font=("Consolas", 9)).pack(side="left", padx=4)
            tk.Label(row, text=site["url"], bg="#071020", fg=TEXT_SEC,
                     font=("Consolas", 8),
                     anchor="w").pack(side="left", padx=(0, 8), fill="x", expand=True)
            tk.Button(row, text="✕",
                      bg="#1a0000", fg=RED,
                      font=("Consolas", 8, "bold"),
                      relief="flat", cursor="hand2",
                      padx=6, pady=2,
                      command=lambda k=site["key"]: self._delete_custom_website(k)
                      ).pack(side="right", padx=6)

    def _add_custom_website(self):
        name = self._ws_name_entry.get().strip()
        url  = self._ws_url_entry.get().strip()
        if not name or not url:
            self._ws_msg_var.set("Name and URL required.")
            return
        try:
            import requests as _req
            r = _req.post("http://127.0.0.1:5050/websites",
                          json={"name": name, "url": url}, timeout=5)
            data = r.json()
            if data.get("ok"):
                self._ws_name_entry.delete(0, "end")
                self._ws_url_entry.delete(0, "end")
                self._ws_msg_var.set(f'Added "{name}"')
                self._load_custom_websites_ui()
                self._safe_after(3000, lambda: self._ws_msg_var.set(""))
            else:
                self._ws_msg_var.set(data.get("error", "Error"))
        except Exception as e:
            self._ws_msg_var.set(f"Error: {e}")

    def _delete_custom_website(self, key):
        try:
            import requests as _req
            _req.delete(f"http://127.0.0.1:5050/websites/{key}", timeout=5)
            self._load_custom_websites_ui()
        except Exception:
            pass

    # ── About Section ──
    def _build_about_section(self):
        card = self._section("ABOUT iZACH")
        for line, val in [
            ("Version", "9.0 — FORGE UI"),
            ("AI Providers", "Groq (primary) + Gemini (fallback)"),
            ("Voice Engine", "Edge-TTS — Christopher Neural"),
            ("Developer", "Vansh Kishore Sharma"),
            ("Future", "Add Spotify API key in API section above"),
            ("Reminder", "Add more APIs here when ready in future"),
        ]:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=f"{line:<18}", bg=BG_CARD, fg=TEXT_SEC,
                     font=("Consolas", 8), width=18, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=BG_CARD, fg=TEXT_PRI,
                     font=("Consolas", 8)).pack(side="left", padx=8)
        tk.Frame(card, bg=BG_CARD, height=8).pack()

    def _load_ww_setting(self) -> bool:
        try:
            import json
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("wake_word_enabled", False)
        except Exception:
            pass
        return False

    def _save_ww_setting(self):
        try:
            import json
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["wake_word_enabled"] = self._ww_var.get()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Wake word save error: {e}")

    def _load_nickname_setting(self) -> str:
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f).get("nickname", "") or ""
        except Exception:
            pass
        return ""

    def _save_nickname_setting(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
            data["nickname"] = self._nickname_entry.get().strip()
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SETTINGS] Nickname save error: {e}")

    # ── Generic /settings REST helpers — new sections below use these
    # instead of the local api_keys.json read/write older sections use.
    # It's the same underlying file (SETTINGS_FILE = "api_keys.json" in
    # modules/ui_api.py), but going through the route matters for
    # dual_instance specifically (its POST handler installs/uninstalls the
    # auto-promote watchdog as a side effect) and for anything that needs
    # live backend state rather than a static flag. ──
    def _settings_get(self):
        try:
            return requests.get(f"{_API}/settings", timeout=5).json()
        except Exception as e:
            print(f"[SETTINGS] GET /settings error: {e}")
            return None

    def _settings_post(self, payload):
        def _work():
            try:
                requests.post(f"{_API}/settings", json=payload, timeout=8)
            except Exception as e:
                print(f"[SETTINGS] POST /settings error: {e}")
        threading.Thread(target=_work, daemon=True).start()

    # ── Appearance Section ──
    def _build_appearance_section(self):
        card = self._section("APPEARANCE")
        tk.Label(card, text="FONT SIZE", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9)).pack(anchor="w", padx=12, pady=(0, 6))

        self._font_size_var = tk.StringVar(value="13")
        opt_row = tk.Frame(card, bg=BG_CARD)
        opt_row.pack(anchor="w", padx=12, pady=(0, 4))
        for label, val in [("Small", "11"), ("Normal", "13"), ("Large", "15"), ("X-Large", "17")]:
            tk.Radiobutton(opt_row, text=label, value=val, variable=self._font_size_var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8), command=self._save_font_size
                          ).pack(side="left", padx=(0, 10))

        tk.Label(card,
                 text="Shared with Cortex UI (restart required to apply there). Forge UI\n"
                      "hardcodes font sizes at each widget — living font-scaling here would\n"
                      "need a much larger refactor, out of scope for this change.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 10))

        self._load_font_size()

    def _load_font_size(self):
        def _work():
            d = self._settings_get()
            fs = "13"
            if d and d.get("ok"):
                fs = str((d.get("settings") or {}).get("font_size", 13))
            def _apply():
                try:
                    self._font_size_var.set(fs)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_font_size(self):
        try:
            self._settings_post({"font_size": int(self._font_size_var.get())})
        except Exception:
            pass

    # ── Device Connection Section — dual-instance + mobile phone ──
    def _build_device_connection_section(self):
        card = self._section("MULTI-DEVICE (WINDOWS + MAC)")
        tk.Label(card,
                 text="Run iZACH on two machines — whichever starts second detects the other\n"
                      "and offers Secondary Connector mode instead of a duplicate brain.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 8))

        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=4)
        self._dual_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Enable Dual-Instance Coordination", variable=self._dual_enabled_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(side="left")

        # Peer Device card — friendlier UI over the same
        # dual_instance.peer_host/peer_port/peer_label fields; no new
        # architecture, still exactly one peer. Mirrors cortex-ui.html's
        # _renderPeerDeviceCard()/peerDeviceEdit()/peerDeviceSave()/
        # peerDeviceRemove(). Exactly one of (info card / add button /
        # form) is visible at a time via pack()/pack_forget().
        tk.Label(card, text="PEER DEVICE", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 4))

        self._peer_device_card = tk.Frame(card, bg=BG_CARD, highlightthickness=1,
                                          highlightbackground=BORDER_HI)
        info_row = tk.Frame(self._peer_device_card, bg=BG_CARD)
        info_row.pack(fill="x", padx=10, pady=8)
        name_col = tk.Frame(info_row, bg=BG_CARD)
        name_col.pack(side="left", fill="x", expand=True)
        self._peer_device_name_lbl = tk.Label(name_col, text="", bg=BG_CARD, fg=CYAN,
                                              font=("Consolas", 10, "bold"), anchor="w")
        self._peer_device_name_lbl.pack(fill="x")
        self._peer_device_hostport_lbl = tk.Label(name_col, text="", bg=BG_CARD, fg=TEXT_SEC,
                                                  font=("Consolas", 8), anchor="w")
        self._peer_device_hostport_lbl.pack(fill="x")
        btn_col = tk.Frame(info_row, bg=BG_CARD)
        btn_col.pack(side="right")
        tk.Button(btn_col, text="EDIT", command=self._peer_device_edit,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left", padx=(0, 6))
        tk.Button(btn_col, text="REMOVE", command=self._peer_device_remove,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left")

        self._peer_device_add_btn = tk.Button(card, text="+ ADD PEER DEVICE", command=self._peer_device_edit,
                 bg=BG_PANEL, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=4)

        self._peer_device_form = tk.Frame(card, bg=BG_CARD)
        tk.Label(self._peer_device_form, text="Device Name", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self._peer_label_entry = tk.Entry(self._peer_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                          font=("Consolas", 9), relief="flat",
                                          highlightthickness=1, highlightbackground=BORDER_HI, width=22)
        self._peer_label_entry.grid(row=0, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._peer_device_form, text="Host (LAN IP)", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self._peer_host_entry = tk.Entry(self._peer_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                          font=("Consolas", 9), relief="flat",
                                          highlightthickness=1, highlightbackground=BORDER_HI, width=22)
        self._peer_host_entry.grid(row=1, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._peer_device_form, text="Port", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=2, column=0, sticky="w", pady=3)
        self._peer_port_entry = tk.Entry(self._peer_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                          font=("Consolas", 9), relief="flat",
                                          highlightthickness=1, highlightbackground=BORDER_HI, width=8)
        self._peer_port_entry.grid(row=2, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._peer_device_form,
                 text="Shared secret token: Settings → Keys & ID → Dual-Instance Peer\nToken — must match on both machines.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 7), justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))
        form_btn_row = tk.Frame(self._peer_device_form, bg=BG_CARD)
        form_btn_row.grid(row=4, column=0, columnspan=2, sticky="w")
        tk.Button(form_btn_row, text="SAVE DEVICE", command=self._peer_device_save,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left")
        tk.Button(form_btn_row, text="CANCEL", command=self._peer_device_cancel_edit,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left", padx=(6, 0))
        self._peer_device_msg_lbl = tk.Label(form_btn_row, text="", bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        self._peer_device_msg_lbl.pack(side="left", padx=(10, 0))

        pin_row = tk.Frame(card, bg=BG_CARD)
        pin_row.pack(fill="x", padx=12, pady=4)
        tk.Label(pin_row, text="Primary Pin", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        self._primary_pin_var = tk.StringVar(value="auto")
        for label, val in [("Auto", "auto"), ("Prefer Mac", "always_mac"), ("Prefer Windows", "always_windows")]:
            tk.Radiobutton(pin_row, text=label, value=val, variable=self._primary_pin_var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8)).pack(side="left", padx=(0, 8))

        promote_row = tk.Frame(card, bg=BG_CARD)
        promote_row.pack(fill="x", padx=12, pady=4)
        self._auto_promote_var = tk.BooleanVar(value=False)
        tk.Checkbutton(promote_row, text="Auto-Promote if Primary Goes Offline", variable=self._auto_promote_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(side="left")
        tk.Label(promote_row, text="Timeout (min)", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9)).pack(side="left", padx=(12, 4))
        self._auto_promote_timeout_entry = tk.Entry(promote_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                                     font=("Consolas", 9), relief="flat",
                                                     highlightthickness=1, highlightbackground=BORDER_HI, width=5)
        self._auto_promote_timeout_entry.pack(side="left", ipady=3)

        save_row = tk.Frame(card, bg=BG_CARD)
        save_row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Button(save_row, text="SAVE", command=self._save_dual_instance,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left")

        status_row = tk.Frame(card, bg=BG_CARD)
        status_row.pack(fill="x", padx=12, pady=(8, 4))
        self._peer_status_lbl = tk.Label(status_row, text="● NOT CONFIGURED", bg=BG_CARD, fg=TEXT_SEC,
                                         font=("Consolas", 9, "bold"))
        self._peer_status_lbl.pack(side="left")
        tk.Button(status_row, text="TEST CONNECTION", command=self._test_peer_connection,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left", padx=(12, 0))

        tk.Frame(card, bg=BG_CARD, height=10).pack()
        tk.Label(card, text="SWITCH MACHINE", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=12)
        tk.Label(card,
                 text="Boots iZACH on the other machine if it's not already running, waits\n"
                      "for it to come up healthy, then hands off and shuts down here. Nothing\n"
                      "here is touched if the peer can't be reached.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(2, 6))
        switch_row = tk.Frame(card, bg=BG_CARD)
        switch_row.pack(fill="x", padx=12)
        tk.Button(switch_row, text="SWITCH TO WINDOWS", command=lambda: self._switch_machine("windows"),
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left")
        tk.Button(switch_row, text="SWITCH TO MAC", command=lambda: self._switch_machine("mac"),
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left", padx=(8, 0))
        # Real backend-reported progress (GET /switch_status), polled while
        # the POST /switch_machine below is still in flight — main.py's
        # Flask app runs threaded=True specifically so this works, same as
        # Cortex's _setSwitchProgressUI()/switchMachine(). Not a fake
        # client-side animation.
        self._switch_progress_canvas = tk.Canvas(card, width=300, height=8, bg=BG_DEEP,
                                                  highlightthickness=1, highlightbackground=BORDER_HI)
        self._switch_progress_fill = self._switch_progress_canvas.create_rectangle(
            0, 0, 0, 8, fill=CYAN, width=0)
        self._switch_machine_lbl = tk.Label(card, text="", bg=BG_CARD, fg=TEXT_SEC,
                                            font=("Consolas", 8))
        self._switch_machine_lbl.pack(anchor="w", padx=12, pady=(6, 4))
        self._switch_poller_active = False

        tk.Frame(card, bg=BG_CARD, height=8).pack()
        self._load_dual_instance()

        # Peer Device Control sub-card — Phase 3 remote control (vitals/
        # media/power/screenshot/processes), proxied server-side through
        # /peer/* so IZACH_PEER_TOKEN never reaches this UI. No terminal,
        # no file transfer — same deliberate scope cut as boot_daemon.py's
        # /control/* routes. Card is shown/hidden based on whether
        # dual_instance is actually configured (see _load_peer_local).
        self._peer_label = "Peer"
        peer_card = self._section("PEER DEVICE CONTROL")
        self._peer_card_frame = peer_card

        peer_hdr = tk.Frame(peer_card, bg=BG_CARD)
        peer_hdr.pack(fill="x", padx=12, pady=(0, 8))
        self._peer_dot_lbl = tk.Label(peer_hdr, text="●", bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 11))
        self._peer_dot_lbl.pack(side="left")
        self._peer_name_lbl = tk.Label(peer_hdr, text=" Peer — checking…", bg=BG_CARD, fg=TEXT_SEC,
                                       font=("Consolas", 9, "bold"))
        self._peer_name_lbl.pack(side="left", padx=(2, 0))
        tk.Button(peer_hdr, text="↻ REFRESH", command=self._refresh_peer_vitals,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="right")

        tk.Label(peer_card, text="VITALS", bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7)).pack(
            anchor="w", padx=12)
        vitals_row = tk.Frame(peer_card, bg=BG_CARD)
        vitals_row.pack(fill="x", padx=12, pady=(2, 8))
        self._peer_cpu_lbl = tk.Label(vitals_row, text="CPU —", bg=BG_CARD, fg=TEXT_PRI, font=("Consolas", 8))
        self._peer_cpu_lbl.pack(side="left", padx=(0, 10))
        self._peer_ram_lbl = tk.Label(vitals_row, text="RAM —", bg=BG_CARD, fg=TEXT_PRI, font=("Consolas", 8))
        self._peer_ram_lbl.pack(side="left", padx=(0, 10))
        self._peer_disk_lbl = tk.Label(vitals_row, text="DISK —", bg=BG_CARD, fg=TEXT_PRI, font=("Consolas", 8))
        self._peer_disk_lbl.pack(side="left", padx=(0, 10))
        self._peer_batt_lbl = tk.Label(vitals_row, text="BATT —", bg=BG_CARD, fg=TEXT_PRI, font=("Consolas", 8))
        self._peer_batt_lbl.pack(side="left")

        tk.Label(peer_card, text="MEDIA", bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7)).pack(
            anchor="w", padx=12)
        media_row = tk.Frame(peer_card, bg=BG_CARD)
        media_row.pack(fill="x", padx=12, pady=(2, 8))
        for label, action in [("⏮", "prev_track"), ("⏯", "play_pause"), ("⏭", "next_track"),
                              ("🔉", "volume_down"), ("🔊", "volume_up"), ("🔇", "mute")]:
            tk.Button(media_row, text=label, command=lambda a=action: self._peer_media(a),
                     bg=BG_PANEL, fg=CYAN, font=("Consolas", 10),
                     relief="flat", cursor="hand2", padx=6, pady=2).pack(side="left", padx=(0, 4))

        tk.Label(peer_card, text="POWER", bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7)).pack(
            anchor="w", padx=12)
        power_row = tk.Frame(peer_card, bg=BG_CARD)
        power_row.pack(fill="x", padx=12, pady=(2, 8))
        power_btns = [("Lock", "lock", CYAN), ("Sleep", "sleep", CYAN),
                     ("Restart", "restart", AMBER), ("Shutdown", "shutdown", RED)]
        for label, action, color in power_btns:
            tk.Button(power_row, text=label, command=lambda a=action, l=label: self._peer_power(a, l),
                     bg=BG_PANEL, fg=color, font=("Consolas", 8, "bold"),
                     relief="flat", cursor="hand2", padx=8, pady=3).pack(side="left", padx=(0, 6))

        snap_hdr = tk.Frame(peer_card, bg=BG_CARD)
        snap_hdr.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(snap_hdr, text="SCREENSHOT", bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7)).pack(side="left")
        tk.Button(snap_hdr, text="SNAP", command=self._peer_screenshot,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="right")
        self._peer_snap_lbl = tk.Label(peer_card, bg=BG_CARD)
        self._peer_snap_lbl.pack(padx=12, pady=(0, 8))

        procs_hdr = tk.Frame(peer_card, bg=BG_CARD)
        procs_hdr.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(procs_hdr, text="PROCESSES", bg=BG_CARD, fg=CYAN_DIM, font=("Consolas", 7)).pack(side="left")
        tk.Button(procs_hdr, text="↻ REFRESH", command=self._peer_refresh_procs,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=2).pack(side="right")
        procs_frame = tk.Frame(peer_card, bg=BG_CARD)
        procs_frame.pack(fill="both", padx=12, pady=(0, 8))
        procs_sb = tk.Scrollbar(procs_frame, bg=BG_CARD, troughcolor=BORDER)
        procs_sb.pack(side="right", fill="y")
        self._peer_procs_text = tk.Text(procs_frame, height=8, bg="#010814", fg="#60b8d0",
                                        font=("Consolas", 8), relief="flat", wrap="none",
                                        highlightthickness=1, highlightbackground=BORDER_HI,
                                        state="disabled", yscrollcommand=procs_sb.set)
        self._peer_procs_text.pack(side="left", fill="both", expand=True)
        procs_sb.config(command=self._peer_procs_text.yview)

        self._load_peer_local()

        # AlliedNode 2 card — same "friendlier UI over existing config"
        # pattern as the Peer Device card above, but for the satellite-PC
        # node (modules/remote_node.py). Unlike the peer device, this one
        # has no REMOVE (there must always be exactly one entry named
        # "alliednode 2" for the DEVICES widget's hardcoded row to point
        # at) and no ADD flow — it always exists, defaulting to the
        # pre-config hardcoded values server-side if never touched.
        an2_card = self._section("ALLIEDNODE 2")
        tk.Label(an2_card,
                 text="The satellite PC controllable from the DEVICES widget — separate from\n"
                      "the dual-instance peer above. Shared secret token: Settings → Keys & ID\n"
                      "→ ALLIEDNODE2 TOKEN.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 8))

        self._an2_device_card = tk.Frame(an2_card, bg=BG_CARD, highlightthickness=1,
                                         highlightbackground=BORDER_HI)
        an2_info_row = tk.Frame(self._an2_device_card, bg=BG_CARD)
        an2_info_row.pack(fill="x", padx=10, pady=8)
        an2_name_col = tk.Frame(an2_info_row, bg=BG_CARD)
        an2_name_col.pack(side="left", fill="x", expand=True)
        self._an2_device_name_lbl = tk.Label(an2_name_col, text="", bg=BG_CARD, fg=CYAN,
                                             font=("Consolas", 10, "bold"), anchor="w")
        self._an2_device_name_lbl.pack(fill="x")
        self._an2_device_hostport_lbl = tk.Label(an2_name_col, text="", bg=BG_CARD, fg=TEXT_SEC,
                                                 font=("Consolas", 8), anchor="w")
        self._an2_device_hostport_lbl.pack(fill="x")
        tk.Button(an2_info_row, text="EDIT", command=self._an2_device_edit,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=3).pack(side="right")

        self._an2_device_form = tk.Frame(an2_card, bg=BG_CARD)
        tk.Label(self._an2_device_form, text="Device Name", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self._an2_label_entry = tk.Entry(self._an2_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                         font=("Consolas", 9), relief="flat",
                                         highlightthickness=1, highlightbackground=BORDER_HI, width=22)
        self._an2_label_entry.grid(row=0, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._an2_device_form, text="Host (LAN IP)", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self._an2_host_entry = tk.Entry(self._an2_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                        font=("Consolas", 9), relief="flat",
                                        highlightthickness=1, highlightbackground=BORDER_HI, width=22)
        self._an2_host_entry.grid(row=1, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._an2_device_form, text="Port", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=2, column=0, sticky="w", pady=3)
        self._an2_port_entry = tk.Entry(self._an2_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                        font=("Consolas", 9), relief="flat",
                                        highlightthickness=1, highlightbackground=BORDER_HI, width=8)
        self._an2_port_entry.grid(row=2, column=1, sticky="w", padx=(4, 0), ipady=3)
        tk.Label(self._an2_device_form, text="MAC Address (WoL)", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").grid(row=3, column=0, sticky="w", pady=3)
        self._an2_mac_entry = tk.Entry(self._an2_device_form, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                       font=("Consolas", 9), relief="flat",
                                       highlightthickness=1, highlightbackground=BORDER_HI, width=22)
        self._an2_mac_entry.grid(row=3, column=1, sticky="w", padx=(4, 0), ipady=3)
        an2_form_btn_row = tk.Frame(self._an2_device_form, bg=BG_CARD)
        an2_form_btn_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Button(an2_form_btn_row, text="SAVE DEVICE", command=self._an2_device_save,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left")
        tk.Button(an2_form_btn_row, text="CANCEL", command=self._an2_device_cancel_edit,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left", padx=(6, 0))
        self._an2_device_msg_lbl = tk.Label(an2_form_btn_row, text="", bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        self._an2_device_msg_lbl.pack(side="left", padx=(10, 0))

        self._load_an2_device()

        # Mobile Phone sub-card
        phone_card = self._section("MOBILE PHONE")
        phone_status_row = tk.Frame(phone_card, bg=BG_CARD)
        phone_status_row.pack(fill="x", padx=12, pady=(0, 6))
        self._dc_phone_status_lbl = tk.Label(phone_status_row, text="● DISCONNECTED", bg=BG_CARD, fg=TEXT_SEC,
                                             font=("Consolas", 9, "bold"))
        self._dc_phone_status_lbl.pack(side="left")

        self._dc_phone_name_lbl = tk.Label(phone_card, text="", bg=BG_CARD, fg=CYAN,
                                           font=("Consolas", 8))
        self._dc_phone_name_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        tk.Button(phone_card, text="REMOVE DEVICE", command=self._remove_phone_device,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(anchor="w", padx=12, pady=(0, 4))
        tk.Label(phone_card,
                 text="Rotates the pairing secret — the connected phone will need to\n"
                      "re-scan the QR code (above) to reconnect.",
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 8))
        tk.Frame(phone_card, bg=BG_CARD, height=8).pack()

        self._load_dc_phone_status()

    def _load_dual_instance(self):
        def _work():
            d = self._settings_get()
            di = {}
            if d and d.get("ok"):
                di = (d.get("settings") or {}).get("dual_instance") or {}
            def _apply():
                try:
                    self._dual_enabled_var.set(bool(di.get("enabled")))
                    self._peer_label_entry.delete(0, "end")
                    self._peer_label_entry.insert(0, di.get("peer_label", "") or "")
                    self._peer_host_entry.delete(0, "end")
                    self._peer_host_entry.insert(0, di.get("peer_host", "") or "")
                    self._peer_port_entry.delete(0, "end")
                    self._peer_port_entry.insert(0, str(di.get("peer_port", 5050)))
                    self._primary_pin_var.set(di.get("primary_pin", "auto"))
                    self._auto_promote_var.set(bool(di.get("auto_promote_enabled")))
                    self._auto_promote_timeout_entry.delete(0, "end")
                    self._auto_promote_timeout_entry.insert(0, str(di.get("auto_promote_timeout_minutes", 5)))
                    self._render_peer_device_card()
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_dual_instance(self):
        try:
            port = int(self._peer_port_entry.get().strip() or 5050)
        except ValueError:
            port = 5050
        try:
            timeout = int(self._auto_promote_timeout_entry.get().strip() or 5)
        except ValueError:
            timeout = 5
        payload = {"dual_instance": {
            "enabled": self._dual_enabled_var.get(),
            "peer_host": self._peer_host_entry.get().strip(),
            "peer_port": port,
            "peer_label": self._peer_label_entry.get().strip(),
            "primary_pin": self._primary_pin_var.get(),
            "auto_promote_enabled": self._auto_promote_var.get(),
            "auto_promote_timeout_minutes": timeout,
        }}
        self._settings_post(payload)

    # ── Peer Device card (Device Connection) — friendlier UI over the
    # same dual_instance.peer_host/peer_port/peer_label fields. Mirrors
    # cortex-ui.html's _renderPeerDeviceCard()/peerDeviceEdit()/
    # peerDeviceSave()/peerDeviceRemove(). ──
    def _render_peer_device_card(self):
        host = self._peer_host_entry.get().strip()
        self._peer_device_form.pack_forget()
        if host:
            label = self._peer_label_entry.get().strip() or "Peer Device"
            port = self._peer_port_entry.get().strip() or "5050"
            self._peer_device_name_lbl.config(text=label)
            self._peer_device_hostport_lbl.config(text=f"{host}:{port}")
            self._peer_device_add_btn.pack_forget()
            self._peer_device_card.pack(fill="x", padx=12, pady=(0, 8))
        else:
            self._peer_device_card.pack_forget()
            self._peer_device_add_btn.pack(anchor="w", padx=12, pady=(0, 8))

    def _peer_device_edit(self):
        self._peer_device_card.pack_forget()
        self._peer_device_add_btn.pack_forget()
        self._peer_device_msg_lbl.config(text="", fg=TEXT_SEC)
        self._peer_device_form.pack(fill="x", padx=12, pady=(0, 8))

    def _peer_device_cancel_edit(self):
        self._peer_device_form.pack_forget()
        self._render_peer_device_card()

    def _peer_device_save(self):
        host = self._peer_host_entry.get().strip()
        if not host:
            self._peer_device_msg_lbl.config(text="Host is required.", fg=RED)
            return
        # Adding a device implies turning dual-instance on — otherwise a
        # freshly filled-in host silently does nothing until the user
        # finds the toggle further down.
        self._dual_enabled_var.set(True)
        try:
            port = int(self._peer_port_entry.get().strip() or 5050)
        except ValueError:
            port = 5050
        try:
            timeout = int(self._auto_promote_timeout_entry.get().strip() or 5)
        except ValueError:
            timeout = 5
        payload = {"dual_instance": {
            "enabled": True,
            "peer_host": host,
            "peer_port": port,
            "peer_label": self._peer_label_entry.get().strip(),
            "primary_pin": self._primary_pin_var.get(),
            "auto_promote_enabled": self._auto_promote_var.get(),
            "auto_promote_timeout_minutes": timeout,
        }}
        self._peer_device_msg_lbl.config(text="Saving…", fg=TEXT_SEC)
        def _work():
            try:
                requests.post(f"{_API}/settings", json=payload, timeout=8)
                ok = True
            except Exception:
                ok = False
            def _apply():
                if ok:
                    self._peer_device_form.pack_forget()
                    self._render_peer_device_card()
                else:
                    self._peer_device_msg_lbl.config(text="Save failed — connection error.", fg=RED)
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _peer_device_remove(self):
        def _do():
            self._peer_host_entry.delete(0, "end")
            self._peer_label_entry.delete(0, "end")
            self._dual_enabled_var.set(False)
            try:
                port = int(self._peer_port_entry.get().strip() or 5050)
            except ValueError:
                port = 5050
            try:
                timeout = int(self._auto_promote_timeout_entry.get().strip() or 5)
            except ValueError:
                timeout = 5
            payload = {"dual_instance": {
                "enabled": False,
                "peer_host": "",
                "peer_port": port,
                "peer_label": "",
                "primary_pin": self._primary_pin_var.get(),
                "auto_promote_enabled": self._auto_promote_var.get(),
                "auto_promote_timeout_minutes": timeout,
            }}
            self._settings_post(payload)
            self._render_peer_device_card()
        self._confirm_dialog(
            "Remove peer device",
            "Remove this peer device? Dual-instance coordination and remote control "
            "will stop working until you add one again.",
            _do)

    # ── AlliedNode 2 device card — see modules/remote_node.py; no ADD/
    # REMOVE flow, always exists (defaults server-side to the pre-config
    # hardcoded values if never touched). Mirrors cortex-ui.html's
    # _renderAn2DeviceCard()/an2DeviceEdit()/an2DeviceSave(). ──
    def _render_an2_device_card(self):
        label = self._an2_label_entry.get().strip() or "AlliedNode 2"
        host = self._an2_host_entry.get().strip()
        port = self._an2_port_entry.get().strip() or "9797"
        self._an2_device_form.pack_forget()
        self._an2_device_name_lbl.config(text=label)
        self._an2_device_hostport_lbl.config(text=f"{host}:{port}" if host else "")
        self._an2_device_card.pack(fill="x", padx=12, pady=(0, 8))

    def _an2_device_edit(self):
        self._an2_device_card.pack_forget()
        self._an2_device_msg_lbl.config(text="", fg=TEXT_SEC)
        self._an2_device_form.pack(fill="x", padx=12, pady=(0, 8))

    def _an2_device_cancel_edit(self):
        self._an2_device_form.pack_forget()
        self._render_an2_device_card()

    def _load_an2_device(self):
        def _work():
            d = self._settings_get()
            an2 = {}
            if d and d.get("ok"):
                an2 = ((d.get("settings") or {}).get("allied_nodes") or {}).get("alliednode 2") or {}
            def _apply():
                try:
                    self._an2_label_entry.delete(0, "end")
                    self._an2_label_entry.insert(0, an2.get("label", "") or "AlliedNode 2")
                    self._an2_host_entry.delete(0, "end")
                    self._an2_host_entry.insert(0, an2.get("host", "") or "")
                    self._an2_port_entry.delete(0, "end")
                    self._an2_port_entry.insert(0, str(an2.get("port", 9797)))
                    self._an2_mac_entry.delete(0, "end")
                    self._an2_mac_entry.insert(0, an2.get("mac", "") or "")
                    self._render_an2_device_card()
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _an2_device_save(self):
        host = self._an2_host_entry.get().strip()
        if not host:
            self._an2_device_msg_lbl.config(text="Host is required.", fg=RED)
            return
        try:
            port = int(self._an2_port_entry.get().strip() or 9797)
        except ValueError:
            port = 9797
        payload = {"allied_nodes": {"alliednode 2": {
            "label": self._an2_label_entry.get().strip() or "AlliedNode 2",
            "host": host,
            "port": port,
            "mac": self._an2_mac_entry.get().strip(),
        }}}
        self._an2_device_msg_lbl.config(text="Saving…", fg=TEXT_SEC)
        def _work():
            try:
                r = requests.post(f"{_API}/settings", json=payload, timeout=8)
                ok = r.status_code == 200
            except Exception:
                ok = False
            def _apply():
                if ok:
                    self._an2_device_form.pack_forget()
                    self._render_an2_device_card()
                else:
                    self._an2_device_msg_lbl.config(text="Save failed — connection error.", fg=RED)
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _test_peer_connection(self):
        try:
            self._peer_status_lbl.config(text="● CHECKING…", fg=AMBER)
        except Exception:
            pass
        def _work():
            try:
                d = requests.get(f"{_API}/peer/check", timeout=8).json()
            except Exception:
                d = {"ok": False}
            def _apply():
                try:
                    if not d.get("ok"):
                        self._peer_status_lbl.config(text="● ERROR CHECKING", fg=RED)
                    elif not d.get("configured"):
                        self._peer_status_lbl.config(text="● NOT CONFIGURED", fg=TEXT_SEC)
                    elif d.get("reachable") and d.get("peer"):
                        p = d["peer"]
                        self._peer_status_lbl.config(
                            text=f"● REACHABLE — {p.get('platform','?')} ({p.get('hostname','?')})", fg=GREEN)
                    else:
                        self._peer_status_lbl.config(text="● UNREACHABLE", fg=RED)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _set_switch_progress_ui(self, pct, message, is_error):
        try:
            self._switch_progress_canvas.coords(self._switch_progress_fill, 0, 0, 300 * (pct / 100.0), 8)
            self._switch_progress_canvas.itemconfig(self._switch_progress_fill, fill=(RED if is_error else CYAN))
            self._switch_machine_lbl.config(text=f"{pct}% — {message}" if message else f"{pct}%",
                                            fg=(RED if is_error else TEXT_SEC))
        except Exception:
            pass

    def _switch_status_poll_loop(self):
        while self._switch_poller_active:
            try:
                d = requests.get(f"{_API}/switch_status", timeout=3).json()
                if d.get("stage") and d.get("stage") != "idle":
                    stage, pct, msg = d.get("stage"), d.get("percent") or 0, d.get("message") or ""
                    self._safe_after(0, lambda p=pct, m=msg, e=(stage == "failed"): self._set_switch_progress_ui(p, m, e))
            except Exception:
                pass  # peer/local process may already be mid-exit near the end — the POST's own response is authoritative
            time.sleep(0.8)

    def _switch_machine(self, target):
        def _do():
            self._switch_progress_canvas.pack(anchor="w", padx=12, pady=(4, 0))
            self._set_switch_progress_ui(0, "Starting...", False)
            self._switch_poller_active = True
            threading.Thread(target=self._switch_status_poll_loop, daemon=True).start()

            def _work():
                try:
                    d = requests.post(f"{_API}/switch_machine", json={"target": target}, timeout=95).json()
                except Exception:
                    d = {"ok": False, "message": "Connection error — this machine was not touched."}
                self._switch_poller_active = False
                def _apply():
                    if d.get("ok"):
                        self._set_switch_progress_ui(100, "Device Transfer Successful", False)
                        # Same mechanism Tkinter's own default WM_DELETE_WINDOW
                        # handler uses when no override is registered (there
                        # is none on self.root in JarvisUI) — winfo_toplevel()
                        # resolves to that root regardless of how deep this
                        # frame is nested, so this destroys the actual Forge
                        # window, matching Cortex's window.electronAPI.close().
                        self._safe_after(1800, lambda: self.winfo_toplevel().destroy())
                    else:
                        self._set_switch_progress_ui(0, d.get("message") or "Switch failed.", True)
                self._safe_after(0, _apply)
            threading.Thread(target=_work, daemon=True).start()

        self._confirm_dialog(
            "Switch machine",
            f"Switch iZACH to {'Windows' if target == 'windows' else 'Mac'}? This boots it there if "
            "needed, then shuts down here once it's confirmed healthy.",
            _do)

    # ── Peer Device Control (Phase 3) ──────────────────────────
    def _confirm_dialog(self, title, text, on_yes):
        # Toplevel + explicit buttons, not tkinter.messagebox — same
        # WebView2/pythonnet GIL-corruption reason as BrowserWindow's
        # _notify/_prompt_text (messagebox's blocking wait_window() loop
        # crashes once WebView2 is active in this process).
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=BG_PANEL)
        win.geometry("340x140")
        tk.Label(win, text=text, bg=BG_PANEL, fg=TEXT_PRI, font=("Consolas", 9),
                wraplength=300, justify="left").pack(padx=16, pady=16, expand=True)
        state = {"done": False}
        def _finish(v):
            if state["done"]:
                return
            state["done"] = True
            win.destroy()
            if v:
                on_yes()
        btn_row = tk.Frame(win, bg=BG_PANEL)
        btn_row.pack(pady=(0, 14))
        tk.Button(btn_row, text="YES", command=lambda: _finish(True),
                 bg="#2a0000", fg=RED, font=("Consolas", 9, "bold"), relief="flat",
                 cursor="hand2", padx=14, pady=5).pack(side="left", padx=6)
        tk.Button(btn_row, text="CANCEL", command=lambda: _finish(False),
                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 9, "bold"), relief="flat",
                 cursor="hand2", padx=14, pady=5).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: _finish(False))

    def _load_peer_local(self):
        def _work():
            try:
                d = requests.get(f"{_API}/peer/local", timeout=5).json()
            except Exception:
                d = {"ok": False}
            def _apply():
                try:
                    configured = bool(d.get("ok") and d.get("configured"))
                    if not configured:
                        self._peer_card_frame.pack_forget()
                        return
                    peer = d.get("peer") or {}
                    self._peer_label = (peer.get("platform") or "Peer").capitalize()
                    self._peer_name_lbl.config(text=f" {self._peer_label} — checking…")
                    self._refresh_peer_vitals()
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _refresh_peer_vitals(self):
        def _work():
            try:
                d = requests.get(f"{_API}/peer/vitals", timeout=8).json()
            except Exception:
                d = {"ok": False}
            def _apply():
                try:
                    if d.get("ok"):
                        self._peer_dot_lbl.config(fg=GREEN)
                        self._peer_name_lbl.config(text=f" {self._peer_label} — ONLINE")
                        self._peer_cpu_lbl.config(text=f"CPU {round(d.get('cpu_percent') or 0)}%")
                        self._peer_ram_lbl.config(text=f"RAM {round(d.get('ram_percent') or 0)}%")
                        self._peer_disk_lbl.config(text=f"DISK {round(d.get('disk_percent') or 0)}%")
                        batt = d.get("battery_percent")
                        batt_txt = f"BATT {batt}%{' ⚡' if d.get('battery_charging') else ''}" if batt is not None else "BATT N/A"
                        self._peer_batt_lbl.config(text=batt_txt)
                    else:
                        self._peer_dot_lbl.config(fg=RED)
                        self._peer_name_lbl.config(text=f" {self._peer_label} — OFFLINE")
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _peer_media(self, action):
        def _work():
            try:
                d = requests.post(f"{_API}/peer/media", json={"action": action}, timeout=8).json()
            except Exception:
                d = {"ok": False, "error": "request failed"}
            if not d.get("ok"):
                def _apply():
                    try:
                        self._peer_name_lbl.config(text=f" {self._peer_label}: {d.get('error') or d.get('message') or 'failed'}")
                    except Exception:
                        pass
                self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _peer_power(self, action, label):
        def _do():
            def _work():
                try:
                    d = requests.post(f"{_API}/peer/power", json={"action": action}, timeout=8).json()
                except Exception:
                    d = {"ok": False, "message": "request failed"}
                def _apply():
                    try:
                        self._peer_name_lbl.config(
                            text=f" {self._peer_label}: {d.get('message') or ('done' if d.get('ok') else 'failed')}")
                    except Exception:
                        pass
                self._safe_after(0, _apply)
            threading.Thread(target=_work, daemon=True).start()
        self._confirm_dialog("Confirm", f"{label} {self._peer_label}?", _do)

    def _peer_screenshot(self):
        def _work():
            try:
                d = requests.get(f"{_API}/peer/screenshot", timeout=15).json()
            except Exception:
                d = {"ok": False, "error": "request failed"}
            photo = None
            if d.get("ok") and d.get("screenshot"):
                try:
                    import base64, io
                    img = Image.open(io.BytesIO(base64.b64decode(d["screenshot"])))
                    w = 320
                    h = int(img.height * (w / img.width))
                    img = img.resize((w, h))
                    photo = ImageTk.PhotoImage(img)
                except Exception:
                    photo = None
            def _apply():
                try:
                    if photo is not None:
                        self._peer_snap_lbl.config(image=photo, text="")
                        self._peer_snap_lbl.image = photo  # keep a reference, Tk drops it otherwise
                    else:
                        self._peer_snap_lbl.config(text=d.get("error") or "Screenshot failed", fg=RED, image="")
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _peer_refresh_procs(self):
        def _work():
            try:
                d = requests.get(f"{_API}/peer/processes", timeout=8).json()
            except Exception:
                d = {"ok": False, "error": "request failed"}
            def _apply():
                try:
                    self._peer_procs_text.config(state="normal")
                    self._peer_procs_text.delete("1.0", "end")
                    if d.get("ok") and d.get("processes"):
                        for p in d["processes"]:
                            self._peer_procs_text.insert(
                                "end",
                                f"{p.get('name',''):<28} C:{p.get('cpu_percent',0):.1f}% M:{p.get('memory_percent',0):.1f}%\n")
                    else:
                        self._peer_procs_text.insert("end", d.get("error") or "No processes returned")
                    self._peer_procs_text.config(state="disabled")
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _load_dc_phone_status(self):
        def _work():
            try:
                d = requests.get(f"{_API}/phone/status", timeout=5).json()
            except Exception:
                d = {"connected": False, "device_name": ""}
            def _apply():
                try:
                    connected = bool(d.get("connected"))
                    self._dc_phone_status_lbl.config(
                        text="● CONNECTED" if connected else "● DISCONNECTED",
                        fg=GREEN if connected else TEXT_SEC)
                    name = d.get("device_name") or ""
                    self._dc_phone_name_lbl.config(text=f"Device: {name}" if (connected and name) else "")
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _remove_phone_device(self):
        def _work():
            try:
                requests.post(f"{_API}/phone/unpair", timeout=8)
            except Exception as e:
                print(f"[SETTINGS] Phone unpair error: {e}")
            self._safe_after(0, self._load_dc_phone_status)
            self._safe_after(0, self._load_phone_pairing_ui)
        threading.Thread(target=_work, daemon=True).start()

    # ── Connected Services additions — Calendar, Spotify, WhatsApp restart ──
    def _build_connected_services_section(self):
        card = self._section("GOOGLE CALENDAR")
        cal_status_row = tk.Frame(card, bg=BG_CARD)
        cal_status_row.pack(fill="x", padx=12, pady=(0, 6))
        self._cal_status_lbl = tk.Label(cal_status_row, text="● NOT CONNECTED", bg=BG_CARD, fg=TEXT_SEC,
                                        font=("Consolas", 9, "bold"))
        self._cal_status_lbl.pack(side="left")
        cal_btn_row = tk.Frame(card, bg=BG_CARD)
        cal_btn_row.pack(fill="x", padx=12, pady=(0, 10))
        self._cal_connect_btn = tk.Button(cal_btn_row, text="⊕ CONNECT GOOGLE CALENDAR", command=self._cal_connect_start,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)
        self._cal_connect_btn.pack(side="left")
        self._cal_disconnect_btn = tk.Button(cal_btn_row, text="DISCONNECT", command=self._cal_disconnect,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        card2 = self._section("SPOTIFY")
        sp_status_row = tk.Frame(card2, bg=BG_CARD)
        sp_status_row.pack(fill="x", padx=12, pady=(0, 6))
        self._sp_status_lbl = tk.Label(sp_status_row, text="● NOT CONNECTED", bg=BG_CARD, fg=TEXT_SEC,
                                       font=("Consolas", 9, "bold"))
        self._sp_status_lbl.pack(side="left")
        sp_btn_row = tk.Frame(card2, bg=BG_CARD)
        sp_btn_row.pack(fill="x", padx=12, pady=(0, 10))
        self._sp_connect_btn = tk.Button(sp_btn_row, text="⊕ CONNECT SPOTIFY", command=self._sp_connect_start,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)
        self._sp_connect_btn.pack(side="left")
        self._sp_disconnect_btn = tk.Button(sp_btn_row, text="DISCONNECT", command=self._sp_disconnect,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4)
        tk.Label(card2, text="Client ID/Secret are entered separately under Keys & ID — this is\n"
                             "just the connect/disconnect step on top of those credentials.",
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8), justify="left").pack(
            anchor="w", padx=12, pady=(0, 8))
        tk.Frame(card2, bg=BG_CARD, height=6).pack()

        card3 = self._section("WHATSAPP")
        self._wa_restart_msg_var = tk.StringVar()
        tk.Button(card3, text="RESTART WHATSAPP BRIDGE", command=self._restart_whatsapp_bridge,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(anchor="w", padx=12, pady=(0, 4))
        tk.Label(card3, textvariable=self._wa_restart_msg_var, bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 8))
        tk.Frame(card3, bg=BG_CARD, height=6).pack()

        self._cal_refresh_status()
        self._sp_refresh_status()

    def _cal_refresh_status(self):
        def _work():
            try:
                r = requests.get(f"{_API}/calendar/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False}
            self._safe_after(0, lambda: self._cal_apply_status(r))
        threading.Thread(target=_work, daemon=True).start()

    def _cal_apply_status(self, status):
        try:
            connected = bool(status.get("connected"))
            if connected:
                user = status.get("user") or ""
                self._cal_status_lbl.config(text=f"● CONNECTED — {user}" if user else "● CONNECTED", fg=GREEN)
                self._cal_connect_btn.pack_forget()
                self._cal_disconnect_btn.pack(side="left")
            else:
                self._cal_status_lbl.config(text="● NOT CONNECTED", fg=TEXT_SEC)
                self._cal_disconnect_btn.pack_forget()
                self._cal_connect_btn.pack(side="left")
        except Exception:
            pass

    def _cal_connect_start(self):
        def _work():
            try:
                requests.post(f"{_API}/calendar/auth/connect", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Calendar connect error: {e}")
                return
            self._safe_after(0, lambda: self._cal_poll_connect())
        threading.Thread(target=_work, daemon=True).start()

    def _cal_poll_connect(self, attempt=0):
        try:
            self._cal_status_lbl.config(text="● CONNECTING…", fg=AMBER)
        except Exception:
            pass
        def _work():
            try:
                r = requests.get(f"{_API}/calendar/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False}
            def _apply():
                if r.get("connected") or attempt > 40:
                    self._cal_apply_status(r)
                else:
                    self._safe_after(3000, lambda: self._cal_poll_connect(attempt + 1))
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _cal_disconnect(self):
        def _work():
            try:
                requests.post(f"{_API}/calendar/auth/disconnect", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Calendar disconnect error: {e}")
            self._safe_after(0, self._cal_refresh_status)
        threading.Thread(target=_work, daemon=True).start()

    def _sp_refresh_status(self):
        def _work():
            try:
                r = requests.get(f"{_API}/spotify/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False}
            self._safe_after(0, lambda: self._sp_apply_status(r))
        threading.Thread(target=_work, daemon=True).start()

    def _sp_apply_status(self, status):
        try:
            connected = bool(status.get("connected"))
            if connected:
                user = status.get("user") or ""
                self._sp_status_lbl.config(text=f"● CONNECTED — {user}" if user else "● CONNECTED", fg=GREEN)
                self._sp_connect_btn.pack_forget()
                self._sp_disconnect_btn.pack(side="left")
            else:
                self._sp_status_lbl.config(text="● NOT CONNECTED", fg=TEXT_SEC)
                self._sp_disconnect_btn.pack_forget()
                self._sp_connect_btn.pack(side="left")
        except Exception:
            pass

    def _sp_connect_start(self):
        def _work():
            try:
                requests.post(f"{_API}/spotify/auth/connect", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Spotify connect error: {e}")
                return
            self._safe_after(0, lambda: self._sp_poll_connect())
        threading.Thread(target=_work, daemon=True).start()

    def _sp_poll_connect(self, attempt=0):
        try:
            self._sp_status_lbl.config(text="● CONNECTING…", fg=AMBER)
        except Exception:
            pass
        def _work():
            try:
                r = requests.get(f"{_API}/spotify/auth/status", timeout=5).json()
            except Exception:
                r = {"connected": False}
            def _apply():
                if r.get("connected") or attempt > 40:
                    self._sp_apply_status(r)
                else:
                    self._safe_after(3000, lambda: self._sp_poll_connect(attempt + 1))
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _sp_disconnect(self):
        def _work():
            try:
                requests.post(f"{_API}/spotify/auth/disconnect", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Spotify disconnect error: {e}")
            self._safe_after(0, self._sp_refresh_status)
        threading.Thread(target=_work, daemon=True).start()

    def _restart_whatsapp_bridge(self):
        try:
            self._wa_restart_msg_var.set("Restarting…")
        except Exception:
            pass
        def _work():
            try:
                d = requests.post(f"{_API}/whatsapp/restart-bridge", timeout=10).json()
                msg = f"Bridge {d.get('status', 'restarted')}." if d.get("ok") else f"Error: {d.get('error', 'unknown')}"
            except Exception as e:
                msg = f"Backend offline: {e}"
            def _apply():
                try:
                    self._wa_restart_msg_var.set(msg)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    # ── Boot Settings Section ──
    def _build_boot_settings_section(self):
        card = self._section("INTERFACE MODE")
        tk.Label(card, text="Restart required to apply", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 6))
        self._boot_ui_var = tk.StringVar(value="classic")
        for label, val in [("Interactive (Cortex/Forge UI opens)", "classic"),
                            ("Background — voice/tray only, low RAM", "background")]:
            tk.Radiobutton(card, text=label, value=val, variable=self._boot_ui_var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8)).pack(anchor="w", padx=12, pady=2)
        self._ask_ui_boot_var = tk.BooleanVar(value=False)
        tk.Checkbutton(card, text="Ask Every Time During Boot", variable=self._ask_ui_boot_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(4, 8))
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        card2 = self._section("BOOT TERMINALS")
        tk.Label(card2, text="Skip launching terminals for services you don't use.",
                bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 6))
        self._boot_term_vars = {}
        for key, label in [
            ("boot_interface", "Boot Interface Terminal"),
            ("backend", "Python Backend Terminal"),
            ("ngrok", "Ngrok Terminal"),
            ("whatsapp_bridge", "WhatsApp Bridge Terminal"),
            ("n8n", "n8n Terminal"),
        ]:
            var = tk.BooleanVar(value=True)
            self._boot_term_vars[key] = var
            tk.Checkbutton(card2, text=label, variable=var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8)).pack(anchor="w", padx=12, pady=2)

        tk.Button(card2, text="SAVE BOOT SETTINGS", command=self._save_boot_settings,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(anchor="w", padx=12, pady=(8, 10))

        self._load_boot_settings()

    def _load_boot_settings(self):
        def _work():
            d = self._settings_get()
            s = (d.get("settings") or {}) if (d and d.get("ok")) else {}
            def _apply():
                try:
                    self._boot_ui_var.set(s.get("ui", "classic"))
                    self._ask_ui_boot_var.set(bool(s.get("ask_ui_on_boot")))
                    bt = s.get("boot_terminals") or {}
                    for key, var in self._boot_term_vars.items():
                        var.set(bool(bt.get(key, True)))
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_boot_settings(self):
        payload = {
            "ui": self._boot_ui_var.get(),
            "ask_ui_on_boot": self._ask_ui_boot_var.get(),
            "boot_terminals": {k: v.get() for k, v in self._boot_term_vars.items()},
        }
        self._settings_post(payload)

    # ── Security Section ──
    def _build_security_section(self):
        card = self._section("VOICE AUTHENTICATION")
        self._voice_status_lbl = tk.Label(card, text="● CHECKING…", bg=BG_CARD, fg=TEXT_SEC,
                                          font=("Consolas", 9, "bold"))
        self._voice_status_lbl.pack(anchor="w", padx=12, pady=(0, 8))
        btn_row = tk.Frame(card, bg=BG_CARD)
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(btn_row, text="ENROLL VOICE", command=self._enroll_voice,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="DELETE", command=self._delete_voice,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left")
        self._voice_msg_var = tk.StringVar()
        tk.Label(card, textvariable=self._voice_msg_var, bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 8))
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        card2 = self._section("FACE AUTHENTICATION")
        self._face_status_lbl = tk.Label(card2, text="● CHECKING…", bg=BG_CARD, fg=TEXT_SEC,
                                         font=("Consolas", 9, "bold"))
        self._face_status_lbl.pack(anchor="w", padx=12, pady=(0, 8))
        btn_row2 = tk.Frame(card2, bg=BG_CARD)
        btn_row2.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(btn_row2, text="ENROLL FACE", command=self._enroll_face,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left", padx=(0, 8))
        tk.Button(btn_row2, text="DELETE", command=self._delete_face,
                 bg="#2a0000", fg=RED, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left")
        self._face_msg_var = tk.StringVar()
        tk.Label(card2, textvariable=self._face_msg_var, bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 8))
        tk.Frame(card2, bg=BG_CARD, height=6).pack()

        card3 = self._section("EXPORT")
        exp_row = tk.Frame(card3, bg=BG_CARD)
        exp_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(exp_row, text="EXPORT CHAT (TXT)", command=lambda: self._export_chat("txt"),
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left", padx=(0, 8))
        tk.Button(exp_row, text="EXPORT CHAT (PDF)", command=lambda: self._export_chat("pdf"),
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left")
        tk.Frame(card3, bg=BG_CARD, height=6).pack()

        self._refresh_voice_status()
        self._refresh_face_status()

    def _refresh_voice_status(self):
        def _work():
            try:
                d = requests.get(f"{_API}/voice/status", timeout=5).json()
                enrolled = bool(d.get("enrolled"))
            except Exception:
                enrolled = False
            def _apply():
                try:
                    self._voice_status_lbl.config(
                        text="● ENROLLED" if enrolled else "● NOT ENROLLED",
                        fg=GREEN if enrolled else TEXT_SEC)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _enroll_voice(self):
        self._voice_msg_var.set("Starting guided enrollment — follow the voice prompts…")
        def _work():
            try:
                requests.post(f"{_API}/voice/enroll", json={"label": "owner"}, timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Voice enroll error: {e}")
            self._safe_after(5000, self._refresh_voice_status)
        threading.Thread(target=_work, daemon=True).start()

    def _delete_voice(self):
        def _work():
            try:
                requests.delete(f"{_API}/voice/delete", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Voice delete error: {e}")
            self._safe_after(0, self._refresh_voice_status)
        threading.Thread(target=_work, daemon=True).start()

    def _refresh_face_status(self):
        def _work():
            try:
                d = requests.get(f"{_API}/face/status", timeout=5).json()
                enrolled = bool(d.get("enrolled"))
            except Exception:
                enrolled = False
            def _apply():
                try:
                    self._face_status_lbl.config(
                        text="● ENROLLED" if enrolled else "● NOT ENROLLED",
                        fg=GREEN if enrolled else TEXT_SEC)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _enroll_face(self):
        self._face_msg_var.set("Starting enrollment — look at the camera…")
        def _work():
            try:
                d = requests.post(f"{_API}/face/enroll", timeout=5).json()
                if not d.get("ok"):
                    msg = d.get("error", "Enrollment failed")
                    self._safe_after(0, lambda: self._face_msg_var.set(msg))
                    return
            except Exception as e:
                self._safe_after(0, lambda: self._face_msg_var.set(f"Error: {e}"))
                return
            self._safe_after(5000, self._refresh_face_status)
        threading.Thread(target=_work, daemon=True).start()

    def _delete_face(self):
        def _work():
            try:
                requests.delete(f"{_API}/face/delete", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Face delete error: {e}")
            self._safe_after(0, self._refresh_face_status)
        threading.Thread(target=_work, daemon=True).start()

    def _export_chat(self, fmt):
        def _work():
            try:
                r = requests.get(f"{_API}/export-chat", params={"format": fmt}, timeout=15)
                content = r.content
            except Exception as e:
                print(f"[SETTINGS] Export error: {e}")
                return
            def _save():
                import tkinter.filedialog as fd
                ext = ".pdf" if fmt == "pdf" else ".txt"
                path = fd.asksaveasfilename(defaultextension=ext,
                                            initialfile=f"iZACH-chat-export{ext}")
                if path:
                    with open(path, "wb") as f:
                        f.write(content)
            self._safe_after(0, _save)
        threading.Thread(target=_work, daemon=True).start()

    # ── Contacts Section ──
    def _build_contacts_section(self):
        card = self._section("CONTACTS")

        add_row = tk.Frame(card, bg=BG_CARD)
        add_row.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(add_row, text="Number", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")
        self._contact_num_entry = tk.Entry(add_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                            font=("Consolas", 9), relief="flat",
                                            highlightthickness=1, highlightbackground=BORDER_HI, width=16)
        self._contact_num_entry.pack(side="left", padx=(4, 8), ipady=3)
        tk.Label(add_row, text="Name", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left")
        self._contact_name_entry = tk.Entry(add_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                             font=("Consolas", 9), relief="flat",
                                             highlightthickness=1, highlightbackground=BORDER_HI, width=20)
        self._contact_name_entry.pack(side="left", padx=(4, 8), ipady=3)
        tk.Button(add_row, text="+ ADD", command=self._add_contact,
                 bg=GREEN_DIM, fg=GREEN, font=("Consolas", 9, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(side="left")

        import_row = tk.Frame(card, bg=BG_CARD)
        import_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(import_row, text="IMPORT CSV / VCF", command=self._import_contacts,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left")
        self._contact_msg_var = tk.StringVar()
        tk.Label(import_row, textvariable=self._contact_msg_var, bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(side="left", padx=(8, 0))

        self._contacts_frame = tk.Frame(card, bg=BG_CARD)
        self._contacts_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        self._load_contacts_ui()

    def _load_contacts_ui(self):
        def _work():
            try:
                d = requests.get(f"{_API}/contacts", timeout=5).json()
                contacts = d.get("contacts", []) if d.get("ok") else []
            except Exception:
                contacts = []
            def _apply():
                try:
                    for w in self._contacts_frame.winfo_children():
                        w.destroy()
                    if not contacts:
                        tk.Label(self._contacts_frame, text="No contacts saved.",
                                 bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8)).pack(anchor="w")
                        return
                    for c in contacts:
                        row = tk.Frame(self._contacts_frame, bg="#071020",
                                      highlightthickness=1, highlightbackground=BORDER)
                        row.pack(fill="x", pady=2)
                        tk.Label(row, text=c.get("name", ""), bg="#071020", fg=CYAN,
                                 font=("Consolas", 9, "bold"), width=22,
                                 anchor="w").pack(side="left", padx=(8, 4), pady=4)
                        tk.Label(row, text=c.get("number", ""), bg="#071020", fg=TEXT_SEC,
                                 font=("Consolas", 8), anchor="w").pack(side="left", fill="x", expand=True)
                        tk.Button(row, text="✕", bg="#1a0000", fg=RED,
                                  font=("Consolas", 8, "bold"), relief="flat", cursor="hand2",
                                  padx=6, pady=2,
                                  command=lambda n=c.get("number", ""): self._delete_contact(n)
                                  ).pack(side="right", padx=6)
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _add_contact(self):
        number = self._contact_num_entry.get().strip()
        name = self._contact_name_entry.get().strip()
        if not number or not name:
            self._contact_msg_var.set("Number and name required.")
            return
        def _work():
            try:
                d = requests.post(f"{_API}/contacts", json={"number": number, "name": name}, timeout=5).json()
            except Exception as e:
                d = {"ok": False, "error": str(e)}
            def _apply():
                try:
                    if d.get("ok"):
                        self._contact_num_entry.delete(0, "end")
                        self._contact_name_entry.delete(0, "end")
                        self._contact_msg_var.set(f'Added "{name}"')
                        self._load_contacts_ui()
                    else:
                        self._contact_msg_var.set(d.get("error", "Error"))
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _delete_contact(self, number):
        def _work():
            try:
                requests.delete(f"{_API}/contacts/{quote(number, safe='')}", timeout=5)
            except Exception as e:
                print(f"[SETTINGS] Contact delete error: {e}")
            self._safe_after(0, self._load_contacts_ui)
        threading.Thread(target=_work, daemon=True).start()

    def _import_contacts(self):
        import tkinter.filedialog as fd
        path = fd.askopenfilename(filetypes=[("Contacts", "*.csv;*.vcf")])
        if not path:
            return
        def _work():
            try:
                with open(path, "rb") as f:
                    d = requests.post(f"{_API}/contacts/import",
                                      files={"file": (os.path.basename(path), f)}, timeout=15).json()
            except Exception as e:
                d = {"ok": False, "error": str(e)}
            def _apply():
                try:
                    if d.get("ok"):
                        self._contact_msg_var.set(f"Imported {d.get('imported', 0)} contacts.")
                        self._load_contacts_ui()
                    else:
                        self._contact_msg_var.set(d.get("error", "Import failed"))
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    # ── Commands Section — static list, mirrors Cortex UI's own hardcoded
    # accordion (cortex-ui.html buildCommandsAccordion) rather than any live
    # backend registry, since no such registry exists on either side. ──
    _COMMAND_CATEGORIES = [
        ("Media & Spotify", ["Play [song/artist]", "Pause / Resume music", "Next track / Previous track",
                              "Set volume to [0-100]", "Search Spotify for [query]", "Add to liked songs",
                              "Show current song"]),
        ("System Control", ["Set brightness to [0-100]", "Mute / Unmute system", "Open Task Manager",
                             "Lock screen", "Restart / Shutdown PC", "Take screenshot", "Empty recycle bin"]),
        ("WhatsApp", ['Send "[message]" to [contact]', "Read messages from [contact]",
                      "Read last WhatsApp message", "Reply to last message", "Mark as read",
                      "Show group summary"]),
        ("Web & Search", ["Search [query] on Google", "Open YouTube and search [query]",
                          "Look up [topic] on Wikipedia", "Open [website]", "Translate [text] to [language]",
                          "Find news about [topic]"]),
        ("Productivity & Files", ["Open [app name]", "Open [file/folder]", "Create a new note in Obsidian",
                                  "Set reminder for [time]: [task]", "Show my reminders", "Sync Obsidian vault"]),
        ("Weather & News", ["What's the weather today?", "Weather in [city]", "5-day forecast",
                            "Top headlines today", "News about [topic]", "Any sports results?"]),
        ("Memory & Knowledge", ["Remember [key] is [value]", "What is [key]?", "Forget [key]",
                                "What do you know about me?", "Show all memories", "Update [key] to [value]"]),
        ("App Launcher", ["Open Chrome / Firefox", "Open VS Code", "Open Spotify", "Open WhatsApp Web",
                         "Open File Explorer", "Open Notepad", "Open Settings"]),
        ("Clipboard & Docs", ["Read clipboard", "Copy [text] to clipboard", "Summarize clipboard",
                             "Translate clipboard", "Format as code", "Ask AI about clipboard"]),
        ("Smart Devices & IoT", ["Turn on/off [device]", "Set [device] brightness to [%]",
                                 "What devices are connected?", "Run scene [name]"]),
        ("Finance & Research", ["Stock price of [symbol]", "Research [topic]", "Summarize this URL",
                               "Compare [A] vs [B]", "Calculate [expression]"]),
        ("Automation & Chains", ["Run chain [name]", "Create a command chain", "Schedule [task] at [time]",
                                 "What chains are saved?", "Run morning routine"]),
    ]

    def _build_commands_section(self):
        card = self._section("VOICE COMMANDS")
        self._cmd_open = set()
        for name, cmds in self._COMMAND_CATEGORIES:
            block = tk.Frame(card, bg=BG_CARD)
            block.pack(fill="x", padx=12, pady=2)
            list_frame = tk.Frame(block, bg="#071020", highlightthickness=1, highlightbackground=BORDER)

            def _toggle(n=name, lf=list_frame, btn_holder=[]):
                if n in self._cmd_open:
                    self._cmd_open.discard(n)
                    lf.pack_forget()
                else:
                    self._cmd_open.add(n)
                    lf.pack(fill="x", pady=(2, 6))

            btn = tk.Button(block, text=f"▾ {name}", command=_toggle,
                            bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                            relief="flat", cursor="hand2", anchor="w", padx=8, pady=4)
            btn.pack(fill="x")
            for c in cmds:
                tk.Label(list_frame, text=f"· {c}", bg="#071020", fg=TEXT_PRI,
                         font=("Consolas", 8), anchor="w").pack(fill="x", padx=10, pady=1)
        tk.Frame(card, bg=BG_CARD, height=6).pack()

    # ── Others Section — privacy + system actions ──
    def _build_others_section(self):
        card = self._section("PRIVACY")
        row = tk.Frame(card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=4)
        self._cmd_history_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="Save Command History", variable=self._cmd_history_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(side="left")

        ret_row = tk.Frame(card, bg=BG_CARD)
        ret_row.pack(fill="x", padx=12, pady=4)
        tk.Label(ret_row, text="Log Retention", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        self._log_retention_var = tk.StringVar(value="30")
        for label, val in [("7d", "7"), ("14d", "14"), ("30d", "30"), ("90d", "90")]:
            tk.Radiobutton(ret_row, text=label, value=val, variable=self._log_retention_var,
                          bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                          font=("Consolas", 8)).pack(side="left", padx=(0, 8))

        tk.Button(card, text="SAVE", command=self._save_privacy_settings,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(anchor="w", padx=12, pady=(6, 10))
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        card2 = self._section("SYSTEM ACTIONS")
        act_row = tk.Frame(card2, bg=BG_CARD)
        act_row.pack(fill="x", padx=12, pady=(0, 6))
        tk.Button(act_row, text="ANALYZE LOGS", command=self._analyze_logs,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left", padx=(0, 8))
        tk.Button(act_row, text="SYNC OBSIDIAN", command=self._sync_obsidian,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left", padx=(0, 8))
        tk.Button(act_row, text="CLEAR CACHE", command=self._clear_cache,
                 bg=BG_PANEL, fg=TEXT_SEC, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=8, pady=4).pack(side="left")
        self._sys_action_msg_var = tk.StringVar()
        tk.Label(card2, textvariable=self._sys_action_msg_var, bg=BG_CARD, fg=AMBER,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 8))
        tk.Frame(card2, bg=BG_CARD, height=6).pack()

        self._load_privacy_settings()

    def _load_privacy_settings(self):
        def _work():
            d = self._settings_get()
            s = (d.get("settings") or {}) if (d and d.get("ok")) else {}
            def _apply():
                try:
                    self._cmd_history_var.set(bool(s.get("command_history_enabled", True)))
                    self._log_retention_var.set(str(s.get("log_retention_days", 30)))
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_privacy_settings(self):
        self._settings_post({
            "command_history_enabled": self._cmd_history_var.get(),
            "log_retention_days": int(self._log_retention_var.get()),
        })

    def _analyze_logs(self):
        self._sys_action_msg_var.set("Analyzing…")
        def _work():
            try:
                d = requests.post(f"{_API}/analyze", params={"mode": "overwrite"}, timeout=30).json()
                msg = d.get("message", "Done.") if d.get("ok") else d.get("error", "Failed")
            except Exception as e:
                msg = f"Error: {e}"
            self._safe_after(0, lambda: self._sys_action_msg_var.set(msg))
        threading.Thread(target=_work, daemon=True).start()

    def _sync_obsidian(self):
        self._sys_action_msg_var.set("Syncing…")
        def _work():
            try:
                d = requests.post(f"{_API}/obsidian/sync", timeout=15).json()
                msg = d.get("message", "Synced.") if d.get("ok") else d.get("error", "Failed")
            except Exception as e:
                msg = f"Error: {e}"
            self._safe_after(0, lambda: self._sys_action_msg_var.set(msg))
        threading.Thread(target=_work, daemon=True).start()

    def _clear_cache(self):
        self._sys_action_msg_var.set("Clearing…")
        def _work():
            try:
                d = requests.post(f"{_API}/cache/clear", json={"targets": ["temp", "screenshots"]}, timeout=15).json()
                msg = ", ".join(d.get("cleared", [])) or "Cleared." if d.get("ok") else d.get("error", "Failed")
            except Exception as e:
                msg = f"Error: {e}"
            self._safe_after(0, lambda: self._sys_action_msg_var.set(msg))
        threading.Thread(target=_work, daemon=True).start()

    # ── Advanced Section — overlays, hotkeys, power ──
    def _build_advanced_section(self):
        card = self._section("OVERLAYS")
        hk_row = tk.Frame(card, bg=BG_CARD)
        hk_row.pack(fill="x", padx=12, pady=4)
        tk.Label(hk_row, text="Command Bar", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        self._hotkey_bar_entry = tk.Entry(hk_row, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                          font=("Consolas", 9), relief="flat",
                                          highlightthickness=1, highlightbackground=BORDER_HI, width=20)
        self._hotkey_bar_entry.pack(side="left", padx=(4, 0), ipady=3)

        hk_row2 = tk.Frame(card, bg=BG_CARD)
        hk_row2.pack(fill="x", padx=12, pady=4)
        tk.Label(hk_row2, text="Mic Toggle", bg=BG_CARD, fg=TEXT_PRI,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        self._hotkey_mic_entry = tk.Entry(hk_row2, bg=BG_DEEP, fg=CYAN, insertbackground=CYAN,
                                          font=("Consolas", 9), relief="flat",
                                          highlightthickness=1, highlightbackground=BORDER_HI, width=20)
        self._hotkey_mic_entry.pack(side="left", padx=(4, 0), ipady=3)
        tk.Label(card, text="restart required to apply", bg=BG_CARD, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(anchor="w", padx=12, pady=(0, 4))

        ptt_row = tk.Frame(card, bg=BG_CARD)
        ptt_row.pack(fill="x", padx=12, pady=4)
        self._ptt_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ptt_row, text="Push-to-Talk Mode (coming soon — hotkey toggles regardless for now)", variable=self._ptt_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(side="left")
        tk.Frame(card, bg=BG_CARD, height=6).pack()

        card2 = self._section("POWER SETTINGS")
        self._batt_auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(card2, text="Auto Background on Battery", variable=self._batt_auto_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(anchor="w", padx=12, pady=2)
        self._lid_close_var = tk.BooleanVar(value=False)
        tk.Checkbutton(card2, text="Auto Background on Lid Close", variable=self._lid_close_var,
                      bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_DEEP, activebackground=BG_CARD,
                      font=("Consolas", 8)).pack(anchor="w", padx=12, pady=2)

        tk.Button(card2, text="SAVE", command=self._save_advanced_settings,
                 bg=CYAN_DARK, fg=CYAN, font=("Consolas", 8, "bold"),
                 relief="flat", cursor="hand2", padx=10, pady=3).pack(anchor="w", padx=12, pady=(8, 10))

        self._load_advanced_settings()

    def _load_advanced_settings(self):
        def _work():
            d = self._settings_get()
            s = (d.get("settings") or {}) if (d and d.get("ok")) else {}
            def _apply():
                try:
                    self._hotkey_bar_entry.delete(0, "end")
                    self._hotkey_bar_entry.insert(0, s.get("hotkey_bar", "ctrl+shift+space"))
                    self._hotkey_mic_entry.delete(0, "end")
                    self._hotkey_mic_entry.insert(0, s.get("hotkey_mic", "ctrl+shift+m"))
                    self._ptt_var.set(bool(s.get("push_to_talk")))
                    self._batt_auto_var.set(bool(s.get("battery_auto_switch")))
                    self._lid_close_var.set(bool(s.get("lid_close_trigger")))
                except Exception:
                    pass
            self._safe_after(0, _apply)
        threading.Thread(target=_work, daemon=True).start()

    def _save_advanced_settings(self):
        self._settings_post({
            "hotkey_bar": self._hotkey_bar_entry.get().strip().lower(),
            "hotkey_mic": self._hotkey_mic_entry.get().strip().lower(),
            "push_to_talk": self._ptt_var.get(),
            "battery_auto_switch": self._batt_auto_var.get(),
            "lid_close_trigger": self._lid_close_var.get(),
        })

    def _safe_after(self, delay, fn):
        """Wraps self.after() so a background request that outlives its tab
        (user switched tabs before the response came back) fails silently
        instead of throwing "invalid command name" — destroy-and-rebuild-on-
        switch means the widget a deferred callback was going to update may
        no longer exist by the time it actually runs."""
        def _wrapped():
            try:
                fn()
            except tk.TclError:
                pass
        self.after(delay, _wrapped)

    def _close(self):
        self.pack_forget()
        if self.on_close:
            self.on_close()


# ─────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────
class JarvisUI:
    def __init__(self, face_path="face.png", orchestrator=None, spotify_handler=None):
        self.orchestrator = orchestrator
        self.spotify_handler = spotify_handler
        self._chain = None
        self._mic_active = True

        self.root = tk.Tk()
        self.root.title("iZACH — FORGE UI")
        self.root.geometry("1280x800")
        self.root.minsize(1100, 720)
        self.root.configure(bg=BG_DEEP)
        self._build()

    def set_chain(self, chain):
        self._chain = chain

    def _build(self):
        # ── Title bar ──
        title_bar = tk.Frame(self.root, bg=BG_DEEP, height=60)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        tk.Label(title_bar,
                 text="INTENT ZENITH ADAPTIVE COGNITIVE HANDLER",
                 bg=BG_DEEP, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack()

        tk.Button(title_bar, text="⚙ SETTINGS",
                  bg=BG_DEEP, fg=TEXT_SEC,
                  font=("Consolas", 8), relief="flat",
                  cursor="hand2",
                  activebackground=BG_PANEL,
                  command=self._open_settings,
                  padx=10, pady=2).place(relx=1.0, x=-120, y=12)

        tk.Button(title_bar, text="🌐 BROWSER",
                  bg=BG_DEEP, fg=TEXT_SEC,
                  font=("Consolas", 8), relief="flat",
                  cursor="hand2",
                  activebackground=BG_PANEL,
                  command=self._open_browser,
                  padx=10, pady=2).place(relx=1.0, x=-230, y=12)

        # ── Bottom ticker ──
        ticker_bar = tk.Frame(self.root, bg=BG_PANEL, height=24)
        ticker_bar.pack(side="bottom", fill="x")
        ticker_bar.pack_propagate(False)

        self._ticker_var = tk.StringVar(value="")
        tk.Label(ticker_bar, textvariable=self._ticker_var,
                 bg=BG_PANEL, fg=TEXT_SEC,
                 font=("Consolas", 8)).pack(side="left", padx=10)
        self._status_var = tk.StringVar(value="A.I LINK ACTIVE")
        tk.Label(ticker_bar, textvariable=self._status_var,
                 bg=BG_PANEL, fg=GREEN,
                 font=("Consolas", 8, "bold")).pack(side="right", padx=10)
        self._update_ticker()

        # ── Outer border frame ──
        outer = tk.Frame(self.root, bg=BG_DEEP,
                         highlightthickness=1,
                         highlightbackground=BORDER_HI)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # ── 3-column layout ──
        # LEFT | CENTER | RIGHT
        left = tk.Frame(outer, bg=BG_DEEP, width=300)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        left.pack_propagate(False)

        right = tk.Frame(outer, bg=BG_DEEP, width=280)
        right.pack(side="right", fill="y", padx=(4, 8), pady=8)
        right.pack_propagate(False)

        center = tk.Frame(outer, bg=BG_DEEP)
        center.pack(side="left", fill="both", expand=True, padx=4, pady=8)

        # ── LEFT: stats (top) + camera (bottom) ──
        stats_card = _card(left)
        stats_card.pack(fill="x", pady=(0, 6))
        StatsPanel(stats_card).pack(fill="x")

        cam_card = _card(left)
        cam_card.pack(fill="both", expand=True)
        CameraPanel(cam_card).pack(fill="both", expand=True)

        # ── CENTER: neural (top) + mic + chat + input ──
        neural_card = _card(center)
        neural_card.pack(fill="x", pady=(0, 6))

        self._neural = NeuralCore(neural_card, size=300)
        self._neural.pack(pady=(10, 6))
        # Phase 5: live word display — shown at top of chat during speech
        self._live_text_var = tk.StringVar(value="")
        self._live_bar = tk.Frame(neural_card, bg=CYAN_DARK, height=0)
        self._live_bar.pack(fill="x")
        self._live_text = tk.Label(
            self._live_bar,
            textvariable=self._live_text_var,
            bg=CYAN_DARK, fg=CYAN,
            font=("Consolas", 10, "italic"),
            wraplength=560,
            justify="center",
            padx=12, pady=6
        )
        self._mic_btn = tk.Button(
            neural_card,
            text="  MIC ON / OFF",
            bg=BG_PANEL, fg=CYAN,
            font=("Consolas", 9),
            relief="flat", cursor="hand2",
            activebackground=CYAN_DARK,
            command=self._toggle_mic,
            padx=12, pady=5
        )
        self._mic_btn.pack(fill="x", padx=12, pady=(0, 10))

        # Command log
        log_card = _card(center)
        log_card.pack(fill="both", expand=True, pady=(0, 6))
        _section_header(log_card, "COMMAND LOG")
        self._chat = ChatPanel(log_card)
        self._chat.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Input bar
        input_card = _card(center)
        input_card.pack(fill="x")

        self._entry = tk.Entry(
            input_card,
            bg=BG_DEEP, fg=CYAN,
            insertbackground=CYAN,
            font=("Consolas", 11),
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_HI
        )
        self._entry.insert(0, "[ TYPE COMMAND HERE ]...")
        self._entry.bind("<FocusIn>", lambda e: (
            self._entry.delete(0, "end")
            if self._entry.get() == "[ TYPE COMMAND HERE ]..." else None
        ))
        self._entry.pack(side="left", fill="x", expand=True,
                         ipady=10, padx=(10, 6), pady=8)
        self._entry.bind("<Return>", lambda _e: self._send())

        tk.Button(
            input_card,
            text="⏹ STOP",
            bg=BG_PANEL, fg=RED,
            font=("Consolas", 9, "bold"),
            relief="flat", cursor="hand2",
            activebackground="#2a0000",
            activeforeground=RED,
            padx=10, pady=4,
            command=self._interrupt
        ).pack(side="right", padx=(0, 4))

        tk.Button(
            input_card,
            text="TRANSMIT",
            bg=BG_PANEL, fg=CYAN,
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2",
            activebackground=CYAN_DARK,
            activeforeground=CYAN,
            padx=14, pady=4,
            command=self._send
        ).pack(side="right", padx=(0, 6))

        # ── RIGHT: spotify + printer + ocr + notifications ──
        spotify_card = _card(right)
        spotify_card.pack(fill="x", pady=(0, 6))
        SpotifyPanel(spotify_card, spotify_handler=self.spotify_handler).pack(fill="x")

        printer_card = _card(right)
        printer_card.pack(fill="x", pady=(0, 6))
        PrinterPanel(printer_card).pack(fill="x")

        ocr_card = _card(right)
        ocr_card.pack(fill="x", pady=(0, 6))
        OCRPanel(ocr_card).pack(fill="x")

        # MMA Status panel
        mma_card = _card(right)
        mma_card.pack(fill="x", pady=(0, 6))
        _section_header(mma_card, "MMA REMOTE AGENT")
        mma_body = tk.Frame(mma_card, bg=BG_CARD)
        mma_body.pack(fill="x", padx=10, pady=(0, 8))

        self._mma_status_dot = tk.Label(mma_body, text="●",
                                         bg=BG_CARD, fg=RED,
                                         font=("Consolas", 10))
        self._mma_status_dot.pack(side="left")

        self._mma_status_label = tk.Label(mma_body, text="OFFLINE",
                                           bg=BG_CARD, fg=RED,
                                           font=("Consolas", 8, "bold"))
        self._mma_status_label.pack(side="left", padx=(4, 16))

        self._mma_last_cmd = tk.Label(mma_body,
                                       text="No commands yet",
                                       bg=BG_CARD, fg=TEXT_SEC,
                                       font=("Consolas", 8),
                                       wraplength=180, justify="left")
        self._mma_last_cmd.pack(side="left", fill="x", expand=True)

        # Start polling MMA status
        self._poll_mma_status()

        # WhatsApp Bridge status panel
        wa_card = _card(right)
        wa_card.pack(fill="x", pady=(0, 6))
        _section_header(wa_card, "WHATSAPP BRIDGE")
        wa_body = tk.Frame(wa_card, bg=BG_CARD)
        wa_body.pack(fill="x", padx=10, pady=(0, 8))

        self._wa_status_dot = tk.Label(wa_body, text="●",
                                        bg=BG_CARD, fg=RED,
                                        font=("Consolas", 10))
        self._wa_status_dot.pack(side="left")

        self._wa_status_label = tk.Label(wa_body, text="OFFLINE",
                                          bg=BG_CARD, fg=RED,
                                          font=("Consolas", 8, "bold"))
        self._wa_status_label.pack(side="left", padx=(4, 0))

        self._poll_wa_status()
        # Notifications panel
        notif_card = _card(right)
        notif_card.pack(fill="x", pady=(0, 6))
        _section_header(notif_card, "NOTIFICATIONS")
        self._notif_list = tk.Frame(notif_card, bg=BG_CARD)
        self._notif_list.pack(fill="x", padx=8, pady=(0, 8))
        self._notif_empty = tk.Label(self._notif_list, text="No notifications",
                                     bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        self._notif_empty.pack(anchor="w", padx=4, pady=2)

        # Error log panel
        log_card = _card(right)
        log_card.pack(fill="x")
        _section_header(log_card, "SYSTEM LOG")
        self._log_list = tk.Frame(log_card, bg=BG_CARD)
        self._log_list.pack(fill="x", padx=8, pady=(0, 8))
        self._log_empty = tk.Label(self._log_list, text="No errors",
                                   bg=BG_CARD, fg=TEXT_SEC, font=("Consolas", 8))
        self._log_empty.pack(anchor="w", padx=4, pady=2)

    def _poll_mma_status(self):
        def _check():
            try:
                import requests as req
                r = req.get(
                    "http://localhost:6060/status",
                    headers={"X-MMA-Token": "izach-mma-2024"},
                    timeout=2
                )
                if r.status_code == 200:
                    data = r.json()
                    try:
                        self.root.after(0, lambda d=data: self._set_mma_online(d))
                    except RuntimeError:
                        pass
                else:
                    try:
                        self.root.after(0, self._set_mma_offline)
                    except RuntimeError:
                        pass
            except Exception:
                try:
                    self.root.after(0, self._set_mma_offline)
                except RuntimeError:
                    pass
        threading.Thread(target=_check, daemon=True).start()
        try:
            self.root.after(30000, self._poll_mma_status)
        except RuntimeError:
            pass

    def _set_mma_online(self, data: dict):
        try:
            self._mma_status_dot.config(fg=GREEN)
            self._mma_status_label.config(fg=GREEN, text="ONLINE")
            last = data.get("last_command", "No commands yet")
            total = data.get("total_commands", 0)
            self._mma_last_cmd.config(
                text=f"[{total} cmds] {last[:40]}" if last else f"[{total} cmds] Ready"
            )
        except Exception:
            pass

    def _set_mma_offline(self):
        try:
            self._mma_status_dot.config(fg=RED)
            self._mma_status_label.config(fg=RED, text="OFFLINE")
            self._mma_last_cmd.config(text="MMA not running")
        except Exception:
            pass

    def add_mma_log(self, entry: dict):
        """Called when iZACH executes a command from MMA."""
        def _add():
            try:
                timestamp = entry.get("timestamp", "")
                cmd = entry.get("input", "")[:40]
                result = entry.get("result", "")[:40]
                if hasattr(self, '_notif_list'):
                    row = tk.Frame(self._notif_list, bg="#0a0a1a",
                                   highlightthickness=1,
                                   highlightbackground="#1a1a3a")
                    row.pack(fill="x", pady=2)
                    tk.Label(row, text=f"[MMA] {cmd}",
                             bg="#0a0a1a", fg=CYAN,
                             font=("Consolas", 8, "bold"),
                             wraplength=220, justify="left").pack(
                                 anchor="w", padx=6, pady=(4, 0))
                    tk.Label(row, text=result,
                             bg="#0a0a1a", fg=TEXT_PRI,
                             font=("Consolas", 8),
                             wraplength=220, justify="left").pack(
                                 anchor="w", padx=6, pady=(0, 4))
                    children = self._notif_list.winfo_children()
                    if len(children) > 5:
                        children[0].destroy()
            except Exception:
                pass
        try:
            self.root.after(0, _add)
        except RuntimeError:
            pass

    def _poll_wa_status(self):
        def _check():
            try:
                import requests as req
                r = req.get("http://127.0.0.1:3000/health", timeout=2)
                if r.status_code == 200:
                    status = r.json().get("status", "")
                    if status == "connected":
                        try:
                            self.root.after(0, self._set_wa_online)
                        except RuntimeError:
                            pass
                        return
            except Exception:
                pass
            try:
                self.root.after(0, self._set_wa_offline)
            except RuntimeError:
                pass
        threading.Thread(target=_check, daemon=True).start()
        try:
            self.root.after(20000, self._poll_wa_status)
        except RuntimeError:
            pass

    def _set_wa_online(self):
        try:
            self._wa_status_dot.config(fg=GREEN)
            self._wa_status_label.config(fg=GREEN, text="CONNECTED")
        except Exception:
            pass

    def _set_wa_offline(self):
        try:
            self._wa_status_dot.config(fg=RED)
            self._wa_status_label.config(fg=RED, text="OFFLINE")
        except Exception:
            pass

    def add_notification(self, title: str, body: str):
        def _add():
            if self._notif_empty.winfo_exists():
                self._notif_empty.destroy()
            row = tk.Frame(self._notif_list, bg="#0a1a10",
                           highlightthickness=1, highlightbackground=GREEN_DIM)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=title, bg="#0a1a10", fg=GREEN,
                     font=("Consolas", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
            tk.Label(row, text=body, bg="#0a1a10", fg=TEXT_PRI,
                     font=("Consolas", 8), wraplength=220,
                     justify="left").pack(anchor="w", padx=6, pady=(0, 4))
            # Keep max 5 notifications
            children = self._notif_list.winfo_children()
            if len(children) > 5:
                children[0].destroy()
        self.root.after(0, _add)

    def add_error_log(self, message: str):
        import time
        def _add():
            if self._log_empty.winfo_exists():
                self._log_empty.destroy()
            timestamp = time.strftime("%H:%M")
            row = tk.Frame(self._log_list, bg="#1a0a0a",
                           highlightthickness=1, highlightbackground="#3a0000")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"[{timestamp}] {message}",
                     bg="#1a0a0a", fg=AMBER,
                     font=("Consolas", 8), wraplength=220,
                     justify="left").pack(anchor="w", padx=6, pady=4)
            children = self._log_list.winfo_children()
            if len(children) > 8:
                children[0].destroy()
        self.root.after(0, _add)
    
    
    def update_live_text(self, text: str):
        """Phase 5: word-by-word live display — appears/disappears with speech."""
        try:
            self._live_text_var.set(text)
            if text:
                # Show the bar
                self._live_text.pack(fill="x")
                self._live_bar.config(height=36)
                self._neural.set_speaking(True)
            else:
                # Hide when speech ends
                self._live_text.pack_forget()
                self._live_bar.config(height=0)
                self._neural.set_speaking(False)
        except Exception:
            pass

    # ── Public API ──
    def write_log(self, text):
        known_senders = ["iZACH", "YOU", "USER", "SYSTEM"]
        if ":" in text:
            sender, message = text.split(":", 1)
            sender = sender.strip()
            if sender in known_senders:
                self.root.after(0, lambda s=sender, m=message.strip(): self._chat.add_message(s, m))
            else:
                # Not a known sender — treat whole thing as iZACH message
                self.root.after(0, lambda t=text: self._chat.add_message("iZACH", t))
        else:
            self.root.after(0, lambda t=text: self._chat.add_message("iZACH", text))

    def set_speaking(self, val):
        try:
            self.root.after(0, lambda: self._neural.set_speaking(val))
        except RuntimeError:
            pass

    def update_status(self, text, is_warning=False):
        col = AMBER if is_warning else GREEN
        self.root.after(0, lambda: self._status_var.set(text.upper()))

    def is_mic_active(self):
        return self._mic_active
    
    def _open_settings(self):
        if not hasattr(self, '_settings_page'):
            self._settings_page = SettingsPage(
                self.root,
                on_close=self._close_settings
            )
        self._settings_page.place(x=0, y=0, relwidth=1, relheight=1)
        self._settings_page.lift()
        self._settings_page._switch_settings_tab(self._settings_page._active_tab)

    def _close_settings(self):
        if hasattr(self, '_settings_page'):
            self._settings_page.place_forget()

    def _open_browser(self):
        if hasattr(self, '_browser_window') and self._browser_window.winfo_exists():
            self._browser_window.deiconify()
            self._browser_window.lift()
            self._browser_window.focus_force()
            return
        self._browser_window = BrowserWindow(self.root, on_close=self._close_browser)

    def _close_browser(self):
        pass

    def _interrupt(self):
        """Stop current speech immediately."""
        try:
            from modules.interrupt_engine import get_interrupt_engine
            get_interrupt_engine().trigger()
            self.update_live_text("")
            self.set_speaking(False)
        except Exception as e:
            print(f"[UI] Interrupt error: {e}")

    def _toggle_mic(self):
        self._mic_active = not self._mic_active
        if self._mic_active:
            self._mic_btn.config(text="  MIC ON / OFF", fg=CYAN)
        else:
            self._mic_btn.config(text="  MIC OFF", fg=RED)

    def _send(self):
        text = self._entry.get().strip()
        if not text or text == "[ TYPE COMMAND HERE ]...":
            return
        self._entry.delete(0, "end")
        self.root.after(0, lambda: self._chat.add_message("USER", text))
        if self._chain:
            threading.Thread(target=self._text_process, args=(text,), daemon=True).start()

    def _text_process(self, text):
        import modules.command_chain as cc
        original_speak = self._chain.speak
        def text_only_speak(msg):
            if msg:
                clean = msg.replace("iZACH:", "").replace(">", "").strip()
                self.root.after(0, lambda m=clean: self._chat.add_message("iZACH", m))
        self._chain.speak = text_only_speak
        self._chain.process(text)
        self._chain.speak = original_speak

    def _update_ticker(self):
        now = time.strftime("%Y-%m-%d  %H:%M:%S")
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self._ticker_var.set(
            f"[ SYSTEM TIME ]  {now}    |    CPU {cpu:.0f}%    |    RAM {ram:.0f}%    |    RAM {ram:.0f}%    |"
        )
        self.root.after(1000, self._update_ticker)

    def run(self):
        self.root.mainloop()