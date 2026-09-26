"""Padrões de alta usados só no backtest da CANDLE-PRICE-PRO.

As contas seguem o corpo e os pavios. O padrão qualifica o candle de 1h.
A compra continua sendo o rompimento da máxima no 15m.
"""

from __future__ import annotations


def body(open_price: float, close_price: float) -> float:
    return abs(float(close_price) - float(open_price))


def bullish_engulfing(
    prev_open: float,
    prev_close: float,
    open_price: float,
    close_price: float,
) -> bool:
    """O corpo de alta cobre o corpo de baixa anterior. Pavios ficam de fora."""
    prev_open = float(prev_open)
    prev_close = float(prev_close)
    open_price = float(open_price)
    close_price = float(close_price)
    if prev_close >= prev_open or close_price <= open_price:
        return False
    if body(prev_open, prev_close) <= 0 or body(open_price, close_price) <= 0:
        return False
    return open_price <= prev_close and close_price >= prev_open


def hammer(open_price: float, high: float, low: float, close_price: float) -> bool:
    """Corpo no topo, pavio inferior com pelo menos o dobro do corpo."""
    open_price = float(open_price)
    high = float(high)
    low = float(low)
    close_price = float(close_price)
    candle_body = body(open_price, close_price)
    if candle_body <= 0 or high < low:
        return False
    upper = high - max(open_price, close_price)
    lower = min(open_price, close_price) - low
    if upper < 0 or lower < 0:
        return False
    return lower >= 2 * candle_body and upper < candle_body


def morning_star(
    first_open: float,
    first_close: float,
    second_open: float,
    second_close: float,
    third_open: float,
    third_close: float,
    avg_body: float,
) -> bool:
    """Estrela de três candles, sem exigir gap.

    O primeiro corpo de baixa é maior que a média recente. O segundo é
    curto e fica na metade de baixo desse corpo. O terceiro fecha em alta
    acima da metade do primeiro corpo.
    """
    first_open = float(first_open)
    first_close = float(first_close)
    second_open = float(second_open)
    second_close = float(second_close)
    third_open = float(third_open)
    third_close = float(third_close)
    avg_body = float(avg_body)
    first_body = body(first_open, first_close)
    second_body = body(second_open, second_close)
    if first_close >= first_open or third_close <= third_open:
        return False
    if avg_body <= 0 or first_body <= avg_body:
        return False
    if second_body >= first_body / 2:
        return False
    midpoint = (first_open + first_close) / 2
    second_top = max(second_open, second_close)
    return second_top <= midpoint and third_close > midpoint
