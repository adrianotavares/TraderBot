from types import SimpleNamespace

from services.breakout_detector import BreakoutResult
from services.regime_detector import RegimeResult
from services.regime_router import resolve_regime_action


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
