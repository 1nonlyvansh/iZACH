"""
overlay_ui.py — themed floating overlays for iZACH Background Mode.

Two global-hotkey overlays (Tkinter, iZACH cyan/dark theme):
  • Command bar  — type a command, Enter sends to backend. Default Ctrl+Alt+Space.
  • Mic toggle   — small window to turn the mic on/off.       Default Ctrl+Alt+M.

Hotkeys are configurable in api_keys.json: "hotkey_bar", "hotkey_mic".

A single Tk root runs on its own thread. Global hotkeys (the `keyboard` lib)
fire on their own thread and marshal to the Tk thread via root.after().
"""

import json
import threading

import tkinter as tk
import requests

# ── Theme (matches Forge / Cortex) ───────────────────────────
BG_DEEP   = "#050d1a"
BG_PANEL  = "#071020"
CYAN      = "#00e5ff"
CYAN_DIM  = "#005060"
GREEN     = "#1db954"
RED       = "#ff3d3d"
TEXT_PRI  = "#c8e8f0"
TEXT_SEC  = "#3a6070"
BORDER    = "#0d2a3a"
BORDER_HI = "#1a4a5a"
FONT      = "Consolas"

API = "http://localhost:5050"

_DEFAULT_HOTKEY_BAR = "ctrl+shift+space"   # ctrl+alt+space = Claude; ctrl+shift+space is free
_DEFAULT_HOTKEY_MIC = "ctrl+shift+m"       # ctrl+alt+m = Mouse Without Borders; ctrl+shift+m is free

_started   = False
_root      = None
_bar       = None
_bar_entry = None
_resp_var  = None
_bar_visible = False

_mic       = None
_mic_lbl   = None
_mic_btn   = None
_mic_dot   = None
_mic_state = True       # last-known mic active
_mic_visible = False

# ── Command history ───────────────────────────────────────────
_bar_history  = []
_bar_hist_idx = -1

# ── Drag helpers ──────────────────────────────────────────────
_drag_data = {}   # window_id -> {x, y}


# ── Config ────────────────────────────────────────────────────
def _read_hotkeys():
    bar, mic = _DEFAULT_HOTKEY_BAR, _DEFAULT_HOTKEY_MIC
    try:
        with open("api_keys.json", encoding="utf-8") as f:
            c = json.load(f)
        bar = (c.get("hotkey_bar") or bar).lower()
        mic = (c.get("hotkey_mic") or mic).lower()
    except Exception:
        pass
    return bar, mic


# ── Command bar ───────────────────────────────────────────────
def _build_bar():
    global _bar, _bar_entry, _resp_var
    _bar = tk.Toplevel(_root)
    _bar.withdraw()
    _bar.overrideredirect(True)
    _bar.attributes("-topmost", True)
    _bar.configure(bg=CYAN)          # 1px cyan outer border via padding

    inner = tk.Frame(_bar, bg=BG_DEEP)
    inner.pack(padx=1, pady=1, fill="both", expand=True)

    head = tk.Frame(inner, bg=BG_DEEP)
    head.pack(fill="x", padx=14, pady=(10, 0))
    tk.Label(head, text="iZACH", bg=BG_DEEP, fg=CYAN,
             font=(FONT, 10, "bold")).pack(side="left")
    tk.Label(head, text="COMMAND", bg=BG_DEEP, fg=TEXT_SEC,
             font=(FONT, 8)).pack(side="left", padx=(8, 0))
    tk.Label(head, text="Esc to close", bg=BG_DEEP, fg=TEXT_SEC,
             font=(FONT, 7)).pack(side="right")

    _bar_entry = tk.Entry(
        inner, bg=BG_PANEL, fg=CYAN, insertbackground=CYAN,
        font=(FONT, 13), relief="flat",
        highlightthickness=1, highlightbackground=BORDER_HI,
        highlightcolor=CYAN,
    )
    _bar_entry.pack(fill="x", padx=14, pady=(8, 6), ipady=8)
    _bar_entry.bind("<Return>", _submit)
    _bar_entry.bind("<Escape>", lambda e: _hide_bar())
    _bar_entry.bind("<Up>",     _history_up)
    _bar_entry.bind("<Down>",   _history_down)

    _resp_var = tk.StringVar(value="")
    tk.Label(inner, textvariable=_resp_var, bg=BG_DEEP, fg=TEXT_PRI,
             font=(FONT, 9), wraplength=532, justify="left",
             anchor="w").pack(fill="x", padx=14, pady=(0, 10))

    # Make bar draggable
    _make_draggable(_bar, "bar_pos_x", "bar_pos_y")


def _position_bar():
    _bar.update_idletasks()
    w, h = 560, _bar.winfo_reqheight()
    sw = _bar.winfo_screenwidth()
    x = (sw - w) // 2
    y = 150
    # Load saved position if available
    try:
        with open("api_keys.json", encoding="utf-8") as _f:
            _c = json.load(_f)
        saved_x = _c.get("bar_pos_x")
        saved_y = _c.get("bar_pos_y")
        if saved_x is not None and saved_y is not None:
            x = int(saved_x)
            y = int(saved_y)
    except Exception:
        pass
    _bar.geometry(f"{w}x{h}+{x}+{y}")


def _show_bar():
    global _bar_visible
    _resp_var.set("")
    _bar_entry.delete(0, "end")
    _bar.deiconify()
    _position_bar()
    _bar.lift()
    _bar.attributes("-topmost", True)
    _bar.after(30, lambda: (_bar.focus_force(), _bar_entry.focus_set()))
    _bar_visible = True


def _hide_bar():
    global _bar_visible
    try:
        _bar.withdraw()
    except Exception:
        pass
    _bar_visible = False


def _toggle_bar():
    if _bar_visible:
        _hide_bar()
    else:
        _show_bar()


# ── Drag to reposition ───────────────────────────────────────
def _make_draggable(win, pos_key_x: str, pos_key_y: str):
    """Bind drag events on a Toplevel so the user can reposition it.
    Saves final position to api_keys.json on mouse release."""
    _dd = {}

    def _start_drag(event):
        _dd["sx"] = event.x_root - win.winfo_x()
        _dd["sy"] = event.y_root - win.winfo_y()

    def _on_drag(event):
        nx = event.x_root - _dd.get("sx", 0)
        ny = event.y_root - _dd.get("sy", 0)
        win.geometry(f"+{nx}+{ny}")

    def _stop_drag(event):
        nx = win.winfo_x()
        ny = win.winfo_y()
        try:
            with open("api_keys.json", encoding="utf-8") as _f:
                _cfg = json.load(_f)
        except Exception:
            _cfg = {}
        _cfg[pos_key_x] = nx
        _cfg[pos_key_y] = ny
        try:
            with open("api_keys.json", "w", encoding="utf-8") as _f:
                json.dump(_cfg, _f, indent=2)
        except Exception:
            pass

    win.bind("<Button-1>",  _start_drag)
    win.bind("<B1-Motion>", _on_drag)
    win.bind("<ButtonRelease-1>", _stop_drag)


def _history_up(event=None):
    global _bar_hist_idx
    if not _bar_history:
        return
    if _bar_hist_idx < len(_bar_history) - 1:
        _bar_hist_idx += 1
    _bar_entry.delete(0, "end")
    _bar_entry.insert(0, _bar_history[-(1 + _bar_hist_idx)])
    return "break"


def _history_down(event=None):
    global _bar_hist_idx
    if _bar_hist_idx <= 0:
        _bar_hist_idx = -1
        _bar_entry.delete(0, "end")
        return "break"
    _bar_hist_idx -= 1
    _bar_entry.delete(0, "end")
    _bar_entry.insert(0, _bar_history[-(1 + _bar_hist_idx)])
    return "break"


def _submit(event=None):
    global _bar_hist_idx
    text = _bar_entry.get().strip()
    if not text:
        return
    # Append to history (avoid duplicate at end)
    if not _bar_history or _bar_history[-1] != text:
        _bar_history.append(text)
    _bar_hist_idx = -1
    _resp_var.set("Sending…")
    threading.Thread(target=_send_command, args=(text,), daemon=True).start()


def _send_command(text):
    try:
        r = requests.post(API + "/command",
                          json={"text": text, "source": "overlay"}, timeout=30)
        d = r.json()
        resp = d.get("response") or ("Sent ✓" if d.get("ok") else d.get("error", "Failed"))
    except Exception:
        resp = "Backend offline."
    def _apply():
        _resp_var.set(str(resp)[:200])
        _bar_entry.delete(0, "end")
        _bar.after(6000, _hide_bar)
    try:
        _root.after(0, _apply)
    except Exception:
        pass


# ── Mic toggle window ─────────────────────────────────────────
def _build_mic():
    global _mic, _mic_lbl, _mic_btn, _mic_dot
    _mic = tk.Toplevel(_root)
    _mic.withdraw()
    _mic.overrideredirect(True)
    _mic.attributes("-topmost", True)
    _mic.configure(bg=CYAN)

    inner = tk.Frame(_mic, bg=BG_DEEP)
    inner.pack(padx=1, pady=1, fill="both", expand=True)

    head = tk.Frame(inner, bg=BG_DEEP)
    head.pack(fill="x", padx=12, pady=(10, 4))
    _mic_dot = tk.Label(head, text="●", bg=BG_DEEP, fg=GREEN, font=(FONT, 11))
    _mic_dot.pack(side="left")
    _mic_lbl = tk.Label(head, text="MIC: …", bg=BG_DEEP, fg=TEXT_PRI,
                        font=(FONT, 10, "bold"))
    _mic_lbl.pack(side="left", padx=(6, 0))

    _mic_btn = tk.Button(inner, text="TOGGLE MIC", bg=BG_PANEL, fg=CYAN,
                         font=(FONT, 9, "bold"), relief="flat", cursor="hand2",
                         activebackground=CYAN_DIM, activeforeground=CYAN,
                         command=_toggle_mic_state, padx=10, pady=6)
    _mic_btn.pack(fill="x", padx=12, pady=(2, 6))
    tk.Label(inner, text="Esc to close", bg=BG_DEEP, fg=TEXT_SEC,
             font=(FONT, 7)).pack(pady=(0, 8))

    _mic.bind("<Escape>", lambda e: _hide_mic())

    # Make mic window draggable
    _make_draggable(_mic, "mic_pos_x", "mic_pos_y")


def _position_mic():
    _mic.update_idletasks()
    w, h = 220, _mic.winfo_reqheight()
    sw = _mic.winfo_screenwidth()
    x = sw - w - 24
    y = 70
    # Load saved position if available
    try:
        with open("api_keys.json", encoding="utf-8") as _f:
            _c = json.load(_f)
        saved_x = _c.get("mic_pos_x")
        saved_y = _c.get("mic_pos_y")
        if saved_x is not None and saved_y is not None:
            x = int(saved_x)
            y = int(saved_y)
    except Exception:
        pass
    _mic.geometry(f"{w}x{h}+{x}+{y}")


def _apply_mic(active):
    global _mic_state
    _mic_state = bool(active)
    if _mic_lbl is None:
        return
    _mic_lbl.config(text="MIC: ON" if active else "MIC: OFF")
    _mic_dot.config(fg=GREEN if active else RED)
    _mic_btn.config(fg=RED if active else CYAN,
                    text="TURN MIC OFF" if active else "TURN MIC ON")


def _mic_get():
    try:
        active = requests.get(API + "/mic", timeout=5).json().get("mic_active", True)
    except Exception:
        active = True
    try:
        _root.after(0, lambda: _apply_mic(active))
    except Exception:
        pass


def _mic_set(active):
    try:
        requests.post(API + "/mic", json={"active": bool(active)}, timeout=5)
    except Exception:
        pass
    try:
        _root.after(0, lambda: _apply_mic(active))
    except Exception:
        pass


def _toggle_mic_state():
    threading.Thread(target=lambda: _mic_set(not _mic_state), daemon=True).start()


def _show_mic():
    global _mic_visible
    threading.Thread(target=_mic_get, daemon=True).start()
    _mic.deiconify()
    _position_mic()
    _mic.lift()
    _mic.attributes("-topmost", True)
    _mic.after(30, _mic.focus_force)
    _mic_visible = True


def _hide_mic():
    global _mic_visible
    try:
        _mic.withdraw()
    except Exception:
        pass
    _mic_visible = False


def _toggle_mic_window():
    if _mic_visible:
        _hide_mic()
    else:
        _show_mic()


# ── Push-to-talk helper ───────────────────────────────────────
def _is_ptt_enabled() -> bool:
    try:
        with open("api_keys.json", encoding="utf-8") as _f:
            return bool(json.load(_f).get("push_to_talk", False))
    except Exception:
        return False


# ── Hotkeys ───────────────────────────────────────────────────
def _register_hotkeys():
    try:
        import keyboard
    except Exception as e:
        print(f"[OVERLAY] keyboard lib unavailable — hotkeys disabled: {e}")
        return
    bar_key, mic_key = _read_hotkeys()
    # TODO: PTT mic recording — phase 2.
    # If push_to_talk is enabled, hold bar_key to show bar,
    # release to auto-submit. For now, hotkey toggles bar regardless.
    try:
        keyboard.add_hotkey(bar_key, lambda: _root.after(0, _toggle_bar))
        keyboard.add_hotkey(mic_key, lambda: _root.after(0, _toggle_mic_window))
        print(f"[OVERLAY] Hotkeys active — command bar: {bar_key.upper()} · mic: {mic_key.upper()}")
        if _is_ptt_enabled():
            print("[OVERLAY] Push-to-Talk mode enabled (UI wired; mic integration is phase 2).")
    except Exception as e:
        print(f"[OVERLAY] Hotkey registration failed: {e}")


# ── Lifecycle ─────────────────────────────────────────────────
def _run():
    global _root
    try:
        _root = tk.Tk()
        _root.withdraw()                       # no main window — overlays only
        _build_bar()
        _build_mic()
        _register_hotkeys()
        _root.mainloop()
    except Exception as e:
        print(f"[OVERLAY] Crashed: {e}")


def start():
    """Start the overlay UI on its own thread (non-blocking)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_run, daemon=True, name="OverlayUI").start()
    print("[OVERLAY] Floating command bar + mic toggle ready.")
