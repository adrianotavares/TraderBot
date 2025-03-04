# indicators/macd.py
def macd(series, fast_window, slow_window, signal_window):
    fast_ema = series.ewm(span=fast_window, adjust=False).mean()
    slow_ema = series.ewm(span=slow_window, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_window, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
