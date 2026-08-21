import pytest

from services.market_data import MarketDataService


def test_adjust_to_step_string():
    result = MarketDataService.adjust_to_step(0.00173, 0.0001, as_string=True)
    assert result == "0.0017"


def test_adjust_to_step_float():
    result = MarketDataService.adjust_to_step(0.00173, 0.0001, as_string=False)
    assert result == pytest.approx(0.0017)


def test_adjust_to_step_invalid():
    with pytest.raises(ValueError):
        MarketDataService.adjust_to_step(1.0, 0, as_string=False)


def test_size_quantity_ceils_to_min_notional():
    qty = MarketDataService.size_quantity_for_filters(
        quantity=5.0 / 72000.0,
        price=72000.0,
        step_size=0.00001,
        min_notional=5.0,
        max_quote=8.43,
    )
    assert qty == pytest.approx(0.00007)
    assert qty * 72000.0 >= 5.0


def test_size_quantity_returns_zero_when_quote_cannot_meet_notional():
    qty = MarketDataService.size_quantity_for_filters(
        quantity=2.0 / 72000.0,
        price=72000.0,
        step_size=0.00001,
        min_notional=5.0,
        max_quote=4.0,
    )
    assert qty == 0.0
