import pandas as pd
import pytest

from backtest.replay import build_replay_engine
from persistence.state_store import StateStore


def _ohlc(n: int, last_price: float = 90.0, prev_price: float = 90.0) -> pd.DataFrame:
    rows = []
    for i in range(n - 2):
        price = 100.0 + i * 0.1
        rows.append(
            {
                "close_price": price,
                "open_price": price,
                "high_price": price + 1,
                "low_price": price - 1,
                "volume": 1000.0,
            }
        )
    for price in (prev_price, last_price):
        rows.append(
            {
                "close_price": price,
                "open_price": price,
                "high_price": price + 1,
                "low_price": price - 1,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def test_replay_pauses_in_gray_with_short_history(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    data = _ohlc(10)
    bot, engine = build_replay_engine(data, store=store, regime_enabled=True)
    engine.bootstrap()
    engine.execute()
    assert engine.state.active_mode == "trend"
    assert engine.bot.time_to_sleep == engine.bot.time_to_trade
    assert bot.broker.orders == []
    assert engine._last_strategy_decision is None


def test_replay_stop_loss_sells_before_strategy(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    data = _ohlc(5, last_price=90.0, prev_price=90.0)
    bot, engine = build_replay_engine(
        data,
        store=store,
        quote_balance=0.0,
        base_balance=0.1,
        stop_loss_pct=2.0,
        main_strategy=lambda **_k: True,
    )
    engine.bootstrap()
    bot.last_buy_price = 100.0
    engine.execute()
    assert bot.actual_trade_position is False
    assert bot.base_balance == 0
    assert store.list_outcomes()[0]["kind"] == "stop_loss"
    restarted = StateStore(tmp_path / "replay.db")
    loaded = restarted.load_state("BTCUSDT")
    assert loaded.actual_trade_position is False


def test_replay_trailing_stop_sells_from_peak(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    data = _ohlc(5, last_price=102.0, prev_price=102.0)
    bot, engine = build_replay_engine(
        data,
        store=store,
        quote_balance=0.0,
        base_balance=0.1,
        stop_loss_pct=2.0,
        trailing_stop_loss=True,
        main_strategy=lambda **_k: None,
    )
    engine.bootstrap()
    bot.last_buy_price = 100.0
    engine.state.stop_loss_peak_price = 105.0
    engine.execute()
    assert bot.actual_trade_position is False
    assert store.list_outcomes()[0]["kind"] == "stop_loss"
    assert engine.state.stop_loss_peak_price == 0.0


def test_replay_fixed_stop_ignores_pullback_above_entry_floor(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    data = _ohlc(5, last_price=102.0, prev_price=102.0)
    bot, engine = build_replay_engine(
        data,
        store=store,
        quote_balance=0.0,
        base_balance=0.1,
        stop_loss_pct=2.0,
        trailing_stop_loss=False,
        main_strategy=lambda **_k: None,
    )
    engine.bootstrap()
    bot.last_buy_price = 100.0
    engine.state.stop_loss_peak_price = 105.0
    engine.execute()
    assert bot.actual_trade_position is True
    assert store.list_outcomes() == []
    assert engine.state.stop_loss_peak_price == 105.0


def test_replay_strategy_buy_fills(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    data = _ohlc(30, last_price=100.0, prev_price=100.0)
    bot, engine = build_replay_engine(
        data,
        store=store,
        quote_balance=1000.0,
        base_balance=0.0,
        main_strategy=lambda **_k: True,
        regime_enabled=False,
    )
    engine.bootstrap()
    engine.execute()
    assert bot.actual_trade_position is True
    assert bot.base_balance > 0
    assert engine._last_strategy_decision.source == "main"
    assert engine._last_strategy_decision.side is True
    assert engine.state.last_trade_decision is True
    assert bot.last_buy_price > 0
    loaded = StateStore(tmp_path / "replay.db").load_state("BTCUSDT")
    assert loaded.last_trade_decision is True
    assert loaded.actual_trade_position is True


def test_replay_bot_fields_are_engine_state(tmp_path):
    store = StateStore(tmp_path / "replay.db")
    bot, engine = build_replay_engine(_ohlc(5), store=store)
    engine.bootstrap()
    bot.last_buy_price = 123.45
    bot.last_trade_decision = True
    bot.take_profit_index = 2
    assert engine.state.last_buy_price == pytest.approx(123.45)
    assert engine.state.last_trade_decision is True
    assert engine.state.take_profit_index == 2
    engine._save_state()
    loaded = StateStore(tmp_path / "replay.db").load_state("BTCUSDT")
    assert loaded.last_buy_price == pytest.approx(123.45)
    assert loaded.last_trade_decision is True
    assert loaded.take_profit_index == 2
