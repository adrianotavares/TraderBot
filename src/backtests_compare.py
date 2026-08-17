"""
Comparacao de estrategias em 4h para validar atr_trend vs alternativas.
"""
from binance.client import Client

from config.settings import load_settings
from modules.BinanceTraderBot import BinanceTraderBot
from strategies.atr_trend import getAtrTrendStrategy
from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.ut_bot_alerts import utBotAlerts
from strategies.weapon_candle_trade_strategy import getWeaponCandleTradeStrategy
from tests.backtestRunner import backtestRunner

PERIODS_4H_180_DAYS = 180 * 6  # 6 candles de 4h por dia

SCENARIOS = [
    {
        "name": "weapon_candle (atual)",
        "fn": getWeaponCandleTradeStrategy,
        "kwargs": {},
    },
    {
        "name": "ut_bot_alerts",
        "fn": utBotAlerts,
        "kwargs": {"atr_period": 14, "atr_multiplier": 2.5},
    },
    {
        "name": "atr_trend",
        "fn": getAtrTrendStrategy,
        "kwargs": {"atr_period": 14, "atr_multiplier": 2.5, "trend_sma_period": 200},
    },
    {
        "name": "moving_average 21/55",
        "fn": getMovingAverageTradeStrategy,
        "kwargs": {"fast_window": 21, "slow_window": 55},
    },
]


def main():
    settings, env = load_settings()
    asset = settings.assets[0]

    candle_period = Client.KLINE_INTERVAL_4HOUR
    initial_balance = asset.traded_quantity or 0.001

    bot = BinanceTraderBot(
        stock_code=asset.stock_code,
        operation_code=asset.operation_code,
        traded_quantity=0,
        traded_percentage=100,
        candle_period=candle_period,
        api_key=env.api_key,
        secret_key=env.secret_key,
        testnet=settings.environment == "testnet",
    )
    bot.updateAllData()

    print(f"\nComparacao de estrategias — {asset.operation_code} — 4h")
    print(f"Periodo: ultimos ~180 dias ({PERIODS_4H_180_DAYS} candles)\n")

    rows = []
    for scenario in SCENARIOS:
        result = backtestRunner(
            stock_data=bot.stock_data,
            strategy_function=scenario["fn"],
            periods=PERIODS_4H_180_DAYS,
            initial_balance=initial_balance,
            verbose=False,
            **scenario["kwargs"],
        )
        rows.append(
            {
                "strategy": scenario["name"],
                "return_pct": result["profit_percentage"],
                "trades": result["trades"],
                "max_drawdown": result["max_drawdown_pct"],
                "fees": result["total_fees"],
                "sharpe": result["sharpe_approx"],
            }
        )

    _print_table(rows)
    _export_csv(rows)


def _print_table(rows):
    header = f"{'Strategy':<28} {'Return%':>10} {'Trades':>8} {'MaxDD%':>10} {'Fees':>10} {'Sharpe':>8}"
    print(header)
    print("-" * len(header))
    for row in sorted(rows, key=lambda r: (-r["return_pct"], r["max_drawdown"], r["trades"])):
        print(
            f"{row['strategy']:<28} "
            f"{row['return_pct']:>10.2f} "
            f"{row['trades']:>8} "
            f"{row['max_drawdown']:>10.2f} "
            f"{row['fees']:>10.4f} "
            f"{row['sharpe']:>8.2f}"
        )
    print()


def _export_csv(rows):
    path = "data/backtest_compare_4h.csv"
    import os

    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("strategy,return_pct,trades,max_drawdown,fees,sharpe\n")
        for row in rows:
            f.write(
                f"{row['strategy']},{row['return_pct']:.4f},"
                f"{row['trades']},{row['max_drawdown']:.4f},"
                f"{row['fees']:.4f},{row['sharpe']:.4f}\n"
            )
    print(f"Resultados exportados para {path}")


if __name__ == "__main__":
    main()
