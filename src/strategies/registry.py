import inspect
from typing import Any, Callable, Optional

from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy
from strategies.rsi_strategy import getRsiTradeStrategy
from strategies.weapon_candle_trade_strategy import getWeaponCandleTradeStrategy
from strategies.ut_bot_alerts import utBotAlerts
from strategies.atr_trend import getAtrTrendStrategy, get_atr_trend_snapshot
from strategies.vwap_scalp import getVwapScalpStrategy, get_vwap_scalp_snapshot
from strategies.orb_day import getOrbDayStrategy, get_orb_day_snapshot

STRATEGY_REGISTRY = {
    "weapon_candle": getWeaponCandleTradeStrategy,
    "moving_average": getMovingAverageTradeStrategy,
    "moving_average_antecipation": getMovingAverageAntecipationTradeStrategy,
    "vortex": getVortexTradeStrategy,
    "rsi": getRsiTradeStrategy,
    "ma_rsi_volume": getMovingAverageRSIVolumeStrategy,
    "ut_bot_alerts": utBotAlerts,
    "atr_trend": getAtrTrendStrategy,
    "vwap_scalp": getVwapScalpStrategy,
    "orb_day": getOrbDayStrategy,
}

STRATEGY_SNAPSHOTS = {
    "atr_trend": get_atr_trend_snapshot,
    "vwap_scalp": get_vwap_scalp_snapshot,
    "orb_day": get_orb_day_snapshot,
}

# Legacy names used by the old dashboard
LEGACY_STRATEGY_NAMES = {
    "getWeaponCandleTradeStrategy": "weapon_candle",
    "getMovingAverageTradeStrategy": "moving_average",
    "getMovingAverageAntecipationTradeStrategy": "moving_average_antecipation",
    "getVortexTradeStrategy": "vortex",
    "getRsiTradeStrategy": "rsi",
    "getMovingAverageRSIVolumeStrategy": "ma_rsi_volume",
    "utBotAlerts": "ut_bot_alerts",
    "getAtrTrendStrategy": "atr_trend",
    "getVwapScalpStrategy": "vwap_scalp",
    "getOrbDayStrategy": "orb_day",
}

_SKIP_ARG_NAMES = frozenset({"stock_data", "verbose"})


def resolve_strategy(name: str):
    """Resolve strategy by registry key or legacy function name."""
    if name in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[name]
    if name in LEGACY_STRATEGY_NAMES:
        return STRATEGY_REGISTRY[LEGACY_STRATEGY_NAMES[name]]
    raise ValueError(
        f"Unknown strategy '{name}'. Available: {', '.join(sorted(STRATEGY_REGISTRY))}"
    )


def list_strategies():
    return sorted(STRATEGY_REGISTRY.keys())


def canonical_strategy_name(name: str) -> str:
    if name in STRATEGY_REGISTRY:
        return name
    if name in LEGACY_STRATEGY_NAMES:
        return LEGACY_STRATEGY_NAMES[name]
    raise ValueError(
        f"Unknown strategy '{name}'. Available: {', '.join(sorted(STRATEGY_REGISTRY))}"
    )


def strategy_key_for(fn: Callable) -> Optional[str]:
    for key, registered in STRATEGY_REGISTRY.items():
        if registered is fn:
            return key
    return None


def snapshot_for(name: str) -> Optional[Callable]:
    try:
        key = canonical_strategy_name(name)
    except ValueError:
        return None
    return STRATEGY_SNAPSHOTS.get(key)


def default_args_for(name: str) -> dict[str, Any]:
    """YAML-ready kwargs taken from the strategy function signature."""
    fn = resolve_strategy(name)
    args: dict[str, Any] = {}
    for param in inspect.signature(fn).parameters.values():
        if param.name in _SKIP_ARG_NAMES:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if param.default is inspect.Parameter.empty:
            continue
        value = param.default
        if isinstance(value, bool) or isinstance(value, (int, float, str)):
            args[param.name] = value
    return args


def all_strategy_default_args() -> dict[str, dict[str, Any]]:
    return {name: default_args_for(name) for name in list_strategies()}
