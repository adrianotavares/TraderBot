import pandas as pd

from indicators.atr import atr, compute_trailing_stop, compute_ut_position


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

    df = stock_data.copy()
    for col in ("close_price", "high_price", "low_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["close_price", "high_price", "low_price"], inplace=True)

    if len(df) < min_points:
        if verbose:
            print(f"Dados insuficientes apos limpeza ({len(df)}).")
        return None

    close = df["close_price"]
    atr_values = atr(df, window=atr_period)
    sma = close.rolling(window=trend_sma_period).mean()

    if pd.isna(atr_values.iloc[-1]) or pd.isna(sma.iloc[-1]):
        if verbose:
            print("Indicadores ainda nao calculaveis (NaN no ultimo candle).")
        return None

    trailing_stop = compute_trailing_stop(close, atr_values, atr_multiplier)
    position = compute_ut_position(close, trailing_stop)

    last_pos = position[-1]
    last_close = close.iloc[-1]
    last_sma = sma.iloc[-1]
    last_stop = trailing_stop.iloc[-1]

    if last_pos == 0:
        if verbose:
            print("Estrategia ATR Trend: sem sinal definido ainda.")
        return None

    trailing_long = last_pos == 1
    above_sma = last_close > last_sma

    if trailing_long and above_sma:
        decision = True
    else:
        decision = False

    if verbose:
        print("-------")
        print("Estrategia: ATR Trend Following")
        print(f" | ATR({atr_period}) x {atr_multiplier}: stop={last_stop:.4f}")
        print(f" | SMA({trend_sma_period}): {last_sma:.4f} | Close: {last_close:.4f}")
        print(f" | Trailing: {'long' if trailing_long else 'short'}")
        print(
            f' | Decisao: {"Comprar" if decision else "Vender"}'
        )
        print("-------")

    return decision
