import logging
import time
from datetime import datetime

from binance.exceptions import BinanceAPIException

from modules.StrategyRunner import StrategyRunner
from modules.alerts import send_alert
from modules.logging_setup import log_event
from persistence.state_store import BotState
from services.order_executor import OrderExecutor


class TradingEngine:
    def __init__(
        self,
        bot,
        market_data,
        order_executor: OrderExecutor,
        risk_manager,
        state_store,
        alerts_config=None,
        regime_detector=None,
    ):
        self.bot = bot
        self.market_data = market_data
        self.order_executor = order_executor
        self.risk_manager = risk_manager
        self.state_store = state_store
        self.alerts_config = alerts_config or {}
        self.regime_detector = regime_detector
        self.state = BotState(operation_code=bot.operation_code)

    def bootstrap(self):
        self.state = self.state_store.load_state(self.bot.operation_code)
        self.update_all_data(verbose=False)
        self.state = self.state_store.reconcile(
            self.state,
            self.bot.actual_trade_position,
            self.bot.last_buy_price,
            self.bot.last_sell_price,
        )
        self._sync_state_to_bot()

    def _sync_state_to_bot(self):
        self.bot.take_profit_index = self.state.take_profit_index
        self.bot.last_buy_price = self.state.last_buy_price
        self.bot.last_sell_price = self.state.last_sell_price
        self.bot.last_trade_decision = self.state.last_trade_decision

    def _sync_bot_to_state(self):
        self.state.take_profit_index = self.bot.take_profit_index
        self.state.last_buy_price = self.bot.last_buy_price
        self.state.last_sell_price = self.bot.last_sell_price
        self.state.last_trade_decision = self.bot.last_trade_decision
        self.state.actual_trade_position = self.bot.actual_trade_position
        self.state_store.save_state(self.state)

    def update_all_data(self, verbose=False):
        try:
            self.bot.account_data = self.bot.getUpdatedAccountData()
            self.risk_manager.record_api_success()
            self.bot.last_stock_account_balance = self.bot.getLastStockAccountBalance()
            self.bot.actual_trade_position = self.bot.getActualTradePosition()
            self.bot.stock_data = self.market_data.fetch_klines()
            self.bot.open_orders = self.bot.getOpenOrders()
            self.bot.last_buy_price = self.bot.getLastBuyPrice(verbose)
            self.bot.last_sell_price = self.bot.getLastSellPrice(verbose)
            if not self.bot.actual_trade_position:
                self.bot.take_profit_index = 0
        except BinanceAPIException as e:
            self.risk_manager.record_api_error()
            logging.error("Data update failed for %s: %s", self.bot.operation_code, e)
            raise

    def _quote_balance(self) -> float:
        return self.market_data.get_account_balance(
            self.bot.quote_asset, self.bot.account_data
        )

    def _check_regime(self):
        if not self.regime_detector or not self.regime_detector.enabled:
            return None
        return self.regime_detector.evaluate(self.bot.stock_data)

    def _handle_stop_loss(self) -> bool:
        if not self.risk_manager.check_stop_loss(
            self.bot.stock_data,
            self.bot.last_buy_price,
            self.bot.actual_trade_position,
        ):
            return False

        log_event(
            logging.WARNING,
            "Stop loss triggered",
            operation_code=self.bot.operation_code,
            event="stop_loss",
        )
        send_alert(
            self.alerts_config.get("webhook_url", ""),
            "Stop Loss",
            f"{self.bot.operation_code} stop loss triggered",
            self.alerts_config.get("enabled", False),
        )
        self.bot.cancelAllOrders()
        time.sleep(2)
        order = self.bot.sellMarketOrder()
        if OrderExecutor.is_filled(order):
            self.bot.actual_trade_position = False
            self.bot.take_profit_index = 0
            self._sync_bot_to_state()
        return True

    def _handle_take_profit(self) -> bool:
        result = self.risk_manager.check_take_profit(
            self.bot.stock_data,
            self.bot.last_buy_price,
            self.bot.actual_trade_position,
            self.bot.take_profit_index,
            self.bot.last_stock_account_balance,
        )
        if not result:
            return False

        quantity, tp_pct, new_index = result
        order = self.bot.sellMarketOrder(quantity=quantity)
        if OrderExecutor.is_filled(order):
            self.bot.take_profit_index = new_index
            self.state_store.log_order(self.bot.operation_code, order)
            if quantity >= self.bot.last_stock_account_balance * 0.99:
                self.bot.actual_trade_position = False
            self._sync_bot_to_state()
            log_event(
                logging.INFO,
                "Take profit executed",
                operation_code=self.bot.operation_code,
                event="take_profit",
                tp_pct=tp_pct,
            )
            return True
        return False

    def _resolve_quantity(self, side: str) -> float:
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        return self.risk_manager.compute_trade_quantity(
            self.bot.traded_quantity,
            self.bot.traded_percentage,
            self.bot.last_stock_account_balance,
            self._quote_balance(),
            close_price,
            side,
        )

    def _validate_before_order(self, side: str, quantity: float, price: float) -> bool:
        ok, reason = self.risk_manager.validate_order(
            side=side,
            quantity=quantity,
            price=price,
            quote_balance=self._quote_balance(),
            base_balance=self.bot.last_stock_account_balance,
            min_notional=self.bot.min_notional,
            step_size=self.bot.step_size,
            open_orders_count=len(self.bot.open_orders),
        )
        if not ok:
            logging.warning(
                "Order blocked for %s: %s", self.bot.operation_code, reason
            )
            return False
        if self.risk_manager.should_stop_trading_daily_loss():
            logging.warning("Daily loss limit reached for %s", self.bot.operation_code)
            return False
        return True

    def _place_buy(self, price=0):
        quantity = self._resolve_quantity("BUY")
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        if not self._validate_before_order("BUY", quantity, close_price):
            return False
        order = self.order_executor.buy_limited(
            self.bot.stock_data, quantity, price
        )
        if OrderExecutor.is_filled(order):
            self.bot.actual_trade_position = True
            self.state_store.log_order(self.bot.operation_code, order)
            self.risk_manager.record_trade_pnl(0)
        elif OrderExecutor.is_order_active(order):
            self.bot.actual_trade_position = True
        self._sync_bot_to_state()
        return order

    def _place_sell(self, price=0):
        quantity = self.bot.last_stock_account_balance
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        if not self._validate_before_order("SELL", quantity, close_price):
            return False
        order = self.order_executor.sell_limited(
            self.bot.stock_data,
            quantity,
            self.bot.last_buy_price,
            self.bot.acceptable_loss_percentage / 100,
            self.bot.getMinimumPriceToSell,
            price,
        )
        if OrderExecutor.is_filled(order):
            self.bot.actual_trade_position = False
            self.bot.take_profit_index = 0
            self.state_store.log_order(self.bot.operation_code, order)
            self.risk_manager.record_trade_pnl(0)
        elif OrderExecutor.is_order_active(order):
            pass
        self._sync_bot_to_state()
        return order

    def execute(self):
        if self.risk_manager.is_circuit_open():
            logging.warning("Circuit breaker open, skipping cycle for %s", self.bot.operation_code)
            self.bot.time_to_sleep = self.bot.time_to_trade
            return

        print("------------------------------------------------")
        print(f'Executado {datetime.now().strftime("(%H:%M:%S) %d-%m-%Y")}\n')

        self.update_all_data(verbose=True)
        self._sync_state_to_bot()

        print("\n-------")
        print("Detalhes:")
        print(f' - Posição atual: {"Comprado" if self.bot.actual_trade_position else "Vendido"}')
        print(f" - Balanço atual: {self.bot.last_stock_account_balance:.4f} ({self.bot.stock_code})")

        if self._handle_stop_loss():
            print("\nSTOP LOSS finalizado.\n")
            return

        if self.bot.actual_trade_position and self._handle_take_profit():
            print("\nTAKE PROFIT finalizado.\n")
            return

        regime = self._check_regime()
        if regime and regime.regime in ("LATERAL", "GRAY"):
            log_event(
                logging.INFO,
                "Regime pause: strategy skipped",
                operation_code=self.bot.operation_code,
                event="regime_pause",
                regime=regime.regime,
                score=regime.score,
                adx=regime.adx_value,
                rsi=regime.rsi_value,
                signals=regime.signals,
            )
            print(
                f"\nRegime {regime.regime} (score={regime.score}, "
                f"ADX={regime.adx_value:.1f}, RSI={regime.rsi_value:.1f}) — pausando estrategia"
            )
            print(f" - Sinais: {regime.signals}")
            self.bot.time_to_sleep = self.bot.time_to_trade
            self._sync_bot_to_state()
            print("------------------------------------------------")
            return

        self.bot.last_trade_decision = StrategyRunner.execute(
            self.bot,
            stock_data=self.bot.stock_data,
            main_strategy=self.bot.main_strategy,
            main_strategy_args=self.bot.main_strategy_args,
            fallback_strategy=self.bot.fallback_strategy,
            fallback_strategy_args=self.bot.fallback_strategy_args,
        )
        self.state.last_trade_decision = self.bot.last_trade_decision

        if self.bot.last_trade_decision is True:
            if self.bot.hasOpenBuyOrder():
                self.bot.cancelAllOrders()
                time.sleep(2)

        if self.bot.last_trade_decision is False:
            if self.bot.hasOpenSellOrder():
                self.bot.cancelAllOrders()
                time.sleep(2)

        print("\n--------------")
        decision_label = (
            "Comprar"
            if self.bot.last_trade_decision is True
            else "Vender"
            if self.bot.last_trade_decision is False
            else "Inconclusiva"
        )
        print(f"Decisão Final: {decision_label}")

        if (
            not self.bot.actual_trade_position
            and self.bot.last_trade_decision is True
        ):
            print("Ação final: Comprar")
            self.bot.printStock()
            self._place_buy()
            time.sleep(2)
            self.update_all_data()
            self.bot.printStock()
            self.bot.time_to_sleep = self.bot.delay_after_order

        elif (
            self.bot.actual_trade_position
            and self.bot.last_trade_decision is False
        ):
            print("Ação final: Vender")
            self.bot.printStock()
            self._place_sell()
            time.sleep(2)
            self.update_all_data()
            self.bot.printStock()
            self.bot.time_to_sleep = self.bot.delay_after_order

        else:
            print(
                f'Ação final: Manter posição ({"Comprado" if self.bot.actual_trade_position else "Vendido"})'
            )
            self.bot.time_to_sleep = self.bot.time_to_trade

        self._sync_bot_to_state()
        print("------------------------------------------------")
