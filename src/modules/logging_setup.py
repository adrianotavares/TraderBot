import json
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
LOG_JSON_FILE = os.path.join(LOG_DIR, "trading_bot.json.log")
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def log_event(level: int, message: str, **fields):
    logger = logging.getLogger("traderbot")
    record = logger.makeRecord(
        logger.name, level, "", 0, message, (), None
    )
    record.extra_fields = fields
    logger.handle(record)


def setup_logging(level=None):
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    log_level = level or getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    text_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)
    text_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    json_handler = RotatingFileHandler(LOG_JSON_FILE, maxBytes=5_000_000, backupCount=5)
    json_handler.setFormatter(JsonFormatter())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT))

    root.addHandler(text_handler)
    root.addHandler(json_handler)
    root.addHandler(console)

    _configured = True
