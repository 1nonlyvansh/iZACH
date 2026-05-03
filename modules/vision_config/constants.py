# =============================================================================
# config/constants.py
# All shared constants for AURA vision modules.
# No imports from other AURA modules — safe to import anywhere.
# =============================================================================

# --- Gesture action identifiers ---
AVAILABLE_ACTIONS = {
    "None":               "none",
    "Volume Control":     "volume_control",
    "Brightness Control": "brightness_control",
    "Switch Desktops":    "switch_desktops",
    "Show Desktop":       "show_desktop",
    "Next Track":         "next_track",
    "Previous Track":     "prev_track",
    "Play/Pause":         "play_pause",
    "Mute/Unmute":        "mute_unmute",
}

# --- Default gesture → action mappings per profile ---
DEFAULT_DESKTOP_MAPPINGS = {
    "right_pinch":      "volume_control",
    "left_pinch":       "brightness_control",
    "right_five_swipe": "switch_desktops",
    "left_five_swipe":  "switch_desktops",
    "right_fist":       "show_desktop",
    "left_fist":        "show_desktop",
}

DEFAULT_MUSIC_MAPPINGS = {
    "right_pinch":      "volume_control",
    "left_pinch":       "brightness_control",
    "right_five_swipe": "next_track",
    "left_five_swipe":  "prev_track",
    "right_fist":       "play_pause",
    "left_fist":        "mute_unmute",
}

DEFAULT_KEYBOARD_MAPPINGS = {
    "right_pinch":      "none",
    "left_pinch":       "none",
    "right_five_swipe": "none",
    "left_five_swipe":  "none",
    "right_fist":       "none",
    "left_fist":        "none",
}

DEFAULT_CURSOR_MAPPINGS = {
    "right_pinch":      "none",
    "left_pinch":       "none",
    "right_five_swipe": "none",
    "left_five_swipe":  "none",
    "right_fist":       "none",
    "left_fist":        "none",
}

DEFAULT_PROFILES = {
    "desktop":  DEFAULT_DESKTOP_MAPPINGS,
    "music":    DEFAULT_MUSIC_MAPPINGS,
    "keyboard": DEFAULT_KEYBOARD_MAPPINGS,
    "cursor":   DEFAULT_CURSOR_MAPPINGS,
}

# --- Gesture detection thresholds ---
SWIPE_THRESHOLD_X  = 200    # pixels of horizontal movement to trigger a swipe
SWIPE_COOLDOWN     = 1.5    # seconds between swipe triggers
FIST_THRESHOLD     = 10     # frames fist must be held before triggering
NOD_THRESHOLD      = 15     # pixels nose must move to register a nod phase

# --- Face auth ---
FACE_SCAN_HOLD_FRAMES   = 30    # frames face must be stable during registration
FACE_RECOGNITION_TOL    = 0.6   # tolerance for face_recognition.compare_faces

# --- Cursor engine ---
CURSOR_SMOOTHENING  = 7
CLICK_COOLDOWN      = 0.5
SCROLL_DIVISOR      = 20
ZOOM_COOLDOWN       = 0.1
ZOOM_TRIGGER_DIST   = 20

# --- Virtual keyboard ---
KEY_WIDTH           = 80
KEY_HEIGHT          = 80
KEY_MARGIN          = 15
FRAME_WIDTH         = 1280
PRESS_COOLDOWN      = 0.5
TOGGLE_COOLDOWN     = 1.0

# --- UI themes (kept here for aura_app.py to import, not used by logic modules) ---
dark_theme = {
    "background":           "#121212",
    "text":                 "#EAEAEA",
    "muted_text":           "#888888",
    "button_bg":            "#282828",
    "button_hover_bg":      "#3A3A3A",
    "border":               "#444444",
    "border_hover":         "#666666",
    "input_bg":             "#1E1E1E",
    "delete_button_bg":     "#B71C1C",
    "delete_button_hover_bg": "#D32F2F",
    "accent":               "#BB86FC",
    "msg_box_bg":           "#2A2A2A",
    "profile_active_bg":    "#BB86FC",
    "profile_active_text":  "#000000",
}

light_theme = {
    "background":           "#FFFFFF",
    "text":                 "#000000",
    "muted_text":           "#555555",
    "button_bg":            "#F0F0F0",
    "button_hover_bg":      "#E0E0E0",
    "border":               "#DDDDDD",
    "border_hover":         "#CCCCCC",
    "input_bg":             "#FAFAFA",
    "delete_button_bg":     "#D32F2F",
    "delete_button_hover_bg": "#E57373",
    "accent":               "#6200EE",
    "msg_box_bg":           "#FDFDFD",
    "profile_active_bg":    "#6200EE",
    "profile_active_text":  "#FFFFFF",
}