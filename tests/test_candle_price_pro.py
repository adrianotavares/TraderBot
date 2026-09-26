import numpy as np
import pandas as pd

from backtest.candle_patterns import bullish_engulfing, hammer, morning_star
from backtest.candle_price_pro import (
    entry_allowed,
    reward_risk,
    score_points,
    should_enter,
    simulate,
)


def test_bullish_engulfing_covers_the_previous_body():
    assert bullish_engulfing(10, 9, 8.9, 10.2)
    assert not bullish_engulfing(10, 9, 8.9, 9.5)
    assert not bullish_engulfing(9, 10, 8.9, 10.2)


def test_hammer_needs_a_long_lower_wick_and_a_short_upper_wick():
    assert hammer(9.8, 10.1, 9.0, 10.0)
    assert not hammer(9.8, 11.0, 9.0, 10.0)
    assert not hammer(9.2, 10.0, 9.0, 10.0)


def test_morning_star_closes_above_the_first_body_midpoint():
    assert morning_star(10, 8, 7.9, 8.1, 8.2, 9.4, avg_body=1.0)
    assert not morning_star(10, 8, 7.9, 8.1, 8.2, 8.5, avg_body=1.0)
    assert not morning_star(10, 8, 7.9, 8.1, 8.2, 9.4, avg_body=3.0)


def test_score_without_the_candle_does_not_enter():
    flags = dict(
        h4=True,
        h1=True,
        ema=True,
        pullback=True,
        candle=False,
        volume=True,
        macd=True,
        rsi=True,
        adx=True,
        breakout=True,
    )
    score = score_points(**flags)
    assert score == 12
    assert score >= 10
    assert not entry_allowed(pattern=False, score=score, reward_risk_value=3)
    flags["candle"] = True
    with_candle = score_points(**flags)
    assert with_candle == 14
    assert entry_allowed(pattern=True, score=with_candle, reward_risk_value=3)


def test_reward_risk_below_two_does_not_enter():
    assert reward_risk(100, 98, 102) == 1
    assert not should_enter(
        pattern=True, score=14, entry=100, stop=98, resistance=102
    )
    assert reward_risk(100, 98, 106) == 3
    assert should_enter(pattern=True, score=14, entry=100, stop=98, resistance=106)
    assert not should_enter(
        pattern=True, score=14, entry=100, stop=98, resistance=None
    )


def test_flat_market_has_no_reentry_trades():
    start = pd.Timestamp("2026-01-01", tz="America/Sao_Paulo")

    def frame(step: pd.Timedelta, count: int) -> pd.DataFrame:
        rows = []
        for i in range(count):
            price = 100 + np.sin(i / 7)
            rows.append(
                {
                    "open_time": start + step * i,
                    "open_price": price,
                    "high_price": price + 0.2,
                    "low_price": price - 0.2,
                    "close_price": price,
                    "volume": 1000,
                }
            )
        return pd.DataFrame(rows)

    result = simulate(
        frame(pd.Timedelta(minutes=15), 400),
        frame(pd.Timedelta(hours=1), 120),
        frame(pd.Timedelta(hours=4), 80),
        eval_start=start,
    )
    assert result["trades"] == 0
