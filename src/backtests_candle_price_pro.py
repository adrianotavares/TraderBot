"""
Compara CANDLE-PRICE-PRO com o atr_trend ao vivo.

Nao coloca ordem. Nao altera config/trading.yaml e nao registra a estrategia.
O baseline usa stop de 5% e take profit de 7% no fechamento de um candle de 4h.
Ele nao aplica a confirmacao de dois fechamentos nem o trailing ATR do bot ao vivo.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd
from binance.client import Client

from backtest.candle_price_pro import simulate, summarize_price_trades
from backtest.signals import atr_trend_signals
from services.market_data import MarketDataService
from strategies.atr_trend import getAtrTrendStrategy
from tests.backtestRunner import backtestRunner

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "UNIUSDT", "ZECUSDT"]
FETCH_DAYS = 200
EVAL_DAYS = 120
ATR_TREND_ARGS = {
    "atr_period": 14,
    "atr_multiplier": 3.5,
    "trend_sma_period": 100,
}
ATR_TREND_STOP = 5.0
ATR_TREND_TP = 7.0
INTERVALS = {
    "15m": (Client.KLINE_INTERVAL_15MINUTE, pd.Timedelta(minutes=15)),
    "1h": (Client.KLINE_INTERVAL_1HOUR, pd.Timedelta(hours=1)),
    "4h": (Client.KLINE_INTERVAL_4HOUR, pd.Timedelta(hours=4)),
}
CACHE_DIR = "data"


def _cache_path(symbol: str, interval: str) -> str:
    return os.path.join(CACHE_DIR, f"backtest_cpp_{symbol}_{interval}.csv")


def _read_cache(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    frame = pd.read_csv(path)
    if frame.empty or "open_time" not in frame.columns:
        return None
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True).dt.tz_convert(
        "America/Sao_Paulo"
    )
    return frame


def _drop_open_candle(frame: pd.DataFrame, duration: pd.Timedelta) -> pd.DataFrame:
    now = pd.Timestamp.now(tz="America/Sao_Paulo")
    closed = frame["open_time"] + duration <= now
    return frame.loc[closed].reset_index(drop=True)


def fetch_frame(symbol: str, interval: str, *, refresh: bool, client: Client) -> pd.DataFrame:
    code, duration = INTERVALS[interval]
    path = _cache_path(symbol, interval)
    cached = None if refresh else _read_cache(path)
    if cached is not None:
        return _drop_open_candle(cached, duration)
    raw = client.get_historical_klines(symbol, code, f"{FETCH_DAYS} days ago UTC")
    frame = MarketDataService.normalize_klines(raw)
    os.makedirs(CACHE_DIR, exist_ok=True)
    frame.to_csv(path, index=False)
    return _drop_open_candle(frame, duration)


def _fmt_factor(value: float) -> str:
    if value == float("inf"):
        return "inf"
    return f"{value:.2f}"


def _atr_trend_row(frame: pd.DataFrame, eval_start: pd.Timestamp) -> dict:
    signals = atr_trend_signals(frame, **ATR_TREND_ARGS)
    mask = frame["open_time"] >= eval_start
    window = frame.loc[mask].reset_index(drop=True)
    kept = [signals[i] for i, flag in enumerate(mask.tolist()) if flag]
    result = backtestRunner(
        stock_data=window,
        strategy_function=getAtrTrendStrategy,
        periods=len(window),
        initial_balance=1000.0,
        verbose=False,
        stop_loss_pct=ATR_TREND_STOP,
        take_profit_pct=ATR_TREND_TP,
        signals=kept,
        **ATR_TREND_ARGS,
    )
    summary = summarize_price_trades(result["closed_trades"], risk_pct=ATR_TREND_STOP)
    return {
        "strategy": "atr_trend",
        "return_pct": result["profit_percentage"],
        "trades": summary["trades"],
        "win_rate": summary["win_rate"],
        "profit_factor": summary["profit_factor"],
        "expectancy_r": summary["expectancy_r"],
        "max_drawdown_pct": result["max_drawdown_pct"],
        "fees": result["total_fees"],
        "gross_win": summary["gross_win"],
        "gross_loss": summary["gross_loss"],
        "setups": "",
        "gated": "",
    }


def _cpp_row(m15, h1, h4, eval_start: pd.Timestamp) -> dict:
    result = simulate(m15, h1, h4, eval_start=eval_start)
    return {
        "strategy": "candle_price_pro",
        "return_pct": result["profit_percentage"],
        "trades": result["trades"],
        "win_rate": result["win_rate"],
        "profit_factor": result["profit_factor"],
        "expectancy_r": result["expectancy_r"],
        "max_drawdown_pct": result["max_drawdown_pct"],
        "fees": result["total_fees"],
        "gross_win": result["gross_win"],
        "gross_loss": result["gross_loss"],
        "setups": result["setups"],
        "gated": result["gated"],
    }


def _print_table(rows: list[dict]) -> None:
    header = (
        f"{'Ativo':<10} {'Estrategia':<18} {'Retorno%':>9} {'Trades':>7} "
        f"{'Acerto%':>8} {'PF':>7} {'E[R]':>7} {'MaxDD%':>8} {'Taxas':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['symbol']:<10} {row['strategy']:<18} "
            f"{row['return_pct']:>9.2f} {row['trades']:>7} "
            f"{row['win_rate']:>8.1f} {_fmt_factor(row['profit_factor']):>7} "
            f"{row['expectancy_r']:>7.2f} {row['max_drawdown_pct']:>8.2f} "
            f"{row['fees']:>8.2f}"
        )
    print()


def _write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    columns = [
        "symbol",
        "strategy",
        "return_pct",
        "trades",
        "win_rate",
        "profit_factor",
        "expectancy_r",
        "max_drawdown_pct",
        "fees",
        "setups",
        "gated",
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(",".join(columns) + "\n")
        for row in rows:
            handle.write(
                ",".join(
                    [
                        str(row["symbol"]),
                        str(row["strategy"]),
                        f"{row['return_pct']:.4f}",
                        str(row["trades"]),
                        f"{row['win_rate']:.4f}",
                        _fmt_factor(row["profit_factor"]),
                        f"{row['expectancy_r']:.4f}",
                        f"{row['max_drawdown_pct']:.4f}",
                        f"{row['fees']:.4f}",
                        str(row["setups"]),
                        str(row["gated"]),
                    ]
                )
                + "\n"
            )


def _total(rows: list[dict], strategy: str) -> dict:
    chosen = [row for row in rows if row["strategy"] == strategy]
    trades = sum(row["trades"] for row in chosen)
    gross_win = sum(row["gross_win"] for row in chosen)
    gross_loss = sum(row["gross_loss"] for row in chosen)
    if trades:
        win_rate = sum(row["win_rate"] * row["trades"] for row in chosen) / trades
        expectancy = sum(row["expectancy_r"] * row["trades"] for row in chosen) / trades
    else:
        win_rate = 0.0
        expectancy = 0.0
    factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win else 0.0)
    return {
        "symbol": "TOTAL",
        "strategy": strategy,
        "return_pct": sum(row["return_pct"] for row in chosen) / len(chosen) if chosen else 0.0,
        "trades": trades,
        "win_rate": win_rate,
        "profit_factor": factor,
        "expectancy_r": expectancy,
        "max_drawdown_pct": max((row["max_drawdown_pct"] for row in chosen), default=0.0),
        "fees": sum(row["fees"] for row in chosen),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "setups": sum(int(row["setups"]) for row in chosen if row["setups"] != ""),
        "gated": sum(int(row["gated"]) for row in chosen if row["gated"] != ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest CANDLE-PRICE-PRO vs atr_trend")
    parser.add_argument("--refresh", action="store_true", help="Baixa os klines de novo")
    args = parser.parse_args()
    client = Client()
    rows: list[dict] = []
    print(
        "Baseline atr_trend: stop de 5% e take profit de 7% no fechamento de um candle de 4h.\n"
        "Sem a confirmacao de dois fechamentos e sem o trailing ATR do bot ao vivo.\n"
        f"Janela: ultimos {EVAL_DAYS} dias. Taxa 0,1% e slippage 0,05%.\n"
    )
    for symbol in SYMBOLS:
        print(f"Baixando {symbol}...")
        m15 = fetch_frame(symbol, "15m", refresh=args.refresh, client=client)
        h1 = fetch_frame(symbol, "1h", refresh=args.refresh, client=client)
        h4 = fetch_frame(symbol, "4h", refresh=args.refresh, client=client)
        eval_start = m15["open_time"].iloc[-1] - pd.Timedelta(days=EVAL_DAYS)
        cpp = _cpp_row(m15, h1, h4, eval_start)
        trend = _atr_trend_row(h4, eval_start)
        cpp["symbol"] = symbol
        trend["symbol"] = symbol
        rows.extend([trend, cpp])
        print(
            f"  atr_trend {trend['return_pct']:+.2f}% em {trend['trades']} trades | "
            f"candle-price-pro {cpp['return_pct']:+.2f}% em {cpp['trades']} trades "
            f"({cpp['setups']} entradas de {cpp['gated']} setups; o resto ficou sem 2R)"
        )
    rows.extend([_total(rows, "atr_trend"), _total(rows, "candle_price_pro")])
    print()
    _print_table(rows)
    path = os.path.join(CACHE_DIR, "backtest_candle_price_pro.csv")
    _write_csv(rows, path)
    print(f"Resultados em {path}")
    print("TOTAL e a media do retorno e o pior drawdown entre os seis ativos.")


if __name__ == "__main__":
    main()
