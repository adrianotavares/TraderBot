import pytest

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
