from types import SimpleNamespace

import pandas as pd
import pytest

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore
from services.breakout_detector import BreakoutResult
from services.regime_detector import RegimeResult
from services.regime_router import resolve_regime_action

PERIOD = 4 * 3600
CANDLE_OPEN = 1_700_000_000 - (1_700_000_000 % PERIOD)


def test_resolve_action_trend():
    regime = RegimeResult(regime="TREND", score=1, adx_value=30.0, rsi_value=45.0)
    action = resolve_regime_action(
        regime,
        None,
        regime_detector=SimpleNamespace(enabled=True, action_in_lateral="grid"),
        grid_manager=None,
        breakout_detector=None,
        breakout_cooldown_candles=0,
    )
    assert action == "atr_trend"


def test_resolve_action_pause_gray():
    regime = RegimeResult(regime="GRAY", score=2, adx_value=18.0, rsi_value=50.0)
    action = resolve_regime_action(
        regime,
        None,
        regime_detector=SimpleNamespace(enabled=True, action_in_lateral="grid"),
        grid_manager=None,
        breakout_detector=None,
        breakout_cooldown_candles=0,
    )
    assert action == "pause"


def _stock_data(candle_open: int = CANDLE_OPEN) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "open_time": [candle_open - PERIOD, candle_open],
            "close_price": [100.0, 101.0],
            "high_price": [101.0, 102.0],
            "low_price": [99.0, 100.0],
            "open_price": [99.5, 100.5],
            "volume": [10.0, 12.0],
        }
    )
    frame["open_time"] = (
        pd.to_datetime(frame["open_time"], unit="s")
        .dt.tz_localize("UTC")
        .dt.tz_convert("America/Sao_Paulo")
    )
    return frame


def _engine(store, stock_data=None, detector_enabled=True):
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        stock_code="BTC",
        stock_data=_stock_data() if stock_data is None else stock_data,
        engine=None,
    )
    return TradingEngine(
        bot=bot,
        market_data=None,
        order_executor=None,
        risk_manager=None,
        state_store=store,
        regime_detector=SimpleNamespace(enabled=detector_enabled),
    )


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "engine.db")


def test_regime_detected_persists_current_candle(store):
    engine = _engine(store)
    regime = RegimeResult(regime="TREND", score=1, adx_value=30.4, rsi_value=61.2)

    engine._log_regime_detected(regime, None, "atr_trend")

    rows = store.list_regime("BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["candle_time"] == CANDLE_OPEN
    assert rows[0]["regime"] == "TREND"
    assert rows[0]["adx"] == 30.4
    assert rows[0]["action"] == "atr_trend"
    assert rows[0]["source"] == "live"


def test_later_cycle_in_the_same_candle_replaces_the_row(store):
    """Cycles run every few minutes but a candle spans hours."""
    engine = _engine(store)
    engine._log_regime_detected(
        RegimeResult(regime="GRAY", score=2, adx_value=21.0, rsi_value=55.0),
        None,
        "pause",
    )
    engine._log_regime_detected(
        RegimeResult(regime="LATERAL", score=4, adx_value=15.0, rsi_value=50.0),
        None,
        "grid",
    )

    rows = store.list_regime("BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["regime"] == "LATERAL"
    assert rows[0]["action"] == "grid"


def test_disabled_detector_persists_nothing(store):
    engine = _engine(store, detector_enabled=False)
    engine._log_regime_detected(None, None, "atr_trend")
    assert store.list_regime("BTCUSDT") == []


def test_missing_candles_persist_nothing(store):
    engine = _engine(store, stock_data=pd.DataFrame())
    engine._log_regime_detected(
        RegimeResult(regime="TREND", score=1, adx_value=30.0, rsi_value=60.0),
        None,
        "atr_trend",
    )
    assert store.list_regime("BTCUSDT") == []


def test_store_failure_does_not_break_the_cycle():
    """Regime history feeds the dashboard; it must never abort trading."""

    class _Broken:
        def save_regime(self, *args, **kwargs):
            raise RuntimeError("disk full")

    engine = _engine(_Broken())
    engine._log_regime_detected(
        RegimeResult(regime="TREND", score=1, adx_value=30.0, rsi_value=60.0),
        None,
        "atr_trend",
    )


def test_resolve_action_breakout():
    regime = RegimeResult(regime="LATERAL", score=4, adx_value=15.0, rsi_value=50.0)
    breakout = BreakoutResult(confirmed=True, adx_value=28.0, volume_ratio=2.0)
    action = resolve_regime_action(
        regime,
        breakout,
        regime_detector=SimpleNamespace(enabled=True, action_in_lateral="grid"),
        grid_manager=None,
        breakout_detector=None,
        breakout_cooldown_candles=0,
    )
    assert action == "atr_trend_breakout"


def test_resolve_action_hold_cash_is_pause():
    regime = RegimeResult(
        regime="LATERAL",
        score=4,
        adx_value=15.0,
        rsi_value=50.0,
        support=100.0,
        resistance=110.0,
        channel_width_pct=3.0,
    )
    action = resolve_regime_action(
        regime,
        None,
        regime_detector=SimpleNamespace(enabled=True, action_in_lateral="hold_cash"),
        grid_manager=SimpleNamespace(enabled=True, channel_valid=lambda _r: True),
        breakout_detector=None,
        breakout_cooldown_candles=0,
    )
    assert action == "pause"
