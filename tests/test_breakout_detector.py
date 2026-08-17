import numpy as np
import pandas as pd
import pytest

from services.breakout_detector import BreakoutDetector


def _make_breakout_data(
    n: int = 80,
    start: float = 65000,
    step: float = 300,
    volume: float = 3000,
) -> pd.DataFrame:
    rows = []
    for i in range(n):
        price = start + step * i
        rows.append(
            {
                "close_price": price,
                "open_price": price - 100,
                "high_price": price + 200,
                "low_price": price - 200,
                "volume": volume if i < n - 1 else volume * 2,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def detector():
    return BreakoutDetector(
        enabled=True,
        adx_min=20,
        adx_rising_bars=2,
        volume_multiplier=1.5,
        require_bullish_candle=True,
    )


def test_breakout_confirmed_on_strong_trend(detector):
    data = _make_breakout_data()
    result = detector.evaluate(data, breakout_price=67000)
    assert result.confirmed is True
    assert result.signals["price_break"] is True
    assert result.signals["volume_ok"] is True


def test_breakout_not_confirmed_below_price(detector):
    data = _make_breakout_data(start=60000, step=50, volume=3000)
    result = detector.evaluate(data, breakout_price=67000)
    assert result.confirmed is False
    assert result.signals["price_break"] is False


def test_can_reenter_grid_respects_cooldown(detector):
    assert detector.can_reenter_grid(adx_value=18, cooldown_remaining=2) is False
    assert detector.can_reenter_grid(adx_value=18, cooldown_remaining=0) is True
    assert detector.can_reenter_grid(adx_value=30, cooldown_remaining=0) is False
