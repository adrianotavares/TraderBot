import pandas as pd


def rsi(series, window, last_only):
    # Diferença entre os preços
    delta = series.diff(1)

    # Ganhos e perdas
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    # Média suavizada (Wilder's EMA)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()

    # RS e RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Retornar apenas o último valor ou a série inteira
    if last_only:
        return rsi.iloc[-1]
    else:
        return rsi
