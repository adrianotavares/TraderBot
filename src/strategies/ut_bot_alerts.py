import numpy as np
import pandas as pd
from indicators import Indicators


def calculate_atr(high, low, close, period=10):
    """
    Calcula o Average True Range (ATR) com base nos valores de alta, baixa e fechamento.
    """
    tr1 = high - low
    tr2 = np.abs(high - close.shift(1))
    tr3 = np.abs(low - close.shift(1))

    tr = np.maximum(tr1, np.maximum(tr2, tr3))  # Obtém o maior True Range
    atr = tr.rolling(window=period).mean()  # Calcula a média do TR para obter o ATR

    return atr


def utBotAlerts(stock_data: pd.DataFrame, atr_period=10, atr_multiplier=2, verbose=True):
    """
    Implementa o indicador UT Bot Alerts para gerar sinais de compra e venda.

    :param stock_data: DataFrame com colunas 'high_price', 'low_price' e 'close_price'.
    :param atr_period: Período do ATR.
    :param atr_multiplier: Multiplicador para o cálculo do Trailing Stop.
    :return: True se o sinal for de compra (long), False se for de venda (short).
    """

    # Obtém os preços do DataFrame
    high = stock_data["high_price"]
    low = stock_data["low_price"]
    close = stock_data["close_price"]

    # Calcula o ATR
    atr = calculate_atr(high, low, close, atr_period)

    # atr = Indicators.getAtr(stock_data, window=atr_period)

    # Inicializa o Trailing Stop
    trailing_stop = pd.Series(np.zeros(len(close)), index=close.index)

    # Itera para calcular o trailing stop dinamicamente
    for i in range(1, len(close)):
        if close[i] > trailing_stop[i - 1] and close[i - 1] > trailing_stop[i - 1]:
            trailing_stop[i] = max(trailing_stop[i - 1], close[i] - atr_multiplier * atr[i])
        elif close[i] < trailing_stop[i - 1] and close[i - 1] < trailing_stop[i - 1]:
            trailing_stop[i] = min(trailing_stop[i - 1], close[i] + atr_multiplier * atr[i])
        else:
            trailing_stop[i] = (
                close[i] - atr_multiplier * atr[i] if close[i] > trailing_stop[i - 1] else close[i] + atr_multiplier * atr[i]
            )

    # Inicializa a variável de posição
    pos = np.zeros(len(close))

    # Define as regras de compra e venda com base no cruzamento do preço com o trailing stop
    for i in range(1, len(close)):
        if close[i - 1] < trailing_stop[i - 1] and close[i] > trailing_stop[i]:
            pos[i] = 1  # Compra
        elif close[i - 1] > trailing_stop[i - 1] and close[i] < trailing_stop[i]:
            pos[i] = -1  # Venda
        else:
            pos[i] = pos[i - 1]  # Mantém a posição anterior

    trade_decision = pos[-1] == 1  # Define a decisão com base no último valor de pos

    if verbose:
        print("-------")
        print("📊 Estratégia: UT Bots")
        print(f' | Decisão: {"Comprar" if trade_decision == True else "Vender" if trade_decision == False else "Nenhuma"}')
        print("-------")

    return trade_decision  # Retorna True se for para estar comprado, False se for para estar vendido
