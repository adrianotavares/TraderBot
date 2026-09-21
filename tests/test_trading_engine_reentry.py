from types import SimpleNamespace
from unittest.mock import MagicMock

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore
from strategies.decision import StrategyDecision


def _engine(tmp_path):
    store = StateStore(tmp_path / "engine.db")
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
    risk_manager = SimpleNamespace(
        is_circuit_open=lambda: False,
        trailing_stop_loss=False,
        stop_loss_confirm_with_atr=False,
    )
    engine = TradingEngine(bot, market_data, order_executor, risk_manager, store)
    engine.state = store.load_state("BTCUSDT")
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
    engine._strategy_snapshot = lambda: None
    engine._log_cycle_summary = lambda **_k: None
    engine._sleep = lambda _seconds: None
    return engine, bot, store


def test_need_fresh_long_blocks_buy_until_sell_seen(tmp_path, monkeypatch):
    engine, bot, store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.need_fresh_long == 1
    assert bot.time_to_sleep == 15

    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    assert engine.state.need_fresh_long == 0
    engine._place_buy.assert_not_called()


def test_buy_uses_tempo_entre_trades_not_delay(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._place_buy.assert_called()
    assert bot.time_to_sleep == bot.time_to_trade


def test_arm_fresh_long_on_strategy_sell(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    bot.actual_trade_position = True

    def _sell(*_a, **_k):
        engine._arm_fresh_long()
        bot.actual_trade_position = False

    engine._place_sell = MagicMock(side_effect=_sell)
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_sell.assert_called()
    assert engine.state.need_fresh_long == 1
    assert bot.time_to_sleep == bot.delay_after_order
