import numpy as np
import pandas as pd


def _resolve_ohlc(data: pd.DataFrame):
    if "high_price" in data.columns:
        return data["high_price"], data["low_price"], data["close_price"]
    return data["high"], data["low"], data["close"]


def adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index (Wilder).
    Returns ADX series aligned with input index.
    """
    high, low, close = _resolve_ohlc(data)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=data.index).ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=data.index).ewm(alpha=alpha, adjust=False).mean() / atr

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx_values = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx_values
