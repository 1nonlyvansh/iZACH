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

    logging.getLogger('google').setLevel(logging.ERROR)
    logging.getLogger('httpx').setLevel(logging.ERROR)