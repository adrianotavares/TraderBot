from types import SimpleNamespace
from unittest.mock import MagicMock

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore


def test_execute_skips_create_order_when_action_hold(tmp_path):
    store = StateStore(tmp_path / "engine.db")
    store.set_action_hold(True)
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        stock_code="BTC",
        time_to_trade=15,
        time_to_sleep=0,
        engine=None,
    )
    market_data = MagicMock()
    order_executor = MagicMock()
    risk_manager = SimpleNamespace(is_circuit_open=lambda: False)
    engine = TradingEngine(bot, market_data, order_executor, risk_manager, store)

    engine.execute()

    market_data.fetch_klines.assert_not_called()
    order_executor.buy_market.assert_not_called()
    order_executor.sell_market.assert_not_called()
    order_executor.place_market.assert_not_called()
    assert bot.time_to_sleep == 15
