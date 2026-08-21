import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import app  # noqa: E402


def test_api_logs_returns_structured_events_only(tmp_path, monkeypatch):
    log_file = tmp_path / "trading_bot.json.log"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "message": "Retrying urllib3",
                        "logger": "urllib3.connectionpool",
                        "level": "WARNING",
                    }
                ),
                json.dumps(
                    {
                        "message": "Regime detected",
                        "event": "regime_detected",
                        "operation_code": "BTCUSDT",
                        "regime": "LATERAL",
                        "score": 3,
                        "adx": 18.2,
                        "rsi": 52.1,
                        "signals": {"adx_low": True, "rsi_neutral": True},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("modules.logging_setup.LOG_JSON_FILE", str(log_file))

    client = app.test_client()
    response = client.get("/api/logs")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["logs"]) == 1
    entry = payload["logs"][0]
    assert entry["event"] == "regime_detected"
    assert entry["regime"] == "LATERAL"
    assert entry["score"] == 3
    assert entry["adx"] == 18.2
    assert entry["rsi"] == 52.1


def test_api_logs_filters_by_operation_code(tmp_path, monkeypatch):
    log_file = tmp_path / "trading_bot.json.log"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "message": "btc",
                        "event": "asset_variation",
                        "operation_code": "BTCUSDT",
                    }
                ),
                json.dumps(
                    {
                        "message": "eth",
                        "event": "asset_variation",
                        "operation_code": "ETHUSDT",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("modules.logging_setup.LOG_JSON_FILE", str(log_file))

    client = app.test_client()
    response = client.get("/api/logs?operation_code=BTCUSDT")
    assert response.status_code == 200
    logs = response.get_json()["logs"]
    assert len(logs) == 1
    assert logs[0]["message"] == "btc"


def test_api_logs_rejects_invalid_limit():
    client = app.test_client()
    response = client.get("/api/logs?limit=abc")
    assert response.status_code == 400


def test_api_portfolio_returns_total_usd(monkeypatch):
    monkeypatch.setattr(
        "routes.get_portfolio_snapshot",
        lambda: {
            "total_usd": 1250.5,
            "total_pnl_usd": 150.0,
            "total_pnl_pct": 15.0,
            "assets": [
                {
                    "stock_code": "BTC",
                    "operation_code": "BTCUSDT",
                    "quantity": 0.01,
                    "price": 65000.0,
                    "usd_value": 650.0,
                    "pnl_usd": 50.0,
                    "pnl_pct": 8.33,
                }
            ],
        },
    )
    client = app.test_client()
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_usd"] == 1250.5
    assert payload["total_pnl_usd"] == 150.0
    assert payload["total_pnl_pct"] == 15.0
    assert payload["assets"][0]["stock_code"] == "BTC"


def test_api_portfolio_returns_503_when_credentials_missing(monkeypatch):
    def raise_missing():
        raise ValueError("Credenciais da Binance não configuradas")

    monkeypatch.setattr("routes.get_portfolio_snapshot", raise_missing)
    client = app.test_client()
    response = client.get("/api/portfolio")
    assert response.status_code == 503
    assert "Credenciais" in response.get_json()["error"]
