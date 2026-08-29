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


def test_api_logs_requires_token_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_TOKEN", "secret")
    log_file = tmp_path / "trading_bot.json.log"
    log_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("modules.logging_setup.LOG_JSON_FILE", str(log_file))
    client = app.test_client()
    denied = client.get("/api/logs")
    assert denied.status_code == 401
    allowed = client.get("/api/logs", headers={"X-TraderBot-Token": "secret"})
    assert allowed.status_code == 200
    html = client.get("/")
    assert html.status_code == 200


def test_api_logs_hides_assets_removed_from_yaml(tmp_path, monkeypatch):
    import routes

    log_file = tmp_path / "trading_bot.json.log"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "message": "Ciclo BTCUSDT: Manter posição",
                        "event": "cycle_summary",
                        "operation_code": "BTCUSDT",
                    }
                ),
                json.dumps(
                    {
                        "message": "Ciclo LINKUSDT: Regime pause",
                        "event": "cycle_summary",
                        "operation_code": "LINKUSDT",
                        "stock_code": "LINK",
                    }
                ),
                json.dumps({"message": "Config reloaded", "event": "config_reloaded"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("modules.logging_setup.LOG_JSON_FILE", str(log_file))
    monkeypatch.setattr(
        routes,
        "_configured_operation_codes",
        lambda settings=None: {"BTCUSDT", "ETHUSDT"},
    )

    client = app.test_client()
    logs = client.get("/api/logs").get_json()["logs"]
    assert [entry["message"] for entry in logs] == [
        "Config reloaded",
        "Ciclo BTCUSDT: Manter posição",
    ]
    assert client.get("/api/logs?operation_code=LINKUSDT").get_json()["logs"] == []


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


def test_profit_page_renders():
    client = app.test_client()
    response = client.get("/profit")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h1>Profit</h1>" in html
    assert "Custo realizado" in html
    assert "Custo em aberto" in html
    assert "Saldo total" in html
    assert "Receita realizada" in html
    assert "Valor total agregado" not in html
    assert "P&amp;L realizado" in html
    assert "Posição aberta" in html
    assert "profit-warnings" in html


def test_api_profit_returns_classified_operations(monkeypatch):
    monkeypatch.setattr(
        "routes.get_profit_board",
        lambda force_refresh=False: {
            "total_usd": 800.0,
            "realized_proceeds_usd": 800.0,
            "nav_usd": 661.59,
            "total_cost_usd": 600.0,
            "open_cost_usd": 91.12,
            "total_pnl_usd": 200.0,
            "total_pnl_pct": 33.33,
            "warnings": [],
            "open_positions": [],
            "operations": [
                {
                    "kind": "take_profit",
                    "stock_code": "BTC",
                    "operation_code": "BTCUSDT",
                    "usd_value": 800.0,
                    "pnl_usd": 200.0,
                    "pnl_pct": 33.33,
                }
            ],
        },
    )
    client = app.test_client()
    response = client.get("/api/profit")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_usd"] == 800.0
    assert payload["realized_proceeds_usd"] == 800.0
    assert payload["nav_usd"] == 661.59
    assert payload["total_pnl_usd"] == 200.0
    assert payload["operations"][0]["kind"] == "take_profit"
    assert payload["operations"][0]["stock_code"] == "BTC"


def test_api_profit_returns_503_when_credentials_missing(monkeypatch):
    def raise_missing(force_refresh=False):
        raise ValueError("Credenciais da Binance não configuradas")

    monkeypatch.setattr("routes.get_profit_board", raise_missing)
    client = app.test_client()
    response = client.get("/api/profit")
    assert response.status_code == 503
    assert "Credenciais" in response.get_json()["error"]


def test_get_profit_board_reconciles_live_inventory(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import routes
    from persistence.state_store import StateStore

    store = StateStore(tmp_path / "profit.db")
    settings = SimpleNamespace(
        environment="testnet",
        assets=[],
        risk=SimpleNamespace(take_profit=[], stop_loss_pct=2.0),
    )
    env = SimpleNamespace(api_key="", secret_key="")
    monkeypatch.setattr(routes, "StateStore", lambda: store)
    monkeypatch.setattr(routes, "load_settings", lambda: (settings, env))
    monkeypatch.setattr(routes, "rebuild_outcomes_from_orders", lambda *a, **k: 0)
    monkeypatch.setattr(routes, "kind_hints_from_log", lambda *a, **k: {})
    monkeypatch.setattr(
        routes,
        "match_trades_and_open_lots",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(
        routes,
        "get_portfolio_snapshot",
        lambda: {
            "total_usd": 661.59,
            "assets": [
                {
                    "stock_code": "ETH",
                    "operation_code": "ETHUSDT",
                    "quantity": 0.211,
                    "last_buy_price": 2414.93,
                }
            ],
        },
    )
    routes._history_cache["ts"] = 0.0
    routes._history_cache["data"] = None
    board = routes.get_profit_board(force_refresh=True)
    assert board["nav_usd"] == 661.59
    assert board["open_positions"][0]["source"] == "external"
    assert board["open_positions"][0]["stock_code"] == "ETH"
    assert board["warnings"][0]["code"] == "untracked_inventory"
    routes._history_cache["ts"] = 0.0
    routes._history_cache["data"] = None


def test_get_profit_board_keeps_fifo_when_nav_unavailable(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import routes
    from persistence.state_store import StateStore

    store = StateStore(tmp_path / "profit.db")
    settings = SimpleNamespace(
        environment="testnet",
        assets=[],
        risk=SimpleNamespace(take_profit=[], stop_loss_pct=2.0),
    )
    env = SimpleNamespace(api_key="", secret_key="")
    monkeypatch.setattr(routes, "StateStore", lambda: store)
    monkeypatch.setattr(routes, "load_settings", lambda: (settings, env))
    monkeypatch.setattr(routes, "rebuild_outcomes_from_orders", lambda *a, **k: 0)
    monkeypatch.setattr(routes, "kind_hints_from_log", lambda *a, **k: {})
    monkeypatch.setattr(
        routes,
        "match_trades_and_open_lots",
        lambda *a, **k: (
            [],
            [
                {
                    "kind": "open",
                    "source": "orders",
                    "stock_code": "SOL",
                    "operation_code": "SOLUSDT",
                    "quantity": 0.5,
                    "buy_price": 140.0,
                    "cost_usd": 70.0,
                }
            ],
        ),
    )

    def raise_missing():
        raise ValueError("Credenciais da Binance não configuradas")

    monkeypatch.setattr(routes, "get_portfolio_snapshot", raise_missing)
    routes._history_cache["ts"] = 0.0
    routes._history_cache["data"] = None
    board = routes.get_profit_board(force_refresh=True)
    assert board["nav_usd"] is None
    assert board["open_positions"][0]["stock_code"] == "SOL"
    assert board["open_positions"][0]["source"] == "orders"
    assert board["warnings"][0]["code"] == "nav_unavailable"
    routes._history_cache["ts"] = 0.0
    routes._history_cache["data"] = None


def test_api_portfolio_returns_503_when_credentials_missing(monkeypatch):
    def raise_missing():
        raise ValueError("Credenciais da Binance não configuradas")

    monkeypatch.setattr("routes.get_portfolio_snapshot", raise_missing)
    client = app.test_client()
    response = client.get("/api/portfolio")
    assert response.status_code == 503
    assert "Credenciais" in response.get_json()["error"]
