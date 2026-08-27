from typing import Any, Iterable, Optional

from services.asset_variation import unrealized_pnl_pct
from services.market_data import MarketDataService

STABLE_USD = frozenset({"USDT", "BUSD", "USDC", "FDUSD", "TUSD", "USD"})


def _asset_fields(asset: Any) -> tuple[str, str]:
    if isinstance(asset, dict):
        stock_code = asset.get("stock_code") or asset.get("stockCode") or ""
        operation_code = asset.get("operation_code") or asset.get("operationCode") or ""
        return str(stock_code), str(operation_code)
    return str(asset.stock_code), str(asset.operation_code)


def quote_from_pair(stock_code: str, operation_code: str) -> str:
    if stock_code and operation_code.startswith(stock_code):
        quote = operation_code[len(stock_code) :]
        if quote:
            return quote
    for candidate in ("USDT", "BUSD", "USDC", "FDUSD", "TUSD", "BTC", "ETH"):
        if operation_code.endswith(candidate) and operation_code != candidate:
            return candidate
    return "USDT"


def parse_balances(account_data: Optional[dict]) -> dict[str, float]:
    balances: dict[str, float] = {}
    if not account_data:
        return balances
    for row in account_data.get("balances", []):
        asset = row.get("asset")
        if not asset:
            continue
        quantity = float(row.get("free", 0) or 0) + float(row.get("locked", 0) or 0)
        if quantity:
            balances[asset] = quantity
    return balances


def parse_free_balances(account_data: Optional[dict]) -> dict[str, float]:
    balances: dict[str, float] = {}
    if not account_data:
        return balances
    for row in account_data.get("balances", []):
        asset = row.get("asset")
        if not asset:
            continue
        quantity = float(row.get("free", 0) or 0)
        if quantity:
            balances[asset] = quantity
    return balances


def _holding_pnl(
    quantity: float, mark_price: float, last_buy_price: float
) -> tuple[Optional[float], Optional[float], float]:
    if quantity <= 0 or mark_price <= 0 or last_buy_price <= 0:
        return None, None, 0.0
    cost_basis = quantity * last_buy_price
    pnl_usd = quantity * (mark_price - last_buy_price)
    pnl_pct = unrealized_pnl_pct(mark_price, last_buy_price)
    return pnl_usd, pnl_pct, cost_basis


def compute_portfolio(
    assets: Iterable[Any],
    balances: dict[str, float],
    prices: dict[str, float],
    last_buy_prices: Optional[dict[str, float]] = None,
) -> dict:
    holdings = []
    total_usd = 0.0
    total_pnl_usd = 0.0
    total_cost_basis = 0.0
    quotes: set[str] = set()
    seen_assets: set[str] = set()
    last_buy_prices = last_buy_prices or {}

    for asset in assets:
        stock_code, operation_code = _asset_fields(asset)
        if not stock_code or not operation_code:
            continue
        quantity = float(balances.get(stock_code, 0.0))
        price = float(prices.get(operation_code, 0.0) or 0.0)
        last_buy = float(last_buy_prices.get(operation_code, 0.0) or 0.0)
        usd_value = quantity * price if price > 0 else 0.0
        pnl_usd, pnl_pct, cost_basis = _holding_pnl(quantity, price, last_buy)
        holdings.append(
            {
                "stock_code": stock_code,
                "operation_code": operation_code,
                "quantity": quantity,
                "price": price,
                "usd_value": round(usd_value, 4),
                "last_buy_price": last_buy,
                "pnl_usd": None if pnl_usd is None else round(pnl_usd, 4),
                "pnl_pct": None if pnl_pct is None else round(pnl_pct, 2),
            }
        )
        total_usd += usd_value
        if pnl_usd is not None:
            total_pnl_usd += pnl_usd
            total_cost_basis += cost_basis
        seen_assets.add(stock_code)
        quotes.add(quote_from_pair(stock_code, operation_code))

    for quote in sorted(quotes):
        if quote in seen_assets or quote not in STABLE_USD:
            continue
        quantity = float(balances.get(quote, 0.0))
        if quantity <= 0:
            continue
        holdings.append(
            {
                "stock_code": quote,
                "operation_code": quote,
                "quantity": quantity,
                "price": 1.0,
                "usd_value": round(quantity, 4),
                "last_buy_price": 1.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
            }
        )
        total_usd += quantity
        seen_assets.add(quote)

    total_pnl_pct = None
    if total_cost_basis > 0:
        total_pnl_pct = round((total_pnl_usd / total_cost_basis) * 100, 2)

    return {
        "total_usd": round(total_usd, 2),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "total_pnl_pct": total_pnl_pct,
        "assets": holdings,
    }


def fetch_prices(client, symbols: Iterable[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for symbol in symbols:
        if not symbol or symbol in prices:
            continue
        ticker = client.get_symbol_ticker(symbol=symbol)
        prices[symbol] = float(ticker["price"])
    return prices


def fetch_missing_entry_prices(
    client,
    assets: Iterable[Any],
    balances: dict[str, float],
    last_buy_prices: dict[str, float],
) -> dict[str, float]:
    filled = dict(last_buy_prices)
    for asset in assets:
        stock_code, operation_code = _asset_fields(asset)
        if float(filled.get(operation_code, 0.0) or 0.0) > 0:
            continue
        if float(balances.get(stock_code, 0.0) or 0.0) <= 0:
            continue
        orders = client.get_all_orders(symbol=operation_code, limit=100)
        entry = MarketDataService.get_last_fill_price(orders, "BUY")
        if entry > 0:
            filled[operation_code] = entry
    return filled


def fetch_portfolio(
    client,
    assets: Iterable[Any],
    last_buy_prices: Optional[dict[str, float]] = None,
) -> dict:
    account_data = client.get_account()
    balances = parse_balances(account_data)
    symbols = [_asset_fields(asset)[1] for asset in assets]
    prices = fetch_prices(client, symbols)
    entries = fetch_missing_entry_prices(
        client, assets, balances, last_buy_prices or {}
    )
    return compute_portfolio(assets, balances, prices, entries)
