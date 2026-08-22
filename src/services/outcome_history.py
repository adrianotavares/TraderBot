import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from persistence.state_store import StateStore
from services.order_sync import DEFAULT_PROFIT_CUTOFF

KIND_TAKE_PROFIT = "take_profit"
KIND_STOP_LOSS = "stop_loss"
KIND_SELL = "sell"
META_REBUILT = "outcomes_from_orders_v3"


def realized_pnl(
    quantity: float, buy_price: float, sell_price: float
) -> tuple[Optional[float], Optional[float]]:
    if quantity <= 0 or buy_price <= 0 or sell_price <= 0:
        return None, None
    pnl_usd = quantity * (sell_price - buy_price)
    pnl_pct = ((sell_price - buy_price) / buy_price) * 100
    return round(pnl_usd, 4), round(pnl_pct, 2)


def first_take_profit_pct(take_profit_at: Iterable[float] | None) -> float:
    for level in take_profit_at or []:
        pct = float(level or 0)
        if pct > 0:
            return pct
    return 0.0


def classify_kind(
    pnl_pct: Optional[float],
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    hint: str | None = None,
) -> str:
    if hint in {KIND_TAKE_PROFIT, KIND_STOP_LOSS, KIND_SELL}:
        return hint
    if pnl_pct is None:
        return KIND_SELL
    rounded = round(pnl_pct, 2)
    if take_profit_pct > 0 and rounded >= round(take_profit_pct, 2):
        return KIND_TAKE_PROFIT
    if stop_loss_pct > 0 and rounded <= round(-stop_loss_pct, 2):
        return KIND_STOP_LOSS
    return KIND_SELL


def stock_code_from_operation(operation_code: str, stock_code: str = "") -> str:
    if stock_code:
        return stock_code
    for quote in ("USDT", "BUSD", "USDC", "FDUSD", "TUSD"):
        if operation_code.endswith(quote) and len(operation_code) > len(quote):
            return operation_code[: -len(quote)]
    return operation_code


def parse_log_timestamp(value: str) -> str:
    raw = (value or "").replace(",", ".")
    naive = None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if naive is None:
        return value or datetime.now(timezone.utc).isoformat()
    local_tz = datetime.now().astimezone().tzinfo
    return naive.replace(tzinfo=local_tz).astimezone(timezone.utc).isoformat()


def _parse_iso_ts(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def fill_from_order(order: dict) -> tuple[float, float, float]:
    quantity = float(order.get("executedQty") or order.get("quantity") or 0)
    quote = float(order.get("cummulativeQuoteQty") or order.get("total_quote") or 0)
    if quantity > 0 and quote > 0:
        return quantity, quote / quantity, quote
    fills = order.get("fills") or []
    price = float(fills[0].get("price") or 0) if fills else float(order.get("fill_price") or 0)
    return quantity, price, quote


def _iter_log_paths(path: str) -> list[Path]:
    base = Path(path)
    paths = []
    for index in range(5, 0, -1):
        rotated = Path(f"{base}.{index}")
        if rotated.exists():
            paths.append(rotated)
    if base.exists():
        paths.append(base)
    return paths


def load_log_events(path: str) -> list[dict]:
    events = []
    for log_path in _iter_log_paths(path):
        with open(log_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("event"):
                    events.append(entry)
    return events


def _order_unit_price(order: dict) -> float:
    quantity = float(order.get("quantity") or 0)
    quote = float(order.get("total_quote") or 0)
    if quantity > 0 and quote > 0:
        return quote / quantity
    return float(order.get("price") or 0)


def match_closed_trades(
    orders: Iterable[dict],
    take_profit_at: Iterable[float] | None = None,
    stop_loss_pct: float = 0.0,
    kind_hints: Optional[dict[int, str]] = None,
) -> list[dict]:
    """Pair FILLED SELL qty against earlier BUY lots (FIFO) and return realized closes."""
    closed, _open_lots = match_trades_and_open_lots(
        orders,
        take_profit_at=take_profit_at,
        stop_loss_pct=stop_loss_pct,
        kind_hints=kind_hints,
    )
    return closed


def match_trades_and_open_lots(
    orders: Iterable[dict],
    take_profit_at: Iterable[float] | None = None,
    stop_loss_pct: float = 0.0,
    kind_hints: Optional[dict[int, str]] = None,
) -> tuple[list[dict], list[dict]]:
    """FIFO match SELL→BUY and return (closed trades, remaining open lots)."""
    take_profit_pct = first_take_profit_pct(take_profit_at)
    kind_hints = kind_hints or {}
    lots: dict[str, deque] = defaultdict(deque)
    closed: list[dict] = []

    for order in orders:
        if (order.get("status") or "FILLED") != "FILLED":
            continue
        side = (order.get("side") or "").upper()
        operation_code = order.get("operation_code") or ""
        quantity = float(order.get("quantity") or 0)
        if quantity <= 0 or not operation_code:
            continue
        unit = _order_unit_price(order)
        quote = float(order.get("total_quote") or 0)
        if quote <= 0 and unit > 0:
            quote = quantity * unit

        if side == "BUY":
            lots[operation_code].append(
                {
                    "qty": quantity,
                    "price": unit,
                    "created_at": order.get("created_at") or "",
                    "order_id": order.get("order_id"),
                }
            )
            continue
        if side != "SELL":
            continue

        remaining = quantity
        cost = 0.0
        matched = 0.0
        while remaining > 1e-12 and lots[operation_code]:
            lot = lots[operation_code][0]
            take = min(remaining, lot["qty"])
            cost += take * float(lot["price"])
            matched += take
            lot["qty"] -= take
            remaining -= take
            if lot["qty"] <= 1e-12:
                lots[operation_code].popleft()

        if matched <= 0:
            continue

        sell_quote = quote * (matched / quantity) if quantity > 0 else quote
        buy_price = cost / matched if matched > 0 else 0.0
        sell_price = sell_quote / matched if matched > 0 else unit
        pnl_usd, pnl_pct = realized_pnl(matched, buy_price, sell_price)
        order_id = order.get("order_id")
        hint = None
        if order_id is not None:
            hint = kind_hints.get(int(order_id))
        kind = classify_kind(pnl_pct, take_profit_pct, stop_loss_pct, hint=hint)
        closed.append(
            {
                "kind": kind,
                "operation_code": operation_code,
                "stock_code": stock_code_from_operation(operation_code),
                "quantity": round(matched, 8),
                "buy_price": round(buy_price, 8) if buy_price else None,
                "sell_price": round(sell_price, 8) if sell_price else None,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "quote_qty": round(sell_quote, 8),
                "cost_usd": round(cost, 8),
                "order_id": order_id,
                "source": "orders",
                "filled": True,
                "partial_sell": remaining > 1e-12,
                "occurred_at": order.get("created_at")
                or datetime.now(timezone.utc).isoformat(),
            }
        )

    open_lots: list[dict] = []
    for operation_code, queue in lots.items():
        for lot in queue:
            qty = float(lot["qty"])
            if qty <= 1e-12:
                continue
            price = float(lot["price"] or 0)
            cost_usd = qty * price if price > 0 else 0.0
            open_lots.append(
                {
                    "kind": "open",
                    "operation_code": operation_code,
                    "stock_code": stock_code_from_operation(operation_code),
                    "quantity": round(qty, 8),
                    "buy_price": round(price, 8) if price else None,
                    "cost_usd": round(cost_usd, 8),
                    "order_id": lot.get("order_id"),
                    "occurred_at": lot.get("created_at") or "",
                }
            )
    open_lots.sort(key=lambda row: (row["stock_code"], row["occurred_at"] or ""))
    return closed, open_lots


def open_lots_from_orders(orders: Iterable[dict]) -> list[dict]:
    _closed, open_lots = match_trades_and_open_lots(orders)
    return open_lots


def kind_hints_from_log(
    path: str,
    orders: Optional[Iterable[dict]] = None,
) -> dict[int, str]:
    """Map SELL order_id → take_profit/stop_loss from nearby bot events."""
    events = load_log_events(path)
    hints: dict[int, str] = {}
    for index, event in enumerate(events):
        kind = event.get("event")
        if kind not in {KIND_TAKE_PROFIT, KIND_STOP_LOSS}:
            continue
        operation_code = event.get("operation_code")
        window = events[max(0, index - 8) : index + 3]
        for entry in window:
            if entry.get("event") != "order_executed":
                continue
            if entry.get("operation_code") != operation_code:
                continue
            if entry.get("side") != "SELL":
                continue
            order_id = entry.get("order_id")
            if order_id is None:
                continue
            hints[int(order_id)] = kind
            break

    sell_orders = [
        row
        for row in (orders or [])
        if (row.get("side") or "").upper() == "SELL" and row.get("order_id") is not None
    ]
    if not sell_orders:
        return hints

    for event in events:
        kind = event.get("event")
        if kind not in {KIND_TAKE_PROFIT, KIND_STOP_LOSS}:
            continue
        operation_code = event.get("operation_code")
        event_ts = _parse_iso_ts(parse_log_timestamp(event.get("timestamp") or ""))
        if event_ts is None:
            continue
        best_id = None
        best_delta = None
        for row in sell_orders:
            if row.get("operation_code") != operation_code:
                continue
            order_id = int(row["order_id"])
            if order_id in hints:
                continue
            row_ts = _parse_iso_ts(row.get("created_at") or "")
            if row_ts is None:
                continue
            delta = abs(row_ts - event_ts)
            if delta > 600:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_id = order_id
        if best_id is not None:
            hints[best_id] = kind
    return hints


def rebuild_outcomes_from_orders(
    store: StateStore,
    take_profit_at: Iterable[float] | None = None,
    stop_loss_pct: float = 0.0,
    log_path: str | None = None,
    cutoff_iso: str = DEFAULT_PROFIT_CUTOFF,
    force: bool = False,
) -> int:
    if not force and store.get_meta(META_REBUILT) == "1":
        return 0
    orders = store.list_orders(since=cutoff_iso)
    hints = kind_hints_from_log(log_path, orders=orders) if log_path else {}
    closed = match_closed_trades(
        orders,
        take_profit_at=take_profit_at,
        stop_loss_pct=stop_loss_pct,
        kind_hints=hints,
    )
    store.clear_outcomes()
    inserted = 0
    for row in closed:
        if store.record_outcome(row):
            inserted += 1
    store.set_meta(META_REBUILT, "1")
    store.set_meta("outcomes_log_imported", "1")
    store.set_meta("profit_cutoff", cutoff_iso)
    return inserted


def build_outcome_board(
    outcomes: Iterable[dict],
    open_lots: Iterable[dict] | None = None,
) -> dict:
    operations = []
    total_proceeds = 0.0
    total_cost = 0.0
    total_pnl_usd = 0.0

    for row in outcomes:
        if not bool(row.get("filled", True)):
            continue
        quantity = float(row.get("quantity") or 0)
        sell_price = float(row.get("sell_price") or 0)
        buy_price = float(row.get("buy_price") or 0)
        quote_qty = float(row.get("quote_qty") or 0)
        cost_usd = row.get("cost_usd")
        if cost_usd is None and buy_price > 0 and quantity > 0:
            cost_usd = quantity * buy_price
        cost_usd = float(cost_usd or 0)
        if quote_qty <= 0 and quantity > 0 and sell_price > 0:
            quote_qty = quantity * sell_price
        pnl_usd = row.get("pnl_usd")
        pnl_pct = row.get("pnl_pct")
        if pnl_usd is None and cost_usd and quote_qty:
            pnl_usd = round(quote_qty - cost_usd, 4)
            pnl_pct = round((pnl_usd / cost_usd) * 100, 2) if cost_usd else None
        operations.append(
            {
                "kind": row.get("kind") or KIND_SELL,
                "stock_code": row.get("stock_code") or "",
                "operation_code": row.get("operation_code") or "",
                "usd_value": round(quote_qty, 4),
                "cost_usd": round(cost_usd, 4),
                "pnl_usd": None if pnl_usd is None else round(float(pnl_usd), 4),
                "pnl_pct": None if pnl_pct is None else round(float(pnl_pct), 2),
                "occurred_at": row.get("occurred_at") or "",
                "filled": True,
                "partial_sell": bool(row.get("partial_sell")),
            }
        )
        total_proceeds += quote_qty
        total_cost += cost_usd
        if pnl_usd is not None:
            total_pnl_usd += float(pnl_usd)

    open_positions = []
    open_cost = 0.0
    for lot in open_lots or []:
        cost_usd = float(lot.get("cost_usd") or 0)
        quantity = float(lot.get("quantity") or 0)
        buy_price = float(lot.get("buy_price") or 0)
        if cost_usd <= 0 and quantity > 0 and buy_price > 0:
            cost_usd = quantity * buy_price
        open_positions.append(
            {
                "kind": "open",
                "stock_code": lot.get("stock_code") or "",
                "operation_code": lot.get("operation_code") or "",
                "quantity": quantity,
                "buy_price": None if buy_price <= 0 else round(buy_price, 4),
                "cost_usd": round(cost_usd, 4),
                "occurred_at": lot.get("occurred_at") or "",
                "order_id": lot.get("order_id"),
            }
        )
        open_cost += cost_usd

    total_pnl_pct = None
    if total_cost > 0:
        total_pnl_pct = round((total_pnl_usd / total_cost) * 100, 2)

    return {
        "total_cost_usd": round(total_cost, 2),
        "open_cost_usd": round(open_cost, 2),
        "total_usd": round(total_proceeds, 2),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "total_pnl_pct": total_pnl_pct,
        "operations": operations,
        "open_positions": open_positions,
    }
