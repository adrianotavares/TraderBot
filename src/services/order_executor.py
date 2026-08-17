import logging
from typing import Optional

from binance.enums import ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET, SIDE_BUY, SIDE_SELL

from indicators import Indicators
from modules.Logger import createLogOrder
from services.market_data import MarketDataService


class OrderExecutor:
    def __init__(
        self,
        client,
        operation_code: str,
        stock_code: str,
        tick_size: float,
        step_size: float,
    ):
        self.client = client
        self.operation_code = operation_code
        self.stock_code = stock_code
        self.tick_size = tick_size
        self.step_size = step_size
        self.partial_quantity_discount = 0.0

    def _adjust(self, value, step=None, as_string=False):
        return MarketDataService.adjust_to_step(value, step or self.step_size, as_string)

    def cancel_all_orders(self, open_orders: list) -> None:
        for order in open_orders:
            try:
                self.client.cancel_order(symbol=self.operation_code, orderId=order["orderId"])
                logging.info("Cancelled order %s for %s", order["orderId"], self.operation_code)
            except Exception as e:
                logging.error("Failed to cancel order %s: %s", order["orderId"], e)

    def buy_market(self, quantity, position_open: bool) -> Optional[dict]:
        if position_open:
            logging.warning("Buy skipped: position already open")
            return None
        quantity = self._adjust(quantity, as_string=True)
        order = self.client.create_order(
            symbol=self.operation_code,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        createLogOrder(order)
        return order

    def sell_market(self, quantity, position_open: bool) -> Optional[dict]:
        if not position_open:
            logging.warning("Sell skipped: position not open")
            return None
        quantity = self._adjust(quantity, as_string=True)
        order = self.client.create_order(
            symbol=self.operation_code,
            side=SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
        )
        createLogOrder(order)
        return order

    def buy_limited(self, stock_data, traded_quantity: float, price: float = 0) -> Optional[dict]:
        close_price = stock_data["close_price"].iloc[-1]
        volume = stock_data["volume"].iloc[-1]
        avg_volume = stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=stock_data["close_price"])

        if price == 0:
            if rsi < 30:
                limit_price = close_price - (0.002 * close_price)
            elif volume < avg_volume:
                limit_price = close_price + (0.002 * close_price)
            else:
                limit_price = close_price + (0.005 * close_price)
        else:
            limit_price = price

        limit_price = self._adjust(limit_price, self.tick_size, as_string=True)
        quantity = self._adjust(
            traded_quantity - self.partial_quantity_discount, as_string=True
        )

        order = self.client.create_order(
            symbol=self.operation_code,
            side=SIDE_BUY,
            type=ORDER_TYPE_LIMIT,
            timeInForce="GTC",
            quantity=quantity,
            price=limit_price,
        )
        if order:
            createLogOrder(order)
        return order

    def sell_limited(
        self,
        stock_data,
        balance: float,
        last_buy_price: float,
        acceptable_loss_pct: float,
        min_sell_price_fn,
        price: float = 0,
    ) -> Optional[dict]:
        close_price = stock_data["close_price"].iloc[-1]
        volume = stock_data["volume"].iloc[-1]
        avg_volume = stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=stock_data["close_price"])

        if price == 0:
            if rsi > 70:
                limit_price = close_price + (0.002 * close_price)
            elif volume < avg_volume:
                limit_price = close_price - (0.002 * close_price)
            else:
                limit_price = close_price - (0.005 * close_price)
            if limit_price < (last_buy_price * (1 - acceptable_loss_pct)):
                limit_price = min_sell_price_fn()
        else:
            limit_price = price

        limit_price = self._adjust(limit_price, self.tick_size, as_string=True)
        quantity = self._adjust(balance, as_string=True)

        order = self.client.create_order(
            symbol=self.operation_code,
            side=SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            timeInForce="GTC",
            quantity=quantity,
            price=limit_price,
        )
        if order:
            createLogOrder(order)
        return order

    def place_limit(self, side: str, quantity: float, price: float) -> Optional[dict]:
        limit_price = self._adjust(price, self.tick_size, as_string=True)
        quantity = self._adjust(quantity, as_string=True)
        order = self.client.create_order(
            symbol=self.operation_code,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            timeInForce="GTC",
            quantity=quantity,
            price=limit_price,
        )
        if order:
            createLogOrder(order)
        return order

    def has_open_buy_order(self) -> tuple[bool, float, float]:
        self.partial_quantity_discount = 0.0
        last_buy_price = 0.0
        open_orders = self.client.get_open_orders(symbol=self.operation_code)
        buy_orders = [o for o in open_orders if o["side"] == "BUY"]
        if not buy_orders:
            return False, 0.0, 0.0
        for order in buy_orders:
            executed_qty = float(order["executedQty"])
            price = float(order["price"])
            self.partial_quantity_discount += executed_qty
            if executed_qty > 0 and price > last_buy_price:
                last_buy_price = price
        return True, self.partial_quantity_discount, last_buy_price

    def has_open_sell_order(self) -> tuple[bool, float]:
        self.partial_quantity_discount = 0.0
        open_orders = self.client.get_open_orders(symbol=self.operation_code)
        sell_orders = [o for o in open_orders if o["side"] == "SELL"]
        if not sell_orders:
            return False, 0.0
        for order in sell_orders:
            self.partial_quantity_discount += float(order["executedQty"])
        return True, self.partial_quantity_discount

    @staticmethod
    def is_filled(order: Optional[dict]) -> bool:
        return bool(order and order.get("status") == "FILLED")

    @staticmethod
    def is_order_active(order: Optional[dict]) -> bool:
        return bool(order and order.get("status") in ("NEW", "PARTIALLY_FILLED"))
