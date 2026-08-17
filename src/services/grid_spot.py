import logging
from dataclasses import dataclass
from typing import Literal, Optional

from services.regime_detector import RegimeResult


@dataclass
class GridLevel:
    price: float
    side: Literal["BUY", "SELL"]


class GridSpotManager:
    def __init__(
        self,
        enabled: bool = True,
        levels: int = 6,
        capital_pct: float = 30.0,
        min_channel_width_pct: float = 1.5,
        max_channel_width_pct: float = 8.0,
        min_profit_per_level_pct: float = 0.35,
    ):
        self.enabled = enabled
        self.levels = max(levels, 2)
        self.capital_pct = capital_pct
        self.min_channel_width_pct = min_channel_width_pct
        self.max_channel_width_pct = max_channel_width_pct
        self.min_profit_per_level_pct = min_profit_per_level_pct

    def channel_valid(self, regime: RegimeResult) -> bool:
        if regime.support is None or regime.resistance is None:
            return False
        if regime.resistance <= regime.support:
            return False
        return self.min_channel_width_pct <= regime.channel_width_pct <= self.max_channel_width_pct

    def build_levels(self, support: float, resistance: float) -> list[float]:
        step = (resistance - support) / (self.levels - 1)
        return [support + i * step for i in range(self.levels)]

    def plan_orders(
        self,
        regime: RegimeResult,
        current_price: float,
    ) -> tuple[list[GridLevel], list[GridLevel]]:
        levels = self.build_levels(regime.support, regime.resistance)
        buy_levels = [GridLevel(price=price, side="BUY") for price in levels if price < current_price]
        sell_levels = []
        min_spread = self.min_profit_per_level_pct / 100
        for price in levels:
            if price <= current_price:
                continue
            sell_price = price * (1 + min_spread)
            if sell_price <= regime.resistance:
                sell_levels.append(GridLevel(price=sell_price, side="SELL"))
        return buy_levels, sell_levels

    def sync_grid(
        self,
        *,
        bot,
        order_executor,
        risk_manager,
        regime: RegimeResult,
        operation_code: str,
        quote_balance: float,
        base_balance: float,
        open_orders: list,
        min_notional: float,
        step_size: float,
    ) -> dict:
        if not self.enabled or not self.channel_valid(regime):
            return {"placed": 0, "skipped": True, "reason": "invalid_channel"}

        current_price = float(bot.stock_data["close_price"].iloc[-1])
        buy_levels, sell_levels = self.plan_orders(regime, current_price)

        open_by_side_price = {
            (order["side"], float(order["price"])): order for order in open_orders
        }
        placed = 0

        if buy_levels:
            quote_per_level = (quote_balance * (self.capital_pct / 100)) / len(buy_levels)
            for level in buy_levels:
                key = ("BUY", level.price)
                if key in open_by_side_price:
                    continue
                quantity = quote_per_level / level.price if level.price > 0 else 0.0
                ok, reason = risk_manager.validate_grid_order(
                    side="BUY",
                    quantity=quantity,
                    price=level.price,
                    quote_balance=quote_balance,
                    base_balance=base_balance,
                    min_notional=min_notional,
                    step_size=step_size,
                    open_orders_count=len(open_orders) + placed,
                )
                if not ok:
                    logging.warning("Grid buy skipped at %.2f: %s", level.price, reason)
                    continue
                order = order_executor.place_limit("BUY", quantity, level.price)
                if order:
                    placed += 1
                    risk_manager.record_grid_trade()
                    open_orders.append(order)

        if sell_levels and base_balance > step_size:
            qty_per_level = base_balance / len(sell_levels)
            for level in sell_levels:
                key = ("SELL", level.price)
                if key in open_by_side_price:
                    continue
                ok, reason = risk_manager.validate_grid_order(
                    side="SELL",
                    quantity=qty_per_level,
                    price=level.price,
                    quote_balance=quote_balance,
                    base_balance=base_balance,
                    min_notional=min_notional,
                    step_size=step_size,
                    open_orders_count=len(open_orders) + placed,
                )
                if not ok:
                    logging.warning("Grid sell skipped at %.2f: %s", level.price, reason)
                    continue
                order = order_executor.place_limit("SELL", qty_per_level, level.price)
                if order:
                    placed += 1
                    risk_manager.record_grid_trade()
                    open_orders.append(order)

        from modules.logging_setup import log_event

        log_event(
            logging.INFO,
            "Grid cycle completed",
            operation_code=operation_code,
            event="grid_cycle",
            support=regime.support,
            resistance=regime.resistance,
            channel_width_pct=round(regime.channel_width_pct, 2),
            buy_levels=len(buy_levels),
            sell_levels=len(sell_levels),
            orders_placed=placed,
        )
        return {
            "placed": placed,
            "skipped": False,
            "support": regime.support,
            "resistance": regime.resistance,
            "buy_levels": len(buy_levels),
            "sell_levels": len(sell_levels),
        }

    def shutdown(self, order_executor, open_orders: list) -> int:
        if not open_orders:
            return 0
        order_executor.cancel_all_orders(open_orders)
        cancelled = len(open_orders)
        open_orders.clear()
        return cancelled
