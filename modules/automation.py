import time
import pyautogui
import pygetwindow as gw
import logging
from datetime import datetime

# Configure logging for debugging window transitions
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. WINDOW SYNC ENGINE ---

def get_active_window_safe(window_title_keyword, timeout=10):
    """
    Ensures the application window is fully loaded, restored, and focused.
    """
    start_time = time.time()
    logger.info(f"[SYNC] Waiting for: {window_title_keyword}")

    while time.time() - start_time < timeout:
        all_windows = gw.getWindowsWithTitle('')
        # Search for keyword in any active window title
        target_windows = [w for w in all_windows if window_title_keyword.lower() in w.title.lower()]
        
        if target_windows:
            target_win = target_windows[0]
            try:
                if target_win.isMinimized:
                    target_win.restore()
                
                target_win.activate()
                time.sleep(1.0) # Buffer for UI thread stabilization
                
                if target_win.isActive:
                    logger.info(f"[SUCCESS] {target_win.title} is focused.")
                    return True
            except Exception as e:
                logger.warning(f"[RETRY] Window found but not ready: {e}")
        
        time.sleep(0.5)
    
    logger.error(f"[TIMEOUT] Failed to sync with {window_title_keyword}")
    return False

# --- 2. CORE AUTOMATION ---

def open_app(app_name):
    """
    Launches app via Windows Search (Win + Name + Enter).
    """
    pyautogui.press('win')
    time.sleep(0.5)
    pyautogui.write(app_name, interval=0.1)
    time.sleep(0.5)
    pyautogui.press('enter')

    # Verify window exists before returning
    return get_active_window_safe(app_name)

def navigate_to_url(url, browser_name="chrome"):
    """
    Ensures browser focus and types URL into address bar.
    """
    if not get_active_window_safe(browser_name, timeout=2):
        open_app(browser_name)
    
    if get_active_window_safe(browser_name):
        pyautogui.hotkey('ctrl', 'l') 
        time.sleep(0.3)
        pyautogui.write(url, interval=0.05)
        pyautogui.press('enter')
        return True
    return False

# --- 3. REFACTORED MEDIA METHODS ---

def play_specific_youtube(song_name):
    """Searches and plays media via YouTube in Chrome."""
    url = f"https://www.youtube.com/results?search_query={song_name.replace(' ', '+')}"
    return navigate_to_url(url, "chrome")



# --- 4. SYSTEM TOOLS ---

def get_current_time():
    return f"It is {datetime.now().strftime('%I:%M %p')}."

def get_current_date():
    return f"Today is {datetime.now().strftime('%A, %B %d')}."

def get_delhi_intel():
    return "Local weather protocols active."

def get_realtime_coordinates():
    return "GPS coordinates synchronized."

def system_media_control(command):
    """Hardware-level media key simulation."""
    if any(word in command for word in ["pause", "stop", "resume"]):
        pyautogui.press("playpause")
    elif "next" in command:
        pyautogui.press("nexttrack")
    elif "previous" in command:
        pyautogui.press("prevtrack")