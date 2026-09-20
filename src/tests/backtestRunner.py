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
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    signals=None,
    **strategy_kwargs,
):
    """
    Executa backtest e retorna metricas detalhadas.

    Retorna dict com: profit_percentage, trades, max_drawdown_pct, total_fees,
    sharpe_approx, final_balance, closed_trades, win_rate, best_trade_pct,
    worst_trade_pct.
    """
    result = _run_backtest(
        stock_data=stock_data,
        strategy_function=strategy_function,
        strategy_instance=strategy_instance,
        periods=periods,
        initial_balance=initial_balance,
        fee_rate=fee_rate,
        slippage=slippage,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        strategy_kwargs=strategy_kwargs,
        signals=signals,
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
    stop_loss_pct=0.0,
    take_profit_pct=0.0,
    signals=None,
):
    min_required_periods = strategy_kwargs.get("slow_window", 40) + 20
    min_required_periods = max(
        min_required_periods,
        strategy_kwargs.get("slow_span", 0) + 20,
        strategy_kwargs.get("trend_sma_period", 0) + 5,
        strategy_kwargs.get("trend_ema_period", 0) + 5,
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
    closed_trades = []
    entry_index = 0

    for i in range(1, len(stock_data)):
        if signals is not None:
            signal = signals[i] if i < len(signals) else None
        elif strategy_instance:
            signal = strategy_function(strategy_instance)
        else:
            current_data = stock_data.iloc[: i + 1]
            signal = strategy_function(current_data, verbose=False, **strategy_kwargs)
        signal = _as_signal(signal)

        close_price = stock_data.iloc[i]["close_price"]
        exit_reason = None
        if position == 1:
            if stop_loss_pct and close_price <= entry_price * (1 - stop_loss_pct / 100):
                exit_reason = "stop_loss"
            elif take_profit_pct and close_price >= entry_price * (
                1 + take_profit_pct / 100
            ):
                exit_reason = "take_profit"

        if signal is True and position == 0 and last_signal != "buy":
            fill_price = close_price * (1 + slippage)
            fee = balance * fee_rate
            balance -= fee
            total_fees += fee
            position = 1
            entry_price = fill_price
            entry_index = i
            last_signal = "buy"
            trades += 1

        elif position == 1 and last_signal != "sell" and (
            exit_reason or signal is False
        ):
            fill_price = close_price * (1 - slippage)
            gross_profit = ((fill_price - entry_price) / entry_price) * balance
            fee = (balance + gross_profit) * fee_rate
            balance += gross_profit - fee
            total_fees += fee
            return_pct = ((fill_price - entry_price) / entry_price) * 100
            closed_trades.append(
                {
                    "entry_index": entry_index,
                    "exit_index": i,
                    "bars": i - entry_index,
                    "entry_price": entry_price,
                    "exit_price": fill_price,
                    "return_pct": return_pct,
                    "reason": exit_reason or "signal",
                }
            )
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
    returns = [trade["return_pct"] for trade in closed_trades]
    wins = [value for value in returns if value > 0]
    win_rate = (len(wins) / len(returns) * 100) if returns else 0.0
    best_trade_pct = max(returns) if returns else 0.0
    worst_trade_pct = min(returns) if returns else 0.0
    gross_wins = sum(wins)
    concentration = (
        (max(wins) / gross_wins * 100) if gross_wins > 0 else 0.0
    )

    return {
        "profit_percentage": profit_percentage,
        "trades": trades,
        "max_drawdown_pct": max_drawdown_pct,
        "total_fees": total_fees,
        "sharpe_approx": sharpe_approx,
        "final_balance": balance,
        "closed_trades": closed_trades,
        "win_rate": win_rate,
        "best_trade_pct": best_trade_pct,
        "worst_trade_pct": worst_trade_pct,
        "top_win_share_pct": concentration,
    }


def _as_signal(signal):
    """Normalize bool / numpy.bool_ / StrategyDecision to True, False, or None."""
    side = getattr(signal, "side", signal)
    if side is None:
        return None
    if side is True or side is False:
        return side
    try:
        if pd.isna(side):
            return None
    except (TypeError, ValueError):
        pass
    return bool(side)


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
