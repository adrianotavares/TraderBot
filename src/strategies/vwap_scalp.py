from __future__ import annotations

import pandas as pd

from indicators.adx import adx
from indicators.atr import atr
from indicators.rsi import rsi
from indicators.vwap import in_session, session_vwap


def _evaluate_vwap_scalp(
    stock_data: pd.DataFrame,
    *,
    session_start_utc: str,
    session_end_utc: str,
    vwap_atr_k: float,
    atr_period: int,
    adx_period: int,
    adx_max: float,
    rsi_period: int,
    rsi_buy: float,
    rsi_exit: float,
    volume_sma: int,
    volume_mult: float,
    fee_round_trip_pct: float,
    min_edge_multiple: float,
):
    min_points = max(atr_period, adx_period, rsi_period, volume_sma) + 5
    if len(stock_data) < min_points:
        return None

    df = stock_data.copy()
    for col in ("close_price", "high_price", "low_price", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["close_price", "high_price", "low_price", "volume"], inplace=True)
    if len(df) < min_points:
        return None

    last = df.iloc[-1]
    last_close = float(last["close_price"])
    last_volume = float(last["volume"])
    inside = in_session(last["open_time"], session_start_utc, session_end_utc)

    vwap_values = session_vwap(df, session_start_utc, session_end_utc)
    atr_values = atr(df, window=atr_period)
    adx_values = adx(df, period=adx_period)
    rsi_values = rsi(df["close_price"], rsi_period, False)
    volume_mean = df["volume"].rolling(window=volume_sma).mean()

    last_vwap = vwap_values.iloc[-1]
    last_atr = atr_values.iloc[-1]
    last_adx = adx_values.iloc[-1]
    last_rsi = rsi_values.iloc[-1]
    last_vol_sma = volume_mean.iloc[-1]

    snapshot = {
        "strategy": "VWAP Scalp",
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
        "in_session": bool(inside),
        "vwap_atr_k": vwap_atr_k,
        "close": round(last_close, 8),
        "vwap": None if pd.isna(last_vwap) else round(float(last_vwap), 8),
        "atr": None if pd.isna(last_atr) else round(float(last_atr), 8),
        "adx": None if pd.isna(last_adx) else round(float(last_adx), 4),
        "rsi": None if pd.isna(last_rsi) else round(float(last_rsi), 4),
        "volume": round(last_volume, 8),
        "volume_sma": None if pd.isna(last_vol_sma) else round(float(last_vol_sma), 8),
        "fee_round_trip_pct": fee_round_trip_pct,
        "min_edge_multiple": min_edge_multiple,
        "decision": "Aguardar",
    }

    if not inside:
        snapshot["decision"] = "Fora da sessao"
        return False, snapshot

    needed = (
        pd.isna(last_vwap),
        pd.isna(last_atr),
        pd.isna(last_adx),
        pd.isna(last_rsi),
        pd.isna(last_vol_sma),
    )
    if any(needed) or last_close <= 0 or float(last_atr) <= 0:
        return None

    atr_pct = float(last_atr) / last_close * 100.0
    hurdle = float(min_edge_multiple) * float(fee_round_trip_pct)
    snapshot["atr_pct"] = round(atr_pct, 4)
    snapshot["hurdle_pct"] = round(hurdle, 4)
    band = float(last_vwap) - float(vwap_atr_k) * float(last_atr)
    snapshot["entry_band"] = round(band, 8)

    if last_close >= float(last_vwap) or float(last_rsi) >= float(rsi_exit):
        snapshot["decision"] = "Vender"
        return False, snapshot

    if atr_pct < hurdle:
        snapshot["decision"] = "Hurdle de taxa"
        return None, snapshot

    if float(last_adx) >= float(adx_max):
        snapshot["decision"] = "ADX alto"
        return None, snapshot

    volume_ok = last_volume > float(last_vol_sma) * float(volume_mult)
    stretched = last_close < band
    oversold = float(last_rsi) < float(rsi_buy)
    if stretched and oversold and volume_ok:
        snapshot["decision"] = "Comprar"
        return True, snapshot

    snapshot["decision"] = "Aguardar"
    return None, snapshot


def get_vwap_scalp_snapshot(
    stock_data: pd.DataFrame,
    session_start_utc: str = "12:00",
    session_end_utc: str = "20:00",
    vwap_atr_k: float = 1.0,
    atr_period: int = 14,
    adx_period: int = 14,
    adx_max: float = 22.0,
    rsi_period: int = 14,
    rsi_buy: float = 30.0,
    rsi_exit: float = 55.0,
    volume_sma: int = 20,
    volume_mult: float = 1.2,
    fee_round_trip_pct: float = 0.15,
    min_edge_multiple: float = 3.0,
) -> dict | None:
    result = _evaluate_vwap_scalp(
        stock_data,
        session_start_utc=session_start_utc,
        session_end_utc=session_end_utc,
        vwap_atr_k=vwap_atr_k,
        atr_period=atr_period,
        adx_period=adx_period,
        adx_max=adx_max,
        rsi_period=rsi_period,
        rsi_buy=rsi_buy,
        rsi_exit=rsi_exit,
        volume_sma=volume_sma,
        volume_mult=volume_mult,
        fee_round_trip_pct=fee_round_trip_pct,
        min_edge_multiple=min_edge_multiple,
    )
    if result is None:
        return None
    return result[1]


def getVwapScalpStrategy(
    stock_data: pd.DataFrame,
    session_start_utc: str = "12:00",
    session_end_utc: str = "20:00",
    vwap_atr_k: float = 1.0,
    atr_period: int = 14,
    adx_period: int = 14,
    adx_max: float = 22.0,
    rsi_period: int = 14,
    rsi_buy: float = 30.0,
    rsi_exit: float = 55.0,
    volume_sma: int = 20,
    volume_mult: float = 1.2,
    fee_round_trip_pct: float = 0.15,
    min_edge_multiple: float = 3.0,
    verbose: bool = True,
):
    """Mean reversion ao VWAP de sessao. Args vêm do YAML ``strategy.main_args``.

    - True: esticada abaixo do VWAP, RSI oversold, volume e ADX ok, ATR paga a taxa
    - False: fora da sessao, close de volta ao VWAP, ou RSI de saida
    - None: inconclusivo (fallback, se habilitado)
    """
    min_points = max(atr_period, adx_period, rsi_period, volume_sma) + 5
    if len(stock_data) < min_points:
        if verbose:
            print(
                f"Dados insuficientes ({len(stock_data)}). "
                f"Minimo necessario: {min_points}."
            )
        return None

    result = _evaluate_vwap_scalp(
        stock_data,
        session_start_utc=session_start_utc,
        session_end_utc=session_end_utc,
        vwap_atr_k=vwap_atr_k,
        atr_period=atr_period,
        adx_period=adx_period,
        adx_max=adx_max,
        rsi_period=rsi_period,
        rsi_buy=rsi_buy,
        rsi_exit=rsi_exit,
        volume_sma=volume_sma,
        volume_mult=volume_mult,
        fee_round_trip_pct=fee_round_trip_pct,
        min_edge_multiple=min_edge_multiple,
    )
    if result is None:
        if verbose:
            print("Estrategia VWAP Scalp: sem sinal definido ainda.")
        return None

    decision, snapshot = result
    if verbose:
        print("-------")
        print(f"Estrategia: {snapshot['strategy']}")
        print(
            f" | VWAP: {snapshot['vwap']} | Close: {snapshot['close']} "
            f"| ATR: {snapshot['atr']}"
        )
        print(
            f" | ADX: {snapshot['adx']} | RSI: {snapshot['rsi']} "
            f"| sessao={snapshot['in_session']}"
        )
        print(f" | Decisao: {snapshot['decision']}")
        print("-------")
    return decision
