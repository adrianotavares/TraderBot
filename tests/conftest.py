import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

PROD_LOG_DIR = SRC / "logs"


@pytest.fixture(autouse=True)
def _isolate_traderbot_logs(tmp_path, monkeypatch):
    """Keep pytest from appending fake SL/TP cycles to the live log files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("TRADERBOT_LOG_DIR", str(log_dir))
    import modules.logging_setup as logging_setup

    monkeypatch.setattr(logging_setup, "LOG_DIR", str(log_dir))
    monkeypatch.setattr(logging_setup, "LOG_FILE", str(log_dir / "trading_bot.log"))
    monkeypatch.setattr(
        logging_setup, "LOG_JSON_FILE", str(log_dir / "trading_bot.json.log")
    )
    logging_setup._configured = False
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        filename = getattr(handler, "baseFilename", "")
        if filename and (
            str(log_dir) in filename or str(PROD_LOG_DIR.resolve()) in filename
        ):
            root.removeHandler(handler)
            handler.close()
    logging_setup._configured = False
