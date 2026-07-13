import tempfile
from pathlib import Path

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
