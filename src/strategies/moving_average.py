import pandas as pd

MA_fast = 7
MA_slow = 25

# Estratégia Simples de Médias Móveis
def getMovingAverageTradeStrategy(stock_data: pd.DataFrame, fast_window=MA_fast, slow_window=MA_slow, verbose=True):
    """
    Estratégia de Médias Móveis Simples.

    - Compra se a média rápida cruza acima da média lenta.
    - Vende se a média rápida cruza abaixo da média lenta.

    :param stock_data: DataFrame contendo os dados do ativo.
    :param fast_window: Período da média móvel rápida.
    :param slow_window: Período da média móvel lenta.
    :param verbose: Se True, imprime logs.
    :return: True (compra) ou False (venda).
    """

    # Criamos uma cópia para evitar o `SettingWithCopyWarning`
    stock_data = stock_data.copy()

    # Calcula as Médias Moveis Rápida e Lenta
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    # 🔹 REMOVE PERÍODOS INICIAIS COM NaN
    stock_data.dropna(subset=["ma_fast", "ma_slow"], inplace=True)

    # Se não houver dados suficientes após remover os NaNs, retorna None
    if len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Dados insuficientes após remoção de NaN. Pulando período...")
        return None

    # Pega os últimos valores das médias móveis
    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]

    # Toma a decisão com base na posição da média móvel
    trade_decision = last_ma_fast > last_ma_slow  # True = Comprar, False = Vender

    if verbose:
        print("-------")
        print("📊 Estratégia: Moving Average Simples")
        print(f" | Última Média Rápida: MA({fast_window}) = {last_ma_fast:.3f}")
        print(f" | Última Média Lenta: MA({slow_window}) = {last_ma_slow:.3f}")
        print(f' | Decisão: {"Comprar" if trade_decision == True else "Vender" if trade_decision == False else "Nenhuma"}')

        print("-------")

    return trade_decision
