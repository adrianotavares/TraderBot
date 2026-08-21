from typing import Optional

import pandas as pd


def compute_candle_variation(stock_data: pd.DataFrame) -> Optional[dict]:
    """Return open/close variation of the last *closed* candle.

    Binance `get_klines` includes the in-progress bar as the final row, so the
    previous row is the completed period that matches copy like "nas últimas 4h".
    """
    if stock_data is None or len(stock_data) == 0:
        return None
    candle = stock_data.iloc[-2] if len(stock_data) >= 2 else stock_data.iloc[-1]
    open_price = float(candle["open_price"])
    close_price = float(candle["close_price"])
    if open_price == 0 or pd.isna(open_price) or pd.isna(close_price):
        return None
    variation_pct = ((close_price - open_price) / open_price) * 100
    if variation_pct > 0:
        direction = "up"
    elif variation_pct < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "open_price": open_price,
        "close_price": close_price,
        "variation_pct": round(variation_pct, 4),
        "direction": direction,
    }


def _format_price_usd(price: float) -> str:
    if abs(price) >= 1:
        return f"{price:.2f} usd"
    formatted = f"{price:.8f}".rstrip("0").rstrip(".")
    return f"{formatted} usd"


def format_qty(quantity: float) -> str:
    formatted = f"{quantity:.8f}".rstrip("0").rstrip(".")
    return formatted or "0"


def unrealized_pnl_pct(mark_price: float, last_buy_price: float) -> Optional[float]:
    if mark_price <= 0 or last_buy_price <= 0:
        return None
    return ((mark_price - last_buy_price) / last_buy_price) * 100


def format_pnl_pct_label(pnl_pct: Optional[float]) -> str:
    if pnl_pct is None:
        return "n/d"
    sign = "+" if pnl_pct > 0 else ""
    return f"{sign}{pnl_pct:.2f}%"


def format_held_position_label(
    stock_code: str,
    quantity: float,
    mark_price: float,
    last_buy_price: float,
) -> str:
    value_usd = quantity * mark_price if mark_price > 0 else 0.0
    pnl_pct = unrealized_pnl_pct(mark_price, last_buy_price)
    if value_usd >= 1:
        value_str = f"{value_usd:.2f}"
    else:
        value_str = f"{value_usd:.4f}".rstrip("0").rstrip(".") or "0"
    return (
        f"Comprado, {format_qty(quantity)} {stock_code}, "
        f"{value_str} usd, {format_pnl_pct_label(pnl_pct)}"
    )


def format_variation_message(
    stock_code: str, variation_pct: float, candle_period: str, close_price: float
) -> str:
    period = candle_period or "?"
    abs_pct = abs(variation_pct)
    price = _format_price_usd(close_price)
    if variation_pct > 0:
        return f"{stock_code} subiu {abs_pct:.2f}% nas últimas {period} ({price})"
    if variation_pct < 0:
        return f"{stock_code} caiu {abs_pct:.2f}% nas últimas {period} ({price})"
    return f"{stock_code} manteve o preço nas últimas {period} ({price})"
