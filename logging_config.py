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

    # FIXED: Added encoding='utf-8' to handle emojis/special characters
    file_handler = RotatingFileHandler(
        'logs/izach.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.ERROR) 

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Suppress noisy loggers
    logging.getLogger('google').setLevel(logging.ERROR)
    logging.getLogger('httpx').setLevel(logging.ERROR)

    # Stop werkzeug from propagating to root logger —
    # without this every HTTP request is logged TWICE (once by werkzeug's
    # own handler, once when it bubbles up to the root handler).
    logging.getLogger('werkzeug').propagate = False

    # Other chatty libraries that don't need root propagation
    for _noisy in ('urllib3', 'googleapiclient', 'google_auth_httplib2',
                   'pymongo', 'apscheduler', 'websockets', 'asyncio',
                   'comtypes', 'PIL'):
        logging.getLogger(_noisy).propagate = False
        logging.getLogger(_noisy).setLevel(logging.WARNING)