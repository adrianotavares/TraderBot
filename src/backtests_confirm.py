"""
Confirmacao multi-ativo / walk-forward do ema_atr vs 21/55, atr_trend e hold.

Nao coloca ordem. So klines + simulacao. Nao altera config/trading.yaml.
"""
from __future__ import annotations

import argparse
import csv
import os

from binance.client import Client

from backtest.confirm import (
    EMA_ATR_ARGS,
    LAST_360,
    STRATEGIES,
    confirmation_score,
    run_engine_replay,
    run_strategy_window,
    slice_windows,
)
from config.settings import load_settings
from services.market_data import MarketDataService

try:
    from strategies.ema_atr import getEmaAtrStrategy
except ImportError as exc:  # pragma: no cover - script utilitario
    raise SystemExit(
        "backtests_confirm.py precisa de strategies.ema_atr; "
        "na main use backtests_regime.py para medir o gate GRAY."
    ) from exc

CACHE_DIR = "data"


def _cache_path(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"backtest_klines_{symbol}_4h.csv")


def _read_cache(symbol: str):
    path = _cache_path(symbol)
    if not os.path.exists(path):
        return None
    import pandas as pd

    frame = pd.read_csv(path)
    if "open_time" in frame.columns:
        frame["open_time"] = pd.to_datetime(frame["open_time"])
    return frame


def _public_client() -> Client:
    return Client()


def fetch_4h_frame(symbol: str, *, days: int, refresh: bool, client: Client | None = None):
    cached = None if refresh else _read_cache(symbol)
    if cached is not None and len(cached) >= LAST_360:
        return cached
    client = client or _public_client()
    raw = client.get_historical_klines(
        symbol,
        Client.KLINE_INTERVAL_4HOUR,
        f"{days} days ago UTC",
    )
    frame = MarketDataService.normalize_klines(raw)
    os.makedirs(CACHE_DIR, exist_ok=True)
    frame.to_csv(_cache_path(symbol), index=False)
    return frame


def _row(
    *,
    operation_code: str,
    window: str,
    result: dict,
    risk_overlay: bool = False,
) -> dict:
    return {
        "operation_code": operation_code,
        "window": window,
        "strategy": result["strategy"],
        "risk_overlay": risk_overlay,
        "return_pct": result["profit_percentage"],
        "trades": result["trades"],
        "max_drawdown_pct": result["max_drawdown_pct"],
        "sharpe": result.get("sharpe_approx") or 0.0,
        "win_rate": result.get("win_rate") or 0.0,
        "best_trade_pct": result.get("best_trade_pct") or 0.0,
        "worst_trade_pct": result.get("worst_trade_pct") or 0.0,
        "top_win_share_pct": result.get("top_win_share_pct") or 0.0,
        "profit_percentage": result["profit_percentage"],
    }


def _print_rows(rows: list[dict]) -> None:
    header = (
        f"{'Asset':<10} {'Window':<10} {'Strategy':<24} {'Risk':<5} "
        f"{'Ret%':>8} {'Trades':>6} {'MaxDD%':>8} {'Win%':>6} {'Best':>7} {'Worst':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['operation_code']:<10} {row['window']:<10} "
            f"{row['strategy']:<24} {'yes' if row['risk_overlay'] else 'no':<5} "
            f"{row['return_pct']:>8.2f} {row['trades']:>6} "
            f"{row['max_drawdown_pct']:>8.2f} {row['win_rate']:>6.1f} "
            f"{row['best_trade_pct']:>7.2f} {row['worst_trade_pct']:>7.2f}"
        )
    print()


def _write_csv(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = [
        "operation_code",
        "window",
        "strategy",
        "risk_overlay",
        "return_pct",
        "trades",
        "max_drawdown_pct",
        "sharpe",
        "win_rate",
        "best_trade_pct",
        "worst_trade_pct",
        "top_win_share_pct",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Resultados exportados para {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest de confirmacao ema_atr")
    parser.add_argument("--refresh", action="store_true", help="Refaz download de klines")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Replay lento do TradingEngine (SL/TP/regime) no first asset last_180",
    )
    parser.add_argument("--days", type=int, default=400)
    args = parser.parse_args()

    settings, _env = load_settings()
    symbols = [asset.operation_code for asset in settings.assets]
    rows: list[dict] = []

    frames = {}
    for symbol in symbols:
        print(f"Klines 4h {symbol}...", flush=True)
        frames[symbol] = fetch_4h_frame(
            symbol, days=args.days, refresh=args.refresh
        )

    walk_symbol = symbols[0]
    for symbol, frame in frames.items():
        windows = slice_windows(frame)
        names = ["last_180"]
        if symbol == walk_symbol:
            names.extend(["last_360", "prior_180"])
        for window_name in names:
            window = windows.get(window_name)
            if window is None or len(window) < 60:
                continue
            for strategy_name, fn, kwargs in STRATEGIES:
                result = run_strategy_window(
                    window,
                    strategy_name=strategy_name,
                    strategy_fn=fn,
                    strategy_kwargs=kwargs,
                )
                rows.append(_row(operation_code=symbol, window=window_name, result=result))
            hold = run_strategy_window(
                window,
                strategy_name="buy_and_hold",
                strategy_fn=None,
                strategy_kwargs={},
            )
            rows.append(_row(operation_code=symbol, window=window_name, result=hold))

    stop_loss_pct = float(settings.risk.stop_loss_pct)
    take_profit_pct = (
        float(settings.risk.take_profit[0].at) if settings.risk.take_profit else 7.0
    )
    btc_last = slice_windows(frames[walk_symbol])["last_180"]
    for strategy_name, fn, kwargs in STRATEGIES:
        result = run_strategy_window(
            btc_last,
            strategy_name=strategy_name,
            strategy_fn=fn,
            strategy_kwargs=kwargs,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        rows.append(
            _row(
                operation_code=walk_symbol,
                window="last_180",
                result=result,
                risk_overlay=True,
            )
        )

    for multiplier in (2.5, 3.0, 3.5):
        for require_trend in (True, False):
            kwargs = dict(EMA_ATR_ARGS)
            kwargs["atr_multiplier"] = multiplier
            kwargs["require_trend_ema"] = require_trend
            result = run_strategy_window(
                btc_last,
                strategy_name=f"ema_atr_{multiplier}_{int(require_trend)}",
                strategy_fn=getEmaAtrStrategy,
                strategy_kwargs=kwargs,
            )
            rows.append(_row(operation_code=walk_symbol, window="sens_180", result=result))

    if args.replay:
        print(f"Replay engine {walk_symbol} last_180 (SL/TP/regime)...", flush=True)
        replay = run_engine_replay(
            btc_last,
            strategy_fn=getEmaAtrStrategy,
            strategy_kwargs=EMA_ATR_ARGS,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        rows.append(
            _row(
                operation_code=walk_symbol,
                window="last_180",
                result={
                    **replay,
                    "max_drawdown_pct": 0.0,
                    "win_rate": 0.0,
                    "best_trade_pct": 0.0,
                    "worst_trade_pct": 0.0,
                    "top_win_share_pct": 0.0,
                    "sharpe_approx": 0.0,
                },
                risk_overlay=True,
            )
        )
        print(
            f"Replay ema_atr: return={replay['profit_percentage']:.2f}% "
            f"orders={replay['trades']} in_position={replay['in_position']}"
        )

    _print_rows(rows)
    _write_csv("data/backtest_confirm.csv", rows)
    score = confirmation_score(rows, walk_symbol=walk_symbol)
    print("Placar de confirmacao")
    print(
        f"  ativos last_180: {score['assets']} | "
        f"ema>=ma: {score['ema_beats_ma']} | "
        f"ema>=hold: {score['ema_beats_hold']} | "
        f"dd<=atr_trend: {score['ema_dd_better_than_atr']}"
    )
    print(
        f"  walk-forward BTC ambos positivos: {score['walk_forward_both_positive']} | "
        f"overlay DD < 21%: {score['overlay_dd_below_atr']}"
    )
    print(
        "  veredito: "
        + (
            "confirmado neste recorte"
            if score["confirmed"]
            else "ainda nao confirmado"
        )
    )


if __name__ == "__main__":
    main()
