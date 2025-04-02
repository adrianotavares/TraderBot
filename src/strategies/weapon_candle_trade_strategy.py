import pandas as pd

# Estratégia Weapon Candle
def getWeaponCandleTradeStrategy(
    stock_data: pd.DataFrame,
    rsi_period=14,
    ema_period=9,
    macd_fast=12,
    macd_slow=24,
    macd_signal=9,
    volume_sma_period=5,
    verbose=True
):
    """
    Estratégia Weapon Candle que combina EMA, MACD, RSI e Volume para decisões de compra/venda.
    """

    debug = False

    # --- Etapa 1: Pré-cálculos e Verificações ---
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

    # --- Etapa 2: Cálculo dos Indicadores ---

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

    # --- Etapa 3: Identificar a Weapon Candle ---

    # Obter as duas últimas velas
    last = df.iloc[-1]
    previous = df.iloc[-2]

    # 1. Verificação do Crossover do MACD
    buy_crossover = previous["macd"] < previous["signal_line"] and last["macd"] > last["signal_line"]
    sell_crossover = previous["macd"] > previous["signal_line"] and last["macd"] < last["signal_line"]
    
    if debug:
        print("-------")
        print("1. Verificação do Crossover do MACD")
        print(f"   - Vela Anterior: MACD={previous['macd']:.2f}, Sinal={previous['signal_line']:.2f}")
        print(f"   - Vela Atual: MACD={last['macd']:.2f}, Sinal={last['signal_line']:.2f}")
        if buy_crossover:
            print("   - Crossover de Compra Detectado")
        elif sell_crossover:
            print("   - Crossover de Venda Detectado")
        else:
            print("   - Nenhum Crossover Detectado")
        print("-------")
        

    # 2. Confirmação da EMA
    ema_confirmation_buy = previous["close_price"] > previous["ema"]
    ema_confirmation_sell = previous["close_price"] < previous["ema"]

    if debug:
        print("-------")
        print("2. Confirmação da EMA")
        print(f"   - Vela Anterior: Preço de Fechamento={previous['close_price']:.2f}, EMA={previous['ema']:.2f}")
        if ema_confirmation_buy:
            print("   - Confirmação de Compra: Preço acima da EMA")
        elif ema_confirmation_sell:
            print("   - Confirmação de Venda: Preço abaixo da EMA")
        else:
            print("   - Nenhuma Confirmação de EMA")
        print("-------")
    

    # 3. Confirmação de Volume
    volume_confirmation = last["volume"] > last["volume_sma"]

    if debug:
        print("-------")
        print("3. Confirmação de Volume")
        print(f"   - Vela Atual: Volume={last['volume']:.2f}, Volume SMA={last['volume_sma']:.2f}")
        if volume_confirmation:
            print("   - Volume acima da média móvel")
        else:
            print("   - Volume abaixo da média móvel")
        print("-------")
    
    # 4. Confirmação do RSI
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
        print("-------")

    # --- Etapa 5: Decisão Final ---
    weapon_candle_decision = None
    if buy_crossover and ema_confirmation_buy and volume_confirmation and rsi_confirmation_buy:
        weapon_candle_decision = True  # Comprar
    elif sell_crossover and ema_confirmation_sell and volume_confirmation and rsi_confirmation_sell:
        weapon_candle_decision = False  # Vender

    # --- Etapa 6: Logs Detalhados ---
    if verbose:
        print("-------")
        print(f"📊 Estratégia: Weapon Candle @ {df.index[-1]}")
        print(f"Parâmetros: EMA={ema_period}, MACD=({macd_fast},{macd_slow},{macd_signal}), RSI={rsi_period}, VolSMA={volume_sma_period}")
        print(f"Preço Atual (Close): {last['close_price']:.2f}")
        print(f"MACD: {last['macd']:.2f}, Sinal: {last['signal_line']:.2f}")
        print(f"EMA Atual: {last['ema']:.2f}")
        print(f"RSI Atual: {last['rsi']:.2f}")
        print(f"Volume Atual: {last['volume']:.2f}, Volume SMA: {last['volume_sma']:.2f}")
        print(f"VWAP Atual: {last['vwap']:.2f}")
        print(f"--- Confirmações ---")
        print(f"1. MACD Crossover: {'COMPRA' if buy_crossover else 'VENDA' if sell_crossover else 'Nenhuma Confirmação'}")
        print(f"2. Conf. EMA (Vela Anterior): {'OK Compra' if ema_confirmation_buy else 'OK Venda' if ema_confirmation_sell else 'Nenhuma Confirmação'}")
        print(f"3. Conf. Volume (Vela Atual): {'OK Acima da Média' if volume_confirmation else 'Fail Abaixo da Média '}")
        print(f"4. Conf. RSI (Vela Atual): {'OK Compra' if rsi_confirmation_buy else ''}{'OK Venda' if rsi_confirmation_sell else ''}{'Neutro' if not rsi_confirmation_buy and not rsi_confirmation_sell else ''}")
        print(f"--- Decisão Final ---")
        print(f"   ➡️ {'🟢 COMPRAR' if weapon_candle_decision == True else '🔴 VENDER' if weapon_candle_decision == False else '⚪️ NENHUMA AÇÃO'}")
        print("-------")

    return weapon_candle_decision