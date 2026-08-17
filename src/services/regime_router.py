def can_run_grid(
    regime,
    *,
    grid_manager,
    regime_detector,
    breakout_detector,
    breakout_cooldown_candles: int,
) -> bool:
    if not regime or regime.regime != "LATERAL":
        return False
    grid_enabled = (
        grid_manager
        and grid_manager.enabled
        and regime_detector
        and regime_detector.action_in_lateral == "grid"
    )
    if not grid_enabled or not grid_manager.channel_valid(regime):
        return False
    if breakout_detector and not breakout_detector.can_reenter_grid(
        regime.adx_value, breakout_cooldown_candles
    ):
        return False
    return True


def resolve_regime_action(
    regime,
    breakout,
    *,
    regime_detector,
    grid_manager,
    breakout_detector,
    breakout_cooldown_candles: int,
) -> str:
    if breakout and breakout.confirmed:
        return "atr_trend_breakout"
    if not regime_detector or not regime_detector.enabled:
        return "atr_trend"
    if regime and regime.regime == "LATERAL":
        if can_run_grid(
            regime,
            grid_manager=grid_manager,
            regime_detector=regime_detector,
            breakout_detector=breakout_detector,
            breakout_cooldown_candles=breakout_cooldown_candles,
        ):
            return "grid"
        return "pause"
    if regime and regime.regime == "GRAY":
        return "pause"
    return "atr_trend"
