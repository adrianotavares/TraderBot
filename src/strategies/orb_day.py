from __future__ import annotations

import pandas as pd

from indicators.adx import adx
from indicators.vwap import candle_utc, in_session, opening_range


def _adx_rising_at(
    adx_values: pd.Series,
    position: int,
    adx_min: float,
    rising_bars: int,
) -> bool:
    if position < rising_bars:
        return False
    recent = adx_values.iloc[position - rising_bars : position + 1]
    if recent.isna().any():
        return False
    start = float(recent.iloc[0])
    end = float(recent.iloc[-1])
    if end < adx_min:
        return False
    if end > start:
        return True
    return end >= adx_min and start >= adx_min * 0.9


def _htf_close_above_sma(
    stock_data: pd.DataFrame,
    period: int,
    as_of,
) -> bool | None:
    """ORBP: last completed 4h close above SMA(period). ``period <= 0`` disables."""
    if period <= 0:
        return True
    as_of_ts = candle_utc(as_of)
    if pd.isna(as_of_ts):
        return None
    times = stock_data["open_time"].map(candle_utc)
    closes = pd.to_numeric(stock_data["close_price"], errors="coerce")
    frame = pd.DataFrame({"close": closes.to_numpy()}, index=pd.DatetimeIndex(times))
    frame = frame.loc[~frame.index.isna()]
    frame = frame[frame.index <= as_of_ts]
    if frame.empty:
        return None
    htf = frame["close"].resample("4h").last().dropna()
    completed = htf.index + pd.Timedelta(hours=4) <= as_of_ts
    htf = htf[completed]
    if len(htf) < period:
        return None
    last_sma = htf.rolling(window=period).mean().iloc[-1]
    if pd.isna(last_sma):
        return None
    return float(htf.iloc[-1]) > float(last_sma)


def _session_positions(
    df: pd.DataFrame,
    day: pd.Timestamp,
    session_start_utc: str,
    session_end_utc: str,
) -> list[int]:
    positions: list[int] = []
    for position in range(len(df)):
        timestamp = candle_utc(df["open_time"].iloc[position])
        if pd.isna(timestamp) or timestamp.floor("D") != day:
            continue
        if in_session(timestamp, session_start_utc, session_end_utc):
            positions.append(position)
    return positions


def _is_entry_at(
    df: pd.DataFrame,
    position: int,
    *,
    or_high: float,
    adx_values: pd.Series,
    volume_mean: pd.Series,
    adx_min: float,
    adx_rising_bars: int,
    volume_mult: float,
    require_bullish_candle: bool,
    htf_sma_period: int,
) -> bool:
    close = float(df["close_price"].iloc[position])
    open_price = float(df["open_price"].iloc[position])
    volume = float(df["volume"].iloc[position])
    vol_sma = volume_mean.iloc[position]
    last_adx = adx_values.iloc[position]
    if pd.isna(vol_sma) or pd.isna(last_adx) or float(vol_sma) <= 0:
        return False
    if close <= or_high:
        return False
    if require_bullish_candle and close <= open_price:
        return False
    if volume <= float(vol_sma) * float(volume_mult):
        return False
    if float(last_adx) < float(adx_min):
        return False
    if not _adx_rising_at(adx_values, position, float(adx_min), int(adx_rising_bars)):
        return False
    htf_ok = _htf_close_above_sma(
        df.iloc[: position + 1],
        int(htf_sma_period),
        df["open_time"].iloc[position],
    )
    return htf_ok is True


def _evaluate_orb_day(
    stock_data: pd.DataFrame,
    *,
    session_start_utc: str,
    session_end_utc: str,
    opening_range_bars: int,
    adx_period: int,
    adx_min: float,
    adx_rising_bars: int,
    volume_sma: int,
    volume_mult: float,
    require_bullish_candle: bool,
    htf_sma_period: int,
    fee_round_trip_pct: float,
    min_edge_multiple: float,
):
    min_points = max(adx_period, volume_sma) + adx_rising_bars + opening_range_bars + 5
    if len(stock_data) < min_points:
        return None

    df = stock_data.copy()
    for col in ("close_price", "open_price", "high_price", "low_price", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(
        subset=["close_price", "open_price", "high_price", "low_price", "volume"],
        inplace=True,
    )
    if len(df) < min_points:
        return None

    last = df.iloc[-1]
    last_pos = len(df) - 1
    last_close = float(last["close_price"])
    last_open = float(last["open_price"])
    last_volume = float(last["volume"])
    last_time = last["open_time"]
    inside = in_session(last_time, session_start_utc, session_end_utc)
    last_day = candle_utc(last_time).floor("D")

    or_info = opening_range(
        df,
        session_start_utc=session_start_utc,
        session_end_utc=session_end_utc,
        opening_range_bars=opening_range_bars,
        as_of=last_time,
    )
    adx_values = adx(df, period=adx_period)
    volume_mean = df["volume"].rolling(window=volume_sma).mean()
    last_adx = adx_values.iloc[-1]
    last_vol_sma = volume_mean.iloc[-1]
    adx_rising = _adx_rising_at(
        adx_values, last_pos, float(adx_min), int(adx_rising_bars)
    )

    snapshot = {
        "strategy": "ORB Day",
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
        "in_session": bool(inside),
        "opening_range_bars": int(opening_range_bars),
        "or_high": None if or_info.high is None else round(float(or_info.high), 8),
        "or_low": None if or_info.low is None else round(float(or_info.low), 8),
        "or_complete": bool(or_info.complete),
        "or_bars": int(or_info.bars_used),
        "close": round(last_close, 8),
        "adx": None if pd.isna(last_adx) else round(float(last_adx), 4),
        "adx_min": float(adx_min),
        "adx_rising": bool(adx_rising),
        "volume": round(last_volume, 8),
        "volume_sma": None if pd.isna(last_vol_sma) else round(float(last_vol_sma), 8),
        "volume_mult": float(volume_mult),
        "require_bullish_candle": bool(require_bullish_candle),
        "htf_sma_period": int(htf_sma_period),
        "fee_round_trip_pct": float(fee_round_trip_pct),
        "min_edge_multiple": float(min_edge_multiple),
        "already_signaled": False,
        "decision": "Aguardar",
    }

    if not inside:
        snapshot["decision"] = "Fora da sessao"
        return False, snapshot

    session_positions = _session_positions(
        df, last_day, session_start_utc, session_end_utc
    )
    if not or_info.complete or or_info.high is None or or_info.low is None:
        snapshot["decision"] = "Faixa incompleta"
        return None, snapshot

    or_high = float(or_info.high)
    or_low = float(or_info.low)
    if last_pos in session_positions[: int(opening_range_bars)]:
        snapshot["decision"] = "Montando faixa"
        return None, snapshot

    mid = (or_high + or_low) / 2.0
    width_pct = ((or_high - or_low) / mid * 100.0) if mid > 0 else 0.0
    hurdle = float(min_edge_multiple) * float(fee_round_trip_pct)
    snapshot["or_width_pct"] = round(width_pct, 4)
    snapshot["hurdle_pct"] = round(hurdle, 4)

    prior_entry = False
    for position in session_positions:
        if position >= last_pos:
            break
        if position in session_positions[: int(opening_range_bars)]:
            continue
        if width_pct < hurdle:
            break
        if _is_entry_at(
            df,
            position,
            or_high=or_high,
            adx_values=adx_values,
            volume_mean=volume_mean,
            adx_min=adx_min,
            adx_rising_bars=adx_rising_bars,
            volume_mult=volume_mult,
            require_bullish_candle=require_bullish_candle,
            htf_sma_period=htf_sma_period,
        ):
            prior_entry = True
            break
    snapshot["already_signaled"] = prior_entry

    if prior_entry:
        if last_close <= or_high:
            snapshot["decision"] = "Vender"
            return False, snapshot
        snapshot["decision"] = "Ja sinalizou"
        return None, snapshot

    if width_pct < hurdle:
        snapshot["decision"] = "Faixa estreita"
        return None, snapshot

    if pd.isna(last_adx) or pd.isna(last_vol_sma) or last_close <= 0:
        return None

    if float(last_adx) < float(adx_min) or not adx_rising:
        snapshot["decision"] = "ADX baixo"
        return None, snapshot

    htf_ok = _htf_close_above_sma(df, int(htf_sma_period), last_time)
    snapshot["htf_bias"] = htf_ok
    if htf_ok is not True:
        snapshot["decision"] = "ORBP SMA"
        return None, snapshot

    volume_ok = (not pd.isna(last_vol_sma)) and last_volume > float(last_vol_sma) * float(
        volume_mult
    )
    bullish = (last_close > last_open) if require_bullish_candle else True
    if last_close > or_high and volume_ok and bullish:
        snapshot["decision"] = "Comprar"
        return True, snapshot

    snapshot["decision"] = "Aguardar"
    return None, snapshot


def get_orb_day_snapshot(
    stock_data: pd.DataFrame,
    session_start_utc: str = "12:00",
    session_end_utc: str = "20:00",
    opening_range_bars: int = 2,
    adx_period: int = 14,
    adx_min: float = 25.0,
    adx_rising_bars: int = 2,
    volume_sma: int = 20,
    volume_mult: float = 1.5,
    require_bullish_candle: bool = True,
    htf_sma_period: int = 50,
    fee_round_trip_pct: float = 0.15,
    min_edge_multiple: float = 3.0,
) -> dict | None:
    result = _evaluate_orb_day(
        stock_data,
        session_start_utc=session_start_utc,
        session_end_utc=session_end_utc,
        opening_range_bars=opening_range_bars,
        adx_period=adx_period,
        adx_min=adx_min,
        adx_rising_bars=adx_rising_bars,
        volume_sma=volume_sma,
        volume_mult=volume_mult,
        require_bullish_candle=require_bullish_candle,
        htf_sma_period=htf_sma_period,
        fee_round_trip_pct=fee_round_trip_pct,
        min_edge_multiple=min_edge_multiple,
    )
    if result is None:
        return None
    return result[1]


def getOrbDayStrategy(
    stock_data: pd.DataFrame,
    session_start_utc: str = "12:00",
    session_end_utc: str = "20:00",
    opening_range_bars: int = 2,
    adx_period: int = 14,
    adx_min: float = 25.0,
    adx_rising_bars: int = 2,
    volume_sma: int = 20,
    volume_mult: float = 1.5,
    require_bullish_candle: bool = True,
    htf_sma_period: int = 50,
    fee_round_trip_pct: float = 0.15,
    min_edge_multiple: float = 3.0,
    verbose: bool = True,
):
    """Opening Range Breakout de sessao. Args vêm do YAML ``strategy.main_args``.

    - True: close acima da maxima da faixa, volume e ADX em expansao, ORBP ok
    - False: fora da sessao, ou close de volta para dentro da faixa apos o sinal
    - None: faixa incompleta, sem expansao, ou ja houve True nesta sessao
    """
    min_points = max(adx_period, volume_sma) + adx_rising_bars + opening_range_bars + 5
    if len(stock_data) < min_points:
        if verbose:
            print(
                f"Dados insuficientes ({len(stock_data)}). "
                f"Minimo necessario: {min_points}."
            )
        return None

    result = _evaluate_orb_day(
        stock_data,
        session_start_utc=session_start_utc,
        session_end_utc=session_end_utc,
        opening_range_bars=opening_range_bars,
        adx_period=adx_period,
        adx_min=adx_min,
        adx_rising_bars=adx_rising_bars,
        volume_sma=volume_sma,
        volume_mult=volume_mult,
        require_bullish_candle=require_bullish_candle,
        htf_sma_period=htf_sma_period,
        fee_round_trip_pct=fee_round_trip_pct,
        min_edge_multiple=min_edge_multiple,
    )
    if result is None:
        if verbose:
            print("Estrategia ORB Day: sem sinal definido ainda.")
        return None

    decision, snapshot = result
    if verbose:
        print("-------")
        print(f"Estrategia: {snapshot['strategy']}")
        print(
            f" | OR: {snapshot['or_low']}–{snapshot['or_high']} "
            f"| Close: {snapshot['close']}"
        )
        print(
            f" | ADX: {snapshot['adx']} rising={snapshot['adx_rising']} "
            f"| sessao={snapshot['in_session']}"
        )
        print(f" | Decisao: {snapshot['decision']}")
        print("-------")
    return decision
