import logging
import time
from datetime import datetime, timezone
from typing import Optional

from services.market_data import MarketDataService


class RiskManager:
    def __init__(
        self,
        acceptable_loss_pct: float,
        stop_loss_pct: float,
        take_profit_at: list,
        take_profit_amount: list,
        max_daily_loss_usdt: float = 100.0,
        max_trades_per_day: int = 50,
        max_open_orders: int = 5,
        max_grid_trades_per_day: int = 20,
        max_grid_open_orders: int = 10,
        circuit_breaker_errors: int = 5,
        circuit_breaker_pause_seconds: int = 300,
        trailing_stop_loss: bool = False,
        state_store=None,
        operation_code: str = "",
    ):
        self.acceptable_loss_pct = acceptable_loss_pct / 100
        self.stop_loss_pct = stop_loss_pct / 100
        self.trailing_stop_loss = bool(trailing_stop_loss)
        self.take_profit_at = take_profit_at
        self.take_profit_amount = take_profit_amount
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_trades_per_day = max_trades_per_day
        self.max_open_orders = max_open_orders
        self.max_grid_trades_per_day = max_grid_trades_per_day
        self.max_grid_open_orders = max_grid_open_orders
        self.circuit_breaker_errors = circuit_breaker_errors
        self.circuit_breaker_pause_seconds = circuit_breaker_pause_seconds
        self._state_store = state_store
        self._operation_code = operation_code
        self._consecutive_errors = 0
        self._circuit_open_until = 0.0
        self._daily_trades = 0
        self._daily_grid_trades = 0
        self._daily_loss_usdt = 0.0
        self._day_key = self._today_key()
        self._hydrate_daily()

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _reset_daily_counters_if_needed(self):
        today = self._today_key()
        if today != self._day_key:
            self._day_key = today
            self._daily_trades = 0
            self._daily_grid_trades = 0
            self._daily_loss_usdt = 0.0

    def _hydrate_daily(self):
        if not self._state_store or not self._operation_code:
            return
        stored = self._state_store.load_daily_risk(self._day_key, self._operation_code)
        derived = self._state_store.derived_daily_risk(self._day_key, self._operation_code)
        self._daily_trades = max(stored["trades"], derived["trades"])
        self._daily_grid_trades = stored["grid_trades"]
        self._daily_loss_usdt = max(stored["loss_usdt"], derived["loss_usdt"])
        self._persist_daily()

    def _persist_daily(self):
        if not self._state_store or not self._operation_code:
            return
        self._state_store.save_daily_risk(
            self._day_key,
            self._operation_code,
            trades=self._daily_trades,
            grid_trades=self._daily_grid_trades,
            loss_usdt=self._daily_loss_usdt,
        )

    def record_api_success(self):
        self._consecutive_errors = 0

    def record_api_error(self):
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.circuit_breaker_errors:
            self._circuit_open_until = time.time() + self.circuit_breaker_pause_seconds
            logging.error(
                "Circuit breaker open for %ss after %s consecutive API errors",
                self.circuit_breaker_pause_seconds,
                self._consecutive_errors,
            )

    def is_circuit_open(self) -> bool:
        return time.time() < self._circuit_open_until

    def get_minimum_price_to_sell(self, last_buy_price: float) -> float:
        return last_buy_price * (1 - self.acceptable_loss_pct)

    def get_price_change_pct(self, initial_price: float, close_price: float) -> float:
        if initial_price == 0:
            raise ValueError("initial_price cannot be zero")
        return ((close_price - initial_price) / initial_price) * 100

    def compute_trade_quantity(
        self,
        traded_quantity: float,
        traded_percentage: float,
        balance: float,
        quote_balance: float,
        close_price: float,
        side: str,
        min_notional: float = 0.0,
        step_size: float = 0.0,
    ) -> float:
        if traded_quantity > 0:
            quantity = traded_quantity
        elif traded_percentage <= 0:
            return 0.0
        elif side == "BUY":
            quote_to_use = quote_balance * (traded_percentage / 100)
            if close_price <= 0:
                return 0.0
            if (
                min_notional > 0
                and quote_to_use < min_notional <= quote_balance
            ):
                quote_to_use = min_notional
            quantity = quote_to_use / close_price
        else:
            quantity = balance * (traded_percentage / 100)

        if step_size <= 0:
            return quantity
        return MarketDataService.size_quantity_for_filters(
            quantity=quantity,
            price=close_price,
            step_size=step_size,
            min_notional=min_notional,
            max_quote=quote_balance if side == "BUY" else None,
            bump_to_min_notional=side == "BUY",
        )

    def validate_order(
        self,
        side: str,
        quantity: float,
        price: float,
        quote_balance: float,
        base_balance: float,
        min_notional: float,
        step_size: float,
        open_orders_count: int,
    ) -> tuple[bool, str]:
        self._reset_daily_counters_if_needed()

        if self.is_circuit_open():
            return False, "circuit breaker is open"
        if self.should_stop_trading_daily_loss():
            return False, "daily loss limit reached"
        if self._daily_trades >= self.max_trades_per_day:
            return False, "max trades per day reached"
        if open_orders_count >= self.max_open_orders:
            return False, "max open orders reached"
        if quantity < step_size:
            return False, f"quantity {quantity} below step_size {step_size}"
        notional = quantity * price
        if min_notional > 0 and notional < min_notional:
            return False, f"notional {notional:.4f} below min {min_notional}"
        if side == "BUY" and notional > quote_balance:
            return False, "insufficient quote balance"
        if side == "SELL" and quantity > base_balance:
            return False, "insufficient base balance"
        return True, "ok"

    def validate_grid_order(
        self,
        side: str,
        quantity: float,
        price: float,
        quote_balance: float,
        base_balance: float,
        min_notional: float,
        step_size: float,
        open_orders_count: int,
    ) -> tuple[bool, str]:
        self._reset_daily_counters_if_needed()

        if self.is_circuit_open():
            return False, "circuit breaker is open"
        if self.should_stop_trading_daily_loss():
            return False, "daily loss limit reached"
        if self._daily_grid_trades >= self.max_grid_trades_per_day:
            return False, "max grid trades per day reached"
        if open_orders_count >= self.max_grid_open_orders:
            return False, "max grid open orders reached"
        if quantity < step_size:
            return False, f"quantity {quantity} below step_size {step_size}"
        notional = quantity * price
        if min_notional > 0 and notional < min_notional:
            return False, f"notional {notional:.4f} below min {min_notional}"
        if side == "BUY" and notional > quote_balance:
            return False, "insufficient quote balance"
        if side == "SELL" and quantity > base_balance:
            return False, "insufficient base balance"
        return True, "ok"

    def record_grid_trade(self):
        self._reset_daily_counters_if_needed()
        self._daily_grid_trades += 1
        self._persist_daily()

    def record_trade_pnl(self, pnl_usdt: float):
        self._reset_daily_counters_if_needed()
        self._daily_trades += 1
        loss = float(pnl_usdt or 0)
        if loss < 0:
            self._daily_loss_usdt += abs(loss)
        if self._daily_loss_usdt >= self.max_daily_loss_usdt:
            logging.warning("Max daily loss reached: %.2f USDT", self._daily_loss_usdt)
        self._persist_daily()

    def apply_config(
        self,
        *,
        acceptable_loss_pct: float,
        stop_loss_pct: float,
        take_profit_at: list,
        take_profit_amount: list,
        max_daily_loss_usdt: float,
        max_trades_per_day: int,
        max_open_orders: int,
        max_grid_trades_per_day: int,
        max_grid_open_orders: int,
        circuit_breaker_errors: int,
        circuit_breaker_pause_seconds: int,
        trailing_stop_loss: bool = False,
    ):
        """Update limits without resetting daily counters."""
        self.acceptable_loss_pct = acceptable_loss_pct / 100
        self.stop_loss_pct = stop_loss_pct / 100
        self.take_profit_at = take_profit_at
        self.take_profit_amount = take_profit_amount
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_trades_per_day = max_trades_per_day
        self.max_open_orders = max_open_orders
        self.max_grid_trades_per_day = max_grid_trades_per_day
        self.max_grid_open_orders = max_grid_open_orders
        self.circuit_breaker_errors = circuit_breaker_errors
        self.circuit_breaker_pause_seconds = circuit_breaker_pause_seconds
        self.trailing_stop_loss = bool(trailing_stop_loss)

    def should_stop_trading_daily_loss(self) -> bool:
        self._reset_daily_counters_if_needed()
        return self._daily_loss_usdt >= self.max_daily_loss_usdt

    @staticmethod
    def ratchet_peak(
        *,
        position_open: bool,
        last_buy_price: float,
        peak_price: float,
        mark_price: float,
    ) -> float:
        """Highest close seen while the position is open; 0 when flat."""
        if not position_open:
            return 0.0
        return max(
            float(last_buy_price or 0.0),
            float(peak_price or 0.0),
            float(mark_price or 0.0),
        )

    def stop_loss_price(
        self, last_buy_price: float, peak_price: float = 0.0
    ) -> float:
        last_buy = float(last_buy_price or 0.0)
        if last_buy <= 0:
            return 0.0
        anchor = last_buy
        if self.trailing_stop_loss:
            anchor = max(last_buy, float(peak_price or 0.0))
        return anchor * (1 - self.stop_loss_pct)

    def check_stop_loss(
        self,
        stock_data,
        last_buy_price: float,
        position_open: bool,
        peak_price: float = 0.0,
    ) -> bool:
        close_price = stock_data["close_price"].iloc[-1]
        weighted_price = stock_data["close_price"].iloc[-2]
        stop_price = self.stop_loss_price(last_buy_price, peak_price)
        return bool(
            position_open
            and stop_price > 0
            and close_price < stop_price
            and weighted_price < stop_price
        )

    def check_take_profit(
        self,
        stock_data,
        last_buy_price: float,
        position_open: bool,
        take_profit_index: int,
        balance: float,
    ) -> Optional[tuple[float, float, int]]:
        if not position_open or take_profit_index >= len(self.take_profit_at):
            return None
        last_buy = float(last_buy_price or 0)
        if last_buy <= 0:
            return None
        close_price = stock_data["close_price"].iloc[-1]
        variation = self.get_price_change_pct(last_buy, close_price)
        tp_pct = self.take_profit_at[take_profit_index]
        tp_amount = self.take_profit_amount[take_profit_index]
        if tp_pct > 0 and round(variation, 2) >= round(tp_pct, 2):
            qty = balance * (tp_amount / 100)
            if qty > 0:
                return qty, tp_pct, take_profit_index + 1
        return None
