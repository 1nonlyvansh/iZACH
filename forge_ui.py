import tkinter as tk
import threading
import os
import time
import math
import psutil
import subprocess
import requests
from PIL import Image, ImageTk, ImageDraw
import cv2


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
            _req.post("http://localhost:5050/ocr/toggle",
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
            r = _req.get("http://localhost:5050/ocr/status", timeout=2).json()
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
                r = _req.post("http://localhost:5050/ocr/scan-image",
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
            _req.post("http://localhost:5050/ocr/save", json={"text": text}, timeout=5)
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
                _req.post("http://localhost:5050/print/settings",
                          json={key: value}, timeout=3)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_status(self):
        import requests as _req, threading
        def _run():
            try:
                r = _req.get("http://localhost:5050/print/status", timeout=3).json()
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
                r = _req.post("http://localhost:5050/print/job",
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
# SETTINGS PAGE
# ─────────────────────────────────────────────
class SettingsPage(tk.Frame):
    def __init__(self, parent, on_close, **kw):
        super().__init__(parent, bg=BG_DEEP, **kw)
        self.on_close = on_close
        self._memory_rows = []
        self._build()
        self._load_all()

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

        self._body = tk.Frame(canvas, bg=BG_DEEP)
        self._body_win = canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._body_win, width=e.width))

        self._build_memory_section()
        self._build_api_section()
        self._build_voice_section()
        self._build_custom_websites_section()
        self._build_about_section()

    def _section(self, title):
        card = _card(self._body)
        card.pack(fill="x", pady=(0, 12))
        _section_header(card, title)
        return card

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

        info = tk.Label(card,
                        text="Changes are saved to memory only. Restart iZACH to apply.",
                        bg=BG_CARD, fg=AMBER, font=("Consolas", 8))
        info.pack(anchor="w", padx=12, pady=(0, 8))

        self._api_entries = {}

        for label, key in [("Groq API Key", "GROQ_KEY"),
                            ("Gemini Key 1", "GEMINI_KEY_1"),
                            ("Gemini Key 2", "GEMINI_KEY_2"),
                            ("Gemini Key 3", "GEMINI_KEY_3"),
                            ("Spotify Client ID", "SPOTIPY_CLIENT_ID"),
                            ("Spotify Client Secret", "SPOTIPY_CLIENT_SECRET")]:
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

        tk.Button(card, text="SAVE API KEYS",
                  bg=CYAN_DARK, fg=CYAN,
                  font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2",
                  command=self._save_api_keys,
                  padx=14, pady=4).pack(anchor="w", padx=12, pady=(6, 10))

    def _load_api_keys(self):
        try:
            import json
            path = os.path.join(os.path.dirname(__file__), "api_keys.json")
            if os.path.exists(path):
                with open(path) as f:
                    keys = json.load(f)
                for k, entry in self._api_entries.items():
                    if k in keys:
                        entry.delete(0, "end")
                        entry.insert(0, keys[k])
        except Exception:
            pass

    def _save_api_keys(self):
        import json
        path = os.path.join(os.path.dirname(__file__), "api_keys.json")
        keys = {k: e.get() for k, e in self._api_entries.items()}
        with open(path, "w") as f:
            json.dump(keys, f, indent=2)
        # Show saved confirmation
        for w in self._body.winfo_children():
            pass
        self._saved_label = tk.Label(self._body, text="✓ API keys saved. Restart to apply.",
                                     bg=BG_DEEP, fg=GREEN,
                                     font=("Consolas", 9))
        self._saved_label.pack(pady=4)
        self.after(3000, lambda: self._saved_label.destroy()
                   if self._saved_label.winfo_exists() else None)

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
            r = _req.post("http://localhost:5050/websites",
                          json={"name": name, "url": url}, timeout=5)
            data = r.json()
            if data.get("ok"):
                self._ws_name_entry.delete(0, "end")
                self._ws_url_entry.delete(0, "end")
                self._ws_msg_var.set(f'Added "{name}"')
                self._load_custom_websites_ui()
                self.after(3000, lambda: self._ws_msg_var.set(""))
            else:
                self._ws_msg_var.set(data.get("error", "Error"))
        except Exception as e:
            self._ws_msg_var.set(f"Error: {e}")

    def _delete_custom_website(self, key):
        try:
            import requests as _req
            _req.delete(f"http://localhost:5050/websites/{key}", timeout=5)
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

    def _load_all(self):
        self._load_memory_ui()
        self._load_api_keys()
        self._load_custom_websites_ui()

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
                r = req.get("http://localhost:3000/health", timeout=2)
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
        self._settings_page._load_all()

    def _close_settings(self):
        if hasattr(self, '_settings_page'):
            self._settings_page.place_forget()

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