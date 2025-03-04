import pandas as pd
import numpy as np


def vortex(data: pd.DataFrame, window=14, positive=True):
    """
    Calcula o Indicador Vortex (VI+ e VI-)
    :param data: DataFrame contendo colunas 'high_price', 'low_price' e 'close_price'.
    :param window: Período para cálculo.
    :param positive: Se True, retorna VI+, senão retorna VI-.
    :return: Pandas Series com os valores de VI+ ou VI-.
    """

    # Cálculo do Movimento Direcional Verdadeiro (True Range)
    tr = np.abs(data["high_price"] - data["low_price"])
    tr = np.maximum(tr, np.abs(data["high_price"] - data["close_price"].shift(1)))
    tr = np.maximum(tr, np.abs(data["low_price"] - data["close_price"].shift(1)))

    # Movimento Direcional Positivo (VM+)
    vm_plus = np.abs(data["high_price"] - data["low_price"].shift(1))

    # Movimento Direcional Negativo (VM-)
    vm_minus = np.abs(data["low_price"] - data["high_price"].shift(1))

    # Suavização por soma móvel
    sum_tr = tr.rolling(window=window).sum()
    sum_vm_plus = vm_plus.rolling(window=window).sum()
    sum_vm_minus = vm_minus.rolling(window=window).sum()

    # Calculando VI+ e VI-
    vi_plus = sum_vm_plus / sum_tr
    vi_minus = sum_vm_minus / sum_tr

    return vi_plus if positive else vi_minus
