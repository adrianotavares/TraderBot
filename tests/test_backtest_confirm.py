import numpy as np
import pandas as pd
import pytest

from backtest.confirm import (
    buy_and_hold_metrics,
    confirmation_score,
    run_engine_replay,
    run_strategy_window,
    slice_windows,
)
from backtest.signals import (
    atr_trend_signals,
    ema_atr_signals,
    last_bar_matches_live,
    moving_average_signals,
)
from strategies.atr_trend import getAtrTrendStrategy
from strategies.ema_atr import getEmaAtrStrategy
from strategies.moving_average import getMovingAverageTradeStrategy


def _ohlc(prices) -> pd.DataFrame:
    rows = []
    for i, price in enumerate(prices):
        rows.append(
            {
                "close_price": float(price),
                "open_price": float(price) - 0.2,
                "high_price": float(price) + 0.5,
                "low_price": float(price) - 0.5,
                "volume": 1000,
                "open_time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=4 * i),
            }
        )
    return pd.DataFrame(rows)


def test_slice_windows_splits_prior_and_last():
    frame = _ohlc(np.linspace(100, 200, 2160))
    windows = slice_windows(frame)
    assert len(windows["last_180"]) == 1080
    assert len(windows["last_360"]) == 2160
    assert len(windows["prior_180"]) == 1080
    assert windows["prior_180"]["close_price"].iloc[0] == frame["close_price"].iloc[0]
    assert windows["last_180"]["close_price"].iloc[-1] == frame["close_price"].iloc[-1]


def test_buy_and_hold_is_price_change():
    frame = _ohlc([100, 110, 105, 120])
    result = buy_and_hold_metrics(frame)
    assert result["trades"] == 1
    assert result["profit_percentage"] == pytest.approx(20.0)


def test_risk_overlay_exits_on_stop_while_strategy_holds():
    prices = [100] * 5 + [97]
    frame = _ohlc(prices)
    calls = {"n": 0}

    def strategy(stock_data, verbose=False, **kwargs):
        calls["n"] += 1
        return True if calls["n"] == 1 else None

    result = run_strategy_window(
        frame,
        strategy_name="hold_after_buy",
        strategy_fn=strategy,
        strategy_kwargs={},
        stop_loss_pct=2.0,
        take_profit_pct=7.0,
    )
    assert result["closed_trades"]
    assert result["closed_trades"][0]["reason"] == "stop_loss"


def test_run_strategy_window_hold_and_ma():
    frame = _ohlc(list(np.linspace(50, 150, 80)))
    hold = run_strategy_window(
        frame,
        strategy_name="buy_and_hold",
        strategy_fn=None,
        strategy_kwargs={},
    )
    assert hold["profit_percentage"] > 100
    ma = run_strategy_window(
        frame,
        strategy_name="moving_average_21_55",
        strategy_fn=__import__(
            "strategies.moving_average", fromlist=["getMovingAverageTradeStrategy"]
        ).getMovingAverageTradeStrategy,
        strategy_kwargs={"fast_window": 5, "slow_window": 10},
    )
    assert ma["trades"] >= 1


def test_precomputed_signals_match_live_last_bar():
    frame = _ohlc(list(np.linspace(80, 160, 260)))
    assert last_bar_matches_live(
        frame,
        builder=moving_average_signals,
        live_fn=getMovingAverageTradeStrategy,
        kwargs={"fast_window": 7, "slow_window": 25},
    )
    assert last_bar_matches_live(
        frame,
        builder=ema_atr_signals,
        live_fn=getEmaAtrStrategy,
        kwargs={
            "fast_span": 21,
            "slow_span": 55,
            "trend_ema_period": 200,
            "atr_period": 14,
            "atr_multiplier": 3.0,
            "require_trend_ema": True,
        },
    )
    assert last_bar_matches_live(
        frame,
        builder=atr_trend_signals,
        live_fn=getAtrTrendStrategy,
        kwargs={"atr_period": 14, "atr_multiplier": 2.5, "trend_sma_period": 200},
    )


def test_engine_replay_runs_without_orders_on_hold():
    frame = _ohlc(list(range(80, 100)))
    replay = run_engine_replay(
        frame,
        strategy_fn=lambda stock_data, verbose=False, **kwargs: None,
        strategy_kwargs={},
        warmup=5,
    )
    assert replay["strategy"] == "ema_atr_replay"
    assert replay["trades"] == 0
    assert replay["in_position"] is False


def test_confirmation_score_requires_majority_and_walk():
    rows = []
    for asset in ("BTCUSDT", "ETHUSDT"):
        rows.extend(
            [
                {
                    "operation_code": asset,
                    "window": "last_180",
                    "strategy": "ema_atr",
                    "risk_overlay": False,
                    "profit_percentage": 10,
                    "max_drawdown_pct": 5,
                },
                {
                    "operation_code": asset,
                    "window": "last_180",
                    "strategy": "moving_average_21_55",
                    "risk_overlay": False,
                    "profit_percentage": 8,
                    "max_drawdown_pct": 7,
                },
                {
                    "operation_code": asset,
                    "window": "last_180",
                    "strategy": "buy_and_hold",
                    "risk_overlay": False,
                    "profit_percentage": 4,
                    "max_drawdown_pct": 12,
                },
                {
                    "operation_code": asset,
                    "window": "last_180",
                    "strategy": "atr_trend",
                    "risk_overlay": False,
                    "profit_percentage": -9,
                    "max_drawdown_pct": 21,
                },
            ]
        )
    rows.append(
        {
            "operation_code": "BTCUSDT",
            "window": "prior_180",
            "strategy": "ema_atr",
            "risk_overlay": False,
            "profit_percentage": 3,
            "max_drawdown_pct": 6,
        }
    )
    rows.append(
        {
            "operation_code": "BTCUSDT",
            "window": "last_180",
            "strategy": "ema_atr",
            "risk_overlay": True,
            "profit_percentage": 5,
            "max_drawdown_pct": 8,
        }
    )
    score = confirmation_score(rows)
    assert score["ema_beats_ma"] == 2
    assert score["walk_forward_both_positive"] is True
    assert score["overlay_dd_below_atr"] is True
    assert score["confirmed"] is True
