import pandas as pd

# Estratégia Weapon Candle
def getWeaponCandleTradeStrategy(
    stock_data: pd.DataFrame,
    rsi_period=14,
    ema_period=9,
    macd_fast=12,
    macd_slow=26,
    macd_signal=9,
    volume_sma_period=5,
    verbose=True
):
    """
    Estratégia Weapon Candle que combina EMA, MACD, RSI e Volume para decisões de compra/venda.
    """

    debug = True

    # --- Pré-cálculos e Verificações ---
    min_data_points = max(rsi_period, ema_period, macd_slow + macd_signal, volume_sma_period) + 2
    if len(stock_data) < min_data_points:
        if verbose:
            print(f"❌ Dados insuficientes ({len(stock_data)} pontos) para calcular indicadores. Mínimo necessário: {min_data_points}.")
        return None

    # Criar uma cópia para evitar alterações no original
    df = stock_data.copy()

    # Garantir que 'close_price' e 'volume' são numéricos
    df['close_price'] = pd.to_numeric(df['close_price'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df.dropna(subset=['close_price', 'volume'], inplace=True)

    if len(df) < min_data_points:
        if verbose:
            print(f"❌ Dados insuficientes ({len(df)} pontos válidos) após limpeza.")
        return None

    # --- Cálculo dos Indicadores ---

    # EMA (Exponential Moving Average)
    df["ema"] = df["close_price"].ewm(span=ema_period, adjust=False).mean()

    # MACD (Moving Average Convergence Divergence)
    ema_fast = df["close_price"].ewm(span=macd_fast, adjust=False).mean()
    ema_slow = df["close_price"].ewm(span=macd_slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["signal_line"] = df["macd"].ewm(span=macd_signal, adjust=False).mean()

    # RSI (Relative Strength Index)
    delta = df["close_price"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=rsi_period, min_periods=rsi_period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=rsi_period, min_periods=rsi_period).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].ffill().fillna(50)  # Preencher NaNs com valores padrão

    # Volume SMA (Simple Moving Average)
    df["volume_sma"] = df["volume"].rolling(window=volume_sma_period, min_periods=volume_sma_period).mean()

    # VWAP (Volume Weighted Average Price)
    df["vwap"] = (df["close_price"] * df["volume"]).cumsum() / df["volume"].cumsum()

    # Remover NaNs gerados pelos cálculos
    df.dropna(inplace=True)

    if len(df) < 2:
        if verbose:
            print("❌ Dados insuficientes após cálculo dos indicadores.")
        return None

    # --- Identificar a Weapon Candle ---

    # Obter as duas últimas velas
    last = df.iloc[-1]
    previous = df.iloc[-2]

    if debug:
        print("-------")
        print("📊 Últimas Velas (Debug)")
        print("Vela Anterior (Previous):")
        print(previous.to_string())
        print("-------")
        print("Vela Atual (Last):")
        print(last.to_string())
        print("-------")

    # 1. Verificação do Crossover do MACD
    crossover_buy = previous["macd"] < previous["signal_line"] and last["macd"] > last["signal_line"]
    crossover_sell = previous["macd"] > previous["signal_line"] and last["macd"] < last["signal_line"]
    
    if debug:
        print("-------")
        print("1. Verificação do Crossover do MACD")
        print(f"   - Vela Anterior: MACD={previous['macd']:.2f}, Sinal={previous['signal_line']:.2f}")
        print(f"   - Vela Atual: MACD={last['macd']:.2f}, Sinal={last['signal_line']:.2f}")
        if crossover_buy:
            print("   - Crossover de Compra Detectado")
        elif crossover_sell:
            print("   - Crossover de Venda Detectado")
        else:
            print("   - Nenhum Crossover Detectado")
        

    # 2. Confirmação da EMA
    ema_confirmation_buy = previous["close_price"] > previous["ema"]
    ema_confirmation_sell = previous["close_price"] < previous["ema"]

    if debug:
        print("-------")
        print("2. Confirmação da EMA")
        print(f"   - Vela Anterior: Preço de Fechamento={previous['close_price']:.2f}, EMA={previous['ema']:.2f}")
        if ema_confirmation_buy:
            print("   - Preço acima da EMA (Confirmação de Compra)")
        elif ema_confirmation_sell:
            print("   - Preço abaixo da EMA (Confirmação de Venda)")
        else:
            print("   - Nenhuma Confirmação de EMA")
    
    # 3. Confirmação do VWAP
    vwap_confirmation_buy = last["close_price"] > last["vwap"]
    vwap_confirmation_sell = last["close_price"] < last["vwap"]

    if debug:
        print("-------")
        print("5. Confirmação do VWAP")
        print(f"   - Preço Atual: {last['close_price']:.2f}, VWAP: {last['vwap']:.2f}")
        if vwap_confirmation_buy:
            print("   - Preço acima do VWAP (Confirmação de Compra)")
        elif vwap_confirmation_sell:
            print("   - Preço abaixo do VWAP (Confirmação de Venda)")
        else:
            print("   - Nenhuma Confirmação do VWAP")

    # 4. Confirmação de Volume
    volume_confirmation_buy = last["volume"] > last["volume_sma"]
    volume_confirmation_sell = last["volume"] < last["volume_sma"]

    if debug:
        print("-------")
        print("3. Confirmação de Volume")
        print(f"   - Vela Atual: Volume={last['volume']:.2f}, Volume SMA={last['volume_sma']:.2f}")
        if volume_confirmation_buy:
            print("   - Volume acima da média móvel (Confirmação de Compra)")
        elif volume_confirmation_sell:
            print("   - Volume abaixo da média móvel (Confirmação de Venda)")
    
    # 5. Confirmação do RSI
    rsi_confirmation_buy = last["rsi"] < 30
    rsi_confirmation_sell = last["rsi"] > 70

    if debug:
        print("-------")
        print("4. Confirmação do RSI")
        print(f"   - Vela Atual: RSI={last['rsi']:.2f}")
        if rsi_confirmation_buy:
            print("   - RSI abaixo de 30 (Sobrevendido)")
        elif rsi_confirmation_sell:
            print("   - RSI acima de 70 (Sobrecomprado)")
        else:
            print("   - RSI em zona neutra")


    # --- Decisão Final ---
    weapon_candle_decision = None
    if crossover_buy and ema_confirmation_buy and volume_confirmation_buy and rsi_confirmation_buy and vwap_confirmation_buy:
        weapon_candle_decision = True  # Comprar
    elif crossover_sell and ema_confirmation_sell and volume_confirmation_sell and rsi_confirmation_sell and vwap_confirmation_sell:
        weapon_candle_decision = False  # Vender
    # elif sell_crossover :
    #     weapon_candle_decision = False  # Vender 
    # elif rsi_confirmation_sell:
    #     weapon_candle_decision = False  # Vender 

    # --- Logs Detalhados ---
    if verbose:
        print("-------")
        print(f"📊 Estratégia: Weapon Candle @ {df.index[-1]}")
        print(f"Parâmetros: EMA={ema_period}, MACD=({macd_fast},{macd_slow},{macd_signal}), RSI={rsi_period}, VolSMA={volume_sma_period}")
        print(f"Preço (Close): {last['close_price']:.2f}")
        print(f"MACD         : {last['macd']:.2f}, Sinal: {last['signal_line']:.2f}")
        print(f"EMA          : {last['ema']:.2f}")
        print(f"VWAP         : {last['vwap']:.2f}")
        print(f"Volume       : {last['volume']:.2f}, Volume SMA: {last['volume_sma']:.2f}")
        print(f"RSI          : {last['rsi']:.2f}")
        print(f"--- Confirmações ---")
        print(f"1. MACD Crossover      : {'OK Compra' if crossover_buy           else 'OK Venda' if crossover_sell           else 'Neutro'}")
        print(f"2. EMA (Vela Anterior) : {'OK Compra' if ema_confirmation_buy    else 'OK Venda' if ema_confirmation_sell    else 'Neutro'}")
        print(f"3. VWAP (Vela Atual)   : {'OK Compra' if vwap_confirmation_buy   else 'OK Venda' if vwap_confirmation_sell   else 'Neutro'}")        
        print(f"4. Volume (Vela Atual) : {'OK Compra' if volume_confirmation_buy else 'OK Venda' if volume_confirmation_sell else 'Neutro'}")
        print(f"5. RSI (Vela Atual)    : {'OK Compra' if rsi_confirmation_buy    else 'OK Venda' if rsi_confirmation_sell    else 'Neutro'}")
        print(f"--- Decisão Final ---")
        print(f"   ➡️ {'🟢 COMPRAR' if weapon_candle_decision == True else '🔴 VENDER' if weapon_candle_decision == False else '⚪️ NENHUMA AÇÃO'}")
        print("-------")

    return weapon_candle_decision