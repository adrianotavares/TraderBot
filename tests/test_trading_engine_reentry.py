from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore
from services.risk_manager import RiskManager
from strategies.decision import StrategyDecision

EXIT_OPEN = 1_700_000_000
FOUR_HOURS = 4 * 3600


def _candles(*opens):
    return pd.DataFrame(
        {
            "open_time": [
                pd.Timestamp(value, unit="s", tz="UTC").tz_convert("America/Sao_Paulo")
                for value in opens
            ],
            "close_price": [10.0 + index for index in range(len(opens))],
        }
    )


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


def test_forming_sell_does_not_clear_fresh_long(tmp_path, monkeypatch):
    engine, _bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.need_fresh_long == 1


def test_fresh_long_blocks_until_next_candle_closes(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(EXIT_OPEN, EXIT_OPEN + FOUR_HOURS)
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 10.0,
        "sma": 9.0,
    }
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.need_fresh_long == 1


def test_fresh_long_buys_when_later_candle_closes_long(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    seen = {}

    def _snapshot(stock_data=None):
        seen["rows"] = None if stock_data is None else len(stock_data)
        seen["last_open"] = (
            None
            if stock_data is None
            else int(stock_data["open_time"].iloc[-1].timestamp())
        )
        return {"trailing": "long", "close": 11.0, "sma": 9.0}

    engine._strategy_snapshot = _snapshot

    def _buy(*_a, **_k):
        bot.actual_trade_position = True

    engine._place_buy = MagicMock(side_effect=_buy)
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_buy.assert_called()
    assert seen["rows"] == 2
    assert seen["last_open"] == EXIT_OPEN + FOUR_HOURS
    assert engine.state.need_fresh_long == 0
    assert engine.state.reentry_pct_stop == 1
    assert engine.state.fresh_long_candle == 0


def test_fresh_long_stays_armed_when_closed_candle_is_not_long(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "short",
        "close": 8.0,
        "sma": 9.0,
    }
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.need_fresh_long == 1
    assert engine.state.reentry_pct_stop == 0


def test_missing_fresh_long_candle_stamps_the_closed_bar(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    bot.stock_data = _candles(EXIT_OPEN, EXIT_OPEN + FOUR_HOURS)
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 11.0,
        "sma": 9.0,
    }
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.fresh_long_candle == EXIT_OPEN
    assert engine.state.need_fresh_long == 1


def test_operator_hold_blocks_closed_long_reentry(tmp_path, monkeypatch):
    engine, bot, store = _engine(tmp_path)
    store.set_operator_hold(True)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 11.0,
        "sma": 9.0,
    }
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_buy.assert_not_called()
    assert engine.state.need_fresh_long == 1
    assert engine.state.fresh_long_candle == EXIT_OPEN


def test_flat_refresh_clears_reentry_pct_stop(tmp_path):
    engine, bot, _store = _engine(tmp_path)
    del engine.update_all_data
    engine.risk_manager.record_api_success = lambda: None
    bot.getUpdatedAccountData = lambda: {}
    bot.getLastStockAccountBalance = lambda: 0.0
    bot.getActualTradePosition = lambda: False
    bot.getOpenOrders = lambda: []
    bot.getLastBuyPrice = lambda verbose=False: 0.0
    bot.getLastSellPrice = lambda verbose=False: 0.0
    bot.stock_data = _candles(EXIT_OPEN, EXIT_OPEN + FOUR_HOURS)
    engine.state.reentry_pct_stop = 1
    engine.state.reentry_order_id = 99

    engine.update_all_data()
    assert engine.state.reentry_pct_stop == 0
    assert engine.state.reentry_order_id == 99

    bot.getActualTradePosition = lambda: True
    bot.getLastStockAccountBalance = lambda: 0.0001
    bot.step_size = 0.01
    bot.min_notional = 5.0
    engine.state.reentry_pct_stop = 1
    engine.update_all_data()
    assert bot.actual_trade_position is False
    assert engine.state.reentry_pct_stop == 0


def test_unconfirmed_reentry_buy_restores_the_gate(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 11.0,
        "sma": 9.0,
    }

    def _buy(*_a, **_k):
        bot.actual_trade_position = True

    def _refresh(verbose=True):
        bot.actual_trade_position = False

    engine._place_buy = MagicMock(side_effect=_buy)
    engine.update_all_data = _refresh
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    engine._place_buy.assert_called()
    assert engine.state.need_fresh_long == 1
    assert engine.state.reentry_pct_stop == 0
    assert engine.state.fresh_long_candle == EXIT_OPEN


def test_resting_reentry_limit_is_not_replaced(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 1
    engine.state.fresh_long_candle = EXIT_OPEN
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 11.0,
        "sma": 9.0,
    }
    del engine._place_buy
    engine._resolve_quantity = lambda _side: 1.0
    engine._validate_before_order = lambda *_a, **_k: True
    calls = {"n": 0}

    def _limited(*_a, **_k):
        calls["n"] += 1
        return {"orderId": 42, "status": "NEW", "side": "BUY"}

    engine.order_executor.buy_limited = _limited
    bot.cancelAllOrders = MagicMock()

    def _refresh(verbose=True):
        bot.actual_trade_position = False
        bot.open_orders = [{"orderId": 42, "status": "NEW", "side": "BUY"}]

    engine.update_all_data = _refresh
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    assert engine.state.reentry_order_id == 42
    assert engine.state.reentry_pct_stop == 0
    assert engine.state.need_fresh_long == 0
    assert engine.state.fresh_long_candle == EXIT_OPEN
    engine.execute()
    assert calls["n"] == 1
    bot.cancelAllOrders.assert_not_called()
    assert engine.state.reentry_order_id == 42


def test_late_reentry_fill_arms_pct_stop(tmp_path):
    engine, bot, _store = _engine(tmp_path)
    del engine.update_all_data
    del engine._handle_stop_loss
    frame = pd.DataFrame(
        {
            "open_time": _candles(EXIT_OPEN, EXIT_OPEN + FOUR_HOURS)["open_time"],
            "close_price": [94.0, 94.0],
        }
    )
    bot.stock_data = frame
    bot.step_size = 0.01
    bot.min_notional = 5.0
    bot.last_buy_price = 100.0
    bot.getUpdatedAccountData = lambda: {}
    bot.getLastStockAccountBalance = lambda: 1.0
    bot.getActualTradePosition = lambda: True
    bot.getOpenOrders = lambda: []
    bot.getLastBuyPrice = lambda verbose=False: 100.0
    bot.getLastSellPrice = lambda verbose=False: 0.0
    engine.market_data.fetch_klines = lambda: frame
    engine.risk_manager = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=5.0,
        take_profit_at=[],
        take_profit_amount=[],
        stop_loss_confirm_with_atr=True,
    )
    engine.state.reentry_order_id = 42
    engine.state.fresh_long_candle = EXIT_OPEN
    engine.state.need_fresh_long = 0
    engine.update_all_data()
    assert engine.state.reentry_pct_stop == 1
    assert engine.state.reentry_order_id == 0
    assert engine.state.fresh_long_candle == 0

    engine._last_strategy_snapshot = {"trailing_stop": 90.0, "trailing": "long"}
    bot.cancelAllOrders = MagicMock()
    bot.sellMarketOrder = MagicMock(return_value={"status": "NEW"})
    assert engine._handle_stop_loss() is False
    bot.sellMarketOrder.assert_called_once()


def test_reentry_limit_cancels_when_closed_candle_is_not_long(tmp_path, monkeypatch):
    engine, bot, _store = _engine(tmp_path)
    engine.state.need_fresh_long = 0
    engine.state.fresh_long_candle = EXIT_OPEN
    engine.state.reentry_order_id = 42
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "short",
        "close": 8.0,
        "sma": 9.0,
    }
    bot.open_orders = [{"orderId": 42, "status": "NEW", "side": "BUY"}]
    bot.cancelAllOrders = MagicMock()
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(False, source="main", reason="sell"),
    )
    engine.execute()
    bot.cancelAllOrders.assert_called_once()
    assert engine.state.reentry_order_id == 0
    assert engine.state.need_fresh_long == 1
    assert engine.state.fresh_long_candle == EXIT_OPEN
    engine._place_buy.assert_not_called()


def test_reentry_limit_cancels_while_operator_hold_is_on(tmp_path, monkeypatch):
    engine, bot, store = _engine(tmp_path)
    store.set_operator_hold(True)
    engine.state.need_fresh_long = 0
    engine.state.fresh_long_candle = EXIT_OPEN
    engine.state.reentry_order_id = 42
    bot.stock_data = _candles(
        EXIT_OPEN, EXIT_OPEN + FOUR_HOURS, EXIT_OPEN + 2 * FOUR_HOURS
    )
    engine._strategy_snapshot = lambda stock_data=None: {
        "trailing": "long",
        "close": 11.0,
        "sma": 9.0,
    }
    bot.open_orders = [{"orderId": 42, "status": "NEW", "side": "BUY"}]
    bot.cancelAllOrders = MagicMock()
    monkeypatch.setattr(
        "core.trading_engine.StrategyRunner.execute",
        lambda *_a, **_k: StrategyDecision(True, source="main", reason="buy"),
    )
    engine.execute()
    bot.cancelAllOrders.assert_called_once()
    assert engine.state.reentry_order_id == 0
    assert engine.state.need_fresh_long == 1
    assert engine.state.fresh_long_candle == EXIT_OPEN
    engine._place_buy.assert_not_called()


def test_reentry_pct_stop_fires_while_atr_trailing_is_long(tmp_path):
    engine, bot, _store = _engine(tmp_path)
    del engine._handle_stop_loss
    engine.risk_manager = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=5.0,
        take_profit_at=[],
        take_profit_amount=[],
        stop_loss_confirm_with_atr=True,
    )
    engine._last_strategy_snapshot = {"trailing_stop": 90.0, "trailing": "long"}
    bot.actual_trade_position = True
    bot.last_buy_price = 100.0
    bot.stock_data = pd.DataFrame(
        {
            "open_time": _candles(EXIT_OPEN, EXIT_OPEN + FOUR_HOURS)["open_time"],
            "close_price": [94.0, 94.0],
        }
    )
    bot.cancelAllOrders = MagicMock()
    bot.sellMarketOrder = MagicMock(return_value={"status": "NEW"})

    engine.state.reentry_pct_stop = 1
    assert engine._handle_stop_loss() is False
    bot.sellMarketOrder.assert_called_once()

    bot.sellMarketOrder.reset_mock()
    engine.state.reentry_pct_stop = 0
    bot.actual_trade_position = True
    assert engine._handle_stop_loss() is False
    bot.sellMarketOrder.assert_not_called()


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
