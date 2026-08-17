from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy
from strategies.rsi_strategy import getRsiTradeStrategy
from strategies.weapon_candle_trade_strategy import getWeaponCandleTradeStrategy
from strategies.ut_bot_alerts import utBotAlerts
from strategies.atr_trend import getAtrTrendStrategy

STRATEGY_REGISTRY = {
    "weapon_candle": getWeaponCandleTradeStrategy,
    "moving_average": getMovingAverageTradeStrategy,
    "moving_average_antecipation": getMovingAverageAntecipationTradeStrategy,
    "vortex": getVortexTradeStrategy,
    "rsi": getRsiTradeStrategy,
    "ma_rsi_volume": getMovingAverageRSIVolumeStrategy,
    "ut_bot_alerts": utBotAlerts,
    "atr_trend": getAtrTrendStrategy,
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
}


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
