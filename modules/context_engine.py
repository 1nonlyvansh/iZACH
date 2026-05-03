import pygetwindow as gw
import win32gui
import win32con
import time
import pyautogui
from screeninfo import get_monitors

def get_screen_resolution():
    """Gets the primary monitor's dimensions."""
    monitor = get_monitors()[0]
    return monitor.width, monitor.height

def wait_for_window(app_name, timeout=10):
    """Polls until a window with app_name appears or timeout hits."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        windows = [w for w in gw.getWindowsWithTitle(app_name) if w.title != ""]
        if windows:
            return windows[0]
        time.sleep(0.5)
    return None

def snap_window(window, position):
    """Calculates coordinates and snaps window to a region of the primary screen."""
    try:
        sw, sh = get_screen_resolution()
        # Ensure window is restored and focusable
        if window.isMinimized:
            window.restore()
        window.activate()
        
        # Define Regions
        # Note: Windows handles taskbars/borders; these are raw offsets
        if position == "left":
            window.moveTo(0, 0)
            window.resizeTo(sw // 2, sh)
        elif position == "right":
            window.moveTo(sw // 2, 0)
            window.resizeTo(sw // 2, sh)
        elif position == "top":
            window.moveTo(0, 0)
            window.resizeTo(sw, sh // 2)
        elif position == "bottom":
            window.moveTo(0, sh // 2)
            window.resizeTo(sw, sh // 2)
        elif position == "maximize":
            window.maximize()
            
        return True
    except Exception as e:
        print(f"[SNAP ERROR] {e}")
        return False

def launch_app_via_search(app_name):
    """Launches app using Windows search simulation."""
    pyautogui.press('win')
    time.sleep(0.4)
    pyautogui.write(app_name, interval=0.05)
    time.sleep(0.4)
    pyautogui.press('enter')

def handle_open_with_position(app_name, position=None):
    """
    Core Logic:
    1. Check if running. 
    2. If not, launch.
    3. Wait for window to exist.
    4. Apply snap if position is provided.
    """
    # 1. Launch if not running
    windows = [w for w in gw.getWindowsWithTitle(app_name) if w.title != ""]
    
    if not windows:
        launch_app_via_search(app_name)
        target_window = wait_for_window(app_name)
    else:
        target_window = windows[0]

    if not target_window:
        return f"I tried launching {app_name}, but it's not showing up."

    # 2. Apply Snap
    if position:
        success = snap_window(target_window, position)
        if success:
            return f"Opening {app_name} and snapping it to the {position}."
        else:
            return f"Opened {app_name}, but the snap failed."
    
    # 3. Default behavior (just bring to front)
    target_window.restore()
    target_window.activate()
    return f"Brought {app_name} to the front."