import pandas as pd
import numpy as np

"""
O que é ATR (Average True Range)?

O ATR (Average True Range) é um indicador técnico desenvolvido por J. Welles Wilder Jr. para medir a volatilidade
de um ativo financeiro. Ele calcula a média das variações reais do preço durante um determinado período.

O True Range (TR) é definido como o maior dos seguintes valores:

Alta atual - Baixa atual
Módulo da Alta atual - Fechamento anterior
Módulo da Baixa atual - Fechamento anterior
O ATR é obtido ao calcular a média móvel do True Range ao longo de um período específico, geralmente 14 períodos.
"""


def atr(data: pd.DataFrame, window=14):
    """
    Calcula o Average True Range (ATR) de um DataFrame contendo preços OHLC.

    :param data: pd.DataFrame com colunas ['high', 'low', 'close']
    :param window: Período para calcular a média do ATR (default = 14)
    :return: Série Pandas com o ATR calculado
    """

    high = data["high"]
    low = data["low"]
    close = data["close"]

    # Cálculo do True Range (TR)
    tr1 = high - low
    tr2 = np.abs(high - close.shift(1))
    tr3 = np.abs(low - close.shift(1))

    # True Range é o maior valor entre os três cálculos acima
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR é a média móvel do True Range
    atr_values = true_range.rolling(window=window).mean()

    return atr_values
