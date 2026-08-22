from services.profit_board import build_profit_board, classify_holding


def _holding(
    stock_code,
    operation_code,
    *,
    quantity=0.01,
    price=65000.0,
    usd_value=None,
    last_buy_price=60000.0,
    pnl_usd=None,
    pnl_pct=None,
):
    usd_value = quantity * price if usd_value is None else usd_value
    if pnl_usd is None and last_buy_price:
        pnl_usd = quantity * (price - last_buy_price)
        pnl_pct = round(((price - last_buy_price) / last_buy_price) * 100, 2)
    return {
        "stock_code": stock_code,
        "operation_code": operation_code,
        "quantity": quantity,
        "price": price,
        "usd_value": usd_value,
        "last_buy_price": last_buy_price,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
    }


def test_classify_holding_as_take_profit_when_variation_reaches_level():
    holding = _holding("BTC", "BTCUSDT", price=64200, last_buy_price=60000)
    assert classify_holding(holding, take_profit_pct=7.0, stop_loss_pct=2.0) == "take_profit"


def test_classify_holding_as_stop_loss_when_variation_hits_stop():
    holding = _holding("ETH", "ETHUSDT", price=1960, last_buy_price=2000)
    assert classify_holding(holding, take_profit_pct=7.0, stop_loss_pct=2.0) == "stop_loss"


def test_classify_holding_marks_open_when_between_thresholds():
    holding = _holding("BTC", "BTCUSDT", price=67000, last_buy_price=65000)
    assert classify_holding(holding, take_profit_pct=7.0, stop_loss_pct=2.0) == "open"


def test_classify_holding_skips_stablecoin_and_empty_qty():
    usdt = _holding("USDT", "USDT", quantity=100, price=1.0, last_buy_price=1.0)
    empty = _holding("BTC", "BTCUSDT", quantity=0, price=80000)
    assert classify_holding(usdt, take_profit_pct=7.0, stop_loss_pct=2.0) is None
    assert classify_holding(empty, take_profit_pct=7.0, stop_loss_pct=2.0) is None


def test_build_profit_board_aggregates_open_and_resolved_operations():
    board = build_profit_board(
        [
            _holding("BTC", "BTCUSDT", quantity=0.01, price=80000, last_buy_price=60000),
            _holding("ETH", "ETHUSDT", quantity=0.2, price=1960, last_buy_price=2000),
            _holding("USDT", "USDT", quantity=100, price=1.0, last_buy_price=1.0),
        ],
        [7.0],
        2.0,
    )
    assert [row["kind"] for row in board["operations"]] == ["take_profit", "stop_loss"]
    assert [row["stock_code"] for row in board["operations"]] == ["BTC", "ETH"]
    # BTC: 0.01 * 80000 = 800; ETH: 0.2 * 1960 = 392
    assert board["total_usd"] == 1192.0
    # BTC: 0.01 * 20000 = 200; ETH: 0.2 * -40 = -8
    assert board["total_pnl_usd"] == 192.0
    # cost: 600 + 400 = 1000 → 19.2%
    assert board["total_pnl_pct"] == 19.2
    assert board["operations"][0]["pnl_usd"] == 200.0
    assert board["operations"][1]["pnl_usd"] == -8.0


def test_build_profit_board_includes_open_positions_between_thresholds():
    board = build_profit_board(
        [_holding("BTC", "BTCUSDT", quantity=0.01, price=67000, last_buy_price=65000)],
        [7.0],
        2.0,
    )
    assert board["operations"][0]["kind"] == "open"
    assert board["operations"][0]["stock_code"] == "BTC"
    assert board["total_usd"] == 670.0
    assert board["total_pnl_usd"] == 20.0
    assert board["total_pnl_pct"] == 3.08
