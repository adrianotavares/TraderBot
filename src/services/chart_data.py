"""Payload builder for the Tracking charts (TradingView Lightweight Charts).

Every timestamp leaving this module is epoch **seconds in UTC**, which is what
Lightweight Charts expects. `MarketDataService.normalize_klines` localizes
`open_time` to America/Sao_Paulo, so the conversion here is explicit; the
browser is responsible for formatting the axis in the user's timezone.
"""

from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from indicators.atr import atr, compute_trailing_stop

_PERIOD_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}

# The regime detector needs 60 candles and the atr_trend SMA up to 200, so the
# oldest charted candle is only as trustworthy as the warmup behind it.
WARMUP_CANDLES = 260
DEFAULT_BARS = 120

# Recomputing one candle's regime costs ~14ms, so a cold 120-candle window would
# block a request for seconds. Backfill newest-first in bounded slices instead:
# the recent part of the ribbon appears immediately and the tail fills in over
# the next few polls, permanently, since the rows are persisted.
MAX_BACKFILL_PER_REQUEST = 25

REGIME_COLORS = {"TREND": "up", "LATERAL": "warn", "GRAY": "neutral"}


def candle_period_seconds(period: str) -> int:
    text = str(period).strip().lower()
    unit = _PERIOD_UNIT_SECONDS.get(text[-1:])
    if unit is None:
        raise ValueError(f"unsupported candle period: {period!r}")
    try:
        amount = int(text[:-1])
    except ValueError as exc:
        raise ValueError(f"unsupported candle period: {period!r}") from exc
    if amount <= 0:
        raise ValueError(f"unsupported candle period: {period!r}")
    return amount * unit


def candle_times(stock_data: pd.DataFrame) -> list[int]:
    """Candle open times as epoch seconds UTC."""
    if stock_data is None or len(stock_data) == 0:
        return []
    times = pd.to_datetime(stock_data["open_time"], utc=True)
    return [int(value) for value in times.astype("int64") // 10**9]


def candles_to_series(stock_data: pd.DataFrame) -> list[dict]:
    if stock_data is None or len(stock_data) == 0:
        return []
    times = candle_times(stock_data)
    series = []
    for index, time in enumerate(times):
        row = stock_data.iloc[index]
        values = (
            row["open_price"],
            row["high_price"],
            row["low_price"],
            row["close_price"],
        )
        if any(pd.isna(value) for value in values):
            continue
        series.append(
            {
                "time": time,
                "open": float(values[0]),
                "high": float(values[1]),
                "low": float(values[2]),
                "close": float(values[3]),
            }
        )
    return series


def snap_to_candle(timestamp: int, times: list[int]) -> Optional[int]:
    """The candle containing `timestamp`, or None when it predates the window.

    Searches the candle list instead of doing modular arithmetic, because
    Binance aligns weekly and 3-day candles to dates rather than to the epoch.
    """
    if not times:
        return None
    index = bisect_right(times, timestamp) - 1
    if index < 0:
        return None
    return times[index]


def is_closed(candle_time: int, period_seconds: int, now: Optional[int] = None) -> bool:
    reference = now if now is not None else int(datetime.now(timezone.utc).timestamp())
    return candle_time + period_seconds <= reference


def parse_iso_seconds(value: Any) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _regime_row(candle_time: int, result) -> dict:
    return {
        "candle_time": candle_time,
        "regime": result.regime,
        "score": int(result.score),
        "adx": round(float(result.adx_value), 2),
        "rsi": round(float(result.rsi_value), 2),
    }


def _closed_regimes(
    store,
    operation_code: str,
    closed: list[int],
    evaluate,
    max_backfill: int = MAX_BACKFILL_PER_REQUEST,
) -> dict[int, dict]:
    """Regimes of closed candles, recomputing and persisting only what is missing."""
    if not closed:
        return {}
    if store is None or not operation_code:
        return {time: _regime_row(time, evaluate(time)) for time in closed}

    pending = store.missing_regime_candles(operation_code, closed)
    if max_backfill > 0:
        pending = pending[-max_backfill:]
    computed = [_regime_row(time, evaluate(time)) for time in pending]
    if computed:
        store.save_regime_batch(operation_code, computed, source="backfill")
    return {
        int(row["candle_time"]): row
        for row in store.list_regime(
            operation_code, since=min(closed), until=max(closed)
        )
    }


def regime_series(
    stock_data: pd.DataFrame,
    window: list[int],
    *,
    detector,
    period_seconds: int,
    store=None,
    operation_code: str = "",
    now: Optional[int] = None,
    max_backfill: int = MAX_BACKFILL_PER_REQUEST,
) -> tuple[list[dict], Optional[dict]]:
    """Regime per candle for `window`, plus the regime of the newest candle.

    Closed candles are read from `regime_history` and only the missing ones are
    recomputed and persisted as `backfill`, so the expensive walk happens once
    per candle rather than once per request. The candle still forming is always
    re-evaluated and never persisted, since its OHLC keeps moving.
    """
    if detector is None or not getattr(detector, "enabled", False) or not window:
        return [], None

    times = candle_times(stock_data)
    position_of = {time: index for index, time in enumerate(times)}

    def evaluate(candle_time: int):
        return detector.evaluate(stock_data.iloc[: position_of[candle_time] + 1])

    closed = [
        time
        for time in window
        if time in position_of and is_closed(time, period_seconds, now)
    ]
    stored = _closed_regimes(store, operation_code, closed, evaluate, max_backfill)

    current: Optional[dict] = None
    forming = window[-1]
    if forming in position_of and not is_closed(forming, period_seconds, now):
        result = evaluate(forming)
        stored[forming] = _regime_row(forming, result)
        current = {
            "regime": result.regime,
            "score": int(result.score),
            "adx": round(float(result.adx_value), 2),
            "rsi": round(float(result.rsi_value), 2),
            "signals": result.signals,
            "support": result.support,
            "resistance": result.resistance,
            "provisional": True,
        }

    series = []
    for time in window:
        row = stored.get(time)
        if not row:
            continue
        series.append(
            {
                "time": time,
                "regime": row["regime"],
                "score": int(row.get("score") or 0),
                "adx": row.get("adx"),
                "rsi": row.get("rsi"),
            }
        )

    if current is None and series:
        last = series[-1]
        current = {
            "regime": last["regime"],
            "score": last["score"],
            "adx": last["adx"],
            "rsi": last["rsi"],
            "signals": {},
            "support": None,
            "resistance": None,
            "provisional": False,
        }
    return series, current


def trailing_stop_series(
    stock_data: pd.DataFrame,
    window: list[int],
    *,
    atr_period: int = 14,
    atr_multiplier: float = 2.5,
) -> list[dict]:
    """UT-Bot style ATR trailing stop, the exit the atr_trend strategy reacts to."""
    if stock_data is None or len(stock_data) == 0 or not window:
        return []
    close = pd.to_numeric(stock_data["close_price"], errors="coerce")
    stops = compute_trailing_stop(close, atr(stock_data, window=atr_period), atr_multiplier)
    times = candle_times(stock_data)
    wanted = set(window)
    series = []
    for index, time in enumerate(times):
        if time not in wanted:
            continue
        value = stops.iloc[index]
        if pd.isna(value):
            continue
        series.append({"time": time, "value": round(float(value), 8)})
    return series


def compute_levels(
    *,
    entry_price: float,
    position_open: bool,
    stop_loss_pct: float,
    acceptable_loss_pct: float,
    take_profit: list,
    take_profit_index: int = 0,
) -> Optional[dict]:
    """Entry, take profit and stop loss prices, or None when flat.

    `last_buy_price` survives in `bot_state` after a sell, so returning None
    while flat keeps stale levels off the chart.
    """
    entry = float(entry_price or 0)
    if not position_open or entry <= 0:
        return None

    levels: dict[str, Any] = {"entry": round(entry, 8)}

    index = int(take_profit_index or 0)
    levels["take_profit"] = None
    if 0 <= index < len(take_profit):
        level = take_profit[index]
        pct = float(getattr(level, "at", 0) or 0)
        if pct > 0:
            levels["take_profit"] = {
                "price": round(entry * (1 + pct / 100), 8),
                "pct": pct,
                "amount_pct": float(getattr(level, "amount", 0) or 0),
                "index": index,
                "total": len(take_profit),
            }

    stop_pct = float(stop_loss_pct or 0)
    levels["stop_loss"] = (
        {"price": round(entry * (1 - stop_pct / 100), 8), "pct": stop_pct}
        if stop_pct > 0
        else None
    )

    loss_pct = float(acceptable_loss_pct or 0)
    levels["min_sell"] = (
        {"price": round(entry * (1 - loss_pct / 100), 8), "pct": loss_pct}
        if loss_pct > 0
        else None
    )
    return levels


def order_markers(orders, operation_code: str, window: list[int]) -> list[dict]:
    """BUY/SELL markers snapped to the candle that contains each fill.

    Lightweight Charts drops markers whose time does not match a candle, and
    requires them sorted ascending.
    """
    markers = []
    for order in orders or []:
        if order.get("operation_code") != operation_code:
            continue
        side = str(order.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            continue
        seconds = parse_iso_seconds(order.get("created_at"))
        if seconds is None:
            continue
        time = snap_to_candle(seconds, window)
        if time is None:
            continue
        markers.append(
            {
                "time": time,
                "side": side,
                "price": float(order.get("price") or 0),
                "quantity": float(order.get("quantity") or 0),
            }
        )
    markers.sort(key=lambda marker: (marker["time"], marker["side"]))
    return markers


def build_chart_payload(
    stock_data: pd.DataFrame,
    *,
    stock_code: str,
    operation_code: str,
    candle_period: str,
    risk,
    position: Optional[dict] = None,
    take_profit_index: int = 0,
    detector=None,
    store=None,
    orders=None,
    strategy_main: str = "",
    strategy_args: Optional[dict] = None,
    bars: int = DEFAULT_BARS,
    now: Optional[int] = None,
    max_backfill: int = MAX_BACKFILL_PER_REQUEST,
) -> dict:
    period_seconds = candle_period_seconds(candle_period)
    candles = candles_to_series(stock_data)[-bars:]
    window = [candle["time"] for candle in candles]

    regime, current_regime = regime_series(
        stock_data,
        window,
        detector=detector,
        period_seconds=period_seconds,
        store=store,
        operation_code=operation_code,
        now=now,
        max_backfill=max_backfill,
    )

    trailing: list[dict] = []
    if strategy_main == "atr_trend":
        args = strategy_args or {}
        trailing = trailing_stop_series(
            stock_data,
            window,
            atr_period=int(args.get("atr_period", 14)),
            atr_multiplier=float(args.get("atr_multiplier", 2.5)),
        )

    position = position or {}
    levels = compute_levels(
        entry_price=position.get("entry_price") or 0,
        position_open=bool(position.get("open")),
        stop_loss_pct=getattr(risk, "stop_loss_pct", 0),
        acceptable_loss_pct=getattr(risk, "acceptable_loss_pct", 0),
        take_profit=getattr(risk, "take_profit", []) or [],
        take_profit_index=take_profit_index,
    )

    return {
        "stock_code": stock_code,
        "operation_code": operation_code,
        "candles": candles,
        "regime": regime,
        "current_regime": current_regime,
        "trailing_stop": trailing,
        "position": position,
        "levels": levels,
        "markers": order_markers(orders, operation_code, window),
        "error": None,
    }
