from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from indicators.adx import adx
from indicators.ema import ema
from indicators.rsi import rsi


@dataclass
class RegimeResult:
    regime: Literal["LATERAL", "TREND", "GRAY"]
    score: int
    signals: dict = field(default_factory=dict)
    adx_value: float = 0.0
    rsi_value: float = 0.0
    support: float | None = None
    resistance: float | None = None
    channel_width_pct: float = 0.0


class RegimeDetector:
    def __init__(
        self,
        enabled: bool = True,
        adx_period: int = 14,
        adx_lateral_threshold: float = 20.0,
        adx_trend_threshold: float = 25.0,
        rsi_period: int = 14,
        rsi_low: float = 40.0,
        rsi_high: float = 60.0,
        ema_fast: int = 20,
        ema_slow: int = 50,
        ema_compression_pct: float = 0.5,
        range_lookback: int = 60,
        min_touches: int = 3,
        touch_tolerance_pct: float = 0.3,
        min_lateral_signals: int = 3,
        min_candles: int = 60,
        action_in_lateral: Literal["pause", "grid"] = "pause",
    ):
        self.enabled = enabled
        self.adx_period = adx_period
        self.adx_lateral_threshold = adx_lateral_threshold
        self.adx_trend_threshold = adx_trend_threshold
        self.rsi_period = rsi_period
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.ema_compression_pct = ema_compression_pct
        self.range_lookback = range_lookback
        self.min_touches = min_touches
        self.touch_tolerance_pct = touch_tolerance_pct
        self.min_lateral_signals = min_lateral_signals
        self.min_candles = min_candles
        self.action_in_lateral = action_in_lateral

    def evaluate(self, stock_data: pd.DataFrame) -> RegimeResult:
        if not self.enabled:
            return RegimeResult(regime="TREND", score=0, signals={})

        if stock_data is None or len(stock_data) < self.min_candles:
            return RegimeResult(
                regime="GRAY",
                score=0,
                signals={"insufficient_data": True},
            )

        df = stock_data.copy()
        for col in ("close_price", "high_price", "low_price"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["close_price", "high_price", "low_price"], inplace=True)

        if len(df) < self.min_candles:
            return RegimeResult(
                regime="GRAY",
                score=0,
                signals={"insufficient_data": True},
            )

        adx_series = adx(df, period=self.adx_period)
        adx_value = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0

        rsi_series = rsi(df["close_price"], self.rsi_period, last_only=False)
        rsi_value = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        channel = self._compute_channel(df)
        signals = {
            "adx_low": self._check_adx_low(adx_value),
            "rsi_neutral": self._check_rsi_neutral(rsi_value),
            "ema_compressed": self._check_ema_compressed(df),
            "range_bound": channel["range_bound"],
        }
        score = sum(1 for v in signals.values() if v)

        if adx_value > self.adx_trend_threshold and score <= 1:
            regime = "TREND"
        elif score >= self.min_lateral_signals:
            regime = "LATERAL"
        else:
            regime = "GRAY"

        return RegimeResult(
            regime=regime,
            score=score,
            signals=signals,
            adx_value=adx_value,
            rsi_value=rsi_value,
            support=channel["support"],
            resistance=channel["resistance"],
            channel_width_pct=channel["channel_width_pct"],
        )

    def _check_adx_low(self, adx_value: float) -> bool:
        return adx_value < self.adx_lateral_threshold

    def _check_rsi_neutral(self, rsi_value: float) -> bool:
        return self.rsi_low <= rsi_value <= self.rsi_high

    def _check_ema_compressed(self, df: pd.DataFrame) -> bool:
        close = df["close_price"]
        ema_fast = ema(close, self.ema_fast)
        ema_slow = ema(close, self.ema_slow)
        if pd.isna(ema_fast.iloc[-1]) or pd.isna(ema_slow.iloc[-1]):
            return False
        last_close = float(close.iloc[-1])
        if last_close == 0:
            return False
        spread_pct = abs(float(ema_fast.iloc[-1]) - float(ema_slow.iloc[-1])) / last_close * 100
        return spread_pct < self.ema_compression_pct

    def _compute_channel(self, df: pd.DataFrame) -> dict:
        window = df.tail(self.range_lookback)
        if len(window) < self.min_touches:
            return {
                "range_bound": False,
                "support": None,
                "resistance": None,
                "channel_width_pct": 0.0,
            }

        support = float(window["low_price"].min())
        resistance = float(window["high_price"].max())
        if support <= 0 or resistance <= support:
            return {
                "range_bound": False,
                "support": None,
                "resistance": None,
                "channel_width_pct": 0.0,
            }

        tol = self.touch_tolerance_pct / 100
        support_hits = 0
        resistance_hits = 0
        for _, row in window.iterrows():
            low = float(row["low_price"])
            high = float(row["high_price"])
            if low <= support * (1 + tol):
                support_hits += 1
            if high >= resistance * (1 - tol):
                resistance_hits += 1

        mid = (support + resistance) / 2
        channel_width_pct = ((resistance - support) / mid * 100) if mid > 0 else 0.0
        range_bound = (
            support_hits >= self.min_touches and resistance_hits >= self.min_touches
        )

        return {
            "range_bound": range_bound,
            "support": support if range_bound else None,
            "resistance": resistance if range_bound else None,
            "channel_width_pct": channel_width_pct if range_bound else 0.0,
        }
