import logging
import os

LOG_DIR = "src/logs"
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

_configured = False


def setup_logging(level=logging.INFO):
    """Create log directory and configure logging once."""
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format=LOG_FORMAT,
    )
    _configured = True
