import pandas as pd
import pytest

from indicators.vwap import in_session, parse_hhmm, session_vwap


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
