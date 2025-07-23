import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "rssbot.log"
logger = logging.getLogger("rssbot")
logger.setLevel(logging.INFO)

fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
file_handler.setFormatter(fmt)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(fmt)
logger.addHandler(console_handler)