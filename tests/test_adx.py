import numpy as np
import pandas as pd
import pytest

from indicators.adx import adx


def _ohlc_from_close(closes):
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "close_price": c,
                "open_price": c - 0.5,
                "high_price": c + 1.0,
                "low_price": c - 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_adx_returns_series():
    df = _ohlc_from_close([100 + i * 0.1 for i in range(50)])
    result = adx(df, period=14)
    assert len(result) == len(df)
    assert not pd.isna(result.iloc[-1])


def test_adx_low_on_flat_market():
    noise = [100 + np.sin(i / 3) * 0.5 for i in range(80)]
    df = _ohlc_from_close(noise)
    result = adx(df, period=14)
    assert float(result.iloc[-1]) < 30


def test_adx_rises_on_trend():
    trend = [100 + i * 2 for i in range(80)]
    df = _ohlc_from_close(trend)
    result = adx(df, period=14)
    assert float(result.iloc[-1]) > 25
