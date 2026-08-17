import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
LOG_JSON_FILE = os.path.join(LOG_DIR, "trading_bot.json.log")
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
_SIGNATURE_RE = re.compile(r"(?i)(signature=)[0-9a-f]+")

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


def _redact_secrets(entry: dict) -> dict:
    message = entry.get("message")
    if not isinstance(message, str) or "signature=" not in message.lower():
        return entry
    redacted = dict(entry)
    redacted["message"] = _SIGNATURE_RE.sub(r"\1[redacted]", message)
    return redacted


def read_structured_logs(
    limit: int = 200,
    operation_code: str | None = None,
    stock_code: str | None = None,
    event: str | None = None,
    path: str | None = None,
    structured_only: bool = True,
) -> list:
    """Return the latest JSON log entries, newest first.

    By default only `log_event` records (those with an `event` field) are
    returned, so urllib3/Binance client noise is not shown on the dashboard.
    """
    log_path = path or LOG_JSON_FILE
    if not os.path.exists(log_path):
        return []

    limit = max(1, min(int(limit), 500))
    max_bytes = 512_000
    with open(log_path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read().decode("utf-8", errors="replace")
    if size > max_bytes:
        data = data.split("\n", 1)[-1]

    entries = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if structured_only and not entry.get("event"):
            continue
        if operation_code and entry.get("operation_code") != operation_code:
            continue
        if stock_code and entry.get("stock_code") != stock_code:
            continue
        if event and entry.get("event") != event:
            continue
        entries.append(_redact_secrets(entry))
    return list(reversed(entries[-limit:]))


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
