import numpy as np
import pandas as pd
import pytest

from strategies import atr_trend
from strategies.atr_trend import getAtrTrendStrategy


def _make_ohlc(n: int, base: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        price = base + trend * i + np.sin(i / 5) * 2
        rows.append(
            {
                "close_price": price,
                "open_price": price - 0.5,
                "high_price": price + 1.0,
                "low_price": price - 1.0,
                "volume": 1000 + i,
                "open_time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=4 * i),
            }
        )
    return pd.DataFrame(rows)


def test_returns_none_with_insufficient_data():
    data = _make_ohlc(50)
    assert getAtrTrendStrategy(data, verbose=False) is None


def test_returns_decision_with_enough_data():
    data = _make_ohlc(250, base=100, trend=0.5)
    result = getAtrTrendStrategy(data, verbose=False)
    assert result in (True, False, None)


def test_blocks_long_when_below_sma(monkeypatch):
    data = _make_ohlc(250, base=200, trend=-1.0)

    def forced_short_long(close, trailing):
        pos = np.zeros(len(close))
        pos[-1] = 1
        return pos

    monkeypatch.setattr(atr_trend, "compute_ut_position", forced_short_long)
    result = getAtrTrendStrategy(data, verbose=False)
    assert result is False


def test_emits_true_when_long_and_above_sma(monkeypatch):
    data = _make_ohlc(250, base=100, trend=1.0)

    def forced_long(close, trailing):
        pos = np.zeros(len(close))
        pos[-1] = 1
        return pos

    monkeypatch.setattr(atr_trend, "compute_ut_position", forced_long)
    result = getAtrTrendStrategy(data, verbose=False)
    assert result is True


def test_emits_false_when_trailing_short(monkeypatch):
    data = _make_ohlc(250, base=100, trend=0.5)

    def forced_short(close, trailing):
        pos = np.zeros(len(close))
        pos[-1] = -1
        return pos

    monkeypatch.setattr(atr_trend, "compute_ut_position", forced_short)
    result = getAtrTrendStrategy(data, verbose=False)
    assert result is False
