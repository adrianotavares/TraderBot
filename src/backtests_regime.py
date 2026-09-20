"""
Quanto o roteador de regime custa por variante de configuracao.

Nao coloca ordem, nao altera config/trading.yaml. Reaproveita o cache de
klines de `backtests_confirm.py`.
"""
from __future__ import annotations

import argparse
import csv
import os

from backtest.confirm import STRATEGIES
from backtest.regime_gate import VARIANTS, evaluate_variant
from backtests_confirm import fetch_4h_frame
from config.settings import load_settings

CANDLES_180D_4H = 180 * 6
CSV_PATH = "data/backtest_regime_gate.csv"


def _print_asset(symbol: str, results: list[dict]) -> None:
    print(f"\n{symbol} — ultimos 180 dias em 4h")
    header = (
        f"  {'Variante':<26} {'pausa%':>7} {'TREND%':>7} {'LAT%':>6} {'GRAY%':>6}"
        f" | {'ema_atr':>17} {'atr_trend':>17}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for result in results:
        stats = result["stats"]
        by_name = {row["strategy"]: row for row in result["rows"]}
        cells = []
        for name in ("ema_atr", "atr_trend"):
            row = by_name.get(name)
            cells.append(
                f"{row['return_pct']:8.2f}% /{row['trades']:3}tr" if row else " " * 17
            )
        print(
            f"  {result['variant']:<26} {stats['paused_pct']:6.1f}% "
            f"{stats['trend_pct']:6.1f}% {stats['lateral_pct']:5.1f}% "
            f"{stats['gray_pct']:5.1f}% | " + " ".join(cells)
        )


def _print_summary(rows: list[dict]) -> None:
    print("\nMedia entre os ativos (retorno com o gate aplicado)")
    header = f"  {'Variante':<26} {'estrategia':<12} {'retorno':>9} {'vs sem gate':>12} {'pausa%':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["variant"], row["strategy"]), []).append(row)
    for (variant, strategy), items in grouped.items():
        gated = sum(item["return_pct"] for item in items) / len(items)
        cost = sum(item["cost_pct"] for item in items) / len(items)
        paused = sum(item["paused_pct"] for item in items) / len(items)
        print(
            f"  {variant:<26} {strategy:<12} {gated:8.2f}% {cost:11.2f}pp {paused:7.1f}%"
        )


def _write_csv(rows: list[dict]) -> None:
    os.makedirs("data", exist_ok=True)
    fields = [
        "operation_code",
        "variant",
        "strategy",
        "paused_pct",
        "trend_pct",
        "lateral_pct",
        "gray_pct",
        "ungated_return_pct",
        "ungated_trades",
        "return_pct",
        "trades",
        "max_drawdown_pct",
        "cost_pct",
    ]
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nResultados exportados para {CSV_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Custo do gate de regime")
    parser.add_argument("--refresh", action="store_true", help="Refaz download de klines")
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--risk-overlay", action="store_true", help="Aplica SL/TP do YAML")
    args = parser.parse_args()

    settings, _env = load_settings()
    stop_loss_pct = float(settings.risk.stop_loss_pct) if args.risk_overlay else 0.0
    take_profit_pct = (
        float(settings.risk.take_profit[0].at)
        if args.risk_overlay and settings.risk.take_profit
        else 0.0
    )

    rows: list[dict] = []
    for asset in settings.assets:
        symbol = asset.operation_code
        print(f"Klines 4h {symbol}...", flush=True)
        frame = fetch_4h_frame(symbol, days=args.days, refresh=args.refresh)
        window = frame.tail(CANDLES_180D_4H).reset_index(drop=True)
        results = []
        for variant in VARIANTS:
            result = evaluate_variant(
                window,
                variant,
                strategies=STRATEGIES,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
            results.append(result)
            for row in result["rows"]:
                rows.append(
                    {
                        "operation_code": symbol,
                        "variant": result["variant"],
                        **result["stats"],
                        **row,
                    }
                )
        _print_asset(symbol, results)

    _print_summary(rows)
    _write_csv(rows)


if __name__ == "__main__":
    main()
