import math
import logging
from typing import Optional

import pandas as pd


class MarketDataService:
    def __init__(self, client, operation_code: str, candle_period: str):
        self.client = client
        self.operation_code = operation_code
        self.candle_period = candle_period

    def fetch_klines(self, limit: int = 1000) -> pd.DataFrame:
        candles = self.client.get_klines(
            symbol=self.operation_code,
            interval=self.candle_period,
            limit=limit,
        )
        return self.normalize_klines(candles)

    @staticmethod
    def normalize_klines(candles) -> pd.DataFrame:
        prices = pd.DataFrame(candles)
        prices.columns = [
            "open_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "-",
        ]
        prices = prices[
            [
                "close_price",
                "open_time",
                "open_price",
                "high_price",
                "low_price",
                "volume",
            ]
        ]
        for col in ("close_price", "open_price", "high_price", "low_price", "volume"):
            prices[col] = pd.to_numeric(prices[col], errors="coerce")
        prices["open_time"] = (
            pd.to_datetime(prices["open_time"], unit="ms")
            .dt.tz_localize("UTC")
            .dt.tz_convert("America/Sao_Paulo")
        )
        return prices

    def get_symbol_filters(self) -> dict:
        symbol_info = self.client.get_symbol_info(self.operation_code)
        filters = {f["filterType"]: f for f in symbol_info["filters"]}
        tick_size = float(filters["PRICE_FILTER"]["tickSize"])
        step_size = float(filters["LOT_SIZE"]["stepSize"])
        min_notional = 0.0
        if "NOTIONAL" in filters:
            min_notional = float(filters["NOTIONAL"].get("minNotional", 0))
        elif "MIN_NOTIONAL" in filters:
            min_notional = float(filters["MIN_NOTIONAL"].get("minNotional", 0))
        return {
            "tick_size": tick_size,
            "step_size": step_size,
            "min_notional": min_notional,
            "quote_asset": symbol_info.get("quoteAsset", "USDT"),
            "base_asset": symbol_info.get("baseAsset", ""),
        }

    @staticmethod
    def _step_decimal_places(step: float) -> int:
        if step <= 0:
            raise ValueError("step must be greater than zero")
        return max(0, abs(int(math.floor(math.log10(step))))) if step < 1 else 0

    @staticmethod
    def adjust_to_step(value: float, step: float, as_string: bool = False):
        decimal_places = MarketDataService._step_decimal_places(step)
        adjusted_value = math.floor(value / step) * step
        adjusted_value = round(adjusted_value, decimal_places)
        if as_string:
            return f"{adjusted_value:.{decimal_places}f}"
        return adjusted_value

    @staticmethod
    def ceil_to_step(value: float, step: float) -> float:
        decimal_places = MarketDataService._step_decimal_places(step)
        adjusted_value = math.ceil(value / step) * step
        return round(adjusted_value, decimal_places)

    @staticmethod
    def size_quantity_for_filters(
        quantity: float,
        price: float,
        step_size: float,
        min_notional: float = 0.0,
        max_quote: float | None = None,
        bump_to_min_notional: bool = True,
    ) -> float:
        """Floor to LOT_SIZE, then raise to NOTIONAL when the quote balance allows."""
        if quantity <= 0 or price <= 0 or step_size <= 0:
            return 0.0
        qty = MarketDataService.adjust_to_step(quantity, step_size)
        if min_notional > 0 and qty * price < min_notional and bump_to_min_notional:
            qty = MarketDataService.ceil_to_step(min_notional / price, step_size)
            if qty * price < min_notional:
                decimal_places = MarketDataService._step_decimal_places(step_size)
                qty = round(qty + step_size, decimal_places)
        if max_quote is not None and qty * price > max_quote:
            qty = MarketDataService.adjust_to_step(max_quote / price, step_size)
        if qty <= 0:
            return 0.0
        if min_notional > 0 and qty * price < min_notional:
            return 0.0
        return qty

    def get_account_balance(self, asset_code: str, account_data: dict) -> float:
        for stock in account_data.get("balances", []):
            if stock["asset"] == asset_code:
                return float(stock["free"]) + float(stock["locked"])
        return 0.0

    def is_position_open(self, balance: float, step_size: float) -> bool:
        return balance >= step_size

    @staticmethod
    def get_last_fill_price(orders: list, side: str) -> float:
        filled = [o for o in orders if o["side"] == side and o["status"] == "FILLED"]
        if not filled:
            return 0.0
        last = sorted(filled, key=lambda x: x["time"], reverse=True)[0]
        executed_qty = float(last["executedQty"])
        if executed_qty == 0:
            return 0.0
        return float(last["cummulativeQuoteQty"]) / executed_qty
