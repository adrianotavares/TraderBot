import pytest

from services.grid_spot import GridSpotManager
from services.regime_detector import RegimeResult


@pytest.fixture
def manager():
    return GridSpotManager(
        enabled=True,
        levels=5,
        capital_pct=30,
        min_channel_width_pct=1.0,
        max_channel_width_pct=10.0,
    )


def test_build_levels_evenly_spaced(manager):
    levels = manager.build_levels(64000, 68000)
    assert len(levels) == 5
    assert levels[0] == 64000
    assert levels[-1] == 68000
    assert levels[2] == pytest.approx(66000)


def test_channel_valid_within_bounds(manager):
    regime = RegimeResult(
        regime="LATERAL",
        score=3,
        support=64000,
        resistance=68000,
        channel_width_pct=6.0,
    )
    assert manager.channel_valid(regime) is True


def test_channel_valid_rejects_narrow_channel(manager):
    regime = RegimeResult(
        regime="LATERAL",
        score=3,
        support=65000,
        resistance=65500,
        channel_width_pct=0.7,
    )
    assert manager.channel_valid(regime) is False


def test_plan_orders_splits_buy_and_sell(manager):
    regime = RegimeResult(
        regime="LATERAL",
        score=3,
        support=64000,
        resistance=68000,
        channel_width_pct=6.0,
    )
    buy_levels, sell_levels = manager.plan_orders(regime, current_price=66000)
    assert buy_levels
    assert sell_levels
    assert all(level.side == "BUY" for level in buy_levels)
    assert all(level.side == "SELL" for level in sell_levels)
    assert all(level.price < 66000 for level in buy_levels)
    assert all(level.price > 66000 for level in sell_levels)
