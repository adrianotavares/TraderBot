from unittest.mock import MagicMock

from services.portfolio import (
    compute_portfolio,
    fetch_portfolio,
    parse_balances,
    parse_free_balances,
    quote_from_pair,
)


def test_quote_from_pair_strips_base_asset():
    assert quote_from_pair("BTC", "BTCUSDT") == "USDT"
    assert quote_from_pair("ETH", "ETHUSDT") == "USDT"


def test_parse_balances_sums_free_and_locked():
    balances = parse_balances(
        {
            "balances": [
                {"asset": "BTC", "free": "0.01", "locked": "0.005"},
                {"asset": "ETH", "free": "0", "locked": "0"},
                {"asset": "USDT", "free": "80", "locked": "20"},
            ]
        }
    )
    assert balances["BTC"] == 0.015
    assert "ETH" not in balances
    assert balances["USDT"] == 100.0


def test_parse_free_balances_ignores_locked():
    balances = parse_free_balances(
        {
            "balances": [
                {"asset": "BTC", "free": "0.01", "locked": "0.005"},
                {"asset": "USDT", "free": "80", "locked": "20"},
            ]
        }
    )
    assert balances["BTC"] == 0.01
    assert balances["USDT"] == 80.0


def test_compute_portfolio_sums_assets_and_quote_to_usd():
    snapshot = compute_portfolio(
        [
            {"stock_code": "BTC", "operation_code": "BTCUSDT"},
            {"stock_code": "ETH", "operation_code": "ETHUSDT"},
        ],
        {"BTC": 0.01, "ETH": 0.2, "USDT": 100.0},
        {"BTCUSDT": 65000.0, "ETHUSDT": 2500.0},
    )
    assert snapshot["total_usd"] == 1250.0
    assert snapshot["total_pnl_usd"] == 0.0
    assert snapshot["total_pnl_pct"] is None
    by_code = {row["stock_code"]: row["usd_value"] for row in snapshot["assets"]}
    assert by_code["BTC"] == 650.0
    assert by_code["ETH"] == 500.0
    assert by_code["USDT"] == 100.0


def test_compute_portfolio_aggregates_pnl_by_cost_basis():
    snapshot = compute_portfolio(
        [
            {"stock_code": "BTC", "operation_code": "BTCUSDT"},
            {"stock_code": "ETH", "operation_code": "ETHUSDT"},
        ],
        {"BTC": 0.01, "ETH": 0.2, "USDT": 100.0},
        {"BTCUSDT": 65000.0, "ETHUSDT": 2500.0},
        {"BTCUSDT": 60000.0, "ETHUSDT": 2000.0},
    )
    # BTC: 0.01 * (65000-60000) = 50; cost 600
    # ETH: 0.2 * (2500-2000) = 100; cost 400
    # USDT cash does not enter the P&L total
    assert snapshot["total_usd"] == 1250.0
    assert snapshot["total_pnl_usd"] == 150.0
    assert snapshot["total_pnl_pct"] == 15.0
    by_code = {row["stock_code"]: row for row in snapshot["assets"]}
    assert by_code["BTC"]["pnl_usd"] == 50.0
    assert by_code["ETH"]["pnl_usd"] == 100.0
    assert by_code["USDT"]["pnl_usd"] == 0.0


def test_compute_portfolio_aggregates_negative_pnl_without_usdt():
    snapshot = compute_portfolio(
        [
            {"stock_code": "BTC", "operation_code": "BTCUSDT"},
            {"stock_code": "ETH", "operation_code": "ETHUSDT"},
        ],
        {"BTC": 0.01, "ETH": 0.2, "USDT": 500.0},
        {"BTCUSDT": 55000.0, "ETHUSDT": 1800.0},
        {"BTCUSDT": 60000.0, "ETHUSDT": 2000.0},
    )
    # BTC: 0.01 * (55000-60000) = -50; cost 600
    # ETH: 0.2 * (1800-2000) = -40; cost 400
    # USDT cash must not dilute the -9% on invested cost
    assert snapshot["total_pnl_usd"] == -90.0
    assert snapshot["total_pnl_pct"] == -9.0
    assert snapshot["total_usd"] == 1410.0


def test_compute_portfolio_skips_assets_without_entry_price():
    snapshot = compute_portfolio(
        [
            {"stock_code": "BTC", "operation_code": "BTCUSDT"},
            {"stock_code": "ETH", "operation_code": "ETHUSDT"},
        ],
        {"BTC": 0.01, "ETH": 0.2},
        {"BTCUSDT": 65000.0, "ETHUSDT": 2500.0},
        {"BTCUSDT": 60000.0},
    )
    assert snapshot["total_pnl_usd"] == 50.0
    assert snapshot["total_pnl_pct"] == 8.33
    by_code = {row["stock_code"]: row for row in snapshot["assets"]}
    assert by_code["ETH"]["pnl_usd"] is None


def test_compute_portfolio_skips_zero_quote_balance():
    snapshot = compute_portfolio(
        [{"stockCode": "BTC", "operationCode": "BTCUSDT"}],
        {"BTC": 0.002},
        {"BTCUSDT": 50000.0},
    )
    assert snapshot["total_usd"] == 100.0
    assert [row["stock_code"] for row in snapshot["assets"]] == ["BTC"]


def test_fetch_portfolio_uses_account_and_tickers():
    client = MagicMock()
    client.get_account.return_value = {
        "balances": [
            {"asset": "BTC", "free": "0.01", "locked": "0"},
            {"asset": "USDT", "free": "40", "locked": "10"},
        ]
    }
    client.get_symbol_ticker.return_value = {"symbol": "BTCUSDT", "price": "50000"}

    snapshot = fetch_portfolio(
        client,
        [{"stock_code": "BTC", "operation_code": "BTCUSDT"}],
        last_buy_prices={"BTCUSDT": 40000.0},
    )

    assert snapshot["total_usd"] == 550.0
    assert snapshot["total_pnl_usd"] == 100.0
    assert snapshot["total_pnl_pct"] == 25.0
    client.get_symbol_ticker.assert_called_once_with(symbol="BTCUSDT")
    client.get_all_orders.assert_not_called()


def test_fetch_portfolio_fills_missing_entry_from_last_buy():
    client = MagicMock()
    client.get_account.return_value = {
        "balances": [{"asset": "BTC", "free": "0.01", "locked": "0"}]
    }
    client.get_symbol_ticker.return_value = {"symbol": "BTCUSDT", "price": "50000"}
    client.get_all_orders.return_value = [
        {
            "side": "BUY",
            "status": "FILLED",
            "time": 2,
            "executedQty": "0.01",
            "cummulativeQuoteQty": "400",
        }
    ]

    snapshot = fetch_portfolio(
        client, [{"stock_code": "BTC", "operation_code": "BTCUSDT"}]
    )

    assert snapshot["total_pnl_usd"] == 100.0
    client.get_all_orders.assert_called_once_with(symbol="BTCUSDT", limit=100)
