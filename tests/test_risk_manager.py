from types import SimpleNamespace

import pandas as pd
import pytest

from core.trading_engine import TradingEngine
from persistence.state_store import StateStore
from services.risk_manager import RiskManager


@pytest.fixture
def risk_manager():
    return RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[10, 20],
        take_profit_amount=[50, 100],
        max_daily_loss_usdt=50.0,
        max_trades_per_day=3,
        max_open_orders=2,
        circuit_breaker_errors=2,
        circuit_breaker_pause_seconds=60,
    )


def test_validate_order_min_notional(risk_manager):
    ok, reason = risk_manager.validate_order(
        side="BUY",
        quantity=0.0001,
        price=100.0,
        quote_balance=1000.0,
        base_balance=0.0,
        min_notional=10.0,
        step_size=0.0001,
        open_orders_count=0,
    )
    assert not ok
    assert "notional" in reason


def test_validate_order_insufficient_balance(risk_manager):
    ok, reason = risk_manager.validate_order(
        side="BUY",
        quantity=1.0,
        price=100.0,
        quote_balance=10.0,
        base_balance=0.0,
        min_notional=5.0,
        step_size=0.001,
        open_orders_count=0,
    )
    assert not ok
    assert "insufficient" in reason


def test_circuit_breaker(risk_manager):
    risk_manager.record_api_error()
    risk_manager.record_api_error()
    assert risk_manager.is_circuit_open()


def test_compute_trade_quantity_percentage(risk_manager):
    qty = risk_manager.compute_trade_quantity(
        traded_quantity=0,
        traded_percentage=50,
        balance=1.0,
        quote_balance=1000.0,
        close_price=50000.0,
        side="BUY",
    )
    assert qty == pytest.approx(0.01)


def test_compute_trade_quantity_bumps_to_min_notional(risk_manager):
    qty = risk_manager.compute_trade_quantity(
        traded_quantity=0,
        traded_percentage=50,
        balance=0.0,
        quote_balance=8.43,
        close_price=72000.0,
        side="BUY",
        min_notional=5.0,
    )
    assert qty == pytest.approx(5.0 / 72000.0)


def test_compute_trade_quantity_does_not_exceed_balance(risk_manager):
    qty = risk_manager.compute_trade_quantity(
        traded_quantity=0,
        traded_percentage=50,
        balance=0.0,
        quote_balance=4.0,
        close_price=72000.0,
        side="BUY",
        min_notional=5.0,
    )
    assert qty == pytest.approx(2.0 / 72000.0)


def test_compute_trade_quantity_meets_notional_after_step_floor(risk_manager):
    qty = risk_manager.compute_trade_quantity(
        traded_quantity=0,
        traded_percentage=50,
        balance=0.0,
        quote_balance=8.43,
        close_price=72000.0,
        side="BUY",
        min_notional=5.0,
        step_size=0.00001,
    )
    assert qty == pytest.approx(0.00007)
    assert qty * 72000.0 >= 5.0


def test_compute_trade_quantity_returns_zero_when_balance_below_notional(risk_manager):
    qty = risk_manager.compute_trade_quantity(
        traded_quantity=0,
        traded_percentage=50,
        balance=0.0,
        quote_balance=4.0,
        close_price=72000.0,
        side="BUY",
        min_notional=5.0,
        step_size=0.00001,
    )
    assert qty == 0.0


def _order_kwargs(**overrides):
    params = dict(
        side="BUY",
        quantity=0.001,
        price=10000.0,
        quote_balance=1000.0,
        base_balance=0.0,
        min_notional=5.0,
        step_size=0.0001,
        open_orders_count=0,
    )
    params.update(overrides)
    return params


def test_daily_loss_blocks_order(risk_manager):
    risk_manager.record_trade_pnl(-50.0)
    assert risk_manager.should_stop_trading_daily_loss()
    ok, reason = risk_manager.validate_order(**_order_kwargs())
    assert not ok
    assert "daily loss" in reason


def test_max_trades_per_day(risk_manager):
    for _ in range(3):
        risk_manager.record_trade_pnl(1.0)
    ok, reason = risk_manager.validate_order(**_order_kwargs())
    assert not ok
    assert "max trades" in reason


def test_daily_counters_persist_across_instances(tmp_path):
    store = StateStore(tmp_path / "test.db")
    first = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=50.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    first.record_trade_pnl(-12.5)
    first.record_grid_trade()

    second = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=50.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    assert second._daily_trades == 1
    assert second._daily_grid_trades == 1
    assert second._daily_loss_usdt == pytest.approx(12.5)


def test_hydrate_from_outcomes_when_counters_missing(tmp_path):
    from datetime import datetime, timezone

    store = StateStore(tmp_path / "test.db")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store.record_outcome(
        {
            "kind": "stop_loss",
            "operation_code": "BTCUSDT",
            "pnl_usd": -40.0,
            "filled": True,
            "occurred_at": f"{today}T08:00:00+00:00",
        }
    )
    store.log_order(
        "BTCUSDT",
        {
            "orderId": 99,
            "side": "SELL",
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": "0.01",
            "cummulativeQuoteQty": "900",
        },
        created_at=f"{today}T08:00:00+00:00",
    )
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=50.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    assert risk._daily_trades == 1
    assert risk._daily_loss_usdt == pytest.approx(40.0)
    ok, reason = risk.validate_order(**_order_kwargs())
    assert ok


def test_closed_trade_records_real_pnl_and_blocks(tmp_path):
    store = StateStore(tmp_path / "test.db")
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=10.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        stock_code="BTC",
        last_buy_price=100.0,
    )
    engine = TradingEngine(
        bot=bot,
        market_data=None,
        order_executor=None,
        risk_manager=risk,
        state_store=store,
    )
    engine._record_closed_trade(
        "stop_loss",
        {
            "orderId": 7,
            "executedQty": "1",
            "cummulativeQuoteQty": "90",
            "fills": [{"price": "90"}],
        },
    )
    assert risk._daily_loss_usdt == pytest.approx(10.0)
    assert risk.should_stop_trading_daily_loss()
    ok, reason = risk.validate_order(**_order_kwargs())
    assert not ok
    assert "daily loss" in reason

    restarted = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=0.5,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=10.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    assert restarted.should_stop_trading_daily_loss()


def _closes(*prices):
    return pd.DataFrame({"close_price": list(prices)})


def test_stop_loss_stays_fixed_on_entry_when_trailing_off():
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=2.0,
        take_profit_at=[],
        take_profit_amount=[],
        trailing_stop_loss=False,
    )
    assert risk.stop_loss_price(100.0, peak_price=105.0) == pytest.approx(98.0)
    assert risk.check_stop_loss(_closes(102.0, 102.0), 100.0, True, peak_price=105.0) is False
    assert risk.check_stop_loss(_closes(97.0, 97.0), 100.0, True, peak_price=105.0) is True


def test_trailing_stop_uses_peak_and_never_lowers_anchor():
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=2.0,
        take_profit_at=[],
        take_profit_amount=[],
        trailing_stop_loss=True,
    )
    assert risk.stop_loss_price(100.0, peak_price=105.0) == pytest.approx(102.9)
    assert risk.check_stop_loss(_closes(103.5, 103.5), 100.0, True, peak_price=105.0) is False
    assert risk.check_stop_loss(_closes(102.0, 102.0), 100.0, True, peak_price=105.0) is True
    assert risk.check_stop_loss(_closes(97.0, 97.0), 100.0, True, peak_price=0.0) is True


def test_ratchet_peak_tracks_high_close_and_resets_when_flat():
    assert (
        RiskManager.ratchet_peak(
            position_open=True,
            last_buy_price=100.0,
            peak_price=0.0,
            mark_price=105.0,
        )
        == 105.0
    )
    assert (
        RiskManager.ratchet_peak(
            position_open=True,
            last_buy_price=100.0,
            peak_price=105.0,
            mark_price=103.0,
        )
        == 105.0
    )
    assert (
        RiskManager.ratchet_peak(
            position_open=False,
            last_buy_price=100.0,
            peak_price=105.0,
            mark_price=103.0,
        )
        == 0.0
    )
