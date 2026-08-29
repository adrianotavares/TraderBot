from __future__ import annotations

import pandas as pd


def candle_utc(value) -> pd.Timestamp:
    """Instant in UTC. Naive timestamps are treated as UTC."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def parse_hhmm(value: str | None) -> tuple[int, int] | None:
    """Parse 'HH:MM'. Empty/None means no bound."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    return hour, minute


def minutes_of_day(timestamp: pd.Timestamp) -> int:
    utc = candle_utc(timestamp)
    return int(utc.hour) * 60 + int(utc.minute)


def in_session(
    timestamp,
    session_start_utc: str = "",
    session_end_utc: str = "",
) -> bool:
    """True when the candle open is inside [start, end) UTC.

    With both bounds empty, the session is the whole UTC day.
    """
    start = parse_hhmm(session_start_utc)
    end = parse_hhmm(session_end_utc)
    if start is None and end is None:
        return True
    if start is None or end is None:
        return False
    start_m = start[0] * 60 + start[1]
    end_m = end[0] * 60 + end[1]
    current = minutes_of_day(timestamp)
    if start_m == end_m:
        return True
    if start_m < end_m:
        return start_m <= current < end_m
    return current >= start_m or current < end_m


def session_vwap(
    stock_data: pd.DataFrame,
    session_start_utc: str = "",
    session_end_utc: str = "",
) -> pd.Series:
    """Cumulative VWAP from the UTC session open, reset each UTC day.

    Typical price is (H+L+C)/3. Bars outside the session window are NaN.
    """
    typical = (
        pd.to_numeric(stock_data["high_price"], errors="coerce")
        + pd.to_numeric(stock_data["low_price"], errors="coerce")
        + pd.to_numeric(stock_data["close_price"], errors="coerce")
    ) / 3.0
    volume = pd.to_numeric(stock_data["volume"], errors="coerce").fillna(0.0)
    values = pd.Series(float("nan"), index=stock_data.index, dtype=float)

    current_day = None
    cum_pv = 0.0
    cum_vol = 0.0
    for position, (idx, row) in enumerate(stock_data.iterrows()):
        timestamp = candle_utc(row["open_time"])
        if pd.isna(timestamp):
            continue
        day = timestamp.floor("D")
        if current_day != day:
            current_day = day
            cum_pv = 0.0
            cum_vol = 0.0
        if not in_session(timestamp, session_start_utc, session_end_utc):
            continue
        bar_volume = float(volume.iloc[position])
        bar_typical = float(typical.iloc[position])
        if pd.isna(bar_typical) or bar_volume < 0:
            continue
        cum_pv += bar_typical * bar_volume
        cum_vol += bar_volume
        if cum_vol > 0:
            values.loc[idx] = cum_pv / cum_vol
    return values
