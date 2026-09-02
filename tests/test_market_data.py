from services.market_data import MarketDataService


def test_is_position_open_requires_step_size():
    assert MarketDataService.is_position_open(0.0005, 0.001) is False
    assert MarketDataService.is_position_open(0.003, 0.001) is True


def test_is_position_open_ignores_dust_below_min_notional():
    assert (
        MarketDataService.is_position_open(
            0.003,
            0.001,
            mark_price=685.0,
            min_notional=5.0,
        )
        is False
    )
    assert (
        MarketDataService.is_position_open(
            0.02,
            0.001,
            mark_price=685.0,
            min_notional=5.0,
        )
        is True
    )
