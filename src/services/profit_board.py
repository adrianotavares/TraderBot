from typing import Iterable, Optional

from services.portfolio import STABLE_USD

KIND_TAKE_PROFIT = "take_profit"
KIND_STOP_LOSS = "stop_loss"
KIND_OPEN = "open"

_KIND_ORDER = {KIND_TAKE_PROFIT: 0, KIND_STOP_LOSS: 1, KIND_OPEN: 2}


def first_take_profit_pct(take_profit_at: Iterable[float] | None) -> float:
    for level in take_profit_at or []:
        pct = float(level or 0)
        if pct > 0:
            return pct
    return 0.0


def variation_pct(last_buy_price: float, mark_price: float) -> Optional[float]:
    if last_buy_price <= 0:
        return None
    return ((mark_price - last_buy_price) / last_buy_price) * 100


def classify_holding(
    holding: dict,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Optional[str]:
    stock = holding.get("stock_code") or ""
    if stock in STABLE_USD:
        return None
    quantity = float(holding.get("quantity") or 0)
    price = float(holding.get("price") or 0)
    last_buy = float(holding.get("last_buy_price") or 0)
    if quantity <= 0 or price <= 0:
        return None
    change = variation_pct(last_buy, price)
    if change is None:
        return KIND_OPEN
    rounded = round(change, 2)
    if take_profit_pct > 0 and rounded >= round(take_profit_pct, 2):
        return KIND_TAKE_PROFIT
    if stop_loss_pct > 0 and rounded <= round(-stop_loss_pct, 2):
        return KIND_STOP_LOSS
    return KIND_OPEN


def build_profit_board(
    holdings: Iterable[dict],
    take_profit_at: Iterable[float],
    stop_loss_pct: float,
) -> dict:
    operations = []
    total_usd = 0.0
    total_pnl_usd = 0.0
    total_cost_basis = 0.0
    take_profit_pct = first_take_profit_pct(take_profit_at)

    for holding in holdings:
        kind = classify_holding(holding, take_profit_pct, stop_loss_pct)
        if not kind:
            continue
        usd_value = float(holding.get("usd_value") or 0)
        pnl_usd = holding.get("pnl_usd")
        pnl_pct = holding.get("pnl_pct")
        quantity = float(holding.get("quantity") or 0)
        last_buy = float(holding.get("last_buy_price") or 0)
        operations.append(
            {
                "kind": kind,
                "stock_code": holding.get("stock_code") or "",
                "operation_code": holding.get("operation_code") or "",
                "usd_value": round(usd_value, 4),
                "pnl_usd": None if pnl_usd is None else round(float(pnl_usd), 4),
                "pnl_pct": None if pnl_pct is None else round(float(pnl_pct), 2),
            }
        )
        total_usd += usd_value
        if pnl_usd is not None:
            total_pnl_usd += float(pnl_usd)
            if last_buy > 0 and quantity > 0:
                total_cost_basis += quantity * last_buy

    operations.sort(
        key=lambda row: (
            _KIND_ORDER.get(row["kind"], 9),
            row["stock_code"] or "",
        )
    )

    total_pnl_pct = None
    if total_cost_basis > 0:
        total_pnl_pct = round((total_pnl_usd / total_cost_basis) * 100, 2)

    return {
        "total_usd": round(total_usd, 2),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "total_pnl_pct": total_pnl_pct,
        "operations": operations,
    }
