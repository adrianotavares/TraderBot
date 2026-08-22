from datetime import datetime, timezone
from typing import Iterable


DEFAULT_PROFIT_CUTOFF = "2026-08-01T00:00:00+00:00"
_SYNC_PAGE_SIZE = 1000


def exchange_order_timestamp(order: dict) -> str:
    ts = int(order.get("updateTime") or order.get("time") or 0)
    if ts <= 0:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()


def cutoff_to_ms(cutoff_iso: str) -> int:
    value = datetime.fromisoformat(cutoff_iso.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def sync_filled_orders_from_binance(
    client,
    store,
    symbols: Iterable[str],
    cutoff_iso: str = DEFAULT_PROFIT_CUTOFF,
) -> dict:
    """Upsert FILLED BUY/SELL orders from Binance into orders_log since cutoff."""
    start_ms = cutoff_to_ms(cutoff_iso)
    inserted = 0
    seen = 0
    for symbol in symbols:
        from_order_id = None
        while True:
            kwargs = {
                "symbol": symbol,
                "limit": _SYNC_PAGE_SIZE,
                "startTime": start_ms,
            }
            if from_order_id is not None:
                kwargs["orderId"] = from_order_id
            orders = client.get_all_orders(**kwargs)
            if not orders:
                break
            for order in orders:
                seen += 1
                update_ms = int(order.get("updateTime") or order.get("time") or 0)
                if update_ms and update_ms < start_ms:
                    continue
                if order.get("status") != "FILLED":
                    continue
                side = (order.get("side") or "").upper()
                if side not in {"BUY", "SELL"}:
                    continue
                if store.log_order(
                    symbol,
                    order,
                    created_at=exchange_order_timestamp(order),
                ):
                    inserted += 1
            if len(orders) < _SYNC_PAGE_SIZE:
                break
            last_id = int(orders[-1].get("orderId") or 0)
            if last_id <= 0:
                break
            next_id = last_id + 1
            if from_order_id is not None and next_id <= from_order_id:
                break
            from_order_id = next_id
    return {
        "inserted": inserted,
        "scanned": seen,
        "cutoff": cutoff_iso,
    }
