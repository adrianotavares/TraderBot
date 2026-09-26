"""Simulador long-only da CANDLE-PRICE-PRO.

Não registra a estratégia no bot e não lê config/trading.yaml.
O candle de alta é trava: a soma de pontos não substitui o padrão.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.candle_patterns import bullish_engulfing, hammer, morning_star
from indicators.adx import adx
from indicators.atr import atr
from indicators.ema import ema
from indicators.rsi import rsi

FEE_RATE = 0.001
SLIPPAGE = 0.0005
SCORE_MIN = 10
MIN_REWARD_RISK = 2.0
RISK_PCT = 0.01
DAILY_LOSS_PCT = 0.02
ATR_STOP_MULT = 1.5
TRAIL_ATR_MULT = 2.0
SETUP_LIFE = pd.Timedelta(hours=4)

SCORE_WEIGHTS = {
    "h4": 2,
    "h1": 2,
    "ema": 1,
    "pullback": 1,
    "candle": 2,
    "volume": 1,
    "macd": 1,
    "rsi": 1,
    "adx": 1,
    "breakout": 2,
}


def score_points(**flags: bool) -> int:
    return sum(SCORE_WEIGHTS[name] for name, on in flags.items() if on)


def reward_risk(entry: float, stop: float, resistance: float | None) -> float | None:
    if resistance is None:
        return None
    risk = float(entry) - float(stop)
    room = float(resistance) - float(entry)
    if risk <= 0 or room <= 0:
        return None
    return room / risk


def entry_allowed(*, pattern: bool, score: int, reward_risk_value: float | None) -> bool:
    """Padrão, score e R:R são travas separadas. Uma soma alta não compra sozinha."""
    if not pattern or score < SCORE_MIN or reward_risk_value is None:
        return False
    return float(reward_risk_value) >= MIN_REWARD_RISK


def should_enter(
    *,
    pattern: bool,
    score: int,
    entry: float,
    stop: float,
    resistance: float | None,
) -> bool:
    return entry_allowed(
        pattern=pattern,
        score=score,
        reward_risk_value=reward_risk(entry, stop, resistance),
    )


def stop_price(entry: float, structure_low: float, atr_value: float) -> float | None:
    """O stop mais longe da entrada: o menor entre a estrutura e 1,5 ATR."""
    if atr_value <= 0 or structure_low <= 0:
        return None
    atr_stop = float(entry) - ATR_STOP_MULT * float(atr_value)
    stop = min(float(structure_low), atr_stop)
    if stop >= float(entry):
        return None
    return stop


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def macd_lines(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, signal)


def _swing_mask(series: pd.Series, *, kind: str, wing: int = 2) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.zeros(len(values), dtype=bool)
    for i in range(wing, len(values) - wing):
        left = values[i - wing : i]
        right = values[i + 1 : i + wing + 1]
        if kind == "high" and values[i] > left.max() and values[i] > right.max():
            out[i] = True
        elif kind == "low" and values[i] < left.min() and values[i] < right.min():
            out[i] = True
    return pd.Series(out, index=series.index)


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().reset_index(drop=True)
    for col in ("open_price", "high_price", "low_price", "close_price", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["open_time"] = pd.to_datetime(out["open_time"], utc=True).dt.tz_convert(
        "America/Sao_Paulo"
    )
    out = (
        out.dropna(subset=["open_price", "high_price", "low_price", "close_price", "volume"])
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    close = out["close_price"]
    out["ema20"] = ema(close, 20)
    out["ema50"] = ema(close, 50)
    out["ema200"] = ema(close, 200)
    out["rsi"] = rsi(close, 14, last_only=False)
    out["macd"], out["macd_signal"] = macd_lines(close)
    out["atr"] = atr(out, window=14)
    out["adx"] = adx(out, period=14)
    out["vol_sma"] = out["volume"].rolling(20).mean()
    out["swing_high"] = _swing_mask(out["high_price"], kind="high")
    out["swing_low"] = _swing_mask(out["low_price"], kind="low")
    return out


def pattern_at(frame: pd.DataFrame, index: int) -> str | None:
    if index < 1:
        return None
    row = frame.iloc[index]
    prev = frame.iloc[index - 1]
    if bullish_engulfing(
        prev["open_price"], prev["close_price"], row["open_price"], row["close_price"]
    ):
        return "engulfing"
    if hammer(row["open_price"], row["high_price"], row["low_price"], row["close_price"]):
        return "hammer"
    if index < 12:
        return None
    first = frame.iloc[index - 2]
    second = frame.iloc[index - 1]
    prior = [
        abs(float(frame["close_price"].iloc[j]) - float(frame["open_price"].iloc[j]))
        for j in range(index - 12, index - 2)
    ]
    avg_body = float(np.mean(prior)) if prior else 0.0
    if morning_star(
        first["open_price"],
        first["close_price"],
        second["open_price"],
        second["close_price"],
        row["open_price"],
        row["close_price"],
        avg_body,
    ):
        return "morning_star"
    return None


def _pattern_low(frame: pd.DataFrame, index: int, name: str) -> float:
    if name == "morning_star":
        window = frame.iloc[index - 2 : index + 1]
    elif name == "engulfing":
        window = frame.iloc[index - 1 : index + 1]
    else:
        window = frame.iloc[index : index + 1]
    return float(window["low_price"].min())


def _near(low: float, high: float, level: float, atr_value: float) -> bool:
    if not _finite(level) or not _finite(atr_value) or atr_value <= 0:
        return False
    tolerance = 0.25 * float(atr_value)
    return float(low) - tolerance <= float(level) <= float(high) + tolerance


def _last_swing_low(frame: pd.DataFrame, index: int) -> float | None:
    confirmed = index - 2
    if confirmed < 0:
        return None
    hits = frame.iloc[: confirmed + 1]
    hits = hits[hits["swing_low"]]
    if hits.empty:
        return None
    return float(hits["low_price"].iloc[-1])


def _nearest_resistance(frame: pd.DataFrame, index: int, price: float) -> float | None:
    confirmed = index - 2
    if confirmed < 0:
        return None
    hits = frame.iloc[: confirmed + 1]
    hits = hits[hits["swing_high"] & (hits["high_price"] > price)]
    if hits.empty:
        return None
    return float(hits["high_price"].min())


def _bullish_stack(row) -> bool:
    values = [row["ema20"], row["ema50"], row["ema200"], row["close_price"], row["atr"]]
    if not all(_finite(value) for value in values):
        return False
    spread = max(row["ema20"], row["ema50"], row["ema200"]) - min(
        row["ema20"], row["ema50"], row["ema200"]
    )
    if spread < 0.5 * float(row["atr"]):
        return False
    return (
        float(row["ema20"]) > float(row["ema50"]) > float(row["ema200"])
        and float(row["close_price"]) > float(row["ema200"])
    )


def _flags(h4, h1, pattern: str | None, pullback: bool) -> dict:
    rsi_value = h1["rsi"]
    return {
        "h4": _bullish_stack(h4) and _finite(h4["adx"]) and float(h4["adx"]) > 20,
        "h1": _finite(h1["ema20"])
        and float(h1["ema20"]) > float(h1["ema50"]) > float(h1["ema200"]),
        "ema": _finite(h1["ema20"]) and float(h1["ema20"]) > float(h1["ema50"]),
        "pullback": pullback,
        "candle": pattern is not None,
        "volume": _finite(h1["vol_sma"]) and float(h1["volume"]) > float(h1["vol_sma"]),
        "macd": _finite(h1["macd"])
        and _finite(h1["macd_signal"])
        and float(h1["macd"]) > float(h1["macd_signal"]),
        "rsi": _finite(rsi_value) and 40 <= float(rsi_value) <= 65,
        "adx": _finite(h4["adx"]) and float(h4["adx"]) > 20,
        "breakout": True,
    }


@dataclass
class _Setup:
    ready: pd.Timestamp
    expire: pd.Timestamp
    trigger: float
    structure_low: float
    atr: float
    resistance: float | None
    score: int
    pattern: str


@dataclass
class _Position:
    qty: float
    original_qty: float
    entry: float
    stop: float
    initial_stop: float
    risk: float
    tp1: float
    tp2: float
    tp1_done: bool
    tp2_done: bool
    highest: float
    atr: float
    score: int
    pattern: str
    entry_time: pd.Timestamp
    realized: float
    fees: float
    filled_at_open: bool


def _last_closed(frame: pd.DataFrame, close_times: pd.Series, asof: pd.Timestamp) -> int | None:
    position = int(close_times.searchsorted(asof, side="right")) - 1
    if position < 0 or position >= len(frame):
        return None
    return position


def _find_setups(h1: pd.DataFrame, h4: pd.DataFrame, h4_close: pd.Series) -> tuple[list[_Setup], int]:
    duration = pd.Timedelta(hours=1)
    setups: list[_Setup] = []
    gated = 0
    for index in range(len(h1)):
        closed_at = h1["open_time"].iloc[index] + duration
        h4_index = _last_closed(h4, h4_close, closed_at)
        if h4_index is None:
            continue
        pattern = pattern_at(h1, index)
        if pattern is None:
            continue
        row = h1.iloc[index]
        atr_value = float(row["atr"]) if _finite(row["atr"]) else 0.0
        swing_low = _last_swing_low(h1, index)
        pullback = any(
            _near(row["low_price"], row["high_price"], level, atr_value)
            for level in (row["ema20"], row["ema50"], swing_low)
            if level is not None
        )
        flags = _flags(h4.iloc[h4_index], row, pattern, pullback)
        required = (
            flags["h4"]
            and flags["pullback"]
            and flags["candle"]
            and flags["volume"]
            and flags["macd"]
            and flags["rsi"]
            and flags["adx"]
        )
        score = score_points(**flags)
        if not required or score < SCORE_MIN:
            continue
        gated += 1
        trigger = float(row["high_price"])
        structure = _pattern_low(h1, index, pattern)
        stop = stop_price(trigger, structure, atr_value)
        resistance = _nearest_resistance(h1, index, trigger)
        if not should_enter(
            pattern=True,
            score=score,
            entry=trigger,
            stop=stop if stop is not None else trigger,
            resistance=resistance,
        ):
            continue
        setups.append(
            _Setup(
                ready=closed_at,
                expire=closed_at + SETUP_LIFE,
                trigger=trigger,
                structure_low=structure,
                atr=atr_value,
                resistance=resistance,
                score=score,
                pattern=pattern,
            )
        )
    return setups, gated


def _sell(position: _Position, qty: float, raw_price: float, fee_rate: float, slippage: float) -> float:
    """Devolve o caixa líquido da venda."""
    qty = min(float(qty), position.qty)
    if qty <= 0:
        return 0.0
    fill = float(raw_price) * (1 - slippage)
    fee = fill * qty * fee_rate
    position.realized += (fill - position.entry) * qty
    position.fees += fee
    position.qty -= qty
    return fill * qty - fee


def _step_position(
    position: _Position,
    bar,
    atr_value: float,
    fee_rate: float,
    slippage: float,
    *,
    opened_this_bar: bool = False,
) -> tuple[_Position | None, dict | None, float]:
    open_price = float(bar.open_price)
    high = float(bar.high_price)
    low = float(bar.low_price)
    close = float(bar.close_price)
    bullish = close >= open_price
    proceeds = 0.0
    # Num candle de alta o fundo ocorre antes do rompimento. Não usa essa
    # mínima contra uma compra que só nasce na máxima.
    skip_prior_low = opened_this_bar and not position.filled_at_open

    def hit_stop(price_low: float) -> tuple[_Position | None, dict | None, float] | None:
        if price_low > position.stop:
            return None
        raw = open_price if open_price <= position.stop else position.stop
        sold = _sell(position, position.qty, raw, fee_rate, slippage)
        trade = _closed_trade(position, bar.open_time, "stop")
        return None, trade, proceeds + sold

    def take_profit(target: float, portion: float, kind: str) -> None:
        nonlocal proceeds
        if position.qty <= 0 or high < target:
            return
        proceeds += _sell(position, position.original_qty * portion, target, fee_rate, slippage)
        if kind == "tp1":
            position.tp1_done = True
            position.stop = max(position.stop, position.entry)
        elif kind == "tp2":
            position.tp2_done = True

    def ratchet() -> None:
        if not position.tp1_done:
            return
        position.highest = max(position.highest, high)
        trail_atr = atr_value if _finite(atr_value) and atr_value > 0 else position.atr
        position.stop = max(position.stop, position.highest - TRAIL_ATR_MULT * trail_atr)

    if bullish:
        if not skip_prior_low:
            stopped = hit_stop(low)
            if stopped is not None:
                return stopped
        if not position.tp1_done:
            take_profit(position.tp1, 0.30, "tp1")
        if position.tp1_done and not position.tp2_done:
            take_profit(position.tp2, 0.30, "tp2")
        ratchet()
    else:
        if not position.tp1_done:
            take_profit(position.tp1, 0.30, "tp1")
        if position.tp1_done and not position.tp2_done:
            take_profit(position.tp2, 0.30, "tp2")
        ratchet()
        stopped = hit_stop(low)
        if stopped is not None:
            return stopped
    return position, None, proceeds


def _closed_trade(position: _Position, exit_time, reason: str) -> dict:
    risk_quote = position.original_qty * position.risk
    realized_r = position.realized / risk_quote if risk_quote > 0 else 0.0
    notional = position.original_qty * position.entry
    return_pct = (position.realized / notional * 100) if notional > 0 else 0.0
    return {
        "entry_time": position.entry_time,
        "exit_time": exit_time,
        "return_pct": return_pct,
        "r": realized_r,
        "pnl": position.realized,
        "fees": position.fees,
        "score": position.score,
        "pattern": position.pattern,
        "reason": reason,
    }


def _open_position(setup: _Setup, bar, cash: float, fee_rate: float, slippage: float):
    raw = setup.trigger if float(bar.open_price) < setup.trigger else float(bar.open_price)
    fill = raw * (1 + slippage)
    stop = stop_price(fill, setup.structure_low, setup.atr)
    if stop is None or not should_enter(
        pattern=True,
        score=setup.score,
        entry=fill,
        stop=stop,
        resistance=setup.resistance,
    ):
        return cash, None, 0.0
    risk = fill - stop
    equity = cash
    notional = equity * RISK_PCT / (risk / fill)
    notional = min(notional, cash / (1 + fee_rate))
    if notional <= 0:
        return cash, None, 0.0
    qty = notional / fill
    fee = notional * fee_rate
    cash -= notional + fee
    position = _Position(
        qty=qty,
        original_qty=qty,
        entry=fill,
        stop=stop,
        initial_stop=stop,
        risk=risk,
        tp1=fill + risk,
        tp2=fill + 2 * risk,
        tp1_done=False,
        tp2_done=False,
        highest=max(fill, float(bar.high_price)),
        atr=setup.atr,
        score=setup.score,
        pattern=setup.pattern,
        entry_time=bar.open_time,
        realized=0.0,
        fees=fee,
        filled_at_open=float(bar.open_price) >= setup.trigger,
    )
    return cash, position, fee


def simulate(
    frame_15m: pd.DataFrame,
    frame_1h: pd.DataFrame,
    frame_4h: pd.DataFrame,
    *,
    eval_start: pd.Timestamp,
    initial_balance: float = 1000.0,
    fee_rate: float = FEE_RATE,
    slippage: float = SLIPPAGE,
) -> dict:
    h1 = prepare(frame_1h)
    h4 = prepare(frame_4h)
    m15 = prepare(frame_15m)
    h1_close = h1["open_time"] + pd.Timedelta(hours=1)
    h4_close = h4["open_time"] + pd.Timedelta(hours=4)
    setups, gated = _find_setups(h1, h4, h4_close)
    eval_start = pd.Timestamp(eval_start)
    if eval_start.tzinfo is None:
        eval_start = eval_start.tz_localize("America/Sao_Paulo")
    else:
        eval_start = eval_start.tz_convert("America/Sao_Paulo")

    cash = float(initial_balance)
    position: _Position | None = None
    trades: list[dict] = []
    equity = [cash]
    day_pnl: dict = {}
    setup_cursor = 0
    consumed_ready: pd.Timestamp | None = None

    def _book_close(closed: dict, sold: float) -> None:
        nonlocal cash, position
        cash += sold
        trades.append(closed)
        day = pd.Timestamp(closed["exit_time"]).tz_convert("America/Sao_Paulo").date()
        day_pnl[day] = day_pnl.get(day, 0.0) + closed["pnl"] - closed["fees"]
        position = None

    for bar in m15.itertuples(index=False):
        if bar.open_time < eval_start:
            continue
        bar_atr = 0.0
        h1_index = _last_closed(h1, h1_close, bar.open_time)
        if h1_index is not None and _finite(h1["atr"].iloc[h1_index]):
            bar_atr = float(h1["atr"].iloc[h1_index])
        if position is not None:
            position, closed, sold = _step_position(
                position, bar, bar_atr, fee_rate, slippage
            )
            if closed is not None:
                _book_close(closed, sold)
        if position is None:
            day = pd.Timestamp(bar.open_time).date()
            locked = day_pnl.get(day, 0.0) <= -DAILY_LOSS_PCT * initial_balance
            while setup_cursor < len(setups) and setups[setup_cursor].ready <= bar.open_time:
                setup_cursor += 1
            setup = setups[setup_cursor - 1] if setup_cursor else None
            if setup is not None and (
                consumed_ready == setup.ready
                or not (setup.ready <= bar.open_time < setup.expire)
            ):
                setup = None
            h4_index = _last_closed(h4, h4_close, bar.open_time)
            regime_ok = h4_index is not None and _bullish_stack(h4.iloc[h4_index]) and (
                _finite(h4["adx"].iloc[h4_index]) and float(h4["adx"].iloc[h4_index]) > 20
            )
            if (
                setup is not None
                and not locked
                and regime_ok
                and float(bar.high_price) >= setup.trigger
            ):
                consumed_ready = setup.ready
                cash, position, _buy_fee = _open_position(
                    setup, bar, cash, fee_rate, slippage
                )
                if position is not None:
                    position, closed, sold = _step_position(
                        position,
                        bar,
                        bar_atr,
                        fee_rate,
                        slippage,
                        opened_this_bar=True,
                    )
                    if closed is not None:
                        _book_close(closed, sold)
        mark = float(bar.close_price)
        equity.append(cash + (position.qty * mark if position is not None else 0.0))

    if position is not None:
        last = m15.iloc[-1]
        sold = _sell(position, position.qty, float(last.close_price), fee_rate, slippage)
        cash += sold
        trades.append(_closed_trade(position, last.open_time, "mark"))
        equity[-1] = cash
        position = None

    total_fees = float(sum(trade["fees"] for trade in trades))
    metrics = _metrics(trades, equity, total_fees, initial_balance, len(setups))
    metrics["gated"] = gated
    return metrics


def _metrics(trades: list[dict], equity: list[float], total_fees: float, initial: float, setups: int) -> dict:
    returns = [trade["return_pct"] for trade in trades]
    rs = [trade["r"] for trade in trades]
    wins = [trade["pnl"] for trade in trades if trade["pnl"] > 0]
    losses = [trade["pnl"] for trade in trades if trade["pnl"] < 0]
    gross_loss = abs(sum(losses))
    profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else (float("inf") if wins else 0.0)
    final = equity[-1] if equity else initial
    return {
        "profit_percentage": (final / initial - 1) * 100 if initial else 0.0,
        "trades": len(trades),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": profit_factor,
        "expectancy_r": float(np.mean(rs)) if rs else 0.0,
        "max_drawdown_pct": _max_drawdown(equity),
        "total_fees": total_fees,
        "final_balance": final,
        "setups": setups,
        "gross_win": float(sum(wins)),
        "gross_loss": float(gross_loss),
        "closed_trades": trades,
    }


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100)
    return worst


def summarize_price_trades(closed_trades: list[dict], *, risk_pct: float) -> dict:
    """Métricas de R a partir dos retornos de preço do backtestRunner."""
    returns = [float(trade["return_pct"]) for trade in closed_trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_loss = abs(sum(losses))
    profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else (float("inf") if wins else 0.0)
    expectancy = float(np.mean([value / risk_pct for value in returns])) if returns and risk_pct else 0.0
    return {
        "trades": len(returns),
        "win_rate": (len(wins) / len(returns) * 100) if returns else 0.0,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy,
        "gross_win": float(sum(wins)),
        "gross_loss": float(gross_loss),
    }
