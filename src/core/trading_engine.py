import logging
import time
from datetime import datetime, timezone

from binance.exceptions import BinanceAPIException

from modules.StrategyRunner import StrategyRunner
from modules.alerts import send_alert
from modules.logging_setup import log_event
from persistence.state_store import BotState
from strategies.decision import StrategyDecision
from services.asset_variation import (
    compute_candle_variation,
    format_held_position_label,
    format_variation_message,
    unrealized_pnl_pct,
)
from services.market_data import MarketDataService, last_candle_epoch
from services.order_executor import OrderExecutor
from services.outcome_history import fill_from_order, realized_pnl
from services.regime_router import can_run_grid, resolve_regime_action
from strategies.atr_trend import get_atr_trend_snapshot


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
        grid_manager=None,
        breakout_detector=None,
        breakout_price: float = 0.0,
        sleep=None,
    ):
        self.bot = bot
        self.market_data = market_data
        self.order_executor = order_executor
        self.risk_manager = risk_manager
        self.state_store = state_store
        self.alerts_config = alerts_config or {}
        self.regime_detector = regime_detector
        self.grid_manager = grid_manager
        self.breakout_detector = breakout_detector
        self.breakout_price = breakout_price
        self._sleep = time.sleep if sleep is None else sleep
        self._last_strategy_decision: StrategyDecision | None = None
        self.state = BotState(operation_code=bot.operation_code)
        if getattr(bot, "engine", None) is None:
            bot.engine = self

    def bootstrap(self):
        self.state = self.state_store.load_state(self.bot.operation_code)
        self.update_all_data(verbose=False)
        self.state = self.state_store.reconcile(
            self.state,
            self.bot.actual_trade_position,
            self.bot.last_buy_price,
            self.bot.last_sell_price,
        )

    def _save_state(self):
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

    def _check_breakout(self):
        if not self.breakout_detector or not self.breakout_detector.enabled:
            return None
        if self.breakout_price <= 0:
            return None
        return self.breakout_detector.evaluate(self.bot.stock_data, self.breakout_price)

    def _can_run_grid(self, regime) -> bool:
        return can_run_grid(
            regime,
            grid_manager=self.grid_manager,
            regime_detector=self.regime_detector,
            breakout_detector=self.breakout_detector,
            breakout_cooldown_candles=self.state.breakout_cooldown_candles,
        )

    def _resolve_regime_action(self, regime, breakout) -> str:
        return resolve_regime_action(
            regime,
            breakout,
            regime_detector=self.regime_detector,
            grid_manager=self.grid_manager,
            breakout_detector=self.breakout_detector,
            breakout_cooldown_candles=self.state.breakout_cooldown_candles,
        )

    def _decision_label(self, decision) -> str:
        side = decision.side if isinstance(decision, StrategyDecision) else decision
        if side is True:
            return "Comprar"
        if side is False:
            return "Vender"
        return "Inconclusiva"

    def _current_mark_price(self) -> float:
        data = self.bot.stock_data
        if data is None or len(data) == 0:
            return 0.0
        return float(data["close_price"].iloc[-1])

    def _held_position_label(self) -> str:
        return format_held_position_label(
            self.bot.stock_code,
            float(self.bot.last_stock_account_balance),
            self._current_mark_price(),
            float(self.bot.last_buy_price or 0),
        )

    def _get_strategy_snapshot(self) -> dict | None:
        if getattr(self.bot.main_strategy, "__name__", "") == "getAtrTrendStrategy":
            return get_atr_trend_snapshot(
                self.bot.stock_data,
                **(self.bot.main_strategy_args or {}),
            )
        return None

    def _log_cycle_summary(
        self,
        *,
        regime,
        action: str,
        final_action: str,
        variation: dict | None = None,
    ):
        strategy = self._get_strategy_snapshot()
        in_position = bool(self.bot.actual_trade_position)
        payload = {
            "operation_code": self.bot.operation_code,
            "stock_code": self.bot.stock_code,
            "event": "cycle_summary",
            "position": "Comprado" if in_position else "Vendido",
            "balance": round(self.bot.last_stock_account_balance, 8),
            "quote_balance": round(self._quote_balance(), 4),
            "last_buy_price": round(self.bot.last_buy_price, 4),
            "last_sell_price": round(self.bot.last_sell_price, 4),
            "decision": self._decision_label(
                self._last_strategy_decision or self.bot.last_trade_decision
            ),
            "final_action": final_action,
            "time_to_sleep_min": round(self.bot.time_to_sleep / 60, 2),
            "active_mode": self.state.active_mode,
            "regime_action": action,
        }
        if in_position:
            mark_price = self._current_mark_price()
            quantity = float(self.bot.last_stock_account_balance)
            pnl_pct = unrealized_pnl_pct(mark_price, float(self.bot.last_buy_price or 0))
            payload["position_qty"] = round(quantity, 8)
            payload["mark_price"] = round(mark_price, 4)
            payload["position_value_usd"] = round(quantity * mark_price, 4)
            if pnl_pct is not None:
                payload["unrealized_pnl_pct"] = round(pnl_pct, 2)
        if variation:
            payload.update(
                {
                    "variation_pct": variation.get("variation_pct"),
                    "variation_direction": variation.get("direction"),
                    "close_price": variation.get("close_price"),
                    "candle_period": self.bot.candle_period,
                }
            )
        if regime:
            payload.update(
                {
                    "regime": regime.regime,
                    "regime_score": regime.score,
                    "adx": round(regime.adx_value, 2),
                    "rsi": round(regime.rsi_value, 2),
                }
            )
        if strategy:
            payload["strategy"] = strategy
        if self._last_strategy_decision:
            payload["strategy_source"] = self._last_strategy_decision.source
            payload["strategy_reason"] = self._last_strategy_decision.reason

        log_event(
            logging.INFO,
            f"Ciclo {self.bot.operation_code}: {final_action}",
            **payload,
        )

    def _log_order_blocked(self, side: str, reason: str):
        log_event(
            logging.WARNING,
            f"Order blocked for {self.bot.operation_code}: {reason}",
            operation_code=self.bot.operation_code,
            event="order_blocked",
            side=side,
            reason=reason,
        )

    def _log_asset_variation(self):
        variation = compute_candle_variation(self.bot.stock_data)
        if not variation:
            return None
        message = format_variation_message(
            self.bot.stock_code,
            variation["variation_pct"],
            self.bot.candle_period,
            variation["close_price"],
        )
        log_event(
            logging.INFO,
            message,
            event="asset_variation",
            operation_code=self.bot.operation_code,
            stock_code=self.bot.stock_code,
            candle_period=self.bot.candle_period,
            **variation,
        )
        print(f" - {message}")
        return variation

    def _log_regime_detected(self, regime, breakout, action: str):
        payload = {
            "operation_code": self.bot.operation_code,
            "event": "regime_detected",
            "action": action,
            "active_mode": self.state.active_mode,
        }
        if not self.regime_detector or not self.regime_detector.enabled:
            payload["regime"] = "DISABLED"
            log_event(logging.INFO, "Regime detected", **payload)
            print("\nRegime: DISABLED -> atr_trend")
            return
        if not regime:
            return

        payload.update(
            {
                "regime": regime.regime,
                "score": regime.score,
                "adx": round(regime.adx_value, 2),
                "rsi": round(regime.rsi_value, 2),
                "signals": regime.signals,
            }
        )
        if regime.support is not None:
            payload["support"] = round(regime.support, 2)
            payload["resistance"] = round(regime.resistance, 2)
            payload["channel_width_pct"] = round(regime.channel_width_pct, 2)
        if breakout:
            payload["breakout_confirmed"] = breakout.confirmed
            if self.breakout_price > 0:
                payload["breakout_price"] = self.breakout_price
            payload["volume_ratio"] = round(breakout.volume_ratio, 2)

        log_event(logging.INFO, "Regime detected", **payload)
        self._save_regime_history(regime, action)
        print(
            f"\nRegime: {regime.regime} (score={regime.score}, "
            f"ADX={regime.adx_value:.1f}, RSI={regime.rsi_value:.1f}) -> {action}"
        )

    def _save_regime_history(self, regime, action: str):
        """Record the regime of the current candle so the chart shows history.

        Later cycles inside the same candle replace this row. Persisting is a
        dashboard concern, so a failure here must never abort a trading cycle.
        """
        candle_time = last_candle_epoch(self.bot.stock_data)
        if candle_time is None:
            return
        try:
            self.state_store.save_regime(
                self.bot.operation_code,
                candle_time,
                regime.regime,
                score=regime.score,
                adx=round(regime.adx_value, 2),
                rsi=round(regime.rsi_value, 2),
                action=action,
                source="live",
            )
        except Exception:
            logging.exception(
                "Failed to persist regime history for %s", self.bot.operation_code
            )

    def _shutdown_grid(self):
        if not self.grid_manager:
            return
        cancelled = self.grid_manager.shutdown(self.order_executor, self.bot.open_orders)
        if cancelled:
            log_event(
                logging.INFO,
                "Grid orders cancelled",
                operation_code=self.bot.operation_code,
                event="grid_shutdown",
                cancelled=cancelled,
            )
        self.state.active_mode = "trend"
        self.state.grid_support = 0.0
        self.state.grid_resistance = 0.0

    def _run_grid_cycle(self, regime):
        self.state.active_mode = "grid"
        self.state.grid_support = regime.support or 0.0
        self.state.grid_resistance = regime.resistance or 0.0
        result = self.grid_manager.sync_grid(
            bot=self.bot,
            order_executor=self.order_executor,
            risk_manager=self.risk_manager,
            regime=regime,
            operation_code=self.bot.operation_code,
            quote_balance=self._quote_balance(),
            base_balance=self.bot.last_stock_account_balance,
            open_orders=self.bot.open_orders,
            min_notional=self.bot.min_notional,
            step_size=self.bot.step_size,
        )
        print(
            f"\nGrid ativo: S={regime.support:.2f} R={regime.resistance:.2f} "
            f"({regime.channel_width_pct:.2f}%) — ordens colocadas: {result.get('placed', 0)}"
        )
        self.bot.time_to_sleep = self.bot.time_to_trade
        self._save_state()
        print("------------------------------------------------")

    def _record_closed_trade(self, kind: str, order: dict, extra: dict | None = None):
        quantity, sell_price, quote_qty = fill_from_order(order)
        buy_price = float(self.bot.last_buy_price or 0)
        pnl_usd, pnl_pct = realized_pnl(quantity, buy_price, sell_price)
        cost_usd = quantity * buy_price if quantity > 0 and buy_price > 0 else None
        inserted = self.state_store.record_outcome(
            {
                "kind": kind,
                "operation_code": self.bot.operation_code,
                "stock_code": self.bot.stock_code,
                "quantity": quantity or None,
                "buy_price": buy_price or None,
                "sell_price": sell_price or None,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "quote_qty": quote_qty or None,
                "order_id": order.get("orderId"),
                "source": "live",
                "filled": True,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if inserted:
            self.risk_manager.record_trade_pnl(float(pnl_usd or 0))
        payload = {
            "operation_code": self.bot.operation_code,
            "stock_code": self.bot.stock_code,
            "event": kind,
            "quantity": quantity,
            "buy_price": round(buy_price, 4) if buy_price else None,
            "sell_price": round(sell_price, 4) if sell_price else None,
            "cost_usd": None if cost_usd is None else round(cost_usd, 4),
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
        }
        if extra:
            payload.update(extra)
        if kind == "take_profit":
            message = "Take profit executed"
            level = logging.INFO
        elif kind == "stop_loss":
            message = "Stop loss executed"
            level = logging.WARNING
        else:
            message = "Sell executed"
            level = logging.INFO
        log_event(level, message, **payload)

    def _handle_stop_loss(self) -> bool:
        if not self.risk_manager.check_stop_loss(
            self.bot.stock_data,
            self.bot.last_buy_price,
            self.bot.actual_trade_position,
        ):
            return False

        send_alert(
            self.alerts_config.get("webhook_url", ""),
            "Stop Loss",
            f"{self.bot.operation_code} stop loss triggered",
            self.alerts_config.get("enabled", False),
        )
        self.bot.cancelAllOrders()
        self._sleep(2)
        try:
            order = self.bot.sellMarketOrder()
        except BinanceAPIException as e:
            self.risk_manager.record_api_error()
            self._log_order_blocked("SELL", str(e))
            return False
        if OrderExecutor.is_filled(order):
            self.state_store.log_order(self.bot.operation_code, order)
            self._record_closed_trade("stop_loss", order)
            self.bot.actual_trade_position = False
            self.bot.take_profit_index = 0
            self._save_state()
            return True
        return False

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
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        quantity = MarketDataService.size_quantity_for_filters(
            quantity=quantity,
            price=close_price,
            step_size=self.bot.step_size,
            min_notional=self.bot.min_notional,
            bump_to_min_notional=False,
        )
        if quantity <= 0:
            self._log_order_blocked(
                "SELL",
                "take profit notional below exchange minimum",
            )
            return False
        try:
            order = self.bot.sellMarketOrder(quantity=quantity)
        except BinanceAPIException as e:
            self.risk_manager.record_api_error()
            self._log_order_blocked("SELL", str(e))
            return False
        if OrderExecutor.is_filled(order):
            self.bot.take_profit_index = new_index
            self.state_store.log_order(self.bot.operation_code, order)
            self._record_closed_trade("take_profit", order, extra={"tp_pct": tp_pct})
            if quantity >= self.bot.last_stock_account_balance * 0.99:
                self.bot.actual_trade_position = False
            self._save_state()
            return True
        return False

    def _resolve_quantity(self, side: str) -> float:
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        # Limit buys can sit ~0.2% below last close; size against that so NOTIONAL still holds.
        sizing_price = close_price * (0.998 if side == "BUY" else 0.995)
        return self.risk_manager.compute_trade_quantity(
            self.bot.traded_quantity,
            self.bot.traded_percentage,
            self.bot.last_stock_account_balance,
            self._quote_balance(),
            sizing_price,
            side,
            min_notional=self.bot.min_notional,
            step_size=self.bot.step_size,
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
            self._log_order_blocked(side, reason)
            return False
        return True

    def _place_buy(self, price=0):
        quantity = self._resolve_quantity("BUY")
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        if not self._validate_before_order("BUY", quantity, close_price * 0.998):
            return False
        try:
            order = self.order_executor.buy_limited(
                self.bot.stock_data, quantity, price
            )
        except BinanceAPIException as e:
            self.risk_manager.record_api_error()
            self._log_order_blocked("BUY", str(e))
            return False
        if OrderExecutor.is_filled(order):
            self.bot.actual_trade_position = True
            if self.state_store.log_order(self.bot.operation_code, order):
                self.risk_manager.record_trade_pnl(0)
        elif OrderExecutor.is_order_active(order):
            self.bot.actual_trade_position = True
        self._save_state()
        return order

    def _place_sell(self, price=0):
        close_price = float(self.bot.stock_data["close_price"].iloc[-1])
        quantity = MarketDataService.size_quantity_for_filters(
            quantity=self.bot.last_stock_account_balance,
            price=close_price * 0.995,
            step_size=self.bot.step_size,
            min_notional=self.bot.min_notional,
            bump_to_min_notional=False,
        )
        if not self._validate_before_order("SELL", quantity, close_price * 0.995):
            return False
        try:
            order = self.order_executor.sell_limited(
                self.bot.stock_data,
                quantity,
                self.bot.last_buy_price,
                self.bot.acceptable_loss_percentage / 100,
                self.bot.getMinimumPriceToSell,
                price,
            )
        except BinanceAPIException as e:
            self.risk_manager.record_api_error()
            self._log_order_blocked("SELL", str(e))
            return False
        if OrderExecutor.is_filled(order):
            self.bot.actual_trade_position = False
            self.bot.take_profit_index = 0
            self.state_store.log_order(self.bot.operation_code, order)
            self._record_closed_trade("sell", order)
        elif OrderExecutor.is_order_active(order):
            pass
        self._save_state()
        return order

    def execute(self):
        if self.risk_manager.is_circuit_open():
            logging.warning("Circuit breaker open, skipping cycle for %s", self.bot.operation_code)
            self.bot.time_to_sleep = self.bot.time_to_trade
            return

        print("------------------------------------------------")
        print(f'Executado {datetime.now().strftime("(%H:%M:%S) %d-%m-%Y")}\n')

        self.update_all_data(verbose=True)

        print("\n-------")
        print("Detalhes:")
        print(f' - Posição atual: {"Comprado" if self.bot.actual_trade_position else "Vendido"}')
        print(f" - Balanço atual: {self.bot.last_stock_account_balance:.4f} ({self.bot.stock_code})")
        variation = self._log_asset_variation()

        if self._handle_stop_loss():
            print("\nSTOP LOSS finalizado.\n")
            self.bot.time_to_sleep = self.bot.time_to_trade
            self._save_state()
            self._log_cycle_summary(
                regime=None,
                action="stop_loss",
                final_action="Stop loss",
                variation=variation,
            )
            print("------------------------------------------------")
            return

        if self.bot.actual_trade_position and self._handle_take_profit():
            print("\nTAKE PROFIT finalizado.\n")
            self.bot.time_to_sleep = self.bot.delay_after_order
            self._save_state()
            self._log_cycle_summary(
                regime=None,
                action="take_profit",
                final_action="Take profit",
                variation=variation,
            )
            print("------------------------------------------------")
            return

        regime = self._check_regime()
        breakout = self._check_breakout()
        action = self._resolve_regime_action(regime, breakout)
        self._log_regime_detected(regime, breakout, action)

        if breakout and breakout.confirmed:
            if self.state.active_mode == "grid":
                self._shutdown_grid()
            self.state.active_mode = "trend"
            if self.breakout_detector:
                self.state.breakout_cooldown_candles = self.breakout_detector.cooldown_candles
            log_event(
                logging.INFO,
                "Breakout confirmed — atr_trend reactivated",
                operation_code=self.bot.operation_code,
                event="regime_resume_breakout",
                price=breakout.price,
                adx=breakout.adx_value,
                volume_ratio=round(breakout.volume_ratio, 2),
                signals=breakout.signals,
            )
            send_alert(
                self.alerts_config.get("webhook_url", ""),
                "Breakout",
                (
                    f"{self.bot.operation_code} breakout at {breakout.price:.2f} "
                    f"(ADX={breakout.adx_value:.1f}, vol={breakout.volume_ratio:.1f}x)"
                ),
                self.alerts_config.get("enabled", False),
            )
            print(
                f"\nBreakout confirmado: preco={breakout.price:.2f}, "
                f"ADX={breakout.adx_value:.1f}, volume={breakout.volume_ratio:.1f}x "
                f"— reativando atr_trend"
            )
        elif action == "grid":
            self._run_grid_cycle(regime)
            return

        elif action == "pause":
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
            if self.state.breakout_cooldown_candles > 0:
                self.state.breakout_cooldown_candles -= 1
            self.bot.time_to_sleep = self.bot.time_to_trade
            self._save_state()
            self._log_cycle_summary(
                regime=regime,
                action=action,
                final_action="Regime pause",
                variation=variation,
            )
            print("------------------------------------------------")
            return
        elif self.state.active_mode == "grid":
            self._shutdown_grid()

        if self.state.breakout_cooldown_candles > 0:
            self.state.breakout_cooldown_candles -= 1

        if regime and regime.regime == "TREND":
            self.state.active_mode = "trend"

        decision = StrategyRunner.execute(
            self.bot,
            stock_data=self.bot.stock_data,
            main_strategy=self.bot.main_strategy,
            main_strategy_args=self.bot.main_strategy_args,
            fallback_strategy=self.bot.fallback_strategy,
            fallback_strategy_args=self.bot.fallback_strategy_args,
        )
        self._last_strategy_decision = decision
        self.bot.last_trade_decision = decision.side

        if decision.side is True:
            if self.bot.hasOpenBuyOrder():
                self.bot.cancelAllOrders()
                self._sleep(2)

        if decision.side is False:
            if self.bot.hasOpenSellOrder():
                self.bot.cancelAllOrders()
                self._sleep(2)

        print("\n--------------")
        print(f"Decisão Final: {self._decision_label(decision)}")

        if not self.bot.actual_trade_position and decision.side is True:
            print("Ação final: Comprar")
            self.bot.printStock()
            self._place_buy()
            self._sleep(2)
            self.update_all_data()
            self.bot.printStock()
            self.bot.time_to_sleep = self.bot.delay_after_order
            final_action = "Comprar"

        elif self.bot.actual_trade_position and decision.side is False:
            print("Ação final: Vender")
            self.bot.printStock()
            self._place_sell()
            self._sleep(2)
            self.update_all_data()
            self.bot.printStock()
            self.bot.time_to_sleep = self.bot.delay_after_order
            final_action = "Vender"

        else:
            if self.bot.actual_trade_position:
                position_label = self._held_position_label()
            else:
                position_label = "Vendido"
            print(f"Ação final: Manter posição ({position_label})")
            self.bot.time_to_sleep = self.bot.time_to_trade
            final_action = f"Manter posição ({position_label})"

        self._save_state()
        self._log_cycle_summary(
            regime=regime,
            action=action,
            final_action=final_action,
            variation=variation,
        )
        print("------------------------------------------------")
