"""Sinais vetorizados para backtest. Equivalentes as estrategias live (causais)."""
from __future__ import annotations

import pandas as pd

from indicators.atr import atr, compute_trailing_stop, compute_ut_position
from indicators.ema import ema


def _numeric_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    for col in ("close_price", "high_price", "low_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close_price", "high_price", "low_price"]).reset_index(
        drop=True
    )


def moving_average_signals(
    frame: pd.DataFrame, *, fast_window: int = 21, slow_window: int = 55, **_kwargs
) -> list:
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    fast = close.rolling(window=fast_window).mean()
    slow = close.rolling(window=slow_window).mean()
    out: list = [None] * len(frame)
    for i in range(len(frame)):
        if pd.isna(fast.iloc[i]) or pd.isna(slow.iloc[i]):
            continue
        if i + 1 < 2 * slow_window - 1:
            continue
        out[i] = bool(fast.iloc[i] > slow.iloc[i])
    return out


def atr_trend_signals(
    frame: pd.DataFrame,
    *,
    atr_period: int = 14,
    atr_multiplier: float = 2.5,
    trend_sma_period: int = 200,
    **_kwargs,
) -> list:
    df = _numeric_ohlc(frame)
    min_points = max(atr_period, trend_sma_period) + 5
    out: list = [None] * len(df)
    if len(df) < min_points:
        return out
    close = df["close_price"]
    atr_values = atr(df, window=atr_period)
    sma = close.rolling(window=trend_sma_period).mean()
    trailing_stop = compute_trailing_stop(close, atr_values, atr_multiplier)
    position = compute_ut_position(close, trailing_stop)
    for i in range(min_points - 1, len(df)):
        if position[i] == 0 or pd.isna(sma.iloc[i]):
            continue
        out[i] = bool(position[i] == 1 and close.iloc[i] > sma.iloc[i])
    return out


def ema_atr_signals(
    frame: pd.DataFrame,
    *,
    fast_span: int = 21,
    slow_span: int = 55,
    trend_ema_period: int = 200,
    atr_period: int = 14,
    atr_multiplier: float = 3.0,
    require_trend_ema: bool = True,
    **_kwargs,
) -> list:
    df = _numeric_ohlc(frame)
    min_points = max(fast_span, slow_span, trend_ema_period, atr_period) + 5
    out: list = [None] * len(df)
    if len(df) < min_points:
        return out
    close = df["close_price"]
    fast = ema(close, fast_span)
    slow = ema(close, slow_span)
    trend = ema(close, trend_ema_period)
    atr_values = atr(df, window=atr_period)
    trailing_stop = compute_trailing_stop(close, atr_values, atr_multiplier)
    for i in range(1, len(df)):
        if i + 1 < min_points:
            continue
        if (
            pd.isna(fast.iloc[i])
            or pd.isna(slow.iloc[i])
            or pd.isna(trend.iloc[i])
            or pd.isna(atr_values.iloc[i])
        ):
            continue
        last_fast = float(fast.iloc[i])
        prev_fast = float(fast.iloc[i - 1])
        last_slow = float(slow.iloc[i])
        prev_slow = float(slow.iloc[i - 1])
        last_close = float(close.iloc[i])
        prev_close = float(close.iloc[i - 1])
        last_trend = float(trend.iloc[i])
        last_stop = trailing_stop.iloc[i]
        prev_stop = trailing_stop.iloc[i - 1]
        last_stop_value = float(last_stop) if pd.notna(last_stop) else float("nan")
        prev_stop_value = float(prev_stop) if pd.notna(prev_stop) else float("nan")
        crossed_up = prev_fast <= prev_slow and last_fast > last_slow
        crossed_down = prev_fast >= prev_slow and last_fast < last_slow
        stop_cross_down = (
            pd.notna(prev_stop)
            and pd.notna(last_stop)
            and prev_close >= prev_stop_value
            and last_close < last_stop_value
        )
        above_trend = (not require_trend_ema) or last_close > last_trend
        above_stop = pd.isna(last_stop) or last_close > last_stop_value
        if crossed_up and above_trend and above_stop:
            out[i] = True
        elif crossed_down or stop_cross_down:
            out[i] = False
    return out


def signals_for(strategy_name: str, frame: pd.DataFrame, kwargs: dict) -> list | None:
    if strategy_name.startswith("ema_atr"):
        return ema_atr_signals(frame, **kwargs)
    if strategy_name.startswith("moving_average"):
        return moving_average_signals(frame, **kwargs)
    if strategy_name.startswith("atr_trend"):
        return atr_trend_signals(frame, **kwargs)
    return None


def last_bar_matches_live(
    frame: pd.DataFrame,
    *,
    builder,
    live_fn,
    kwargs: dict,
) -> bool:
    """Sanity: last precomputed signal equals live strategy on the same frame."""
    if len(frame) < 30:
        return True
    built = builder(frame, **kwargs)
    live = live_fn(frame, verbose=False, **kwargs)
    return built[-1] == live
