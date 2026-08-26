import math
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import routes  # noqa: E402
from app import app  # noqa: E402
from config.settings import TradingSettings  # noqa: E402
from persistence.state_store import StateStore  # noqa: E402
from services.chart_data import AGGREGATE_OPERATION_CODE, MAX_BARS  # noqa: E402

PERIOD_MS = 4 * 3600 * 1000


@pytest.fixture(autouse=True)
def _clear_chart_cache():
    """The chart cache is module level, so it leaks between tests."""
    routes._chart_cache.clear()
    yield
    routes._chart_cache.clear()


def _raw_klines(n: int = 300, start_ms: int = 1_700_000_000_000) -> list:
    """Binance kline rows, exactly the 12 columns normalize_klines expects."""
    start_ms -= start_ms % PERIOD_MS
    rows = []
    for i in range(n):
        open_ms = start_ms + i * PERIOD_MS
        price = 100 + 5 * math.sin(i / 7)
        rows.append(
            [
                open_ms,
                f"{price - 0.2:.4f}",
                f"{price + 0.5:.4f}",
                f"{price - 0.5:.4f}",
                f"{price:.4f}",
                "1000",
                open_ms + PERIOD_MS - 1,
                "0",
                10,
                "0",
                "0",
                "0",
            ]
        )
    return rows


class _FakeClient:
    def __init__(self, failing: set | None = None):
        self.failing = failing or set()
        self.calls = []

    def get_klines(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        if symbol in self.failing:
            raise RuntimeError(f"binance is down for {symbol}")
        return _raw_klines(limit)


def _settings(assets=None) -> TradingSettings:
    return TradingSettings(
        environment="testnet",
        strategy={
            "main": "atr_trend",
            "main_args": {
                "atr_period": 14,
                "atr_multiplier": 2.5,
                "trend_sma_period": 200,
            },
        },
        risk={
            "stop_loss_pct": 2.0,
            "acceptable_loss_pct": 1.5,
            "take_profit": [{"at": 7.0, "amount": 100.0}],
        },
        timing={"candle_period": "4h"},
        assets=assets
        or [
            {
                "stock_code": "BTC",
                "operation_code": "BTCUSDT",
                "traded_quantity": 0.0,
                "traded_percentage": 50.0,
            },
            {
                "stock_code": "ETH",
                "operation_code": "ETHUSDT",
                "traded_quantity": 0.0,
                "traded_percentage": 50.0,
            },
        ],
    )


class _Env:
    api_key = "key"
    secret_key = "secret"


def _portfolio_snapshot(**overrides):
    base = {
        "total_pnl_usd": 12.5,
        "total_pnl_pct": 3.2,
        "assets": [
            {
                "stock_code": "BTC",
                "operation_code": "BTCUSDT",
                "quantity": 0.1,
                "price": 100.0,
                "last_buy_price": 95.0,
                "pnl_usd": 0.5,
                "pnl_pct": 5.26,
            },
            {
                "stock_code": "ETH",
                "operation_code": "ETHUSDT",
                "quantity": 2.0,
                "price": 50.0,
                "last_buy_price": 48.0,
                "pnl_usd": 4.0,
                "pnl_pct": 4.17,
            },
            {
                "stock_code": "USDT",
                "operation_code": "USDT",
                "quantity": 500.0,
                "price": 1.0,
                "last_buy_price": 1.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Wire get_tracking_charts to a temp DB and a fake exchange."""
    client = _FakeClient()
    store = StateStore(tmp_path / "charts.db")
    settings = _settings()

    monkeypatch.setattr(routes, "load_settings", lambda: (settings, _Env()))
    monkeypatch.setattr(routes, "get_spot_client", lambda *a, **k: client)
    monkeypatch.setattr(routes, "StateStore", lambda *a, **k: store)
    monkeypatch.setattr(
        routes, "get_portfolio_snapshot", lambda: _portfolio_snapshot()
    )
    return {"client": client, "store": store, "settings": settings}


def test_charts_todos_returns_aggregate_not_per_asset(wired):
    response = app.test_client().get("/api/tracking/charts")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["candle_period"] == "4h"
    assert payload["strategy"] == "atr_trend"
    assert payload["assets"] == []
    aggregate = payload["aggregate"]
    assert aggregate["operation_code"] == AGGREGATE_OPERATION_CODE
    assert aggregate["series"] == "equity"
    assert aggregate["stock_code"] == "Portfólio"
    assert len(aggregate["equity"]) > 0
    assert aggregate["regime"] == []


def test_charts_include_candles_regime_and_trailing_stop(wired):
    payload = app.test_client().get(
        "/api/tracking/charts?bars=40&operation_code=BTCUSDT"
    ).get_json()
    asset = payload["assets"][0]
    assert len(asset["candles"]) == 40
    assert set(asset["candles"][0]) == {"time", "open", "high", "low", "close"}
    assert asset["trailing_stop"]
    assert asset["regime"]
    assert asset["error"] is None


def test_charts_fetch_warmup_beyond_the_charted_window(wired):
    app.test_client().get("/api/tracking/charts?bars=40&operation_code=BTCUSDT")
    symbol, interval, limit = wired["client"].calls[0]
    assert interval == "4h"
    assert symbol == "BTCUSDT"
    # The regime detector needs 60 candles and the atr_trend SMA up to 200.
    assert limit > 200


def test_charts_todos_fetches_only_chart_window(wired):
    app.test_client().get("/api/tracking/charts?bars=40")
    limits = [call[2] for call in wired["client"].calls]
    assert limits
    assert all(limit == 40 for limit in limits)


def test_charts_omit_levels_when_flat(wired):
    payload = app.test_client().get(
        "/api/tracking/charts?bars=30&operation_code=BTCUSDT"
    ).get_json()
    assert payload["assets"][0]["levels"] is None
    assert payload["assets"][0]["position"]["open"] is False


def test_charts_expose_levels_when_holding(wired):
    state = wired["store"].load_state("BTCUSDT")
    state.actual_trade_position = True
    state.last_buy_price = 100.0
    wired["store"].save_state(state)

    payload = app.test_client().get(
        "/api/tracking/charts?bars=30&operation_code=BTCUSDT"
    ).get_json()
    levels = payload["assets"][0]["levels"]
    assert levels["entry"] == 100.0
    assert levels["take_profit"]["price"] == 107.0
    assert levels["stop_loss"]["price"] == 98.0


def test_charts_aggregate_exposes_portfolio_levels(wired):
    for code in ("BTCUSDT", "ETHUSDT"):
        state = wired["store"].load_state(code)
        state.actual_trade_position = True
        wired["store"].save_state(state)

    aggregate = app.test_client().get("/api/tracking/charts?bars=30").get_json()[
        "aggregate"
    ]
    levels = aggregate["levels"]
    # cost basis = 0.1 * 95 + 2.0 * 48 = 9.5 + 96 = 105.5
    assert levels["entry"] == 105.5
    assert levels["take_profit"]["price"] == pytest.approx(105.5 * 1.07)
    assert aggregate["position"]["pnl_pct"] == 3.2


def test_charts_filter_by_operation_code(wired):
    payload = app.test_client().get(
        "/api/tracking/charts?operation_code=ETHUSDT&bars=30"
    ).get_json()
    assert [a["operation_code"] for a in payload["assets"]] == ["ETHUSDT"]
    assert payload["aggregate"] is None


def test_charts_unknown_operation_code_is_404(wired):
    response = app.test_client().get("/api/tracking/charts?operation_code=DOGEUSDT")
    assert response.status_code == 404


def test_charts_aggregate_skips_a_failing_symbol(monkeypatch, tmp_path):
    """A broken symbol is omitted from the aggregate instead of blanking Todos."""
    client = _FakeClient(failing={"BTCUSDT"})
    monkeypatch.setattr(routes, "load_settings", lambda: (_settings(), _Env()))
    monkeypatch.setattr(routes, "get_spot_client", lambda *a, **k: client)
    monkeypatch.setattr(routes, "StateStore", lambda *a, **k: StateStore(tmp_path / "x.db"))
    monkeypatch.setattr(
        routes, "get_portfolio_snapshot", lambda: _portfolio_snapshot()
    )

    response = app.test_client().get("/api/tracking/charts?bars=30")
    assert response.status_code == 200
    aggregate = response.get_json()["aggregate"]
    assert aggregate["error"] is None
    assert aggregate["equity"]


def test_charts_isolate_a_failing_symbol(monkeypatch, tmp_path):
    """A broken symbol reports its own error on the single-asset view."""
    client = _FakeClient(failing={"BTCUSDT"})
    monkeypatch.setattr(routes, "load_settings", lambda: (_settings(), _Env()))
    monkeypatch.setattr(routes, "get_spot_client", lambda *a, **k: client)
    monkeypatch.setattr(routes, "StateStore", lambda *a, **k: StateStore(tmp_path / "x.db"))
    monkeypatch.setattr(routes, "get_portfolio_snapshot", lambda: {"assets": []})

    response = app.test_client().get(
        "/api/tracking/charts?bars=30&operation_code=BTCUSDT"
    )
    assert response.status_code == 200
    asset = response.get_json()["assets"][0]
    assert "binance is down" in asset["error"]
    assert asset["candles"] == []


def test_charts_survive_a_portfolio_outage(monkeypatch, tmp_path, wired):
    def boom():
        raise RuntimeError("no credentials")

    monkeypatch.setattr(routes, "get_portfolio_snapshot", boom)
    response = app.test_client().get("/api/tracking/charts?bars=30")
    assert response.status_code == 200
    assert response.get_json()["aggregate"]["equity"] == []


def test_charts_are_cached_between_requests(wired):
    client = app.test_client()
    client.get("/api/tracking/charts?bars=30")
    calls_after_first = len(wired["client"].calls)
    client.get("/api/tracking/charts?bars=30")
    assert len(wired["client"].calls) == calls_after_first


def test_charts_503_when_credentials_missing(monkeypatch):
    class _NoKeys:
        api_key = ""
        secret_key = ""

    monkeypatch.setattr(routes, "load_settings", lambda: (_settings(), _NoKeys()))
    response = app.test_client().get("/api/tracking/charts")
    assert response.status_code == 503
    assert "Credenciais" in response.get_json()["error"]


def test_charts_reject_invalid_bars(wired):
    response = app.test_client().get("/api/tracking/charts?bars=abc")
    assert response.status_code == 400


def test_charts_clamp_bars(wired):
    payload = app.test_client().get(
        "/api/tracking/charts?bars=9999&operation_code=BTCUSDT"
    ).get_json()
    assert len(payload["assets"][0]["candles"]) <= MAX_BARS


def test_charts_persist_regime_history(wired):
    app.test_client().get("/api/tracking/charts?bars=30&operation_code=BTCUSDT")
    rows = wired["store"].list_regime("BTCUSDT")
    assert rows
    assert {row["source"] for row in rows} == {"backfill"}
