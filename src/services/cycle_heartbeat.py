import logging
from datetime import datetime, timedelta, timezone

VALID_REASONS = (
    "interval",
    "delay_after_order",
    "circuit_breaker",
    "error",
    "hold",
    "operator_hold",
)


def infer_sleep_reason(bot, *, error: bool = False) -> str:
    if error:
        return "error"
    store = getattr(bot, "state_store", None)
    if store is not None:
        try:
            if store.is_action_hold():
                return "hold"
            if store.is_operator_hold():
                return "operator_hold"
        except Exception:
            logging.exception("Failed to read action hold for cycle heartbeat")
    risk = getattr(bot, "risk_manager", None)
    if risk is not None:
        try:
            if risk.is_circuit_open():
                return "circuit_breaker"
        except Exception:
            logging.exception("Failed to read circuit breaker for cycle heartbeat")
    delay = getattr(bot, "delay_after_order", None)
    interval = getattr(bot, "time_to_trade", None)
    sleep = getattr(bot, "time_to_sleep", None)
    if delay is not None and sleep == delay and delay != interval:
        return "delay_after_order"
    return "interval"


def record_cycle_running(store, operation_code: str) -> None:
    """Mark the asset as executing. Persist failures never abort the cycle."""
    try:
        store.save_cycle_heartbeat(
            operation_code,
            "running",
            cycle_started_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        logging.exception("Failed to persist cycle heartbeat for %s", operation_code)


def record_cycle_sleeping(
    store,
    operation_code: str,
    sleep_seconds,
    reason: str,
) -> None:
    """Mark the asset as waiting until next_cycle_at. Persist failures never abort."""
    try:
        now = datetime.now(timezone.utc)
        sleep = max(0, int(round(float(sleep_seconds or 0))))
        reason = reason if reason in VALID_REASONS else "interval"
        store.save_cycle_heartbeat(
            operation_code,
            "sleeping",
            cycle_finished_at=now.isoformat(),
            sleep_seconds=sleep,
            next_cycle_at=(now + timedelta(seconds=sleep)).isoformat(),
            sleep_reason=reason,
        )
    except Exception:
        logging.exception("Failed to persist cycle heartbeat for %s", operation_code)


def mark_cycle_start(bot) -> None:
    store = getattr(bot, "state_store", None)
    operation_code = getattr(bot, "operation_code", None)
    if store is None or not operation_code:
        return
    record_cycle_running(store, operation_code)


def mark_cycle_end(bot, *, error: bool = False) -> None:
    store = getattr(bot, "state_store", None)
    operation_code = getattr(bot, "operation_code", None)
    if store is None or not operation_code:
        return
    record_cycle_sleeping(
        store,
        operation_code,
        getattr(bot, "time_to_sleep", 0),
        infer_sleep_reason(bot, error=error),
    )
