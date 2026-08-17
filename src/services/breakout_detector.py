from dataclasses import dataclass, field

import pandas as pd

from indicators.adx import adx


@dataclass
class BreakoutResult:
    confirmed: bool
    adx_value: float = 0.0
    adx_rising: bool = False
    price: float = 0.0
    volume_ratio: float = 0.0
    signals: dict = field(default_factory=dict)


class BreakoutDetector:
    def __init__(
        self,
        enabled: bool = True,
        adx_period: int = 14,
        adx_min: float = 25.0,
        adx_rising_bars: int = 2,
        volume_multiplier: float = 1.5,
        volume_sma_period: int = 20,
        require_bullish_candle: bool = True,
        cooldown_candles: int = 3,
        reentry_adx_max: float = 22.0,
    ):
        self.enabled = enabled
        self.adx_period = adx_period
        self.adx_min = adx_min
        self.adx_rising_bars = adx_rising_bars
        self.volume_multiplier = volume_multiplier
        self.volume_sma_period = volume_sma_period
        self.require_bullish_candle = require_bullish_candle
        self.cooldown_candles = cooldown_candles
        self.reentry_adx_max = reentry_adx_max

    def evaluate(
        self,
        stock_data: pd.DataFrame,
        breakout_price: float,
    ) -> BreakoutResult:
        if not self.enabled or breakout_price <= 0:
            return BreakoutResult(confirmed=False)

        min_points = max(self.adx_period, self.volume_sma_period) + self.adx_rising_bars + 2
        if stock_data is None or len(stock_data) < min_points:
            return BreakoutResult(confirmed=False, signals={"insufficient_data": True})

        df = stock_data.copy()
        for col in ("close_price", "open_price", "high_price", "low_price", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(
            subset=["close_price", "open_price", "high_price", "low_price", "volume"],
            inplace=True,
        )
        if len(df) < min_points:
            return BreakoutResult(confirmed=False, signals={"insufficient_data": True})

        adx_series = adx(df, period=self.adx_period)
        adx_value = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0
        adx_rising = self._adx_rising(adx_series)

        close = float(df["close_price"].iloc[-1])
        open_price = float(df["open_price"].iloc[-1])
        volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].rolling(self.volume_sma_period).mean().iloc[-1])
        volume_ratio = (volume / avg_volume) if avg_volume > 0 else 0.0

        price_break = close > breakout_price
        volume_ok = volume_ratio >= self.volume_multiplier
        adx_ok = adx_value >= self.adx_min and adx_rising
        bullish = (close > open_price) if self.require_bullish_candle else True

        signals = {
            "price_break": price_break,
            "volume_ok": volume_ok,
            "adx_ok": adx_ok,
            "bullish_candle": bullish,
        }
        confirmed = all(signals.values())

        return BreakoutResult(
            confirmed=confirmed,
            adx_value=adx_value,
            adx_rising=adx_rising,
            price=close,
            volume_ratio=volume_ratio,
            signals=signals,
        )

    def can_reenter_grid(self, adx_value: float, cooldown_remaining: int) -> bool:
        if cooldown_remaining > 0:
            return False
        return adx_value < self.reentry_adx_max

    def _adx_rising(self, adx_series: pd.Series) -> bool:
        if len(adx_series) < self.adx_rising_bars + 1:
            return False
        recent = adx_series.iloc[-(self.adx_rising_bars + 1) :]
        if recent.isna().any():
            return False
        start = float(recent.iloc[0])
        end = float(recent.iloc[-1])
        if end < self.adx_min:
            return False
        if end > start:
            return True
        return end >= self.adx_min and start >= self.adx_min * 0.9
