import ctypes
import json
import time
import threading
import logging
import os
import cv2
import numpy as np
import pyautogui
import pytesseract
from PIL import Image, ImageGrab

logger = logging.getLogger(__name__)

# --- 1. CONFIGURATION ---
# Path for local icons (Chrome, Spotify, etc.)
ICON_DIR = "assets/icons" 
if not os.path.exists(ICON_DIR):
    os.makedirs(ICON_DIR)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    ctypes.windll.user32.SetProcessDPIAware()

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class VisionManager:
    def __init__(self):
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.ai_client = None
        self.cooldown_period = 15  # Increased cooldown to protect your 3 keys
        self.last_gemini_call = 0

vm = VisionManager()

def update_client(new_client):
    vm.ai_client = new_client
    logger.info("Vision: Synced with active API key.")

# --- 2. PASSIVE DAEMON (Zero Cost) ---
def screen_capture_daemon():
    while True:
        try:
            img = ImageGrab.grab(all_screens=True)
            with vm.frame_lock:
                vm.latest_frame = img
            time.sleep(0.5) 
        except Exception as e:
            logger.error(f"Capture Error: {e}")

threading.Thread(target=screen_capture_daemon, daemon=True).start()

# --- 3. LOCAL TOOLS (The "Quota Protectors") ---

def local_icon_match(target_desc, screen_cv):
    """Checks the assets/icons folder for a matching .png file."""
    for icon_file in os.listdir(ICON_DIR):
        if target_desc.lower() in icon_file.lower():
            template = cv2.imread(os.path.join(ICON_DIR, icon_file), 0)
            res = cv2.matchTemplate(screen_cv, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val > 0.8: # 80% confidence threshold
                h, w = template.shape
                return (max_loc[0] + w//2, max_loc[1] + h//2)
    return None

def local_ocr_match(target_desc, screen_pil):
    """Uses Tesseract to find text coordinates."""
    data = pytesseract.image_to_data(screen_pil, output_type=pytesseract.Output.DICT)
    for i, text in enumerate(data['text']):
        if target_desc.lower() in text.lower() and text.strip() != "":
            w, h = screen_pil.size
            nx = int(((data['left'][i] + data['width'][i]//2) / w) * 1000)
            ny = int(((data['top'][i] + data['height'][i]//2) / h) * 1000)
            return (nx, ny)
    return None

# --- 4. CORE LOGIC ---

def smart_locate_and_click(target_desc, active_client):
    vm.ai_client = active_client
    
    with vm.frame_lock:
        if vm.latest_frame is None: return "Sensors offline."
        current_img = vm.latest_frame.copy()

    # Convert to OpenCV format for icon matching
    screen_cv = cv2.cvtColor(np.array(current_img), cv2.COLOR_RGB2GRAY)

    # STEP 1: Aggressive OCR (Text)
    coords = local_ocr_match(target_desc, current_img)
    if coords:
        logger.info(f"Local Hit (OCR): Found '{target_desc}'")
        execute_hardware_click(coords[0], coords[1])
        return True

    # STEP 2: Aggressive Icon Matching (OpenCV)
    icon_coords = local_icon_match(target_desc, screen_cv)
    if icon_coords:
        logger.info(f"Local Hit (Icon): Found '{target_desc}'")
        sw, sh = pyautogui.size()
        nx, ny = int((icon_coords[0]/sw)*1000), int((icon_coords[1]/sh)*1000)
        execute_hardware_click(nx, ny)
        return True

    # STEP 3: Gemini Fallback (Only if Local Fails + Cooldown Passed)
    elapsed = time.time() - vm.last_gemini_call
    if elapsed < vm.cooldown_period:
        return f"COOLDOWN_{int(vm.cooldown_period - elapsed)}"

    logger.warning(f"Local search failed for '{target_desc}'. Requesting Gemini Vision.")
    vm.last_gemini_call = time.time()
    
    try:
        # Resize to 720p to save tokens
        ai_img = current_img.resize((1280, 720), Image.Resampling.LANCZOS)
        response = vm.ai_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[f"Look at this screenshot. Find '{target_desc}' on screen. Return ONLY a JSON object like this: {{\"x\": 500, \"y\": 250}} where x and y are pixel coordinates (0-1000 scale) of the center of '{target_desc}'. No explanation, no markdown, just raw JSON.", ai_img]
        )
        coords = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        execute_hardware_click(coords['x'], coords['y'])
        return True
    except Exception as e:
        if "429" in str(e): return "ROTATE_TRIGGERED"
        return False

def execute_hardware_click(nx, ny):
    sw, sh = pyautogui.size()
    pyautogui.click(int((nx/1000)*sw), int((ny/1000)*sh))