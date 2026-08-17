import pandas as pd
import numpy as np


def _resolve_ohlc(data: pd.DataFrame):
    if "high_price" in data.columns:
        return data["high_price"], data["low_price"], data["close_price"]
    return data["high"], data["low"], data["close"]


def atr(data: pd.DataFrame, window=14):
    """
    Calcula o Average True Range (ATR) de um DataFrame OHLC.

    Aceita colunas padrão do bot (high_price, low_price, close_price)
    ou nomes genéricos (high, low, close).
    """
    high, low, close = _resolve_ohlc(data)

    tr1 = high - low
    tr2 = np.abs(high - close.shift(1))
    tr3 = np.abs(low - close.shift(1))

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=window).mean()


def compute_trailing_stop(close: pd.Series, atr_values: pd.Series, multiplier: float) -> pd.Series:
    """Calcula trailing stop estilo UT Bot a partir de close e ATR."""
    trailing_stop = pd.Series(np.nan, index=close.index)

    for i in range(1, len(close)):
        prev_stop = trailing_stop.iloc[i - 1]
        if pd.isna(prev_stop):
            prev_stop = close.iloc[i - 1]

        curr_close = close.iloc[i]
        prev_close = close.iloc[i - 1]
        curr_atr = atr_values.iloc[i]

        if pd.isna(curr_atr):
            trailing_stop.iloc[i] = prev_stop
            continue

        if curr_close > prev_stop and prev_close > prev_stop:
            trailing_stop.iloc[i] = max(prev_stop, curr_close - multiplier * curr_atr)
        elif curr_close < prev_stop and prev_close < prev_stop:
            trailing_stop.iloc[i] = min(prev_stop, curr_close + multiplier * curr_atr)
        elif curr_close > prev_stop:
            trailing_stop.iloc[i] = curr_close - multiplier * curr_atr
        else:
            trailing_stop.iloc[i] = curr_close + multiplier * curr_atr

    return trailing_stop


def compute_ut_position(close: pd.Series, trailing_stop: pd.Series) -> np.ndarray:
    """
    Retorna array de posição: 1=long, -1=short, 0=neutro (sem sinal ainda).
    """
    pos = np.zeros(len(close))

    for i in range(1, len(close)):
        if pd.isna(trailing_stop.iloc[i - 1]) or pd.isna(trailing_stop.iloc[i]):
            pos[i] = pos[i - 1]
            continue

        prev_close = close.iloc[i - 1]
        curr_close = close.iloc[i]
        prev_stop = trailing_stop.iloc[i - 1]
        curr_stop = trailing_stop.iloc[i]

        if prev_close < prev_stop and curr_close > curr_stop:
            pos[i] = 1
        elif prev_close > prev_stop and curr_close < curr_stop:
            pos[i] = -1
        else:
            pos[i] = pos[i - 1]

    return pos
