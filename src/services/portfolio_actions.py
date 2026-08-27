import logging
from typing import Any, Iterable

from binance.enums import SIDE_BUY, SIDE_SELL

from modules.logging_setup import log_event
from services.market_data import MarketDataService
from services.order_executor import OrderExecutor
from services.outcome_history import fill_from_order
from services.portfolio import (
    _asset_fields,
    fetch_prices,
    parse_balances,
    parse_free_balances,
    quote_from_pair,
)

WEIGHT_SUM_TOLERANCE = 0.01
QUOTE_BUFFER = 0.002
CONFIRM_REBALANCE = "BALANCE"
CONFIRM_LIQUIDATE = "LIQUIDATE"


class PortfolioActionError(ValueError):
    def __init__(self, message: str, blockers: list | None = None):
        super().__init__(message)
        self.blockers = blockers or []


def _configured_assets(assets: Iterable[Any]) -> list[tuple[str, str]]:
    pairs = []
    for asset in assets:
        stock_code, operation_code = _asset_fields(asset)
        if stock_code and operation_code:
            pairs.append((stock_code, operation_code.upper()))
    return pairs


def _allowlist(assets: Iterable[Any]) -> set[str]:
    return {symbol for _, symbol in _configured_assets(assets)}


def _stock_for(assets: Iterable[Any], symbol: str) -> str:
    wanted = symbol.upper()
    for stock_code, operation_code in _configured_assets(assets):
        if operation_code == wanted:
            return stock_code
    raise PortfolioActionError(f"Par fora do YAML: {symbol}", blockers=[symbol])


def _validate_symbols(symbols: Any, allowlist: set[str]) -> list[str]:
    if not isinstance(symbols, list) or not symbols:
        raise PortfolioActionError(
            "Selecione pelo menos um par para liquidar",
            blockers=["symbols"],
        )
    seen: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol:
            continue
        if symbol not in allowlist:
            raise PortfolioActionError(
                f"Par fora do YAML: {symbol}",
                blockers=[symbol],
            )
        if symbol not in seen:
            seen.append(symbol)
    if not seen:
        raise PortfolioActionError(
            "Selecione pelo menos um par para liquidar",
            blockers=["symbols"],
        )
    return seen


def _validate_weights(weights: Any, allowlist: set[str]) -> dict[str, float]:
    if not isinstance(weights, dict) or not weights:
        raise PortfolioActionError("Informe os pesos alvo", blockers=["weights"])
    parsed: dict[str, float] = {}
    for key, raw in weights.items():
        symbol = str(key or "").strip().upper()
        if symbol not in allowlist:
            raise PortfolioActionError(
                f"Par fora do YAML: {symbol}",
                blockers=[symbol],
            )
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise PortfolioActionError(
                f"Peso inválido para {symbol}",
                blockers=[symbol],
            ) from exc
        if value < 0:
            raise PortfolioActionError(
                f"Peso negativo para {symbol}",
                blockers=[symbol],
            )
        parsed[symbol] = value
    total = sum(parsed.values())
    if abs(total - 100.0) > WEIGHT_SUM_TOLERANCE:
        raise PortfolioActionError(
            f"Soma dos pesos deve ser 100% (atual {total:.2f}%)",
            blockers=["sum"],
        )
    for symbol in allowlist:
        parsed.setdefault(symbol, 0.0)
    return parsed


def _require_confirm(confirm: str, expected: str) -> None:
    if str(confirm or "").strip() != expected:
        raise PortfolioActionError(
            f"Confirmação inválida (digite {expected})",
            blockers=["confirm"],
        )


def _filters(client, symbol: str) -> dict:
    market = MarketDataService(client, symbol, "4h")
    return market.get_symbol_filters()


def _executor(client, symbol: str, stock_code: str, filters: dict) -> OrderExecutor:
    return OrderExecutor(
        client,
        symbol,
        stock_code,
        float(filters["tick_size"]),
        float(filters["step_size"]),
    )


def _cancel_open(client, symbol: str, stock_code: str, filters: dict) -> int:
    open_orders = client.get_open_orders(symbol=symbol) or []
    if not open_orders:
        return 0
    _executor(client, symbol, stock_code, filters).cancel_all_orders(open_orders)
    return len(open_orders)


def _snapshot(client, assets: Iterable[Any], free_only: bool = False) -> dict:
    pairs = _configured_assets(assets)
    if not pairs:
        raise PortfolioActionError("Nenhum par configurado no YAML", blockers=["assets"])
    account = client.get_account()
    balances = parse_free_balances(account) if free_only else parse_balances(account)
    symbols = [symbol for _, symbol in pairs]
    prices = fetch_prices(client, symbols)
    filters = {symbol: _filters(client, symbol) for symbol in symbols}
    quotes = {quote_from_pair(stock, symbol) for stock, symbol in pairs}
    if len(quotes) != 1:
        raise PortfolioActionError(
            "Balance/Liquidate exige o mesmo quote em todos os pares",
            blockers=["quote"],
        )
    quote_asset = quotes.pop()
    holdings = []
    nav = float(balances.get(quote_asset, 0.0) or 0.0)
    for stock_code, symbol in pairs:
        qty = float(balances.get(stock_code, 0.0) or 0.0)
        price = float(prices.get(symbol, 0.0) or 0.0)
        usd_value = qty * price if price > 0 else 0.0
        nav += usd_value
        holdings.append(
            {
                "stock_code": stock_code,
                "operation_code": symbol,
                "quantity": qty,
                "price": price,
                "usd_value": usd_value,
                "step_size": float(filters[symbol]["step_size"]),
                "min_notional": float(filters[symbol]["min_notional"]),
                "tick_size": float(filters[symbol]["tick_size"]),
            }
        )
    return {
        "quote_asset": quote_asset,
        "quote_qty": float(balances.get(quote_asset, 0.0) or 0.0),
        "nav": nav,
        "holdings": holdings,
        "filters": filters,
        "balances": balances,
        "prices": prices,
    }


def _size_sell(quantity: float, price: float, step_size: float, min_notional: float) -> float:
    return MarketDataService.size_quantity_for_filters(
        quantity,
        price,
        step_size,
        min_notional=min_notional,
        bump_to_min_notional=False,
    )


def _size_buy(
    quantity: float,
    price: float,
    step_size: float,
    min_notional: float,
    max_quote: float,
) -> float:
    return MarketDataService.size_quantity_for_filters(
        quantity,
        price,
        step_size,
        min_notional=min_notional,
        max_quote=max_quote,
        bump_to_min_notional=True,
    )


def _order_payload(holding: dict, side: str, quantity: float, reason: str = "") -> dict:
    notional = quantity * float(holding["price"])
    return {
        "operation_code": holding["operation_code"],
        "stock_code": holding["stock_code"],
        "side": side,
        "quantity": quantity,
        "price": holding["price"],
        "notional": round(notional, 8),
        "reason": reason,
    }


def _skipped(holding: dict, side: str, reason: str) -> dict:
    return {
        "operation_code": holding["operation_code"],
        "stock_code": holding["stock_code"],
        "side": side,
        "quantity": 0.0,
        "price": holding["price"],
        "notional": 0.0,
        "skipped": True,
        "reason": reason,
    }


def preview_liquidate(client, assets: Iterable[Any], symbols: Any) -> dict:
    allowlist = _allowlist(assets)
    selected = _validate_symbols(symbols, allowlist)
    snapshot = _snapshot(client, assets)
    by_symbol = {row["operation_code"]: row for row in snapshot["holdings"]}
    sells = []
    for symbol in selected:
        holding = by_symbol[symbol]
        qty = _size_sell(
            holding["quantity"],
            holding["price"],
            holding["step_size"],
            holding["min_notional"],
        )
        if qty <= 0:
            reason = (
                "already flat"
                if holding["quantity"] < holding["step_size"]
                else "below min_notional"
            )
            sells.append(_skipped(holding, SIDE_SELL, reason))
        else:
            sells.append(_order_payload(holding, SIDE_SELL, qty))
    return {
        "nav": round(snapshot["nav"], 8),
        "quote_asset": snapshot["quote_asset"],
        "sells": sells,
        "blockers": [],
    }


def preview_rebalance(client, assets: Iterable[Any], weights: Any) -> dict:
    allowlist = _allowlist(assets)
    parsed = _validate_weights(weights, allowlist)
    snapshot = _snapshot(client, assets)
    nav = snapshot["nav"]
    sells: list[dict] = []
    buys: list[dict] = []
    for holding in snapshot["holdings"]:
        symbol = holding["operation_code"]
        target = nav * (parsed[symbol] / 100.0)
        delta = target - holding["usd_value"]
        min_notional = holding["min_notional"]
        if abs(delta) < min_notional or holding["price"] <= 0:
            skipped = _skipped(
                holding,
                SIDE_SELL if delta < 0 else SIDE_BUY,
                "dust" if holding["price"] > 0 else "no price",
            )
            if delta < 0:
                sells.append(skipped)
            else:
                buys.append(skipped)
            continue
        raw_qty = abs(delta) / holding["price"]
        if delta < 0:
            qty = _size_sell(
                min(raw_qty, holding["quantity"]),
                holding["price"],
                holding["step_size"],
                min_notional,
            )
            if qty <= 0:
                sells.append(_skipped(holding, SIDE_SELL, "dust"))
            else:
                sells.append(_order_payload(holding, SIDE_SELL, qty))
        else:
            qty = _size_buy(
                raw_qty,
                holding["price"],
                holding["step_size"],
                min_notional,
                max_quote=abs(delta),
            )
            if qty <= 0:
                buys.append(_skipped(holding, SIDE_BUY, "dust"))
            else:
                buys.append(_order_payload(holding, SIDE_BUY, qty))
    return {
        "nav": round(nav, 8),
        "quote_asset": snapshot["quote_asset"],
        "weights": parsed,
        "orders": sells + buys,
        "sells": sells,
        "buys": buys,
        "blockers": [],
    }


def _apply_state_after_fill(
    store,
    holding: dict,
    side: str,
    order: dict,
    remaining_qty: float,
) -> None:
    state = store.load_state(holding["operation_code"])
    quantity, fill_price, _quote = fill_from_order(order)
    if side == SIDE_SELL:
        if fill_price > 0:
            state.last_sell_price = fill_price
        state.actual_trade_position = remaining_qty >= holding["step_size"]
        if not state.actual_trade_position:
            state.take_profit_index = 0
    else:
        if fill_price > 0:
            state.last_buy_price = fill_price
        state.actual_trade_position = remaining_qty >= holding["step_size"]
    store.save_state(state)
    store.log_order(holding["operation_code"], order)
    log_event(
        logging.INFO,
        f"Portfolio {side} filled for {holding['operation_code']}",
        event="portfolio_fill",
        operation_code=holding["operation_code"],
        stock_code=holding["stock_code"],
        side=side,
        quantity=quantity,
        price=fill_price,
        order_id=order.get("orderId"),
    )


def _place(
    client,
    holding: dict,
    side: str,
    quantity: float,
) -> dict:
    filters = {
        "tick_size": holding["tick_size"],
        "step_size": holding["step_size"],
    }
    executor = _executor(
        client,
        holding["operation_code"],
        holding["stock_code"],
        filters,
    )
    order = executor.place_market(side, quantity)
    if not OrderExecutor.is_filled(order):
        status = (order or {}).get("status")
        raise RuntimeError(
            f"Ordem {side} {holding['operation_code']} não preenchida ({status})"
        )
    return order


def execute_liquidate(
    client,
    assets: Iterable[Any],
    symbols: Any,
    store,
    confirm: str,
) -> dict:
    _require_confirm(confirm, CONFIRM_LIQUIDATE)
    allowlist = _allowlist(assets)
    selected = _validate_symbols(symbols, allowlist)
    store.set_action_hold(True)
    log_event(
        logging.INFO,
        "Portfolio liquidate started",
        event="portfolio_liquidate",
        symbols=selected,
        hold=True,
    )
    filled: list[dict] = []
    skipped: list[dict] = []
    try:
        pairs = {symbol: _stock_for(assets, symbol) for symbol in selected}
        for symbol, stock_code in pairs.items():
            filters = _filters(client, symbol)
            _cancel_open(client, symbol, stock_code, filters)
        snapshot = _snapshot(client, assets, free_only=True)
        by_symbol = {row["operation_code"]: row for row in snapshot["holdings"]}
        for symbol in selected:
            holding = by_symbol[symbol]
            qty = _size_sell(
                holding["quantity"],
                holding["price"],
                holding["step_size"],
                holding["min_notional"],
            )
            if qty <= 0:
                reason = (
                    "already flat"
                    if holding["quantity"] < holding["step_size"]
                    else "below min_notional"
                )
                skipped.append(_skipped(holding, SIDE_SELL, reason))
                continue
            try:
                order = _place(client, holding, SIDE_SELL, qty)
            except Exception as exc:
                report = {
                    "ok": False,
                    "partial": True,
                    "hold": True,
                    "orders": filled,
                    "skipped": skipped,
                    "aborted_at": symbol,
                    "error": str(exc),
                }
                log_event(
                    logging.ERROR,
                    "Portfolio liquidate aborted",
                    event="portfolio_liquidate",
                    aborted_at=symbol,
                    error=str(exc),
                    hold=True,
                )
                return report
            remaining = max(holding["quantity"] - qty, 0.0)
            _apply_state_after_fill(store, holding, SIDE_SELL, order, remaining)
            payload = _order_payload(holding, SIDE_SELL, qty)
            payload["order_id"] = order.get("orderId")
            filled.append(payload)
        store.set_action_hold(False)
        log_event(
            logging.INFO,
            "Portfolio liquidate finished",
            event="portfolio_liquidate",
            symbols=selected,
            filled=len(filled),
            hold=False,
        )
        return {
            "ok": True,
            "partial": False,
            "hold": False,
            "orders": filled,
            "skipped": skipped,
        }
    except Exception:
        log_event(
            logging.ERROR,
            "Portfolio liquidate failed; hold remains",
            event="portfolio_liquidate",
            hold=True,
        )
        raise


def execute_rebalance(
    client,
    assets: Iterable[Any],
    weights: Any,
    store,
    confirm: str,
) -> dict:
    _require_confirm(confirm, CONFIRM_REBALANCE)
    allowlist = _allowlist(assets)
    parsed = _validate_weights(weights, allowlist)
    store.set_action_hold(True)
    log_event(
        logging.INFO,
        "Portfolio rebalance started",
        event="portfolio_rebalance",
        weights=parsed,
        hold=True,
    )
    filled: list[dict] = []
    skipped: list[dict] = []
    try:
        for stock_code, symbol in _configured_assets(assets):
            filters = _filters(client, symbol)
            _cancel_open(client, symbol, stock_code, filters)
        snapshot = _snapshot(client, assets, free_only=True)
        nav = snapshot["nav"]
        plan: list[tuple[str, dict, float]] = []
        for holding in snapshot["holdings"]:
            symbol = holding["operation_code"]
            target = nav * (parsed[symbol] / 100.0)
            delta = target - holding["usd_value"]
            min_notional = holding["min_notional"]
            if abs(delta) < min_notional or holding["price"] <= 0:
                skipped.append(
                    _skipped(
                        holding,
                        SIDE_SELL if delta < 0 else SIDE_BUY,
                        "dust" if holding["price"] > 0 else "no price",
                    )
                )
                continue
            raw_qty = abs(delta) / holding["price"]
            if delta < 0:
                qty = _size_sell(
                    min(raw_qty, holding["quantity"]),
                    holding["price"],
                    holding["step_size"],
                    min_notional,
                )
                if qty <= 0:
                    skipped.append(_skipped(holding, SIDE_SELL, "dust"))
                else:
                    plan.append((SIDE_SELL, holding, qty))
            else:
                qty = _size_buy(
                    raw_qty,
                    holding["price"],
                    holding["step_size"],
                    min_notional,
                    max_quote=abs(delta),
                )
                if qty <= 0:
                    skipped.append(_skipped(holding, SIDE_BUY, "dust"))
                else:
                    plan.append((SIDE_BUY, holding, qty))

        sells = [(side, holding, qty) for side, holding, qty in plan if side == SIDE_SELL]
        buys = [(side, holding, qty) for side, holding, qty in plan if side == SIDE_BUY]

        def _run_leg(side: str, holding: dict, qty: float):
            try:
                order = _place(client, holding, side, qty)
            except Exception as exc:
                return {
                    "ok": False,
                    "partial": True,
                    "hold": True,
                    "orders": filled,
                    "skipped": skipped,
                    "aborted_at": holding["operation_code"],
                    "error": str(exc),
                }
            remaining = holding["quantity"] - qty if side == SIDE_SELL else holding["quantity"] + qty
            _apply_state_after_fill(store, holding, side, order, max(remaining, 0.0))
            payload = _order_payload(holding, side, qty)
            payload["order_id"] = order.get("orderId")
            filled.append(payload)
            return None

        for side, holding, qty in sells:
            abort = _run_leg(side, holding, qty)
            if abort:
                log_event(
                    logging.ERROR,
                    "Portfolio rebalance aborted",
                    event="portfolio_rebalance",
                    aborted_at=abort["aborted_at"],
                    error=abort["error"],
                    hold=True,
                )
                return abort

        if buys:
            refresh = _snapshot(client, assets, free_only=True)
            quote_free = float(refresh["quote_qty"]) * (1.0 - QUOTE_BUFFER)
            buy_notional = sum(qty * holding["price"] for _, holding, qty in buys)
            scale = 1.0
            if buy_notional > quote_free > 0:
                scale = quote_free / buy_notional
            remaining_quote = quote_free
            for side, holding, qty in buys:
                sized = qty * scale
                sized = _size_buy(
                    sized,
                    holding["price"],
                    holding["step_size"],
                    holding["min_notional"],
                    max_quote=remaining_quote,
                )
                if sized <= 0:
                    skipped.append(_skipped(holding, SIDE_BUY, "insufficient quote"))
                    continue
                abort = _run_leg(side, holding, sized)
                if abort:
                    log_event(
                        logging.ERROR,
                        "Portfolio rebalance aborted",
                        event="portfolio_rebalance",
                        aborted_at=abort["aborted_at"],
                        error=abort["error"],
                        hold=True,
                    )
                    return abort
                remaining_quote = max(remaining_quote - sized * holding["price"], 0.0)

        store.set_action_hold(False)
        log_event(
            logging.INFO,
            "Portfolio rebalance finished",
            event="portfolio_rebalance",
            filled=len(filled),
            hold=False,
        )
        return {
            "ok": True,
            "partial": False,
            "hold": False,
            "orders": filled,
            "skipped": skipped,
            "weights": parsed,
            "nav": round(nav, 8),
        }
    except Exception:
        log_event(
            logging.ERROR,
            "Portfolio rebalance failed; hold remains",
            event="portfolio_rebalance",
            hold=True,
        )
        raise
