import tempfile
from pathlib import Path

import pytest

from persistence.state_store import BotState, StateStore


def test_state_persistence_and_reconcile():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        store = StateStore(db_path)

        state = BotState(operation_code="BTCUSDT", take_profit_index=2, last_buy_price=50000)
        store.save_state(state)

        loaded = store.load_state("BTCUSDT")
        assert loaded.take_profit_index == 2
        assert loaded.last_buy_price == 50000

        reconciled = store.reconcile(
            loaded,
            position_open=False,
            last_buy_price=51000,
            last_sell_price=52000,
        )
        assert reconciled.actual_trade_position is False
        assert reconciled.take_profit_index == 0
        assert reconciled.last_buy_price == 51000


def test_record_outcome_and_list_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(Path(tmp) / "test.db")
        assert store.record_outcome(
            {
                "kind": "stop_loss",
                "operation_code": "BTCUSDT",
                "stock_code": "BTC",
                "occurred_at": "2026-08-20T13:55:40+00:00",
                "filled": False,
                "source": "log",
            }
        )
        assert store.record_outcome(
            {
                "kind": "take_profit",
                "operation_code": "ETHUSDT",
                "stock_code": "ETH",
                "pnl_usd": 0.34,
                "pnl_pct": 6.02,
                "occurred_at": "2026-08-21T19:47:15+00:00",
                "source": "log",
            }
        )
        assert not store.record_outcome(
            {
                "kind": "take_profit",
                "operation_code": "ETHUSDT",
                "occurred_at": "2026-08-21T19:47:15+00:00",
            }
        )
        rows = store.list_outcomes()
        assert [row["kind"] for row in rows] == ["take_profit", "stop_loss"]
        assert rows[0]["pnl_usd"] == 0.34


def test_daily_risk_roundtrip_and_derived(tmp_path):
    store = StateStore(tmp_path / "test.db")
    store.save_daily_risk("2026-08-22", "BTCUSDT", trades=2, grid_trades=4, loss_usdt=12.5)
    loaded = store.load_daily_risk("2026-08-22", "BTCUSDT")
    assert loaded == {"trades": 2, "grid_trades": 4, "loss_usdt": 12.5}
    assert store.load_daily_risk("2026-08-22", "ETHUSDT")["trades"] == 0

    store.log_order(
        "BTCUSDT",
        {
            "orderId": 1,
            "side": "SELL",
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "9000",
            "fills": [{"price": "90000"}],
        },
        created_at="2026-08-22T12:00:00+00:00",
    )
    store.record_outcome(
        {
            "kind": "stop_loss",
            "operation_code": "BTCUSDT",
            "pnl_usd": -15.0,
            "filled": True,
            "occurred_at": "2026-08-22T12:00:01+00:00",
        }
    )
    derived = store.derived_daily_risk("2026-08-22", "BTCUSDT")
    assert derived["trades"] == 1
    assert derived["loss_usdt"] == pytest.approx(15.0)
    assert store.derived_daily_risk("2026-08-21", "BTCUSDT")["trades"] == 0


def test_action_hold_roundtrip(tmp_path):
    store = StateStore(tmp_path / "test.db")
    assert store.is_action_hold() is False
    store.set_action_hold(True)
    assert store.is_action_hold() is True
    store.set_action_hold(False)
    assert store.is_action_hold() is False

