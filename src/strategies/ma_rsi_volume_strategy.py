import pandas as pd


def getMovingAverageRSIVolumeStrategy(
    stock_data: pd.DataFrame,
    fast_window: int = 7,
    slow_window: int = 40,
    rsi_window: int = 14,
    rsi_overbought: int = 70,
    rsi_oversold: int = 30,
    volume_multiplier: float = 1.5,
    verbose: bool = True,
):
    """
    Estratégia de Médias Móveis com confirmação de RSI e Volume.

    - Compra quando a média rápida cruza acima da média lenta, RSI está acima da zona de sobrevenda e o volume está acima da média.
    - Venda quando a média rápida cruza abaixo da média lenta ou RSI está na zona de sobrecompra.
    """
    stock_data = stock_data.copy()

    # Calcula as Médias Móveis
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    # Calcula o RSI
    delta = stock_data["close_price"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_window).mean()
    rs = gain / loss
    stock_data["rsi"] = 100 - (100 / (1 + rs))

    # Calcula a Média do Volume
    stock_data["volume_avg"] = stock_data["volume"].rolling(window=slow_window).mean()

    # Remove NaN
    stock_data.dropna(subset=["ma_fast", "ma_slow", "rsi", "volume_avg"], inplace=True)

    if len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Dados insuficientes após remoção de NaN. Pulando período...")
        return None

    # Últimos valores dos indicadores
    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]
    last_rsi = stock_data["rsi"].iloc[-1]
    last_volume = stock_data["volume"].iloc[-1]
    last_volume_avg = stock_data["volume_avg"].iloc[-1]

    # Condições para compra
    buy_condition = (
        (last_ma_fast > last_ma_slow) and (last_rsi > rsi_oversold) and (last_volume > (volume_multiplier * last_volume_avg))
    )

    # Condições para venda
    sell_condition = (last_ma_fast < last_ma_slow) or (last_rsi > rsi_overbought)

    trade_decision = True if buy_condition else False if sell_condition else None

    if verbose:
        print("-------")
        print("📊 Estratégia: Médias Móveis + RSI + Volume")
        print(f" | Última Média Rápida: {last_ma_fast:.3f}")
        print(f" | Última Média Lenta: {last_ma_slow:.3f}")
        print(f" | Último RSI: {last_rsi:.3f}")
        print(f" | Último Volume: {last_volume:.3f}")
        print(f" | Média de Volume: {last_volume_avg:.3f}")
        print(f' | Decisão: {"Comprar" if trade_decision == True else "Vender" if trade_decision == False else "Nenhuma"}')
        print("-------")

    return trade_decision
