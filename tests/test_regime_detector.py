import numpy as np
import pandas as pd
import pytest

from services.regime_detector import RegimeDetector


def _make_range_data(n: int = 80, base: float = 100.0, amplitude: float = 2.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        price = base + amplitude * np.sin(i / 4)
        rows.append(
            {
                "close_price": price,
                "open_price": price - 0.2,
                "high_price": price + 0.5,
                "low_price": price - 0.5,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def _make_trend_data(n: int = 80, start: float = 100.0, step: float = 2.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        price = start + step * i
        rows.append(
            {
                "close_price": price,
                "open_price": price - 0.5,
                "high_price": price + 1.0,
                "low_price": price - 0.5,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def detector():
    return RegimeDetector(
        enabled=True,
        min_candles=60,
        min_lateral_signals=3,
        range_lookback=60,
        min_touches=3,
    )


def test_insufficient_data_returns_gray(detector):
    data = _make_range_data(30)
    result = detector.evaluate(data)
    assert result.regime == "GRAY"
    assert result.signals.get("insufficient_data") is True


def test_lateral_market_high_score(detector):
    data = _make_range_data(80)
    result = detector.evaluate(data)
    assert result.score >= 2
    assert result.regime in ("LATERAL", "GRAY")


def test_trending_market_returns_trend(detector):
    data = _make_trend_data(80, step=3.0)
    result = detector.evaluate(data)
    assert result.regime == "TREND"
    assert result.adx_value > detector.adx_lateral_threshold


def test_disabled_detector_returns_trend():
    detector = RegimeDetector(enabled=False)
    data = _make_range_data(80)
    result = detector.evaluate(data)
    assert result.regime == "TREND"


def test_signals_dict_keys(detector):
    data = _make_range_data(80)
    result = detector.evaluate(data)
    assert set(result.signals.keys()) == {
        "adx_low",
        "rsi_neutral",
        "ema_compressed",
        "range_bound",
    }
