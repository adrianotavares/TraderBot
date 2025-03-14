import pandas as pd

MA_fast = 7
MA_slow = 30

# Estratégia de Antecipação de Média Móvel
def getMovingAverageAntecipationTradeStrategy(
        stock_data: pd.DataFrame, volatility_factor: float, fast_window=MA_fast, slow_window=MA_slow, verbose=True
):

    # Garantimos que há dados suficientes antes de calcular as médias móveis
    if len(stock_data) < slow_window:
        if verbose:
            print("❌ Dados insuficientes para calcular médias móveis. Pulando...")
        return None  # Retorna None para evitar erro

    # Criamos cópias das colunas para evitar o warning de Pandas
    stock_data = stock_data.copy()

    # Calcula as Médias Moveis Rápida e Lenta
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    # Calcula a volatilidade (desvio padrão) dos preços
    volatility_window = slow_window  # Normalmente é a mesma janela que slow_window da MA strategy.
    stock_data["volatility"] = stock_data["close_price"].rolling(window=volatility_window).std()

    # 🔹 REMOVE LINHAS INICIAIS COM NaN NAS MÉDIAS
    stock_data.dropna(subset=["ma_fast", "ma_slow"], inplace=True)

    # Se ainda restam poucos dados após remover NaN, pula esse período
    if len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Ainda há poucos dados após remover NaN. Pulando...")
        return None

    # Pega as últimas Médias Móveis e as penúltimas para calcular o gradiente
    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    prev_ma_fast = stock_data["ma_fast"].iloc[-3]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]
    prev_ma_slow = stock_data["ma_slow"].iloc[-3]

    # Última volatilidade (evita erro se houver NaN)
    last_volatility = stock_data["volatility"].dropna().iloc[-2] if not stock_data["volatility"].isna().all() else None
    if last_volatility is None:
        return None

    # Calcula o gradiente (mudança) das médias móveis
    fast_gradient = last_ma_fast - prev_ma_fast
    slow_gradient = last_ma_slow - prev_ma_slow

    # Calcula a diferença atual entre as médias
    current_difference = abs(last_ma_fast - last_ma_slow)

    # Inicializa a decisão
    ma_trade_decision = None

    # Toma a decisão com base em volatilidade + gradiente
    if current_difference < last_volatility * volatility_factor:
        if fast_gradient > 0 and fast_gradient > slow_gradient:
            ma_trade_decision = True  # Comprar
        elif fast_gradient < 0 and fast_gradient < slow_gradient:
            ma_trade_decision = False  # Vender

    # Log da estratégia e decisão
    if verbose:
        print("-------")
        print("📊 Estratégia: Moving Average Antecipation")
        print(f" | Última Média Rápida: MA({MA_fast}) = {last_ma_fast:.3f}")
        print(f" | Última Média Lenta: MA({MA_slow}) = {last_ma_slow:.3f}")
        print(f" | Última Volatilidade: {last_volatility:.3f}")
        print(f" | Diferença Atual: {current_difference:.3f}")
        print(f" | Diferença para antecipação: {volatility_factor * last_volatility:.3f}")
        print(f' | Gradiente Rápido: {fast_gradient:.3f} ({ "Subindo" if fast_gradient > 0 else "Descendo" })')
        print(f' | Gradiente Lento: {slow_gradient:.3f} ({ "Subindo" if slow_gradient > 0 else "Descendo" })')
        print(f' | Decisão: {"Comprar" if ma_trade_decision == True else "Vender" if ma_trade_decision == False else "Nenhuma"}')
        print("-------")

    return ma_trade_decision
