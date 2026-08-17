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


def format_variation_message(
    stock_code: str, variation_pct: float, candle_period: str, close_price: float
) -> str:
    period = candle_period or "?"
    abs_pct = abs(variation_pct)
    price = _format_price_usd(close_price)
    if variation_pct > 0:
        return f"{stock_code} subiu {abs_pct:.2f}% nas últimas {period} - {price}"
    if variation_pct < 0:
        return f"{stock_code} caiu {abs_pct:.2f}% nas últimas {period} - {price}"
    return f"{stock_code} manteve o preço nas últimas {period} - {price}"
