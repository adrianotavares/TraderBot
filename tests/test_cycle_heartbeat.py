from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from persistence.state_store import StateStore
from services.cycle_heartbeat import (
    infer_sleep_reason,
    mark_cycle_end,
    mark_cycle_start,
    record_cycle_running,
    record_cycle_sleeping,
)


def test_cycle_heartbeat_roundtrip_preserves_sleep_on_running(tmp_path):
    store = StateStore(tmp_path / "test.db")
    finished = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    nxt = finished + timedelta(seconds=600)
    store.save_cycle_heartbeat(
        "BTCUSDT",
        "sleeping",
        cycle_finished_at=finished.isoformat(),
        sleep_seconds=600,
        next_cycle_at=nxt.isoformat(),
        sleep_reason="interval",
    )
    store.save_cycle_heartbeat(
        "BTCUSDT",
        "running",
        cycle_started_at="2026-08-28T14:10:00+00:00",
    )
    row = store.list_cycle_heartbeats()[0]
    assert row["phase"] == "running"
    assert row["cycle_started_at"] == "2026-08-28T14:10:00+00:00"
    assert row["sleep_seconds"] == 600
    assert row["sleep_reason"] == "interval"
    assert row["next_cycle_at"] == nxt.isoformat()


def test_list_cycle_heartbeats_running_ahead_of_soonest_sleep(tmp_path):
    store = StateStore(tmp_path / "test.db")
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    store.save_cycle_heartbeat(
        "ETHUSDT",
        "sleeping",
        next_cycle_at=(now + timedelta(seconds=30)).isoformat(),
        sleep_seconds=30,
        sleep_reason="interval",
    )
    store.save_cycle_heartbeat(
        "BTCUSDT",
        "running",
        cycle_started_at=now.isoformat(),
        next_cycle_at=(now + timedelta(seconds=5)).isoformat(),
    )
    codes = [row["operation_code"] for row in store.list_cycle_heartbeats()]
    assert codes[0] == "BTCUSDT"
    assert codes[1] == "ETHUSDT"


def test_infer_sleep_reason_variants():
    hold_store = MagicMock()
    hold_store.is_action_hold.return_value = True
    assert infer_sleep_reason(SimpleNamespace(state_store=hold_store)) == "hold"

    risk = SimpleNamespace(is_circuit_open=lambda: True)
    assert infer_sleep_reason(SimpleNamespace(risk_manager=risk)) == "circuit_breaker"

    delayed = SimpleNamespace(
        time_to_sleep=7200,
        delay_after_order=7200,
        time_to_trade=600,
    )
    assert infer_sleep_reason(delayed) == "delay_after_order"

    interval = SimpleNamespace(
        time_to_sleep=600,
        delay_after_order=7200,
        time_to_trade=600,
    )
    assert infer_sleep_reason(interval) == "interval"
    assert infer_sleep_reason(interval, error=True) == "error"


def test_record_helpers_never_raise_on_store_failure():
    class Broken:
        def save_cycle_heartbeat(self, *args, **kwargs):
            raise RuntimeError("disk full")

    record_cycle_running(Broken(), "BTCUSDT")
    record_cycle_sleeping(Broken(), "BTCUSDT", 600, "interval")


def test_mark_cycle_start_and_end_write_rows(tmp_path):
    store = StateStore(tmp_path / "test.db")
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        state_store=store,
        time_to_sleep=600,
        time_to_trade=600,
        delay_after_order=7200,
        risk_manager=SimpleNamespace(is_circuit_open=lambda: False),
    )
    mark_cycle_start(bot)
    row = store.list_cycle_heartbeats()[0]
    assert row["phase"] == "running"
    assert row["cycle_started_at"]

    mark_cycle_end(bot)
    row = store.list_cycle_heartbeats()[0]
    assert row["phase"] == "sleeping"
    assert row["sleep_seconds"] == 600
    assert row["sleep_reason"] == "interval"
    assert row["next_cycle_at"]
    started = datetime.fromisoformat(row["cycle_started_at"])
    finished = datetime.fromisoformat(row["cycle_finished_at"])
    nxt = datetime.fromisoformat(row["next_cycle_at"])
    assert finished >= started
    assert nxt >= finished


def test_mark_cycle_end_on_error_uses_error_reason(tmp_path):
    store = StateStore(tmp_path / "test.db")
    bot = SimpleNamespace(
        operation_code="ETHUSDT",
        state_store=store,
        time_to_sleep=150,
        time_to_trade=150,
        delay_after_order=7200,
    )
    mark_cycle_end(bot, error=True)
    assert store.list_cycle_heartbeats()[0]["sleep_reason"] == "error"


def test_run_cycle_persists_sleep_after_execute(tmp_path):
    from main import _run_cycle

    store = StateStore(tmp_path / "test.db")
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        state_store=store,
        time_to_sleep=12,
        time_to_trade=12,
        delay_after_order=99,
        execute=lambda: None,
        risk_manager=SimpleNamespace(is_circuit_open=lambda: False),
    )
    _run_cycle(bot, 1)
    row = store.list_cycle_heartbeats()[0]
    assert row["phase"] == "sleeping"
    assert row["sleep_seconds"] == 12
    assert row["sleep_reason"] == "interval"


def test_run_cycle_stays_running_when_execute_raises(tmp_path):
    from main import _run_cycle

    store = StateStore(tmp_path / "test.db")
    bot = SimpleNamespace(
        operation_code="BTCUSDT",
        state_store=store,
        time_to_sleep=12,
        time_to_trade=12,
        delay_after_order=99,
        execute=MagicMock(side_effect=RuntimeError("binance down")),
        risk_manager=SimpleNamespace(is_circuit_open=lambda: False),
    )
    with pytest.raises(RuntimeError, match="binance down"):
        _run_cycle(bot, 1)
    assert store.list_cycle_heartbeats()[0]["phase"] == "running"
