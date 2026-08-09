"""
modules/camera_vision.py
Camera vision for iZACH — multi-provider chain.

Provider order:
  1. Groq Vision (llama-4-scout-17b-16e-instruct) — primary
  2. Gemini Flash (3-key rotation) — fallback
  3. OpenRouter free tier — tertiary

Food queries: Edamam API appended for accurate nutrition data.
Frame cache: 6s — same frame reused for rapid follow-up questions.
"""

import base64
import io
import logging
import multiprocessing
import os
import re
import threading
import time

from modules.platform_utils import IS_MAC

# Suppress OpenCV VIDEOIO/DSHOW/MSMF C++ backend warnings BEFORE importing cv2.
# cv2.setLogLevel() only affects Python-level logs; VIDEOIO prints directly to
# stderr bypassing Python logging. The env var is the only reliable suppressor.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")

import cv2
try:
    cv2.setLogLevel(0)
except AttributeError:
    pass

from dotenv import load_dotenv as _ldenv

_ldenv()
logger = logging.getLogger(__name__)

# ── API keys ──────────────────────────────────────────────────────────────────
# Vision uses DEDICATED keys when available so chat-side quota doesn't leak
# into screen/camera analysis. Falls back to chat keys if vision keys unset.
GROQ_KEY        = os.getenv("GROQ_VISION_KEY") or os.getenv("GROQ_API_KEY", "")
OPENROUTER_KEY  = os.getenv("OPENROUTER_API_KEY", "")
EDAMAM_APP_ID   = os.getenv("EDAMAM_APP_ID", "")
EDAMAM_APP_KEY  = os.getenv("EDAMAM_APP_KEY", "")

GEMINI_KEYS = [
    os.getenv("GEMINI_VISION_KEY_1") or os.getenv("GEMINI_KEY_1", ""),
    os.getenv("GEMINI_VISION_KEY_2") or os.getenv("GEMINI_KEY_2", ""),
    os.getenv("GEMINI_VISION_KEY_3") or os.getenv("GEMINI_KEY_3", ""),
]

_gemini_key_idx = 0
_gemini_lock    = threading.Lock()

# ── Rate-limit / cooldown ─────────────────────────────────────────────────────
MIN_CALL_INTERVAL  = 6      # seconds between vision API calls
_SCREEN_COOLDOWN   = 8
_last_call_time    = 0
_screen_last_call  = 0
_vision_in_progress = False

# ── Frame cache ───────────────────────────────────────────────────────────────
_CACHE_TTL      = 6.0       # reuse last frame for rapid follow-ups
_last_frame_b64 = None
_last_frame_ts  = 0.0
_last_question  = ""
_last_answer    = ""

# ── Food keywords ─────────────────────────────────────────────────────────────
_FOOD_KEYWORDS = {
    "calorie", "calories", "nutrition", "nutritional", "eat", "eating",
    "food", "meal", "snack", "drink", "beverage", "fruit", "vegetable",
    "protein", "carb", "carbs", "fat", "sugar", "fiber", "healthy",
    "unhealthy", "diet", "portion", "serving", "kcal", "kj",
    "breakfast", "lunch", "dinner",
}

# ── Persistent streaming camera ───────────────────────────────────────────────
_stream_cap: cv2.VideoCapture | None = None
_stream_lock  = threading.Lock()
_stream_clients = 0
_cam_device_index: int = 0   # active camera index; switchable at runtime


def set_camera_device(index: int) -> None:
    """Switch to a different camera.  Releases any active stream so the next
    open picks up the new index."""
    global _cam_device_index, _stream_cap
    _cam_device_index = index
    with _stream_lock:
        if _stream_cap is not None:
            _stream_cap.release()
            _stream_cap = None


def _get_camera_names_dshow() -> dict[int, str]:
    """
    Get camera names indexed by DirectShow position via pygrabber.
    pygrabber's order matches OpenCV's CAP_DSHOW index — so name[i] is the
    actual name of the camera that VideoCapture(i, CAP_DSHOW) will open.

    This is the ONLY reliable way on Windows to pair name → OpenCV index.
    WMI enumeration order is arbitrary and does NOT match OpenCV indices.
    """
    names: dict[int, str] = {}
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        for i, name in enumerate(graph.get_input_devices()):
            names[i] = str(name).strip()
    except Exception as e:
        logger.debug(f"[CAM] pygrabber unavailable, falling back to WMI: {e}")
    return names


def _get_camera_names_wmi() -> dict[int, str]:
    """Fallback when pygrabber not installed — WMI order may not match OpenCV index."""
    names: dict[int, str] = {}
    try:
        import subprocess, json as _j
        ps = (
            'Get-WmiObject Win32_PnPEntity | '
            'Where-Object { $_.PNPClass -eq "Camera" -or $_.PNPClass -eq "Image" } | '
            'Select-Object -ExpandProperty Name | ConvertTo-Json'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=5
        )
        raw = result.stdout.strip()
        if raw:
            entries = _j.loads(raw) if raw.startswith('[') else [_j.loads(raw)]
            for idx, name in enumerate(entries):
                names[idx] = str(name).strip()
    except Exception:
        pass
    return names


def _get_camera_names() -> dict[int, str]:
    """Prefer pygrabber (accurate index mapping) → fall back to WMI.
    On macOS neither pygrabber (Windows-only DirectShow wrapper) nor WMI exist —
    AVFoundation has no simple Python enumeration API either, so cameras just get
    a generic "Camera N" name via _resolve_cam_name's fallback (macOS rarely has
    more than the built-in camera + maybe one external/Continuity Camera anyway)."""
    if IS_MAC:
        return {}
    dshow = _get_camera_names_dshow()
    if dshow:
        return dshow
    return _get_camera_names_wmi()


_cameras_cache: list[dict] | None = None
_cameras_cache_ts: float = 0.0
_CAMERAS_CACHE_TTL = 60.0  # seconds
_cameras_enum_lock = threading.Lock()   # serialise concurrent VideoCapture calls

# Device names containing these keywords are NOT cameras (printers, scanners, fax, MFPs).
# Opening them via cv2.VideoCapture causes a Windows access violation crash.
_NON_CAMERA_KW = (
    'printer', 'scanner', 'deskjet', 'laserjet', 'officejet', 'envy',
    'mfp', 'fax', 'copier', 'document feed', 'film scan',
    'brother mfc', 'canon mf', 'epson wf', 'epson xp',
    'hp desk', 'hp laser', 'hp offic', 'hp envy',
)

def _is_camera_device(name: str) -> bool:
    """Return False if the WMI device name is clearly a printer/scanner, not a camera."""
    n = name.lower()
    return not any(kw in n for kw in _NON_CAMERA_KW)


def _resolve_cam_name(wmi_names: dict, i: int) -> str:
    # Always coerce name to str — WMI may return dicts/None on some Windows configs
    raw_name = wmi_names.get(i)
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    if raw_name is not None:
        # Extract name from dict if WMI returned a PSObject
        if isinstance(raw_name, dict):
            return str(raw_name.get("Name") or raw_name.get("name") or f"Camera {i}").strip()
        return str(raw_name).strip() or f"Camera {i}"
    return f"Camera {i}"


def _scan_cameras_worker(wmi_names: dict, result_queue) -> None:
    """
    Runs in a child process — cv2.VideoCapture() probing is known to trigger
    Windows access violations on some driver/device combos, which is a hard
    native crash that no Python try/except can catch. Isolating it here means
    a crash only kills this child process, not the whole iZACH backend.
    """
    try:
        cv2.setLogLevel(0)
    except AttributeError:
        pass

    if IS_MAC:
        # AVFoundation's camera backend prints "out device of bound" straight
        # to stderr via NSLog for every unpopulated index — a native-level
        # print that bypasses cv2.setLogLevel(0) above entirely. Safe to
        # blanket-silence: this whole function already runs in an isolated
        # child process (see docstring) whose stderr carries no Python
        # tracebacks the caller depends on — results only ever come back via
        # result_queue.
        try:
            _devnull_fd = os.open(os.devnull, os.O_WRONLY)
            os.dup2(_devnull_fd, 2)
        except Exception:
            pass

    def _try_open(idx: int, backend=None) -> bool:
        try:
            cap = cv2.VideoCapture(idx, backend) if backend is not None else cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                return False
            ret, _ = cap.read()
            cap.release()
            return bool(ret)
        except Exception:
            return False

    result: list[dict] = []
    for i in range(8):  # check up to 8 indices (handles external cameras at higher slots)
        name = _resolve_cam_name(wmi_names, i)

        # Skip printers / scanners — VideoCapture on a printer causes
        # a Windows access violation that kills the entire process.
        if not _is_camera_device(name):
            continue

        if IS_MAC:
            # AVFoundation is macOS's native camera backend — no DSHOW/MSMF
            # access-violation concern here, just try it then a bare fallback.
            opened = _try_open(i, cv2.CAP_AVFOUNDATION) or _try_open(i)
        else:
            # CAP_DSHOW → CAP_MSMF → auto (DSHOW is the more stable backend on
            # Windows for enumeration; MSMF has known access-violation issues
            # probing some webcams)
            opened = _try_open(i, cv2.CAP_DSHOW) or _try_open(i, cv2.CAP_MSMF) or _try_open(i)
        if opened:
            result.append({"index": i, "name": name})

    result_queue.put(result)


def list_cameras(force_refresh: bool = False) -> list[dict]:
    """
    Return list of dicts {index, name} for working cameras 0–7.
    Cached for 60 s — scanning 8 indices × 3 backends takes 5-10 s and
    freezes UI if called on every dropdown click.

    The actual probing runs in a subprocess (see _scan_cameras_worker) since
    cv2.VideoCapture() can trigger a Windows access violation — a native
    crash that would otherwise take down the entire backend process.
    """
    global _cameras_cache, _cameras_cache_ts
    import time as _t
    now = _t.time()
    # Fast path — return cache without acquiring lock (double-checked locking)
    if not force_refresh and _cameras_cache is not None and (now - _cameras_cache_ts) < _CAMERAS_CACHE_TTL:
        return _cameras_cache

    # Serialize: concurrent VideoCapture() calls on Windows cause access violations
    with _cameras_enum_lock:
        # Re-check inside lock — another thread may have just refreshed
        now = _t.time()
        if not force_refresh and _cameras_cache is not None and (now - _cameras_cache_ts) < _CAMERAS_CACHE_TTL:
            return _cameras_cache

        wmi_names = _get_camera_names()
        logger.info(f"[CAM] Scanning cameras… name map: {wmi_names}")

        ctx   = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        proc  = ctx.Process(target=_scan_cameras_worker, args=(wmi_names, queue), daemon=True)
        proc.start()
        proc.join(timeout=20)

        if proc.is_alive():
            logger.error("[CAM] Camera scan subprocess timed out — terminating.")
            proc.terminate()
            proc.join()
            result = _cameras_cache or []
        elif proc.exitcode != 0:
            logger.error(f"[CAM] Camera scan subprocess crashed (exitcode={proc.exitcode}) — "
                         f"likely a driver access violation. Backend kept running.")
            result = _cameras_cache or []
        else:
            try:
                result = queue.get(timeout=2)
            except Exception:
                result = []

        _cameras_cache = result
        _cameras_cache_ts = now
        return result


# ── Camera helpers ────────────────────────────────────────────────────────────

def _open_camera(index: int) -> cv2.VideoCapture:
    """Open camera trying the platform-native backend first, then a fallback."""
    backends = (cv2.CAP_AVFOUNDATION,) if IS_MAC else (cv2.CAP_DSHOW, cv2.CAP_MSMF)
    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                return cap
            cap.release()
    # Last resort: no backend specified
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    return cap


def _start_stream_cam():
    global _stream_cap, _stream_clients
    with _stream_lock:
        _stream_clients += 1
        if _stream_cap is None:
            _stream_cap = _open_camera(_cam_device_index)


def _stop_stream_cam():
    global _stream_cap, _stream_clients
    with _stream_lock:
        _stream_clients = max(0, _stream_clients - 1)
        if _stream_clients == 0 and _stream_cap is not None:
            _stream_cap.release()
            _stream_cap = None


def _read_stream_frame():
    with _stream_lock:
        if _stream_cap is None:
            return None
        ret, frame = _stream_cap.read()
        return cv2.flip(frame, 1) if ret else None


def _capture_frame(flip_h: bool = True):
    """
    Grab one frame — reuses streaming cam if active, else opens/closes.
    Retries up to 2× if camera fails (e.g. briefly held by Cortex UI optics
    screen / getUserMedia — on Windows only one process can hold a cam handle).
    flip_h=True mirrors horizontally (selfie view).
    """
    import time as _t

    with _stream_lock:
        if _stream_cap is not None:
            for _try in range(3):
                ret, frame = _stream_cap.read()
                if ret:
                    return cv2.flip(frame, 1) if flip_h else frame
                _t.sleep(0.15)
            return None

    for _attempt in range(2):
        cap = _open_camera(_cam_device_index)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        try:
            for _ in range(3):
                cap.read()   # flush stale buffer frames
            ret, frame = cap.read()
            if ret:
                return cv2.flip(frame, 1) if flip_h else frame
        except Exception:
            pass
        finally:
            cap.release()
        _t.sleep(0.5)   # brief wait — browser may release handle between attempts
    return None


def _frame_to_b64(frame) -> str | None:
    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        return None
    return base64.b64encode(buf.tobytes()).decode()


# ── Provider: Groq Vision ─────────────────────────────────────────────────────

def _groq_vision(b64: str, question: str) -> str | None:
    if not GROQ_KEY:
        return None
    try:
        import requests
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                            {"type": "text", "text": question},
                        ],
                    }
                ],
                "max_tokens": 256,
                "temperature": 0.3,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json() or {}
            choices = data.get("choices") or []
            if not choices:
                print(f"[VISION] Groq 200 but no choices: {str(data)[:200]}")
                return None
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content")
            if not content:
                print(f"[VISION] Groq 200 but no message.content: {str(data)[:200]}")
                return None
            return content.strip()
        print(f"[VISION] Groq {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"[VISION] Groq error: {e}")
        return None


# ── Provider: Gemini Flash ────────────────────────────────────────────────────

def _next_gemini_key() -> str:
    global _gemini_key_idx
    with _gemini_lock:
        for _ in range(len(GEMINI_KEYS)):
            key = GEMINI_KEYS[_gemini_key_idx % len(GEMINI_KEYS)]
            _gemini_key_idx = (_gemini_key_idx + 1) % len(GEMINI_KEYS)
            if key:
                return key
    return ""


def _gemini_vision(b64: str, question: str) -> str | None:
    key = _next_gemini_key()
    if not key:
        return None
    try:
        import PIL.Image
        raw = base64.b64decode(b64)
        pil_img = PIL.Image.open(io.BytesIO(raw))
        from google import genai
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[pil_img, question],
        )
        if response and response.text:
            return response.text.strip()
        return None
    except Exception as e:
        print(f"[VISION] Gemini error: {e}")
        return None


# ── Provider: OpenRouter ──────────────────────────────────────────────────────

def _openrouter_vision(b64: str, question: str) -> str | None:
    if not OPENROUTER_KEY:
        return None
    try:
        import requests
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://izach.local",
                "X-Title": "iZACH",
            },
            json={
                "model": "meta-llama/llama-3.2-11b-vision-instruct:free",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                            {"type": "text", "text": question},
                        ],
                    }
                ],
                "max_tokens": 256,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        print(f"[VISION] OpenRouter {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"[VISION] OpenRouter error: {e}")
        return None


# ── Provider chain ────────────────────────────────────────────────────────────

def _ask_vision(b64: str, question: str) -> str:
    """Try providers in order; return first successful response."""
    if not (GROQ_KEY or any(GEMINI_KEYS) or OPENROUTER_KEY):
        print("[VISION] No vision API keys set at all (GROQ_VISION_KEY/GROQ_API_KEY, "
              "GEMINI_VISION_KEY_1-3/GEMINI_KEY_1-3, OPENROUTER_API_KEY all empty).")
    for name, fn in [
        ("Groq", _groq_vision),
        ("Gemini", _gemini_vision),
        ("OpenRouter", _openrouter_vision),
    ]:
        result = fn(b64, question)
        if result:
            print(f"[VISION] Answered by {name}")
            return result
        print(f"[VISION] {name} failed, trying next provider")
    return "Camera vision unavailable — all providers failed. Check API keys."


# ── Edamam nutrition ──────────────────────────────────────────────────────────

def _is_food_query(question: str) -> bool:
    words = set(question.lower().split())
    return bool(words & _FOOD_KEYWORDS)


def _edamam_nutrition(food_description: str) -> str | None:
    """Query Edamam Food Database API; return formatted nutrition string or None."""
    if not EDAMAM_APP_ID or not EDAMAM_APP_KEY:
        return None
    try:
        import requests
        resp = requests.get(
            "https://api.edamam.com/api/food-database/v2/parser",
            params={
                "app_id": EDAMAM_APP_ID,
                "app_key": EDAMAM_APP_KEY,
                "ingr": food_description,
                "nutrition-type": "logging",
            },
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        hints = data.get("hints", [])
        if not hints:
            return None

        food = hints[0].get("food") or {}
        if not food:
            return None
        label  = food.get("label", food_description)
        nutr   = food.get("nutrients", {})
        kcal   = nutr.get("ENERC_KCAL")
        prot   = nutr.get("PROCNT")
        fat    = nutr.get("FAT")
        carb   = nutr.get("CHOCDF")
        fiber  = nutr.get("FIBTG")
        sugar  = nutr.get("SUGAR")

        parts = [f"{label} (per 100g):"]
        if kcal  is not None: parts.append(f"{kcal:.0f} kcal")
        if prot  is not None: parts.append(f"protein {prot:.1f}g")
        if carb  is not None: parts.append(f"carbs {carb:.1f}g")
        if fat   is not None: parts.append(f"fat {fat:.1f}g")
        if sugar is not None: parts.append(f"sugar {sugar:.1f}g")
        if fiber is not None: parts.append(f"fiber {fiber:.1f}g")
        return " | ".join(parts)
    except Exception as e:
        logger.debug(f"[VISION] Edamam error: {e}")
        return None


# ── Public: capture_and_ask ───────────────────────────────────────────────────

_VISION_PROMPT = """\
The user is asking about what the camera sees: "{question}"

Focus on the FOREGROUND object being held or shown — not the background.
If a hand holds something, identify WHAT is held: brand, type, color, shape.
If it's food, name it specifically (e.g. "banana", "can of Coke").
If you cannot identify the foreground object, say so directly.
2-3 sentences max. No preamble. Start with the object identification."""


def capture_and_ask(question: str = "What do you see?") -> str:
    """Capture one camera frame → provider chain → return answer.
    Food queries get Edamam nutrition data appended."""
    global _last_call_time, _vision_in_progress
    global _last_frame_b64, _last_frame_ts, _last_question, _last_answer

    now = time.time()

    # Rapid follow-up: reuse cached frame + answer
    if (
        _last_frame_b64
        and (now - _last_frame_ts) < _CACHE_TTL
        and question.lower().strip() == _last_question.lower().strip()
    ):
        return _last_answer

    if _vision_in_progress:
        return "Vision is already processing a request."
    if now - _last_call_time < MIN_CALL_INTERVAL:
        remaining = int(MIN_CALL_INTERVAL - (now - _last_call_time))
        return f"Vision cooling down, try again in {remaining}s."

    _vision_in_progress = True
    _last_call_time = now

    try:
        # Reuse cached frame if fresh enough
        if _last_frame_b64 and (now - _last_frame_ts) < _CACHE_TTL:
            b64 = _last_frame_b64
        else:
            frame = _capture_frame()
            if frame is None:
                return "Camera unavailable or no frame captured."
            b64 = _frame_to_b64(frame)
            if b64 is None:
                return "Failed to encode camera frame."
            _last_frame_b64 = b64
            _last_frame_ts  = now

        prompt = _VISION_PROMPT.format(question=question)
        answer = _ask_vision(b64, prompt)

        # Append Edamam nutrition for food queries
        if _is_food_query(question) and "unavailable" not in answer.lower():
            food_name = _extract_food_name(answer)
            if food_name:
                nutrition = _edamam_nutrition(food_name)
                if nutrition:
                    answer = f"{answer}\n\nNutrition data: {nutrition}"

        _last_question = question
        _last_answer   = answer
        return answer

    except Exception as e:
        return f"Camera vision failed: {e}"
    finally:
        _vision_in_progress = False


def _extract_food_name(vision_response: str) -> str:
    """Extract the first noun phrase likely to be a food name from vision response."""
    # Take first sentence, strip preamble
    first = vision_response.split(".")[0].strip()
    # Remove "This is a", "I can see", etc.
    first = re.sub(
        r"^(this is (a|an)?|i (can )?see (a|an)?|that('s| is) (a|an)?)\s*",
        "",
        first,
        flags=re.IGNORECASE,
    ).strip()
    # Limit to first 5 words (food names aren't long)
    words = first.split()[:5]
    return " ".join(words) if words else ""


# ── Public: capture_image ─────────────────────────────────────────────────────

def capture_image() -> str:
    """Capture one frame, save to temp file, return path. Empty string on failure."""
    try:
        frame = _capture_frame()
        if frame is None:
            return ""
        import tempfile
        tmp  = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        path = tmp.name
        tmp.close()
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path
    except Exception as e:
        logger.error(f"[VISION] capture_image failed: {e}")
        return ""


def get_camera_description() -> str:
    return capture_and_ask("Describe what you see in this camera frame in 2-3 sentences.")


# ── Public: smart_locate_and_click ────────────────────────────────────────────

_LOCATE_PROMPT = (
    'Find "{target}" in this screenshot. '
    'Screen is {w}x{h} pixels. '
    'Reply ONLY: x=<number> y=<number> — center pixel of that element. '
    'If not found reply: NOT_FOUND'
)


def smart_locate_and_click(target: str, vision_client=None):
    """Screenshot → provider chain locates target → pyautogui clicks it.
    Returns True on success, 'COOLDOWN_N' string on cooldown, False on failure."""
    global _screen_last_call
    import pyautogui

    now     = time.time()
    elapsed = now - _screen_last_call
    if elapsed < _SCREEN_COOLDOWN:
        return f"COOLDOWN_{int(_SCREEN_COOLDOWN - elapsed)}"

    _screen_last_call = now

    try:
        screenshot  = pyautogui.screenshot()
        w, h        = pyautogui.size()

        # Encode screenshot to b64
        buf_io = io.BytesIO()
        screenshot.save(buf_io, format="JPEG", quality=85)
        b64 = base64.b64encode(buf_io.getvalue()).decode()

        prompt = _LOCATE_PROMPT.format(target=target, w=w, h=h)
        text   = _ask_vision(b64, prompt)

        if not text or "NOT_FOUND" in text or "unavailable" in text.lower():
            return False

        # Use negative lookbehind so we don't match "axis=123" as "x=123"
        x_m = re.search(r'(?<![A-Za-z])x\s*=\s*(\d+)', text)
        y_m = re.search(r'(?<![A-Za-z])y\s*=\s*(\d+)', text)
        if not x_m or not y_m:
            return False

        x, y = int(x_m.group(1)), int(y_m.group(1))
        if not (0 <= x <= w and 0 <= y <= h):
            return False

        pyautogui.click(x, y)
        return True

    except Exception as e:
        logger.debug(f"[VISION] smart_locate_and_click failed: {e}")
        return False
