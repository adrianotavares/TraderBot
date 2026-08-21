import pandas as pd

from indicators.atr import atr, compute_trailing_stop, compute_ut_position


def _evaluate_atr_trend(
    stock_data: pd.DataFrame,
    atr_period: int,
    atr_multiplier: float,
    trend_sma_period: int,
):
    min_points = max(atr_period, trend_sma_period) + 5
    if len(stock_data) < min_points:
        return None

    df = stock_data.copy()
    for col in ("close_price", "high_price", "low_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["close_price", "high_price", "low_price"], inplace=True)

    if len(df) < min_points:
        return None

    close = df["close_price"]
    atr_values = atr(df, window=atr_period)
    sma = close.rolling(window=trend_sma_period).mean()

    if pd.isna(atr_values.iloc[-1]) or pd.isna(sma.iloc[-1]):
        return None

    trailing_stop = compute_trailing_stop(close, atr_values, atr_multiplier)
    position = compute_ut_position(close, trailing_stop)

    last_pos = position[-1]
    if last_pos == 0:
        return None

    last_close = float(close.iloc[-1])
    last_sma = float(sma.iloc[-1])
    last_stop = float(trailing_stop.iloc[-1])
    trailing_long = last_pos == 1
    decision = bool(trailing_long and last_close > last_sma)

    snapshot = {
        "strategy": "ATR Trend Following",
        "atr_period": atr_period,
        "atr_multiplier": atr_multiplier,
        "trend_sma_period": trend_sma_period,
        "trailing_stop": round(last_stop, 4),
        "sma": round(last_sma, 4),
        "close": round(last_close, 4),
        "trailing": "long" if trailing_long else "short",
        "decision": "Comprar" if decision else "Vender",
    }
    return decision, snapshot


def get_atr_trend_snapshot(
    stock_data: pd.DataFrame,
    atr_period: int = 14,
    atr_multiplier: float = 2.5,
    trend_sma_period: int = 200,
) -> dict | None:
    result = _evaluate_atr_trend(
        stock_data, atr_period, atr_multiplier, trend_sma_period
    )
    if result is None:
        return None
    return result[1]


def getAtrTrendStrategy(
    stock_data: pd.DataFrame,
    atr_period: int = 14,
    atr_multiplier: float = 2.5,
    trend_sma_period: int = 200,
    verbose: bool = True,
):
    """
    Trend following com trailing stop ATR e filtro SMA de tendência.

    - True: trailing stop indica long E close > SMA
    - False: trailing stop indica short OU close < SMA
    - None: dados insuficientes (ativa fallback)
    """
    min_points = max(atr_period, trend_sma_period) + 5
    if len(stock_data) < min_points:
        if verbose:
            print(
                f"Dados insuficientes ({len(stock_data)}). "
                f"Minimo necessario: {min_points}."
            )
        return None

    result = _evaluate_atr_trend(
        stock_data, atr_period, atr_multiplier, trend_sma_period
    )
    if result is None:
        if verbose:
            print("Estrategia ATR Trend: sem sinal definido ainda.")
        return None

    decision, snapshot = result
    if verbose:
        print("-------")
        print(f"Estrategia: {snapshot['strategy']}")
        print(
            f" | ATR({atr_period}) x {atr_multiplier}: "
            f"stop={snapshot['trailing_stop']:.4f}"
        )
        print(
            f" | SMA({trend_sma_period}): {snapshot['sma']:.4f} | "
            f"Close: {snapshot['close']:.4f}"
        )
        print(f" | Trailing: {snapshot['trailing']}")
        print(f" | Decisao: {snapshot['decision']}")
        print("-------")

    return decision
