import pandas as pd
import pytest

from indicators.vwap import in_session, opening_range, parse_hhmm, session_vwap


def _bars(times_and_closes, volume=100.0):
    rows = []
    for open_time, close in times_and_closes:
        rows.append(
            {
                "open_time": pd.Timestamp(open_time, tz="UTC"),
                "open_price": close,
                "high_price": close,
                "low_price": close,
                "close_price": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def test_parse_hhmm_empty_is_none():
    assert parse_hhmm("") is None
    assert parse_hhmm(None) is None
    assert parse_hhmm("12:00") == (12, 0)


def test_parse_hhmm_rejects_invalid():
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        parse_hhmm("noon")


def test_in_session_empty_bounds_is_always_true():
    ts = pd.Timestamp("2026-08-29 03:15", tz="UTC")
    assert in_session(ts, "", "") is True


def test_in_session_half_open_window():
    start, end = "12:00", "20:00"
    assert in_session(pd.Timestamp("2026-08-29 12:00", tz="UTC"), start, end)
    assert in_session(pd.Timestamp("2026-08-29 19:59", tz="UTC"), start, end)
    assert not in_session(pd.Timestamp("2026-08-29 11:59", tz="UTC"), start, end)
    assert not in_session(pd.Timestamp("2026-08-29 20:00", tz="UTC"), start, end)


def test_in_session_overnight_window():
    start, end = "20:00", "04:00"
    assert in_session(pd.Timestamp("2026-08-29 23:00", tz="UTC"), start, end)
    assert in_session(pd.Timestamp("2026-08-30 03:59", tz="UTC"), start, end)
    assert not in_session(pd.Timestamp("2026-08-29 12:00", tz="UTC"), start, end)


def test_session_vwap_equal_volume_is_typical_mean():
    data = _bars(
        [
            ("2026-08-29 13:00", 10.0),
            ("2026-08-29 13:05", 20.0),
            ("2026-08-29 13:10", 30.0),
        ]
    )
    values = session_vwap(data, "12:00", "20:00")
    assert values.iloc[0] == pytest.approx(10.0)
    assert values.iloc[1] == pytest.approx(15.0)
    assert values.iloc[2] == pytest.approx(20.0)


def test_session_vwap_ignores_bars_outside_window():
    data = _bars(
        [
            ("2026-08-29 11:00", 50.0),
            ("2026-08-29 13:00", 10.0),
            ("2026-08-29 13:05", 20.0),
        ]
    )
    values = session_vwap(data, "12:00", "20:00")
    assert pd.isna(values.iloc[0])
    assert values.iloc[1] == pytest.approx(10.0)
    assert values.iloc[2] == pytest.approx(15.0)


def test_session_vwap_resets_each_utc_day():
    data = _bars(
        [
            ("2026-08-29 13:00", 10.0),
            ("2026-08-30 13:00", 40.0),
        ]
    )
    values = session_vwap(data, "12:00", "20:00")
    assert values.iloc[0] == pytest.approx(10.0)
    assert values.iloc[1] == pytest.approx(40.0)


def _or_bars(times_and_hl):
    rows = []
    for open_time, high, low in times_and_hl:
        close = (high + low) / 2.0
        rows.append(
            {
                "open_time": pd.Timestamp(open_time, tz="UTC"),
                "open_price": close,
                "high_price": high,
                "low_price": low,
                "close_price": close,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def test_opening_range_uses_first_n_session_bars_and_freezes():
    data = _or_bars(
        [
            ("2026-08-29 11:00", 200.0, 50.0),
            ("2026-08-29 12:00", 100.0, 99.0),
            ("2026-08-29 12:15", 101.0, 98.5),
            ("2026-08-29 12:30", 120.0, 90.0),
        ]
    )
    result = opening_range(data, "12:00", "20:00", opening_range_bars=2)
    assert result.complete is True
    assert result.bars_used == 2
    assert result.high == pytest.approx(101.0)
    assert result.low == pytest.approx(98.5)


def test_opening_range_incomplete_before_n_bars():
    data = _or_bars(
        [
            ("2026-08-29 12:00", 100.0, 99.0),
        ]
    )
    result = opening_range(data, "12:00", "20:00", opening_range_bars=2)
    assert result.complete is False
    assert result.bars_used == 1
    assert result.high == pytest.approx(100.0)
    assert result.low == pytest.approx(99.0)


def test_opening_range_resets_each_utc_day():
    data = _or_bars(
        [
            ("2026-08-29 12:00", 100.0, 90.0),
            ("2026-08-29 12:15", 110.0, 88.0),
            ("2026-08-30 12:00", 50.0, 40.0),
            ("2026-08-30 12:15", 52.0, 39.0),
        ]
    )
    result = opening_range(data, "12:00", "20:00", opening_range_bars=2)
    assert result.high == pytest.approx(52.0)
    assert result.low == pytest.approx(39.0)
