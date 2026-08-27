from types import SimpleNamespace

import pytest

from persistence.state_store import StateStore
from services.portfolio_actions import (
    PortfolioActionError,
    execute_liquidate,
    execute_rebalance,
    preview_liquidate,
    preview_rebalance,
)

ASSETS = [
    SimpleNamespace(stock_code="BTC", operation_code="BTCUSDT", traded_percentage=99),
    SimpleNamespace(stock_code="ETH", operation_code="ETHUSDT", traded_percentage=1),
    SimpleNamespace(stock_code="SOL", operation_code="SOLUSDT", traded_percentage=0),
    SimpleNamespace(stock_code="XRP", operation_code="XRPUSDT", traded_percentage=0),
]

WEIGHTS_100 = {"BTCUSDT": 40, "ETHUSDT": 30, "SOLUSDT": 20, "XRPUSDT": 10}


class FakeSpot:
    def __init__(self, fail_at=None, min_notional=5.0, open_orders=None):
        self.balances = {
            "BTC": {"free": 0.06, "locked": 0.0},
            "ETH": {"free": 1.0, "locked": 0.0},
            "SOL": {"free": 5.0, "locked": 0.0},
            "XRP": {"free": 500.0, "locked": 0.0},
            "USDT": {"free": 1000.0, "locked": 0.0},
        }
        self.prices = {
            "BTCUSDT": 100_000.0,
            "ETHUSDT": 2_000.0,
            "SOLUSDT": 100.0,
            "XRPUSDT": 1.0,
        }
        self.step = {
            "BTCUSDT": 0.00001,
            "ETHUSDT": 0.0001,
            "SOLUSDT": 0.01,
            "XRPUSDT": 0.1,
        }
        self.min_notional = min_notional
        self.fail_at = fail_at
        self.open_orders = open_orders or {}
        self.created = []
        self.cancelled = []
        self._order_id = 1

    def get_account(self):
        return {
            "balances": [
                {
                    "asset": asset,
                    "free": str(row["free"]),
                    "locked": str(row["locked"]),
                }
                for asset, row in self.balances.items()
            ]
        }

    def get_symbol_ticker(self, symbol):
        return {"symbol": symbol, "price": str(self.prices[symbol])}

    def get_symbol_info(self, symbol):
        return {
            "baseAsset": symbol.replace("USDT", ""),
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": str(self.step[symbol])},
                {"filterType": "NOTIONAL", "minNotional": str(self.min_notional)},
            ],
        }

    def get_open_orders(self, symbol):
        return list(self.open_orders.get(symbol, []))

    def cancel_order(self, symbol, orderId):
        self.cancelled.append((symbol, orderId))
        self.open_orders[symbol] = [
            row for row in self.open_orders.get(symbol, []) if row["orderId"] != orderId
        ]

    def create_order(self, **kwargs):
        symbol = kwargs["symbol"]
        side = kwargs["side"]
        qty = float(kwargs["quantity"])
        price = self.prices[symbol]
        base = symbol.replace("USDT", "")
        if self.fail_at == symbol:
            raise RuntimeError(f"fail {symbol}")
        if side == "SELL":
            if self.balances[base]["free"] + 1e-12 < qty:
                raise RuntimeError("insufficient base")
            self.balances[base]["free"] -= qty
            self.balances["USDT"]["free"] += qty * price
        else:
            cost = qty * price
            if self.balances["USDT"]["free"] + 1e-8 < cost:
                raise RuntimeError("insufficient USDT")
            self.balances["USDT"]["free"] -= cost
            self.balances.setdefault(base, {"free": 0.0, "locked": 0.0})
            self.balances[base]["free"] += qty
        order = {
            "symbol": symbol,
            "orderId": self._order_id,
            "side": side,
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": str(qty),
            "cummulativeQuoteQty": str(qty * price),
            "price": "0",
            "transactTime": 1_700_000_000_000,
            "fills": [{"price": str(price), "commissionAsset": "USDT"}],
        }
        self._order_id += 1
        self.created.append(order)
        return order


def test_preview_rebalance_rejects_sum_not_100():
    client = FakeSpot()
    with pytest.raises(PortfolioActionError, match="100%"):
        preview_rebalance(
            client,
            ASSETS,
            {"BTCUSDT": 40, "ETHUSDT": 30, "SOLUSDT": 10, "XRPUSDT": 10},
        )


def test_preview_rebalance_rejects_unknown_symbol():
    with pytest.raises(PortfolioActionError, match="fora do YAML"):
        preview_rebalance(FakeSpot(), ASSETS, {"BNBUSDT": 100})


def test_preview_rebalance_sells_then_buys():
    preview = preview_rebalance(FakeSpot(), ASSETS, WEIGHTS_100)
    sides = [row["side"] for row in preview["orders"] if not row.get("skipped")]
    assert sides[0] == "SELL"
    assert "BUY" in sides
    assert sides.index("SELL") < sides.index("BUY")
    sell = next(row for row in preview["orders"] if row["operation_code"] == "BTCUSDT")
    assert sell["side"] == "SELL"
    assert sell["notional"] == pytest.approx(2000.0, rel=0.01)


def test_execute_rebalance_sells_before_buys_and_ignores_yaml_weights(tmp_path):
    client = FakeSpot()
    store = StateStore(tmp_path / "t.db")
    result = execute_rebalance(client, ASSETS, WEIGHTS_100, store, "BALANCE")
    assert result["ok"] is True
    assert store.is_action_hold() is False
    sides = [order["side"] for order in client.created]
    assert sides[0] == "SELL"
    assert sides[1:] == ["BUY", "BUY", "BUY"]
    assert [order["symbol"] for order in client.created] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]
    assert client.balances["BTC"]["free"] == pytest.approx(0.04, rel=0.01)
    assert client.balances["ETH"]["free"] == pytest.approx(1.5, rel=0.01)
    btc_state = store.load_state("BTCUSDT")
    assert btc_state.actual_trade_position is True


def test_execute_rebalance_aborts_on_second_sell_and_keeps_hold(tmp_path):
    client = FakeSpot(fail_at="ETHUSDT")
    store = StateStore(tmp_path / "t.db")
    weights = {"BTCUSDT": 10, "ETHUSDT": 10, "SOLUSDT": 40, "XRPUSDT": 40}
    result = execute_rebalance(client, ASSETS, weights, store, "BALANCE")
    assert result["ok"] is False
    assert result["partial"] is True
    assert result["aborted_at"] == "ETHUSDT"
    assert store.is_action_hold() is True
    assert [order["symbol"] for order in client.created] == ["BTCUSDT"]


def test_dust_below_min_notional_is_skipped():
    client = FakeSpot(min_notional=50_000)
    preview = preview_rebalance(client, ASSETS, WEIGHTS_100)
    skipped = [row for row in preview["orders"] if row.get("skipped")]
    assert skipped
    assert {row["reason"] for row in skipped} <= {"dust", "no price"}


def test_liquidate_only_selected_symbol(tmp_path):
    client = FakeSpot()
    store = StateStore(tmp_path / "t.db")
    result = execute_liquidate(client, ASSETS, ["ETHUSDT"], store, "LIQUIDATE")
    assert result["ok"] is True
    assert [order["symbol"] for order in client.created] == ["ETHUSDT"]
    assert order_side(client.created[0]) == "SELL"
    assert client.balances["ETH"]["free"] == pytest.approx(0.0)
    assert client.balances["BTC"]["free"] == pytest.approx(0.06)
    eth_state = store.load_state("ETHUSDT")
    assert eth_state.actual_trade_position is False


def order_side(order):
    return order["side"]


def test_liquidate_empty_symbols_rejected():
    with pytest.raises(PortfolioActionError, match="pelo menos um par"):
        preview_liquidate(FakeSpot(), ASSETS, [])


def test_liquidate_unknown_symbol_rejected():
    with pytest.raises(PortfolioActionError, match="fora do YAML"):
        preview_liquidate(FakeSpot(), ASSETS, ["BNBUSDT"])


def test_liquidate_already_flat_is_skipped(tmp_path):
    client = FakeSpot()
    client.balances["ETH"]["free"] = 0.0
    store = StateStore(tmp_path / "t.db")
    result = execute_liquidate(client, ASSETS, ["ETHUSDT"], store, "LIQUIDATE")
    assert result["ok"] is True
    assert client.created == []
    assert result["skipped"][0]["reason"] == "already flat"


def test_wrong_confirm_does_not_set_hold(tmp_path):
    client = FakeSpot()
    store = StateStore(tmp_path / "t.db")
    with pytest.raises(PortfolioActionError, match="Confirmação"):
        execute_liquidate(client, ASSETS, ["ETHUSDT"], store, "nope")
    assert store.is_action_hold() is False
    assert client.created == []


def test_cancels_open_orders_on_selected_symbol(tmp_path):
    client = FakeSpot(
        open_orders={"ETHUSDT": [{"orderId": 44, "symbol": "ETHUSDT"}]}
    )
    store = StateStore(tmp_path / "t.db")
    execute_liquidate(client, ASSETS, ["ETHUSDT"], store, "LIQUIDATE")
    assert ("ETHUSDT", 44) in client.cancelled
    assert client.open_orders["ETHUSDT"] == []
