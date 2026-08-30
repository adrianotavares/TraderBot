from strategies.registry import (
    all_strategy_default_args,
    canonical_strategy_name,
    default_args_for,
    list_strategies,
    resolve_strategy,
    snapshot_for,
    strategy_key_for,
)
from strategies.atr_trend import getAtrTrendStrategy, get_atr_trend_snapshot
from strategies.vwap_scalp import getVwapScalpStrategy, get_vwap_scalp_snapshot
from strategies.orb_day import getOrbDayStrategy, get_orb_day_snapshot


def test_vwap_scalp_is_registered():
    assert "vwap_scalp" in list_strategies()
    assert resolve_strategy("vwap_scalp") is getVwapScalpStrategy
    assert canonical_strategy_name("getVwapScalpStrategy") == "vwap_scalp"


def test_orb_day_is_registered():
    assert "orb_day" in list_strategies()
    assert resolve_strategy("orb_day") is getOrbDayStrategy
    assert canonical_strategy_name("getOrbDayStrategy") == "orb_day"


def test_strategy_key_and_snapshot_are_registry_driven():
    assert strategy_key_for(getAtrTrendStrategy) == "atr_trend"
    assert strategy_key_for(getVwapScalpStrategy) == "vwap_scalp"
    assert strategy_key_for(getOrbDayStrategy) == "orb_day"
    assert snapshot_for("atr_trend") is get_atr_trend_snapshot
    assert snapshot_for("vwap_scalp") is get_vwap_scalp_snapshot
    assert snapshot_for("orb_day") is get_orb_day_snapshot
    assert snapshot_for("moving_average") is None


def test_default_args_are_json_safe_and_exclude_runtime_params():
    defaults = all_strategy_default_args()
    assert set(defaults) == set(list_strategies())
    for name, args in defaults.items():
        assert "stock_data" not in args
        assert "verbose" not in args
        for value in args.values():
            assert isinstance(value, (bool, int, float, str))
    assert default_args_for("atr_trend")["atr_period"] == 14
    assert default_args_for("vwap_scalp")["adx_max"] == 22.0
    assert default_args_for("orb_day")["opening_range_bars"] == 2
    assert default_args_for("orb_day")["adx_min"] == 25.0
