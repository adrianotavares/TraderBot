import numpy as np
import pandas as pd

DEFAULT_FEE_RATE = 0.001  # 0.1% Binance spot fee
DEFAULT_SLIPPAGE = 0.0005  # 0.05%


def backtestRunner(
    stock_data: pd.DataFrame,
    strategy_function,
    strategy_instance=None,
    periods=900,
    initial_balance=1000,
    fee_rate=DEFAULT_FEE_RATE,
    slippage=DEFAULT_SLIPPAGE,
    **strategy_kwargs,
):
    """
    Executa um backtest de qualquer estratégia que segue a lógica de:
    - True = comprado
    - False = vendido

    Inclui taxas e slippage básicos para aproximar operação real.
    """
    min_required_periods = strategy_kwargs.get("slow_window", 40) + 20
    stock_data = stock_data[-max(periods, min_required_periods) :].copy().reset_index(drop=True)
    stock_data.dropna(inplace=True)

    balance = initial_balance
    position = 0
    entry_price = 0
    last_signal = None
    trades = 0
    total_fees = 0.0

    print(f"Iniciando backtest da estratégia: {strategy_function.__name__}")
    print(f"Balanço inicial: ${balance:.2f}")

    for i in range(1, len(stock_data)):
        current_data = stock_data.iloc[: i + 1]

        if strategy_instance:
            signal = strategy_function(strategy_instance)
        else:
            signal = strategy_function(current_data, **strategy_kwargs)

        if signal is None:
            continue

        close_price = stock_data.iloc[i]["close_price"]

        if signal and position == 0 and last_signal != "buy":
            fill_price = close_price * (1 + slippage)
            fee = balance * fee_rate
            balance -= fee
            total_fees += fee
            position = 1
            entry_price = fill_price
            last_signal = "buy"
            trades += 1

        elif not signal and position == 1 and last_signal != "sell":
            fill_price = close_price * (1 - slippage)
            gross_profit = ((fill_price - entry_price) / entry_price) * balance
            fee = (balance + gross_profit) * fee_rate
            balance += gross_profit - fee
            total_fees += fee
            position = 0
            last_signal = "sell"
            trades += 1

    if position == 1:
        final_price = stock_data.iloc[-1]["close_price"] * (1 - slippage)
        gross_profit = ((final_price - entry_price) / entry_price) * balance
        fee = (balance + gross_profit) * fee_rate
        balance += gross_profit - fee
        total_fees += fee

    profit_percentage = ((balance - initial_balance) / initial_balance) * 100

    print(f"Balanço final: ${balance:.2f}")
    print(f"Lucro/prejuízo percentual: {profit_percentage:.2f}%")
    print(f"Total de operações realizadas: {trades}")
    print(f"Taxas estimadas: ${total_fees:.4f}")

    return profit_percentage
