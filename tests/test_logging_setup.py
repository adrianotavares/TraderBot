import json

from modules.logging_setup import read_structured_logs


def _write_log(path, entries):
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_read_structured_logs_newest_first(tmp_path):
    log_file = tmp_path / "trading_bot.json.log"
    _write_log(
        log_file,
        [
            {"message": "first", "event": "asset_variation", "operation_code": "BTCUSDT"},
            {"message": "second", "event": "regime_detected", "operation_code": "ETHUSDT"},
            {"message": "third", "event": "asset_variation", "operation_code": "BTCUSDT"},
        ],
    )
    entries = read_structured_logs(path=str(log_file), limit=10)
    assert [item["message"] for item in entries] == ["third", "second", "first"]


def test_read_structured_logs_filters_by_operation(tmp_path):
    log_file = tmp_path / "trading_bot.json.log"
    _write_log(
        log_file,
        [
            {"message": "btc", "operation_code": "BTCUSDT", "event": "asset_variation"},
            {"message": "eth", "operation_code": "ETHUSDT", "event": "asset_variation"},
        ],
    )
    entries = read_structured_logs(
        path=str(log_file), operation_code="BTCUSDT"
    )
    assert len(entries) == 1
    assert entries[0]["message"] == "btc"


def test_read_structured_logs_missing_file(tmp_path):
    assert read_structured_logs(path=str(tmp_path / "missing.log")) == []


def test_read_structured_logs_skips_unstructured_noise(tmp_path):
    log_file = tmp_path / "trading_bot.json.log"
    _write_log(
        log_file,
        [
            {
                "message": "Retrying after NameResolutionError",
                "logger": "urllib3.connectionpool",
                "level": "WARNING",
            },
            {
                "message": "BTC subiu 1.00% nas últimas 4h - 100.00 usd",
                "event": "asset_variation",
                "operation_code": "BTCUSDT",
            },
        ],
    )
    entries = read_structured_logs(path=str(log_file))
    assert len(entries) == 1
    assert entries[0]["event"] == "asset_variation"


def test_read_structured_logs_redacts_binance_signature(tmp_path):
    log_file = tmp_path / "trading_bot.json.log"
    signature = "10a7d75b5a8bb8672f9c54717ee8b5ab4d47e63d4bc9b6a00cc51f86ca21d1fb"
    _write_log(
        log_file,
        [
            {
                "message": (
                    "Trader loop error: /api/v3/account?recvWindow=10000"
                    f"&timestamp=1&signature={signature}"
                ),
                "event": "loop_error",
                "operation_code": "ETHUSDT",
            }
        ],
    )
    entries = read_structured_logs(path=str(log_file))
    assert len(entries) == 1
    assert signature not in entries[0]["message"]
    assert "signature=[redacted]" in entries[0]["message"]
