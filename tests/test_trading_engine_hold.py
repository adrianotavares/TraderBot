from types import SimpleNamespace
from unittest.mock import MagicMock

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore
from strategies.decision import StrategyDecision


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


def _engine_for_operator_hold(tmp_path, *, held: bool):
    store = StateStore(tmp_path / "engine.db")
    store.set_operator_hold(held)
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        stock_code="BTC",
        time_to_trade=15,
        time_to_sleep=0,
        delay_after_order=99,
        actual_trade_position=False,
        last_stock_account_balance=0.0,
        last_buy_price=0.0,
        last_sell_price=0.0,
        stock_data=None,
        main_strategy=lambda **_k: True,
        main_strategy_args={},
        fallback_strategy=lambda **_k: None,
        fallback_strategy_args={},
        fallback_activated=False,
        last_trade_decision=None,
        engine=None,
        hasOpenBuyOrder=lambda: False,
        hasOpenSellOrder=lambda: False,
        printStock=lambda: None,
    )
    market_data = MagicMock()
    order_executor = MagicMock()
    risk_manager = SimpleNamespace(is_circuit_open=lambda: False)
    engine = TradingEngine(bot, market_data, order_executor, risk_manager, store)
    engine.update_all_data = lambda verbose=True: None
    engine._log_asset_variation = lambda: None
    engine._handle_stop_loss = MagicMock(return_value=False)
    engine._handle_take_profit = MagicMock(return_value=False)
    engine._check_regime = lambda: None
    engine._check_breakout = lambda: None
    engine._resolve_regime_action = lambda *_a, **_k: "atr_trend"
    engine._log_regime_detected = lambda *_a, **_k: None
    engine._place_buy = MagicMock()
    engine._place_sell = MagicMock()
    engine._save_state = lambda: None
    engine._log_cycle_summary = lambda **_k: None
    engine._sleep = lambda _seconds: None
    return engine, bot


def test_operator_hold_blocks_buy_but_runs_stop_loss(tmp_path, monkeypatch):
    engine, bot = _engine_for_operator_hold(tmp_path, held=True)
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._handle_stop_loss.assert_called()
    engine._place_buy.assert_not_called()
    engine._place_sell.assert_not_called()
    assert bot.time_to_sleep == 15


def test_operator_hold_still_allows_strategy_exit(tmp_path, monkeypatch):
    engine, bot = _engine_for_operator_hold(tmp_path, held=True)
    bot.actual_trade_position = True
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    engine._place_sell.assert_called()
