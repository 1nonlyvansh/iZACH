import logging
import os
import re
from logging.handlers import RotatingFileHandler


# ── Poll-endpoint filter ───────────────────────────────────────────────────────
# Werkzeug logs every HTTP request at INFO level. The UI polls /status, /spotify,
# /phone/status, /whatsapp/status etc. every 2-4s → 40+ terminal lines/minute.
# This filter lets 4xx/5xx and POST/PUT/DELETE through; silences noisy GET polls.

_POLL_ENDPOINTS = re.compile(
    r'"GET /(status|spotify|phone/status|phone/commands|whatsapp/status|'
    r'health|weather|contacts|nodes/vitals|subconsciousness/pending|'
    r'mic/devices|vision/cameras|connect/qr|busy|dnd|calendar/events|'
    r'skills|relationships|print/status|location/status|fitness/summary|'
    r'smarthome/status) HTTP'
)


class _SuppressPollFilter(logging.Filter):
    """Drop routine UI poll GET requests — only pass errors and write ops."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Always show errors (4xx/5xx)
        if '" 4' in msg or '" 5' in msg:
            return True
        # Always show writes
        if '"POST ' in msg or '"PUT ' in msg or '"DELETE ' in msg or '"PATCH ' in msg:
            return True
        # Drop silent polls
        if _POLL_ENDPOINTS.search(msg):
            return False
        return True


def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')

    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File handler — keep INFO and above, polls included (for debug)
    file_handler = RotatingFileHandler(
        'logs/izach.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    # Console handler — ERROR only + iZACH's own prints bypass this anyway
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.ERROR)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ── Werkzeug access log ────────────────────────────────────────────────────
    # Stop propagation to root (prevents double-logging).
    # Add poll-suppression filter so terminal stays clean.
    # Keep a file-only handler so polls still appear in izach.log for debugging.
    wz = logging.getLogger('werkzeug')
    wz.propagate = False
    wz.setLevel(logging.INFO)

    wz_file = RotatingFileHandler(
        'logs/izach.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    wz_file.setFormatter(log_format)
    wz_file.setLevel(logging.INFO)
    wz.addHandler(wz_file)

    # Console version of werkzeug — only errors + writes, no polls
    wz_console = logging.StreamHandler()
    wz_console.setFormatter(log_format)
    wz_console.setLevel(logging.INFO)
    wz_console.addFilter(_SuppressPollFilter())
    wz.addHandler(wz_console)

    # ── Suppress other noisy libraries ────────────────────────────────────────
    logging.getLogger('google').setLevel(logging.ERROR)
    logging.getLogger('httpx').setLevel(logging.ERROR)

    for _noisy in ('urllib3', 'googleapiclient', 'google_auth_httplib2',
                   'pymongo', 'apscheduler', 'websockets', 'asyncio',
                   'comtypes', 'PIL', 'numba', 'llvmlite'):
        logging.getLogger(_noisy).propagate = False
        logging.getLogger(_noisy).setLevel(logging.WARNING)
