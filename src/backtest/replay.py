import time

import pandas as pd

from core.state_fields import PersistedTradeFields
from persistence.state_store import StateStore
from services.order_executor import OrderExecutor
from services.risk_manager import RiskManager
from services.regime_detector import RegimeDetector


class ReplayMarketData:
    def __init__(self, frame: pd.DataFrame, end_index: int | None = None):
        self.frame = frame
        self.end_index = len(frame) if end_index is None else end_index

    def fetch_klines(self, limit: int = 1000) -> pd.DataFrame:
        return self.frame.iloc[: self.end_index].copy().reset_index(drop=True)

    def get_account_balance(self, asset_code: str, account_data: dict) -> float:
        for stock in account_data.get("balances", []):
            if stock["asset"] == asset_code:
                return float(stock["free"]) + float(stock["locked"])
        return 0.0

    def is_position_open(self, balance: float, step_size: float) -> bool:
        return balance >= step_size


class MemoryBroker:
    def __init__(self, mark_price: float = 100.0):
        self.mark_price = mark_price
        self.orders: list[dict] = []
        self._next_id = 1
        self.open_orders: list[dict] = []

    def create_order(self, **kwargs):
        quantity = float(kwargs.get("quantity") or 0)
        price = float(kwargs.get("price") or self.mark_price)
        if price <= 0:
            price = self.mark_price
        order = {
            "orderId": self._next_id,
            "symbol": kwargs.get("symbol", "BTCUSDT"),
            "side": kwargs["side"],
            "type": kwargs.get("type", "MARKET"),
            "status": "FILLED",
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(quantity * price),
            "price": str(price),
            "transactTime": int(time.time() * 1000),
            "time": int(time.time() * 1000),
            "fills": [{"price": str(price), "commissionAsset": "USDT"}],
        }
        self._next_id += 1
        self.orders.append(order)
        return order

    def get_open_orders(self, symbol=None):
        return list(self.open_orders)

    def cancel_order(self, symbol, orderId):
        self.open_orders = [o for o in self.open_orders if o.get("orderId") != orderId]
        return {"orderId": orderId, "status": "CANCELED"}

    def get_all_orders(self, symbol=None, limit=100):
        return list(self.orders)[-limit:]

    def get_account(self):
        return {"balances": []}


class FakeBot(PersistedTradeFields):
    def __init__(
        self,
        *,
        stock_data: pd.DataFrame,
        quote_balance: float = 1000.0,
        base_balance: float = 0.0,
        main_strategy=None,
        fallback_strategy=None,
        fallback_activated: bool = False,
        stop_loss_pct: float = 2.0,
        take_profit_at=None,
        take_profit_amount=None,
    ):
        self.engine = None
        self.operation_code = "BTCUSDT"
        self.stock_code = "BTC"
        self.quote_asset = "USDT"
        self.candle_period = "4h"
        self.stock_data = stock_data
        self.quote_balance = quote_balance
        self.base_balance = base_balance
        self.traded_quantity = 0.0
        self.traded_percentage = 100.0
        self.min_notional = 5.0
        self.step_size = 0.001
        self.tick_size = 0.01
        self.time_to_trade = 1
        self.delay_after_order = 1
        self.time_to_sleep = 1
        self.acceptable_loss_percentage = 1.0
        self.stop_loss_percentage = stop_loss_pct
        self.take_profit_at_percentage = take_profit_at or []
        self.take_profit_amount_percentage = take_profit_amount or []
        self.fallback_activated = fallback_activated
        self.main_strategy = main_strategy or (lambda **_k: None)
        self.main_strategy_args = {}
        self.fallback_strategy = fallback_strategy or (lambda **_k: None)
        self.fallback_strategy_args = {}
        self.open_orders = []
        self.account_data = {"balances": []}
        self.last_stock_account_balance = base_balance
        self.broker = MemoryBroker(
            mark_price=float(stock_data["close_price"].iloc[-1]) if len(stock_data) else 100.0
        )

    def _sync_account(self):
        self.account_data = {
            "balances": [
                {
                    "asset": self.stock_code,
                    "free": str(self.base_balance),
                    "locked": "0",
                },
                {
                    "asset": self.quote_asset,
                    "free": str(self.quote_balance),
                    "locked": "0",
                },
            ]
        }
        self.last_stock_account_balance = self.base_balance

    def getUpdatedAccountData(self):
        self._sync_account()
        return self.account_data

    def getLastStockAccountBalance(self):
        return self.base_balance

    def getActualTradePosition(self):
        return self.base_balance >= self.step_size

    def getLastBuyPrice(self, verbose=False):
        return float(self.last_buy_price or 0)

    def getLastSellPrice(self, verbose=False):
        return float(self.last_sell_price or 0)

    def getOpenOrders(self):
        return list(self.broker.open_orders)

    def cancelAllOrders(self):
        self.broker.open_orders = []
        self.open_orders = []

    def sellMarketOrder(self, quantity=None):
        qty = float(quantity or self.base_balance)
        price = float(self.stock_data["close_price"].iloc[-1])
        order = self.broker.create_order(
            symbol=self.operation_code,
            side="SELL",
            type="MARKET",
            quantity=qty,
            price=price,
        )
        proceeds = qty * price
        self.base_balance = round(self.base_balance - qty, 8)
        self.quote_balance = round(self.quote_balance + proceeds, 8)
        self._sync_account()
        return order

    def hasOpenBuyOrder(self):
        return False

    def hasOpenSellOrder(self):
        return False

    def getMinimumPriceToSell(self):
        return float(self.last_buy_price or 0) * 0.99

    def printStock(self):
        return None


def fill_buy(bot: FakeBot, order: dict):
    qty = float(order.get("executedQty") or 0)
    quote = float(order.get("cummulativeQuoteQty") or 0)
    if qty <= 0:
        return
    bot.base_balance = round(bot.base_balance + qty, 8)
    bot.quote_balance = round(bot.quote_balance - quote, 8)
    if quote > 0:
        bot.last_buy_price = quote / qty
    bot._sync_account()


def fill_sell(bot: FakeBot, order: dict):
    qty = float(order.get("executedQty") or 0)
    quote = float(order.get("cummulativeQuoteQty") or 0)
    if qty <= 0:
        return
    bot.base_balance = round(bot.base_balance - qty, 8)
    bot.quote_balance = round(bot.quote_balance + quote, 8)
    if quote > 0:
        bot.last_sell_price = quote / qty
    bot._sync_account()


class ReplayOrderExecutor(OrderExecutor):
    def buy_limited(self, stock_data, traded_quantity: float, price: float = 0):
        close_price = float(stock_data["close_price"].iloc[-1])
        self.client.mark_price = close_price
        order = self.client.create_order(
            symbol=self.operation_code,
            side="BUY",
            type="LIMIT",
            quantity=traded_quantity,
            price=close_price,
        )
        bot = getattr(self, "_bot", None)
        if bot is not None:
            fill_buy(bot, order)
        return order

    def sell_limited(
        self,
        stock_data,
        balance: float,
        last_buy_price: float,
        acceptable_loss_pct: float,
        min_sell_price_fn,
        price: float = 0,
    ):
        close_price = float(stock_data["close_price"].iloc[-1])
        self.client.mark_price = close_price
        order = self.client.create_order(
            symbol=self.operation_code,
            side="SELL",
            type="LIMIT",
            quantity=balance,
            price=close_price,
        )
        bot = getattr(self, "_bot", None)
        if bot is not None:
            fill_sell(bot, order)
        return order


def build_replay_engine(
    stock_data: pd.DataFrame,
    *,
    store: StateStore,
    quote_balance: float = 1000.0,
    base_balance: float = 0.0,
    main_strategy=None,
    fallback_activated: bool = False,
    regime_enabled: bool = False,
    stop_loss_pct: float = 2.0,
    trailing_stop_loss: bool = False,
    max_daily_loss_usdt: float = 10_000.0,
):
    from core.trading_engine import TradingEngine

    bot = FakeBot(
        stock_data=stock_data,
        quote_balance=quote_balance,
        base_balance=base_balance,
        main_strategy=main_strategy,
        fallback_activated=fallback_activated,
        stop_loss_pct=stop_loss_pct,
    )
    market = ReplayMarketData(stock_data)
    executor = ReplayOrderExecutor(
        bot.broker, bot.operation_code, bot.stock_code, bot.tick_size, bot.step_size
    )
    executor._bot = bot
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=stop_loss_pct,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=max_daily_loss_usdt,
        max_trades_per_day=50,
        trailing_stop_loss=trailing_stop_loss,
        state_store=store,
        operation_code=bot.operation_code,
    )
    regime = RegimeDetector(enabled=regime_enabled, min_candles=60)
    engine = TradingEngine(
        bot=bot,
        market_data=market,
        order_executor=executor,
        risk_manager=risk,
        state_store=store,
        regime_detector=regime,
        sleep=lambda _s: None,
    )
    bot._sync_account()
    return bot, engine
