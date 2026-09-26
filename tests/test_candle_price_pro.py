import numpy as np
import pandas as pd

from backtest.candle_patterns import bullish_engulfing, hammer, morning_star
from backtest.candle_price_pro import (
    _Position,
    _step_position,
    entry_allowed,
    fixed_target,
    pattern_at,
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


def test_fixed_target_is_two_r_above_the_entry():
    assert fixed_target(100, 98) == 104
    assert reward_risk(100, 98, fixed_target(100, 98)) == 2
    assert should_enter(pattern=True, score=14, entry=100, stop=98, resistance=104)
    assert fixed_target(100, 100) is None


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


def _bar(open_price, high, low, close):
    return pd.Series(
        {
            "open_price": open_price,
            "high_price": high,
            "low_price": low,
            "close_price": close,
            "open_time": pd.Timestamp("2026-06-01 10:00", tz="America/Sao_Paulo"),
        }
    )


def _position():
    return _Position(
        qty=10,
        original_qty=10,
        entry=100,
        stop=98,
        initial_stop=98,
        risk=2,
        tp1=110,
        tp2=120,
        tp1_done=False,
        tp2_done=False,
        highest=100,
        atr=2,
        score=12,
        pattern="hammer",
        entry_time=pd.Timestamp("2026-06-01 09:00", tz="America/Sao_Paulo"),
        realized=0.0,
        fees=0.0,
        filled_at_open=True,
    )


def test_morning_star_wins_when_the_third_candle_also_engulfs():
    rows = []
    start = pd.Timestamp("2026-01-01", tz="America/Sao_Paulo")
    for i in range(10):
        rows.append(
            {
                "open_price": 10.0,
                "high_price": 10.2,
                "low_price": 9.8,
                "close_price": 10.05,
                "open_time": start + pd.Timedelta(hours=i),
            }
        )
    rows.extend(
        [
            {"open_price": 10, "high_price": 10, "low_price": 8, "close_price": 8, "open_time": start + pd.Timedelta(hours=10)},
            {"open_price": 8.2, "high_price": 8.3, "low_price": 7.9, "close_price": 8.0, "open_time": start + pd.Timedelta(hours=11)},
            {"open_price": 7.9, "high_price": 9.5, "low_price": 7.8, "close_price": 9.4, "open_time": start + pd.Timedelta(hours=12)},
        ]
    )
    frame = pd.DataFrame(rows)
    assert bullish_engulfing(8.2, 8.0, 7.9, 9.4)
    assert pattern_at(frame, 12) == "morning_star"


def test_gap_through_the_stop_does_not_take_profit():
    position, closed, sold = _step_position(
        _position(),
        _bar(97, 115, 90, 95),
        2,
        fee_rate=0.0,
        slippage=0.0,
    )
    assert position is None
    assert closed["reason"] == "stop"
    assert closed["exit"] == "stop"
    assert closed["pnl"] == -30
    assert closed["sl_pnl"] == -30
    assert closed["tp_pnl"] == 0
    assert sold == 970


def test_partial_take_profit_returns_cash_before_the_position_closes():
    position, closed, sold = _step_position(
        _position(),
        _bar(101, 115, 101, 112),
        2,
        fee_rate=0.0,
        slippage=0.0,
    )
    assert closed is None
    assert position is not None
    assert position.qty == 7
    assert position.tp_pnl == 30
    assert sold == 110 * 3
    cash = 1000 - 100 * 10
    cash += sold
    assert cash == 330
