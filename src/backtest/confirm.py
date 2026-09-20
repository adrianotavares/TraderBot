from __future__ import annotations

import contextlib
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

from backtest.replay import build_replay_engine
from backtest.signals import signals_for
from persistence.state_store import StateStore
from strategies.atr_trend import getAtrTrendStrategy
from strategies.moving_average import getMovingAverageTradeStrategy

try:
    from strategies.ema_atr import getEmaAtrStrategy
except ImportError:  # estrategia ainda nao esta nesta branch
    getEmaAtrStrategy = None

_SRC_TESTS = Path(__file__).resolve().parents[1] / "tests"
if str(_SRC_TESTS) not in sys.path:
    sys.path.insert(0, str(_SRC_TESTS))
from backtestRunner import backtestRunner, _max_drawdown  # noqa: E402

CANDLES_4H_PER_DAY = 6
LAST_180 = 180 * CANDLES_4H_PER_DAY
LAST_360 = 360 * CANDLES_4H_PER_DAY

EMA_ATR_ARGS = {
    "fast_span": 21,
    "slow_span": 55,
    "trend_ema_period": 200,
    "atr_period": 14,
    "atr_multiplier": 3.0,
    "require_trend_ema": True,
}
ATR_TREND_ARGS = {
    "atr_period": 14,
    "atr_multiplier": 2.5,
    "trend_sma_period": 200,
}
MA_ARGS = {"fast_window": 21, "slow_window": 55}

STRATEGIES = (
    ("moving_average_21_55", getMovingAverageTradeStrategy, MA_ARGS),
    ("atr_trend", getAtrTrendStrategy, ATR_TREND_ARGS),
)
if getEmaAtrStrategy is not None:
    STRATEGIES = (("ema_atr", getEmaAtrStrategy, EMA_ATR_ARGS),) + STRATEGIES


def _isolate_replay_logs() -> None:
    """Keep engine replay from appending fake cycles to live src/logs."""
    import modules.logging_setup as logging_setup

    log_dir = tempfile.mkdtemp(prefix="confirm-logs-")
    os.environ["TRADERBOT_LOG_DIR"] = log_dir
    logging_setup.LOG_DIR = log_dir
    logging_setup.LOG_FILE = os.path.join(log_dir, "trading_bot.log")
    logging_setup.LOG_JSON_FILE = os.path.join(log_dir, "trading_bot.json.log")
    root = logging.getLogger()
    for handler in list(root.handlers):
        filename = getattr(handler, "baseFilename", "")
        if filename and "logs" in str(filename):
            root.removeHandler(handler)
            handler.close()
    logging_setup._configured = False
    logging_setup.setup_logging(level=logging.WARNING)


def slice_windows(frame: pd.DataFrame) -> dict[str, pd.DataFrame | None]:
    n = len(frame)
    last_180 = frame.iloc[-LAST_180:].copy() if n >= LAST_180 else frame.copy()
    last_360 = frame.iloc[-LAST_360:].copy() if n >= LAST_360 else frame.copy()
    prior_180 = (
        frame.iloc[-LAST_360:-LAST_180].copy() if n >= LAST_360 else None
    )
    return {
        "last_180": last_180.reset_index(drop=True),
        "last_360": last_360.reset_index(drop=True),
        "prior_180": prior_180.reset_index(drop=True) if prior_180 is not None else None,
    }


def buy_and_hold_metrics(frame: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
    close = pd.to_numeric(frame["close_price"], errors="coerce").dropna()
    if len(close) < 2:
        return {
            "profit_percentage": 0.0,
            "trades": 0,
            "max_drawdown_pct": 0.0,
            "sharpe_approx": 0.0,
            "total_fees": 0.0,
            "closed_trades": [],
            "win_rate": 0.0,
            "best_trade_pct": 0.0,
            "worst_trade_pct": 0.0,
            "top_win_share_pct": 0.0,
            "final_balance": initial_balance,
        }
    first = float(close.iloc[0])
    last = float(close.iloc[-1])
    equity = (close / first * initial_balance).tolist()
    profit_percentage = (last / first - 1.0) * 100
    return {
        "profit_percentage": profit_percentage,
        "trades": 1,
        "max_drawdown_pct": _max_drawdown(equity),
        "sharpe_approx": 0.0,
        "total_fees": 0.0,
        "closed_trades": [
            {
                "entry_index": 0,
                "exit_index": len(close) - 1,
                "bars": len(close) - 1,
                "entry_price": first,
                "exit_price": last,
                "return_pct": profit_percentage,
                "reason": "hold",
            }
        ],
        "win_rate": 100.0 if profit_percentage > 0 else 0.0,
        "best_trade_pct": profit_percentage,
        "worst_trade_pct": profit_percentage,
        "top_win_share_pct": 100.0 if profit_percentage > 0 else 0.0,
        "final_balance": equity[-1],
    }


def run_strategy_window(
    frame: pd.DataFrame,
    *,
    strategy_name: str,
    strategy_fn,
    strategy_kwargs: dict,
    initial_balance: float = 1000.0,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    signals=None,
) -> dict:
    if strategy_name == "buy_and_hold":
        result = buy_and_hold_metrics(frame, initial_balance)
    else:
        if signals is None:
            signals = signals_for(strategy_name, frame, strategy_kwargs)
        result = backtestRunner(
            stock_data=frame,
            strategy_function=strategy_fn,
            periods=len(frame),
            initial_balance=initial_balance,
            verbose=False,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            signals=signals,
            **strategy_kwargs,
        )
    result = dict(result)
    result["strategy"] = strategy_name
    return result


def run_engine_replay(
    frame: pd.DataFrame,
    *,
    strategy_fn,
    strategy_kwargs: dict,
    quote_balance: float = 1000.0,
    stop_loss_pct: float = 2.0,
    take_profit_pct: float = 7.0,
    warmup: int = 210,
) -> dict:
    _isolate_replay_logs()
    store = StateStore(Path(tempfile.mkdtemp()) / "confirm-replay.db")

    def main_strategy(stock_data, verbose=False, **_kwargs):
        return strategy_fn(stock_data, verbose=False, **strategy_kwargs)

    bot, engine = build_replay_engine(
        frame,
        store=store,
        quote_balance=quote_balance,
        base_balance=0.0,
        main_strategy=main_strategy,
        fallback_activated=False,
        regime_enabled=True,
        stop_loss_pct=stop_loss_pct,
        trailing_stop_loss=True,
        max_daily_loss_usdt=10_000.0,
    )
    market = engine.market_data
    start = min(max(warmup, 2), max(len(frame) - 1, 2))
    with contextlib.redirect_stdout(io.StringIO()):
        engine.bootstrap()
        for index in range(start, len(frame)):
            market.end_index = index + 1
            engine.execute()

    last_close = float(frame["close_price"].iloc[-1])
    equity = bot.quote_balance + bot.base_balance * last_close
    return_pct = (equity / quote_balance - 1.0) * 100
    sells = [order for order in bot.broker.orders if order.get("side") == "SELL"]
    return {
        "strategy": "ema_atr_replay",
        "profit_percentage": return_pct,
        "trades": len(bot.broker.orders),
        "sells": len(sells),
        "final_balance": equity,
        "in_position": bool(bot.actual_trade_position),
    }


def compare_row(left: dict, right: dict, metric: str = "profit_percentage") -> str:
    if left[metric] > right[metric]:
        return "better"
    if left[metric] < right[metric]:
        return "worse"
    return "tie"


def confirmation_score(rows: list[dict], walk_symbol: str = "BTCUSDT") -> dict:
    last_180 = [
        row
        for row in rows
        if row.get("window") == "last_180" and not row.get("risk_overlay")
    ]
    assets = sorted({row["operation_code"] for row in last_180})
    ema_beats_ma = 0
    ema_beats_hold = 0
    ema_dd_better_than_atr = 0
    for asset in assets:
        by_name = {
            row["strategy"]: row
            for row in last_180
            if row["operation_code"] == asset
        }
        ema = by_name.get("ema_atr")
        ma = by_name.get("moving_average_21_55")
        hold = by_name.get("buy_and_hold")
        atr = by_name.get("atr_trend")
        if ema and ma and ema["profit_percentage"] >= ma["profit_percentage"]:
            ema_beats_ma += 1
        if ema and hold and ema["profit_percentage"] >= hold["profit_percentage"]:
            ema_beats_hold += 1
        if (
            ema
            and atr
            and ema["max_drawdown_pct"] <= atr["max_drawdown_pct"]
        ):
            ema_dd_better_than_atr += 1

    walk = [
        row
        for row in rows
        if row.get("operation_code") == walk_symbol
        and row.get("strategy") == "ema_atr"
        and not row.get("risk_overlay")
    ]
    prior = next((row for row in walk if row.get("window") == "prior_180"), None)
    last = next((row for row in walk if row.get("window") == "last_180"), None)
    walk_ok = bool(
        prior
        and last
        and prior["profit_percentage"] > 0
        and last["profit_percentage"] > 0
    )

    overlay = next(
        (
            row
            for row in rows
            if row.get("strategy") == "ema_atr"
            and row.get("risk_overlay")
            and row.get("window") == "last_180"
            and row.get("operation_code") == walk_symbol
        ),
        None,
    )
    overlay_ok = bool(overlay and overlay["max_drawdown_pct"] < 21.0)

    return {
        "assets": len(assets),
        "ema_beats_ma": ema_beats_ma,
        "ema_beats_hold": ema_beats_hold,
        "ema_dd_better_than_atr": ema_dd_better_than_atr,
        "walk_forward_both_positive": walk_ok,
        "overlay_dd_below_atr": overlay_ok,
        "confirmed": (
            len(assets) > 0
            and ema_beats_ma >= max(1, (len(assets) + 1) // 2)
            and walk_ok
            and overlay_ok
        ),
    }
