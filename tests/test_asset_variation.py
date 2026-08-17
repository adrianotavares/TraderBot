import pandas as pd

from services.asset_variation import compute_candle_variation, format_variation_message


def _klines(open_price: float, close_price: float) -> pd.DataFrame:
    """Closed candle in the middle; last row is the in-progress Binance bar."""
    return pd.DataFrame(
        [
            {"open_price": 90.0, "close_price": 91.0},
            {"open_price": open_price, "close_price": close_price},
            {"open_price": close_price, "close_price": close_price + 50.0},
        ]
    )


def test_compute_candle_variation_up():
    result = compute_candle_variation(_klines(100.0, 104.0))
    assert result["direction"] == "up"
    assert result["variation_pct"] == 4.0
    assert result["open_price"] == 100.0
    assert result["close_price"] == 104.0


def test_compute_candle_variation_down():
    result = compute_candle_variation(_klines(100.0, 97.5))
    assert result["direction"] == "down"
    assert result["variation_pct"] == -2.5


def test_compute_candle_variation_ignores_forming_candle():
    result = compute_candle_variation(_klines(100.0, 104.0))
    assert result["close_price"] == 104.0
    assert result["close_price"] != 154.0


def test_compute_candle_variation_single_row_fallback():
    result = compute_candle_variation(
        pd.DataFrame([{"open_price": 100.0, "close_price": 104.0}])
    )
    assert result["variation_pct"] == 4.0


def test_compute_candle_variation_empty():
    assert compute_candle_variation(pd.DataFrame()) is None


def test_format_variation_message_uses_candle_period():
    assert (
        format_variation_message("BTC", 1.234, "4h", 67234.5)
        == "BTC subiu 1.23% nas últimas 4h - 67234.50 usd"
    )
    assert (
        format_variation_message("ETH", -0.5, "15m", 2450.0)
        == "ETH caiu 0.50% nas últimas 15m - 2450.00 usd"
    )
    assert (
        format_variation_message("BTC", 0.0, "4h", 67000)
        == "BTC manteve o preço nas últimas 4h - 67000.00 usd"
    )
