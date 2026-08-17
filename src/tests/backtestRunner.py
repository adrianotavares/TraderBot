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
    verbose=True,
    **strategy_kwargs,
):
    """
    Executa backtest e retorna metricas detalhadas.

    Retorna dict com: profit_percentage, trades, max_drawdown_pct, total_fees,
    sharpe_approx, final_balance.
    """
    result = _run_backtest(
        stock_data=stock_data,
        strategy_function=strategy_function,
        strategy_instance=strategy_instance,
        periods=periods,
        initial_balance=initial_balance,
        fee_rate=fee_rate,
        slippage=slippage,
        strategy_kwargs=strategy_kwargs,
    )

    if verbose:
        print(f"Iniciando backtest da estrategia: {strategy_function.__name__}")
        print(f"Balanço inicial: ${initial_balance:.2f}")
        print(f"Balanço final: ${result['final_balance']:.2f}")
        print(f"Lucro/prejuízo percentual: {result['profit_percentage']:.2f}%")
        print(f"Total de operacoes realizadas: {result['trades']}")
        print(f"Max drawdown: {result['max_drawdown_pct']:.2f}%")
        print(f"Sharpe aprox.: {result['sharpe_approx']:.2f}")
        print(f"Taxas estimadas: ${result['total_fees']:.4f}")

    return result


def _run_backtest(
    stock_data,
    strategy_function,
    strategy_instance,
    periods,
    initial_balance,
    fee_rate,
    slippage,
    strategy_kwargs,
):
    min_required_periods = strategy_kwargs.get("slow_window", 40) + 20
    min_required_periods = max(
        min_required_periods,
        strategy_kwargs.get("trend_sma_period", 0) + 5,
    )
    stock_data = stock_data[-max(periods, min_required_periods) :].copy().reset_index(drop=True)
    stock_data.dropna(inplace=True)

    balance = initial_balance
    position = 0
    entry_price = 0
    last_signal = None
    trades = 0
    total_fees = 0.0
    equity_curve = [initial_balance]

    for i in range(1, len(stock_data)):
        current_data = stock_data.iloc[: i + 1]

        if strategy_instance:
            signal = strategy_function(strategy_instance)
        else:
            signal = strategy_function(current_data, verbose=False, **strategy_kwargs)

        if signal is None:
            equity_curve.append(balance if position == 0 else _mark_to_market(balance, entry_price, stock_data.iloc[i]["close_price"], slippage))
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
            equity_curve.append(
                _mark_to_market(balance, entry_price, close_price, slippage)
            )
        else:
            equity_curve.append(balance)

    if position == 1:
        final_price = stock_data.iloc[-1]["close_price"] * (1 - slippage)
        gross_profit = ((final_price - entry_price) / entry_price) * balance
        fee = (balance + gross_profit) * fee_rate
        balance += gross_profit - fee
        total_fees += fee
        equity_curve[-1] = balance

    profit_percentage = ((balance - initial_balance) / initial_balance) * 100
    max_drawdown_pct = _max_drawdown(equity_curve)
    sharpe_approx = _sharpe_approx(equity_curve)

    return {
        "profit_percentage": profit_percentage,
        "trades": trades,
        "max_drawdown_pct": max_drawdown_pct,
        "total_fees": total_fees,
        "sharpe_approx": sharpe_approx,
        "final_balance": balance,
    }


def _mark_to_market(balance, entry_price, close_price, slippage):
    exit_price = close_price * (1 - slippage)
    return balance + ((exit_price - entry_price) / entry_price) * balance


def _max_drawdown(equity_curve):
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * 100
            max_dd = max(max_dd, dd)
    return max_dd


def _sharpe_approx(equity_curve):
    if len(equity_curve) < 2:
        return 0.0
    returns = pd.Series(equity_curve).pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    return float((returns.mean() / returns.std()) * np.sqrt(len(returns)))
