from unittest.mock import MagicMock

from persistence.state_store import StateStore
from services.order_sync import sync_filled_orders_from_binance
from services.outcome_history import (
    SOURCE_EXTERNAL,
    SOURCE_ORDERS,
    WARN_NO_BALANCE,
    WARN_UNTRACKED,
    build_outcome_board,
    match_closed_trades,
    rebuild_outcomes_from_orders,
    realized_pnl,
    reconcile_open_lots,
)


def test_realized_pnl():
    usd, pct = realized_pnl(0.00018, 72338.01, 77630.0)
    assert usd == 0.9526
    assert pct == 7.32


def test_log_order_is_idempotent_by_order_id(tmp_path):
    store = StateStore(tmp_path / "test.db")
    order = {
        "orderId": 65544291506,
        "side": "BUY",
        "type": "LIMIT",
        "status": "FILLED",
        "executedQty": "0.00008",
        "price": "71736.0",
        "cummulativeQuoteQty": "5.73888",
        "fills": [{"price": "71736.0"}],
        "updateTime": 1787234735372,
    }
    assert store.log_order("BTCUSDT", order, created_at="2026-08-20T14:05:35+00:00")
    assert not store.log_order("BTCUSDT", order, created_at="2026-08-20T14:05:35+00:00")
    assert len(store.list_orders()) == 1


def test_sync_filled_orders_from_binance_inserts_missing(tmp_path):
    store = StateStore(tmp_path / "test.db")
    client = MagicMock()
    client.get_all_orders.return_value = [
        {
            "orderId": 65544291506,
            "side": "BUY",
            "type": "LIMIT",
            "status": "FILLED",
            "executedQty": "0.00008",
            "price": "71736.0",
            "cummulativeQuoteQty": "5.73888",
            "updateTime": 1787234735372,
        },
        {
            "orderId": 65544318832,
            "side": "SELL",
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": "0.00011",
            "price": "0",
            "cummulativeQuoteQty": "7.8963148",
            "updateTime": 1787234766681,
        },
        {
            "orderId": 1,
            "side": "BUY",
            "type": "LIMIT",
            "status": "NEW",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
            "updateTime": 1787234800000,
        },
    ]
    first = sync_filled_orders_from_binance(
        client, store, ["BTCUSDT"], cutoff_iso="2026-08-01T00:00:00+00:00"
    )
    second = sync_filled_orders_from_binance(
        client, store, ["BTCUSDT"], cutoff_iso="2026-08-01T00:00:00+00:00"
    )
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    orders = store.list_orders(since="2026-08-01T00:00:00+00:00")
    assert [o["side"] for o in orders] == ["BUY", "SELL"]
    assert orders[0]["order_id"] == 65544291506
    client.get_all_orders.assert_called_with(
        symbol="BTCUSDT",
        limit=1000,
        startTime=1785542400000,
    )


def test_sync_filled_orders_from_binance_paginates_past_page_limit(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "test.db")
    client = MagicMock()
    monkeypatch.setattr("services.order_sync._SYNC_PAGE_SIZE", 2)

    def _page(symbol, limit=2, startTime=None, orderId=None):
        all_orders = [
            {
                "orderId": 10,
                "side": "BUY",
                "type": "LIMIT",
                "status": "FILLED",
                "executedQty": "0.001",
                "price": "100",
                "cummulativeQuoteQty": "0.1",
                "updateTime": 1785542500000,
            },
            {
                "orderId": 11,
                "side": "BUY",
                "type": "LIMIT",
                "status": "FILLED",
                "executedQty": "0.001",
                "price": "101",
                "cummulativeQuoteQty": "0.101",
                "updateTime": 1785542600000,
            },
            {
                "orderId": 12,
                "side": "SELL",
                "type": "MARKET",
                "status": "FILLED",
                "executedQty": "0.001",
                "price": "110",
                "cummulativeQuoteQty": "0.11",
                "updateTime": 1785542700000,
            },
        ]
        if orderId is None:
            return all_orders[:limit]
        return [row for row in all_orders if row["orderId"] >= orderId][:limit]

    client.get_all_orders.side_effect = _page
    result = sync_filled_orders_from_binance(
        client, store, ["BTCUSDT"], cutoff_iso="2026-08-01T00:00:00+00:00"
    )
    assert result["inserted"] == 3
    assert result["scanned"] == 3
    assert client.get_all_orders.call_count == 2
    second_call = client.get_all_orders.call_args_list[1].kwargs
    assert second_call["orderId"] == 12
    orders = store.list_orders(since="2026-08-01T00:00:00+00:00")
    assert [o["order_id"] for o in orders] == [10, 11, 12]


def test_match_closed_trades_fifo_pairs_buys_and_sells():
    closed = match_closed_trades(
        [
            {
                "operation_code": "BTCUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 72338.01,
                "total_quote": 13.0208418,
                "created_at": "2026-08-20T16:25:43+00:00",
                "order_id": 1,
            },
            {
                "operation_code": "ETHUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.0027,
                "price": 2278.18,
                "total_quote": 6.151086,
                "created_at": "2026-08-20T13:55:46+00:00",
                "order_id": 2,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "SELL",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 77630.0,
                "total_quote": 13.9734,
                "created_at": "2026-08-21T15:20:38+00:00",
                "order_id": 3,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 77656.88,
                "total_quote": 13.9782384,
                "created_at": "2026-08-21T15:24:15+00:00",
                "order_id": 4,
            },
            {
                "operation_code": "ETHUSDT",
                "side": "SELL",
                "status": "FILLED",
                "quantity": 0.0025,
                "price": 2415.28,
                "total_quote": 6.0382,
                "created_at": "2026-08-21T19:47:15+00:00",
                "order_id": 5,
            },
        ],
        take_profit_at=[7.0],
        stop_loss_pct=2.0,
        kind_hints={3: "take_profit", 5: "take_profit"},
    )
    assert len(closed) == 2
    btc = next(row for row in closed if row["operation_code"] == "BTCUSDT")
    eth = next(row for row in closed if row["operation_code"] == "ETHUSDT")
    assert btc["kind"] == "take_profit"
    assert btc["pnl_usd"] == 0.9526
    assert eth["kind"] == "take_profit"
    assert abs(eth["pnl_usd"] - 0.3427) < 0.001


def test_rebuild_outcomes_respects_cutoff(tmp_path):
    store = StateStore(tmp_path / "test.db")
    store.log_order(
        "BTCUSDT",
        {
            "orderId": 1,
            "side": "BUY",
            "type": "LIMIT",
            "status": "FILLED",
            "executedQty": "0.00025",
            "cummulativeQuoteQty": "20",
            "fills": [{"price": "80000"}],
        },
        created_at="2025-03-10T13:00:00+00:00",
    )
    store.log_order(
        "BTCUSDT",
        {
            "orderId": 10,
            "side": "BUY",
            "type": "LIMIT",
            "status": "FILLED",
            "executedQty": "0.00018",
            "cummulativeQuoteQty": "13.0208418",
            "fills": [{"price": "72338.01"}],
        },
        created_at="2026-08-20T16:25:43+00:00",
    )
    store.log_order(
        "BTCUSDT",
        {
            "orderId": 11,
            "side": "SELL",
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": "0.00018",
            "cummulativeQuoteQty": "13.9734",
            "fills": [{"price": "77630.0"}],
        },
        created_at="2026-08-21T15:20:38+00:00",
    )
    inserted = rebuild_outcomes_from_orders(
        store,
        take_profit_at=[7.0],
        stop_loss_pct=2.0,
        cutoff_iso="2026-08-01T00:00:00+00:00",
        force=True,
    )
    assert inserted == 1
    rows = store.list_outcomes()
    assert rows[0]["order_id"] == 11
    assert rows[0]["pnl_usd"] == 0.9526


def test_open_lots_from_orders_after_partial_and_full_sells():
    from services.outcome_history import open_lots_from_orders

    open_lots = open_lots_from_orders(
        [
            {
                "operation_code": "ETHUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.0027,
                "price": 2278.18,
                "total_quote": 6.151086,
                "created_at": "2026-08-20T13:55:46+00:00",
                "order_id": 1,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.00008,
                "price": 71736.0,
                "total_quote": 5.73888,
                "created_at": "2026-08-20T14:05:35+00:00",
                "order_id": 2,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "SELL",
                "status": "FILLED",
                "quantity": 0.00011,
                "price": 71784.68,
                "total_quote": 7.8963148,
                "created_at": "2026-08-20T14:06:06+00:00",
                "order_id": 3,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 72338.01,
                "total_quote": 13.0208418,
                "created_at": "2026-08-20T16:25:43+00:00",
                "order_id": 4,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "SELL",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 77630.0,
                "total_quote": 13.9734,
                "created_at": "2026-08-21T15:20:38+00:00",
                "order_id": 5,
            },
            {
                "operation_code": "BTCUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.00018,
                "price": 77656.88,
                "total_quote": 13.9782384,
                "created_at": "2026-08-21T15:24:15+00:00",
                "order_id": 6,
            },
            {
                "operation_code": "ETHUSDT",
                "side": "SELL",
                "status": "FILLED",
                "quantity": 0.0025,
                "price": 2415.28,
                "total_quote": 6.0382,
                "created_at": "2026-08-21T19:47:15+00:00",
                "order_id": 7,
            },
            {
                "operation_code": "ETHUSDT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": 0.0041,
                "price": 2414.93,
                "total_quote": 9.901213,
                "created_at": "2026-08-21T19:53:45+00:00",
                "order_id": 8,
            },
        ]
    )
    eth_lots = [row for row in open_lots if row["operation_code"] == "ETHUSDT"]
    btc_lots = [row for row in open_lots if row["operation_code"] == "BTCUSDT"]
    assert len(btc_lots) == 1
    assert btc_lots[0]["quantity"] == 0.00018
    assert abs(btc_lots[0]["cost_usd"] - 13.9782384) < 0.0001
    assert len(eth_lots) == 2
    assert abs(sum(row["cost_usd"] for row in eth_lots) - (0.0002 * 2278.18 + 9.901213)) < 0.01


def test_build_outcome_board_includes_open_cost_and_skips_unfilled():
    board = build_outcome_board(
        [
            {
                "kind": "take_profit",
                "stock_code": "BTC",
                "operation_code": "BTCUSDT",
                "quantity": 0.00018,
                "buy_price": 72338.01,
                "sell_price": 77630.0,
                "pnl_usd": 0.9526,
                "pnl_pct": 7.32,
                "quote_qty": 13.9734,
                "cost_usd": 13.0208418,
                "filled": 1,
                "occurred_at": "2026-08-21T15:20:38+00:00",
            },
            {
                "kind": "stop_loss",
                "stock_code": "BTC",
                "operation_code": "BTCUSDT",
                "filled": 0,
                "occurred_at": "2026-08-20T13:55:40+00:00",
            },
        ],
        open_lots=[
            {
                "stock_code": "ETH",
                "operation_code": "ETHUSDT",
                "quantity": 0.0041,
                "buy_price": 2414.93,
                "cost_usd": 9.901213,
                "occurred_at": "2026-08-21T19:53:45+00:00",
            }
        ],
    )
    assert board["total_cost_usd"] == 13.02
    assert board["open_cost_usd"] == 9.9
    assert board["total_usd"] == 13.97
    assert board["realized_proceeds_usd"] == 13.97
    assert board["nav_usd"] is None
    assert board["warnings"] == []
    assert board["total_pnl_usd"] == 0.95
    assert len(board["operations"]) == 1
    assert len(board["open_positions"]) == 1
    assert board["open_positions"][0]["stock_code"] == "ETH"
    assert board["open_positions"][0]["source"] == SOURCE_ORDERS


def test_reconcile_open_lots_adds_external_when_live_exceeds_fifo():
    lots, warnings = reconcile_open_lots(
        [],
        [
            {
                "stock_code": "ETH",
                "operation_code": "ETHUSDT",
                "quantity": 0.211,
                "last_buy_price": 2414.93,
            }
        ],
    )
    assert len(lots) == 1
    assert lots[0]["source"] == SOURCE_EXTERNAL
    assert lots[0]["quantity"] == 0.211
    assert abs(lots[0]["cost_usd"] - 0.211 * 2414.93) < 1e-6
    assert warnings[0]["code"] == WARN_UNTRACKED
    assert "ETH" in warnings[0]["message"]


def test_reconcile_open_lots_clips_oldest_when_fifo_exceeds_live():
    lots, warnings = reconcile_open_lots(
        [
            {
                "operation_code": "XRPUSDT",
                "stock_code": "XRP",
                "quantity": 0.10,
                "buy_price": 2.5,
                "cost_usd": 0.25,
                "occurred_at": "2026-08-10T00:00:00+00:00",
            }
        ],
        [
            {
                "stock_code": "XRP",
                "operation_code": "XRPUSDT",
                "quantity": 0.077,
                "last_buy_price": 2.5,
            }
        ],
    )
    assert len(lots) == 1
    assert abs(lots[0]["quantity"] - 0.077) < 1e-9
    assert abs(lots[0]["cost_usd"] - 0.077 * 2.5) < 1e-9
    assert lots[0]["source"] == SOURCE_ORDERS
    assert warnings[0]["code"] == WARN_NO_BALANCE


def test_reconcile_open_lots_clips_oldest_of_two_lots():
    lots, warnings = reconcile_open_lots(
        [
            {
                "operation_code": "XRPUSDT",
                "stock_code": "XRP",
                "quantity": 0.06,
                "buy_price": 2.0,
                "occurred_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "operation_code": "XRPUSDT",
                "stock_code": "XRP",
                "quantity": 0.04,
                "buy_price": 3.0,
                "occurred_at": "2026-08-10T00:00:00+00:00",
            },
        ],
        [{"stock_code": "XRP", "operation_code": "XRPUSDT", "quantity": 0.077}],
    )
    assert warnings[0]["code"] == WARN_NO_BALANCE
    by_price = {row["buy_price"]: row["quantity"] for row in lots}
    assert abs(by_price[2.0] - 0.037) < 1e-9
    assert abs(by_price[3.0] - 0.04) < 1e-9
    assert abs(sum(row["quantity"] for row in lots) - 0.077) < 1e-9


def test_reconcile_open_lots_respects_step_size_as_dust():
    lots, warnings = reconcile_open_lots(
        [
            {
                "operation_code": "XRPUSDT",
                "stock_code": "XRP",
                "quantity": 0.10,
                "buy_price": 2.0,
            }
        ],
        [{"stock_code": "XRP", "operation_code": "XRPUSDT", "quantity": 0.077}],
        step_sizes={"XRPUSDT": 0.1},
    )
    assert len(lots) == 1
    assert abs(lots[0]["quantity"] - 0.10) < 1e-9
    assert warnings == []


def test_reconcile_open_lots_ignores_dust_difference():
    lots, warnings = reconcile_open_lots(
        [
            {
                "operation_code": "SOLUSDT",
                "stock_code": "SOL",
                "quantity": 0.5,
                "buy_price": 140.0,
            }
        ],
        [
            {
                "stock_code": "SOL",
                "operation_code": "SOLUSDT",
                "quantity": 0.5 + 1e-10,
                "last_buy_price": 140.0,
            }
        ],
    )
    assert len(lots) == 1
    assert abs(lots[0]["quantity"] - 0.5) < 1e-9
    assert warnings == []


def test_reconcile_open_lots_skips_stable_quote():
    lots, warnings = reconcile_open_lots(
        [],
        [{"stock_code": "USDT", "operation_code": "USDT", "quantity": 80.0}],
    )
    assert lots == []
    assert warnings == []


def test_reconcile_open_lots_discards_when_live_is_flat():
    lots, warnings = reconcile_open_lots(
        [
            {
                "operation_code": "LINKUSDT",
                "stock_code": "LINK",
                "quantity": 1.0,
                "buy_price": 10.0,
            }
        ],
        [{"stock_code": "LINK", "operation_code": "LINKUSDT", "quantity": 0.0}],
    )
    assert lots == []
    assert warnings[0]["code"] == WARN_NO_BALANCE


def test_build_outcome_board_uses_reconciled_nav_and_external_source():
    board = build_outcome_board(
        [],
        open_lots=[
            {
                "kind": "open",
                "source": SOURCE_EXTERNAL,
                "stock_code": "ETH",
                "operation_code": "ETHUSDT",
                "quantity": 0.211,
                "buy_price": 2414.93,
                "cost_usd": 0.211 * 2414.93,
            }
        ],
        nav_usd=661.59,
        warnings=[{"code": WARN_UNTRACKED, "message": "ETH externo"}],
    )
    assert board["nav_usd"] == 661.59
    assert board["realized_proceeds_usd"] == 0.0
    assert board["open_positions"][0]["source"] == SOURCE_EXTERNAL
    assert board["warnings"][0]["code"] == WARN_UNTRACKED

