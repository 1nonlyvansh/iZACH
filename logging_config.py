import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')

    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # ── File handler — captures everything ────────────────────────────────────
    file_handler = RotatingFileHandler(
        'logs/izach.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    # ── Console handler — ERROR only ──────────────────────────────────────────
    # iZACH's own [SPEAK], [LISTENING], [USER] etc. are plain print() — they
    # bypass Python logging entirely and always appear.
    # Python-logged stuff: only show actual errors in terminal.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.ERROR)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ── Werkzeug — file only, NOT console ────────────────────────────────────
    # Reuse the same file_handler instance (not a second RotatingFileHandler on
    # the same file — two handlers on one file causes WinError 32 on rotation).
    wz = logging.getLogger('werkzeug')
    wz.propagate = False        # never bubble to root (prevents double-log)
    wz.setLevel(logging.INFO)   # capture INFO for file
    wz.addHandler(file_handler) # shared handler → single file lock

    # NO console handler for werkzeug → terminal stays clean

    # ── Suppress all other chatty libraries ───────────────────────────────────
    for _lib in (
        'google', 'httpx', 'urllib3', 'googleapiclient', 'google_auth_httplib2',
        'pymongo', 'apscheduler', 'websockets', 'asyncio', 'comtypes',
        'PIL', 'numba', 'llvmlite',
    ):
        lg = logging.getLogger(_lib)
        lg.propagate = False
        lg.setLevel(logging.ERROR)
