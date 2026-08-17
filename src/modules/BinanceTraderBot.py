import logging
import time
from datetime import datetime

from binance.exceptions import BinanceAPIException

from core.trading_engine import TradingEngine
from modules.BinanceClient import BinanceClient
from modules.alerts import send_alert
from persistence.state_store import StateStore
from services.market_data import MarketDataService
from services.order_executor import OrderExecutor
from services.risk_manager import RiskManager
from services.regime_detector import RegimeDetector


def _validate_api_keys(api_key: str, secret_key: str):
    missing = []
    if not api_key:
        missing.append("BINANCE_API_KEY")
    if not secret_key:
        missing.append("BINANCE_SECRET_KEY")
    if missing:
        raise ValueError(
            "Missing Binance API credentials: "
            + ", ".join(missing)
            + ". Create a .env file in the project root."
        )


def _validate_trading_permissions(client, testnet: bool):
    try:
        permissions = client.get_account_api_permissions()
    except BinanceAPIException as e:
        env_label = "testnet" if testnet else "mainnet"
        if e.code == -2008:
            raise ValueError(
                f"Invalid Binance API key (code -2008). Verify keys for {env_label}."
            ) from e
        if e.code == -2015:
            raise ValueError(
                f"Binance API key rejected (code -2015). Check permissions and {env_label} keys."
            ) from e
        raise

    if not permissions.get("enableSpotAndMarginTrading"):
        raise ValueError(
            "API key has read access but Spot Trading is disabled."
        )
    if permissions.get("ipRestrict"):
        logging.warning("API key has IP restriction enabled.")


class BinanceTraderBot:
    """Facade delegating to TradingEngine for backward compatibility."""

    last_trade_decision = None
    last_buy_price = 0
    last_sell_price = 0
    open_orders = []
    partial_quantity_discount = 0
    take_profit_index = 0

    def __init__(
        self,
        stock_code,
        operation_code,
        traded_quantity,
        traded_percentage,
        candle_period,
        time_to_trade=30 * 60,
        delay_after_order=60 * 60,
        acceptable_loss_percentage=0.5,
        stop_loss_percentage=3.5,
        fallback_activated=True,
        take_profit_at_percentage=None,
        take_profit_amount_percentage=None,
        main_strategy=None,
        main_strategy_args=None,
        fallback_strategy=None,
        fallback_strategy_args=None,
        api_key=None,
        secret_key=None,
        testnet=False,
        risk_config=None,
        alerts_config=None,
        regime_config=None,
        state_store=None,
    ):
        print("------------------------------------------------")
        print("Robo Trader iniciando...")

        take_profit_at_percentage = take_profit_at_percentage or []
        take_profit_amount_percentage = take_profit_amount_percentage or []
        risk_config = risk_config or {}
        alerts_config = alerts_config or {}
        regime_config = regime_config or {}

        self.stock_code = stock_code
        self.operation_code = operation_code
        self.traded_quantity = traded_quantity
        self.traded_percentage = traded_percentage
        self.candle_period = candle_period
        self.fallback_activated = fallback_activated
        self.acceptable_loss_percentage = acceptable_loss_percentage
        self.stop_loss_percentage = stop_loss_percentage
        self.take_profit_at_percentage = take_profit_at_percentage
        self.take_profit_amount_percentage = take_profit_amount_percentage
        self.main_strategy = main_strategy
        self.main_strategy_args = main_strategy_args or {}
        self.fallback_strategy = fallback_strategy
        self.fallback_strategy_args = fallback_strategy_args or {}
        self.time_to_trade = time_to_trade
        self.delay_after_order = delay_after_order
        self.time_to_sleep = time_to_trade
        self.testnet = testnet

        from dotenv import load_dotenv
        import os

        load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")))
        api_key = api_key or os.getenv("BINANCE_API_KEY")
        secret_key = secret_key or os.getenv("BINANCE_SECRET_KEY")

        _validate_api_keys(api_key, secret_key)
        self.client_binance = BinanceClient(
            api_key, secret_key, sync=True, sync_interval=30000, verbose=False, testnet=testnet
        )
        _validate_trading_permissions(self.client_binance, testnet)

        self.market_data = MarketDataService(
            self.client_binance, operation_code, candle_period
        )
        filters = self.market_data.get_symbol_filters()
        self.tick_size = filters["tick_size"]
        self.step_size = filters["step_size"]
        self.min_notional = filters["min_notional"]
        self.quote_asset = filters["quote_asset"]

        self.order_executor = OrderExecutor(
            self.client_binance,
            operation_code,
            stock_code,
            self.tick_size,
            self.step_size,
        )
        self.risk_manager = RiskManager(
            acceptable_loss_pct=acceptable_loss_percentage,
            stop_loss_pct=stop_loss_percentage,
            take_profit_at=take_profit_at_percentage,
            take_profit_amount=take_profit_amount_percentage,
            max_daily_loss_usdt=risk_config.get("max_daily_loss_usdt", 100.0),
            max_trades_per_day=risk_config.get("max_trades_per_day", 50),
            max_open_orders=risk_config.get("max_open_orders", 5),
            circuit_breaker_errors=risk_config.get("circuit_breaker_errors", 5),
            circuit_breaker_pause_seconds=risk_config.get(
                "circuit_breaker_pause_seconds", 300
            ),
        )
        self.state_store = state_store or StateStore()
        self.alerts_config = alerts_config
        self.regime_detector = RegimeDetector(**regime_config) if regime_config else RegimeDetector(enabled=False)

        self.engine = TradingEngine(
            bot=self,
            market_data=self.market_data,
            order_executor=self.order_executor,
            risk_manager=self.risk_manager,
            state_store=self.state_store,
            alerts_config=alerts_config,
            regime_detector=self.regime_detector,
        )
        self.engine.bootstrap()

    def setStepSizeAndTickSize(self):
        filters = self.market_data.get_symbol_filters()
        self.tick_size = filters["tick_size"]
        self.step_size = filters["step_size"]
        self.min_notional = filters["min_notional"]

    def adjust_to_step(self, value, step=None, as_string=False):
        return MarketDataService.adjust_to_step(
            value, step or self.step_size, as_string
        )

    def updateAllData(self, verbose=False):
        self.engine.update_all_data(verbose=verbose)

    def getUpdatedAccountData(self):
        return self.client_binance.get_account()

    def getLastStockAccountBalance(self):
        return self.market_data.get_account_balance(
            self.stock_code, self.account_data
        )

    def getActualTradePosition(self):
        return self.market_data.is_position_open(
            self.last_stock_account_balance, self.step_size
        )

    def getStockData(self):
        return self.market_data.fetch_klines()

    def getLastBuyPrice(self, verbose=False):
        orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
        return self.market_data.get_last_fill_price(orders, "BUY")

    def getLastSellPrice(self, verbose=False):
        orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
        return self.market_data.get_last_fill_price(orders, "SELL")

    def getOpenOrders(self):
        return self.client_binance.get_open_orders(symbol=self.operation_code)

    def cancelAllOrders(self):
        self.order_executor.cancel_all_orders(self.open_orders)

    def getMinimumPriceToSell(self):
        return self.risk_manager.get_minimum_price_to_sell(self.last_buy_price)

    def stopLossTrigger(self):
        return self.engine._handle_stop_loss()

    def takeProfitTrigger(self):
        return self.engine._handle_take_profit()

    def getFinalDecisionStrategy(self):
        from modules.StrategyRunner import StrategyRunner

        return StrategyRunner.execute(
            self,
            stock_data=self.stock_data,
            main_strategy=self.main_strategy,
            main_strategy_args=self.main_strategy_args,
            fallback_strategy=self.fallback_strategy,
            fallback_strategy_args=self.fallback_strategy_args,
        )

    def buyMarketOrder(self, quantity=None):
        qty = quantity or self.last_stock_account_balance
        return self.order_executor.buy_market(qty, self.actual_trade_position)

    def sellMarketOrder(self, quantity=None):
        qty = quantity or self.last_stock_account_balance
        return self.order_executor.sell_market(qty, self.actual_trade_position)

    def buyLimitedOrder(self, price=0):
        return self.engine._place_buy(price)

    def sellLimitedOrder(self, price=0):
        return self.engine._place_sell(price)

    def hasOpenBuyOrder(self):
        has, partial, last_price = self.order_executor.has_open_buy_order()
        self.partial_quantity_discount = partial
        if last_price > 0:
            self.last_buy_price = last_price
        return has

    def hasOpenSellOrder(self):
        has, partial = self.order_executor.has_open_sell_order()
        self.partial_quantity_discount = partial
        return has

    def execute(self):
        self.engine.execute()

    def printStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                print(stock)

    def printOpenOrders(self):
        if self.open_orders:
            for order in self.open_orders:
                print(order)
        else:
            print(f"No open orders for {self.operation_code}")

    def getPriceChangePercentage(self, initial_price, close_price):
        return self.risk_manager.get_price_change_pct(initial_price, close_price)
