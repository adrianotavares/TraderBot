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
