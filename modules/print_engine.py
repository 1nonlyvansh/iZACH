"""
modules/print_engine.py
iZACH Print Intelligence — Phase 2

Features:
- Network printer discovery via win32print
- Default print preference profiles (B&W/color, DPI, margins, pages)
- Send print jobs: Chrome headless for PDF, or win32print for raw
- Queue monitoring via win32print.EnumJobs
- File preview: first-page thumbnail via pypdf / Pillow
- REST surface (called from ui_api.py and command_chain.py)
"""

import os
import json
import base64
import threading
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("iZACH.PrintEngine")

# ── Config file ──────────────────────────────────────────────────
_CFG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "print_settings.json")

_DEFAULT_PREFS = {
    "default_printer": "",          # empty = system default
    "color_mode": "color",          # "color" | "bw"
    "dpi": 600,                     # 120 | 300 | 600
    "pages": "all",                 # "all" | "odd" | "even"
    "margin_mm": 15,                # margin in mm
    "copies": 1,
    "duplex": False,
}

_prefs: dict = {}
_prefs_lock = threading.Lock()

# ── Win32Print availability ──────────────────────────────────────
try:
    import win32print
    _W32 = True
except ImportError:
    _W32 = False
    logger.warning("[PRINT] win32print not available — install pywin32")


# =============================================================================
# Preferences
# =============================================================================

def _load_prefs() -> dict:
    global _prefs
    try:
        with open(_CFG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = {**_DEFAULT_PREFS, **data}
        _prefs = merged
        return merged
    except FileNotFoundError:
        _prefs = dict(_DEFAULT_PREFS)
        _save_prefs(_prefs)
        return _prefs
    except Exception as e:
        logger.error(f"[PRINT] Load prefs error: {e}")
        _prefs = dict(_DEFAULT_PREFS)
        return _prefs


def _save_prefs(data: dict):
    try:
        with open(_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"[PRINT] Save prefs error: {e}")


def get_prefs() -> dict:
    with _prefs_lock:
        if not _prefs:
            return _load_prefs()
        return dict(_prefs)


def update_prefs(updates: dict) -> dict:
    with _prefs_lock:
        current = _prefs if _prefs else _load_prefs()
        current.update({k: v for k, v in updates.items() if k in _DEFAULT_PREFS})
        _prefs.update(current)
        _save_prefs(current)
        return dict(current)


# =============================================================================
# Printer discovery
# =============================================================================

def list_printers() -> list[dict]:
    """
    Return list of available printers.
    Each entry: {name, is_default, status}
    Falls back to empty list if win32print unavailable.
    """
    if not _W32:
        return []
    try:
        default = win32print.GetDefaultPrinter()
        raw = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None, 2
        )
        printers = []
        for p in raw:
            name = p["pPrinterName"]
            status_code = p.get("Status", 0)
            if status_code == 0:
                status = "ready"
            elif status_code & 0x00000004:
                status = "error"
            elif status_code & 0x00000020:
                status = "offline"
            else:
                status = "busy"
            printers.append({
                "name": name,
                "is_default": name == default,
                "status": status,
            })
        return printers
    except Exception as e:
        logger.error(f"[PRINT] List printers error: {e}")
        return []


def get_default_printer() -> str:
    """Return current default printer name or empty string."""
    prefs = get_prefs()
    if prefs.get("default_printer"):
        return prefs["default_printer"]
    if _W32:
        try:
            return win32print.GetDefaultPrinter()
        except Exception:
            pass
    return ""


def get_printer_status(printer_name: str = "") -> dict:
    """
    Return {name, status, jobs_count, is_online} for given printer.
    If printer_name empty, uses default.
    """
    name = printer_name or get_default_printer()
    if not name:
        return {"name": "No printer", "status": "no_printer", "jobs_count": 0, "is_online": False}

    if not _W32:
        return {"name": name, "status": "unknown", "jobs_count": 0, "is_online": False}

    try:
        handle = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(handle, 2)
            status_code = info.get("Status", 0)
            if status_code == 0:
                status = "ready"
            elif status_code & 0x00000004:
                status = "error"
            elif status_code & 0x00000020:
                status = "offline"
            elif status_code & 0x00000001:
                status = "paused"
            else:
                status = "busy"

            jobs = win32print.EnumJobs(handle, 0, -1, 1)
            return {
                "name": name,
                "status": status,
                "jobs_count": len(jobs),
                "is_online": status in ("ready", "busy"),
                "jobs": [{"id": j.get("JobId"), "document": j.get("pDocument", ""), "status": j.get("Status", 0)} for j in jobs[:10]],
            }
        finally:
            win32print.ClosePrinter(handle)
    except Exception as e:
        logger.debug(f"[PRINT] Status error for {name}: {e}")
        return {"name": name, "status": "offline", "jobs_count": 0, "is_online": False, "jobs": []}


# =============================================================================
# Print job dispatch
# =============================================================================

def _chrome_print(file_path: str, printer_name: str, prefs: dict) -> tuple[bool, str]:
    """
    Use Chrome headless to print PDF/HTML to printer.
    Supports most print preferences via flags.
    """
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    chrome_exe = next((p for p in chrome_paths if os.path.exists(p)), None)
    if not chrome_exe:
        return False, "Chrome not found"

    color_flag = "--disable-print-preview"
    margins = prefs.get("margin_mm", 15)

    cmd = [
        chrome_exe,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        f"--print-to-pdf-no-header",
        f"--print-to-printer={printer_name}",
        f"--print-paper-size=A4",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return True, "Sent to printer via Chrome"
        return False, result.stderr[:200] or "Chrome print failed"
    except subprocess.TimeoutExpired:
        return False, "Chrome print timed out"
    except Exception as e:
        return False, str(e)


def _win32_print(file_path: str, printer_name: str) -> tuple[bool, str]:
    """Direct win32 raw print — works for text files."""
    if not _W32:
        return False, "win32print not available"
    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            hjob = win32print.StartDocPrinter(hprinter, 1, (os.path.basename(file_path), None, "RAW"))
            try:
                win32print.StartPagePrinter(hprinter)
                with open(file_path, "rb") as f:
                    data = f.read()
                win32print.WritePrinter(hprinter, data)
                win32print.EndPagePrinter(hprinter)
            finally:
                win32print.EndDocPrinter(hprinter)
        finally:
            win32print.ClosePrinter(hprinter)
        return True, f"Sent {os.path.basename(file_path)} to {printer_name}"
    except Exception as e:
        return False, str(e)


def parse_page_spec(spec: str, total_pages: int) -> list[int]:
    """
    Parse page spec string → sorted unique 1-based page numbers.
    Supports: "all", "odd", "even", "1,3,5", "2-6", "1,3-5,8"
    Returns empty list = print all.
    """
    spec = spec.strip().lower()
    if not spec or spec == "all":
        return []
    if spec == "odd":
        return list(range(1, total_pages + 1, 2))
    if spec == "even":
        return list(range(2, total_pages + 1, 2))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                pages.update(range(int(a), int(b) + 1))
            except ValueError:
                pass
        else:
            try:
                pages.add(int(part))
            except ValueError:
                pass
    # Clamp to valid range
    return sorted(p for p in pages if 1 <= p <= total_pages)


def extract_pages_to_temp(file_path: str, page_numbers: list[int]) -> Optional[str]:
    """
    Extract specific pages from PDF into a temp file.
    page_numbers: 1-based list. Returns temp file path or None on failure.
    """
    if not page_numbers:
        return None  # caller should use original file
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(file_path)
        writer = PdfWriter()
        for pn in page_numbers:
            idx = pn - 1
            if 0 <= idx < len(reader.pages):
                writer.add_page(reader.pages[idx])
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False,
                                          dir=os.path.dirname(file_path))
        with open(tmp.name, "wb") as f:
            writer.write(f)
        return tmp.name
    except ImportError:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(file_path)
            writer = PyPDF2.PdfWriter()
            for pn in page_numbers:
                idx = pn - 1
                if 0 <= idx < len(reader.pages):
                    writer.add_page(reader.pages[idx])
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False,
                                              dir=os.path.dirname(file_path))
            with open(tmp.name, "wb") as f:
                writer.write(f)
            return tmp.name
        except Exception as e:
            logger.error(f"[PRINT] extract_pages PyPDF2: {e}")
            return None
    except Exception as e:
        logger.error(f"[PRINT] extract_pages: {e}")
        return None


def get_pdf_page_count(file_path: str) -> int:
    """Return page count of PDF, 0 if unreadable."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(file_path).pages)
    except Exception:
        try:
            import PyPDF2
            return len(PyPDF2.PdfReader(file_path).pages)
        except Exception:
            return 0


def print_file(file_path: str, overrides: dict = None) -> tuple[bool, str]:
    """
    Print a file using stored preferences (+ any per-job overrides).
    Returns (success, message).
    Supports: .pdf, .docx, .txt, .jpg, .png
    """
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}"

    prefs = get_prefs()
    if overrides:
        prefs = {**prefs, **overrides}

    printer_name = prefs.get("default_printer") or get_default_printer()
    if not printer_name:
        return False, "No printer configured"

    ext = Path(file_path).suffix.lower()
    logger.info(f"[PRINT] Printing {file_path} → {printer_name} | {prefs}")

    # Handle custom page spec for PDFs
    _temp_file = None
    page_spec = prefs.get("pages", "all")
    if ext == ".pdf" and page_spec not in ("all", "", None):
        total = get_pdf_page_count(file_path)
        if total > 0:
            page_nums = parse_page_spec(page_spec, total)
            if page_nums:
                temp = extract_pages_to_temp(file_path, page_nums)
                if temp:
                    _temp_file = temp
                    file_path = temp  # print the extracted subset

    # PDF/HTML → Chrome headless
    if ext in (".pdf", ".html", ".htm"):
        ok, msg = _chrome_print(file_path, printer_name, prefs)
        if _temp_file:
            try: os.remove(_temp_file)
            except Exception: pass
        if ok:
            return ok, msg
        # Fall through to win32 raw on Chrome failure

    # All other files → try win32 raw print
    ok, msg = _win32_print(file_path, printer_name)
    if _temp_file:
        try: os.remove(_temp_file)
        except Exception: pass
    return ok, msg


def print_files_batch(file_paths: list[str], overrides: dict = None,
                      per_file_pages: dict = None) -> list[dict]:
    """
    Print multiple files. Returns list of {file, success, message}.
    per_file_pages: {file_path: "page_spec_string"} for per-file custom pages.
    """
    results = []
    for fp in file_paths:
        file_overrides = dict(overrides) if overrides else {}
        if per_file_pages and fp in per_file_pages:
            file_overrides["pages"] = per_file_pages[fp]
        ok, msg = print_file(fp, file_overrides)
        results.append({"file": os.path.basename(fp), "success": ok, "message": msg})
    return results


# =============================================================================
# Preview generation
# =============================================================================

def generate_preview(file_path: str) -> Optional[str]:
    """
    Generate a base64-encoded PNG thumbnail of the first page/frame.
    Returns base64 string or None on failure.
    Supports: PDF, images (jpg/png/bmp/gif)
    """
    ext = Path(file_path).suffix.lower()

    # Images — just resize + encode
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"):
        try:
            from PIL import Image
            img = Image.open(file_path)
            img.thumbnail((400, 400))
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            logger.debug(f"[PRINT] Image preview error: {e}")
            return None

    # PDF — render first page to image
    if ext == ".pdf":
        # Try pypdf + PIL approach via pdf2image if available
        try:
            import pdf2image
            images = pdf2image.convert_from_path(file_path, first_page=1, last_page=1, dpi=100)
            if images:
                import io
                buf = io.BytesIO()
                images[0].save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[PRINT] pdf2image error: {e}")

        # Fallback: return page count info only
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            pages = len(reader.pages)
            return f"pdf:{pages}"  # special signal: no image, just page count
        except Exception:
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(file_path)
                return f"pdf:{len(reader.pages)}"
            except Exception:
                return None

    # DOCX — count pages via python-docx (approximate)
    if ext in (".docx", ".doc"):
        try:
            from docx import Document
            doc = Document(file_path)
            para_count = len(doc.paragraphs)
            est_pages = max(1, para_count // 30)
            return f"docx:{est_pages}"
        except Exception:
            return None

    return None


# =============================================================================
# Public init
# =============================================================================

def init():
    """Load preferences on startup."""
    _load_prefs()
    logger.info(f"[PRINT] Engine ready. Default printer: {get_default_printer() or 'none'}")


# Init on import
try:
    init()
except Exception:
    pass
