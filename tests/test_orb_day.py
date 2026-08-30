import pandas as pd
import pytest

from indicators.vwap import in_session
from strategies import orb_day
from strategies.orb_day import getOrbDayStrategy, get_orb_day_snapshot
from strategies.registry import default_args_for


def _make_ohlc(
    n: int,
    *,
    last_time: str = "2026-08-29 12:30",
    close: float = 100.0,
    volume: float = 1000.0,
) -> pd.DataFrame:
    last = pd.Timestamp(last_time, tz="UTC")
    times = pd.date_range(end=last, periods=n, freq="15min", tz="UTC")
    rows = []
    for open_time in times:
        rows.append(
            {
                "close_price": close,
                "open_price": close,
                "high_price": close + 0.4,
                "low_price": close - 0.4,
                "volume": volume,
                "open_time": open_time,
            }
        )
    return pd.DataFrame(rows)


def _session_orb_frame(
    *,
    last_time: str,
    or_high: float = 100.5,
    or_low: float = 98.8,
    base_close: float = 100.0,
    last_close: float = 101.0,
    last_open: float = 100.6,
    last_volume: float = 5000.0,
    prior_break_close: float | None = None,
    prior_break_volume: float = 5000.0,
    n: int = 40,
) -> pd.DataFrame:
    last = pd.Timestamp(last_time, tz="UTC")
    times = pd.date_range(end=last, periods=n, freq="15min", tz="UTC")
    day = last.floor("D")
    session_count = 0
    rows = []
    for open_time in times:
        is_last = open_time == last
        in_win = in_session(open_time, "12:00", "20:00") and open_time.floor("D") == day
        if in_win:
            session_count += 1
        if is_last:
            open_price, close, volume = last_open, last_close, last_volume
            high = max(open_price, close) + 0.1
            low = min(open_price, close) - 0.1
        elif in_win and session_count <= 2:
            open_price = (or_high + or_low) / 2.0
            close = open_price
            high, low, volume = or_high, or_low, 1000.0
        elif (
            prior_break_close is not None
            and in_win
            and session_count == 3
            and not is_last
        ):
            open_price = prior_break_close - 0.2
            close = prior_break_close
            high = close + 0.1
            low = open_price - 0.1
            volume = prior_break_volume
        else:
            open_price = close = base_close
            high, low, volume = base_close + 0.2, base_close - 0.2, 1000.0
        rows.append(
            {
                "close_price": close,
                "open_price": open_price,
                "high_price": high,
                "low_price": low,
                "volume": volume,
                "open_time": open_time,
            }
        )
    return pd.DataFrame(rows)


def _patch_adx(monkeypatch, value: float = 30.0):
    monkeypatch.setattr(
        orb_day,
        "adx",
        lambda df, period=14: pd.Series([value] * len(df), index=df.index),
    )


def _buy_kwargs(**overrides):
    args = {"verbose": False, "htf_sma_period": 0}
    args.update(overrides)
    return args


def test_returns_none_with_insufficient_data():
    data = _make_ohlc(10)
    assert getOrbDayStrategy(data, verbose=False) is None


def test_none_while_opening_range_incomplete(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 12:15", last_close=101.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is None


def test_emits_true_on_breakout_with_adx_and_volume(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 12:30")
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is True


def test_blocks_long_when_adx_is_low(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 12:30")
    _patch_adx(monkeypatch, value=15.0)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is None


def test_blocks_long_when_range_is_too_narrow(monkeypatch):
    data = _session_orb_frame(
        last_time="2026-08-29 12:30",
        or_high=100.01,
        or_low=100.00,
        last_close=100.05,
        last_open=100.02,
    )
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is None


def test_emits_false_outside_session(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 20:00")
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is False


def test_blocks_long_when_orbp_sma_fails(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 12:30")
    _patch_adx(monkeypatch)
    monkeypatch.setattr(orb_day, "_htf_close_above_sma", lambda *a, **k: False)
    assert getOrbDayStrategy(data, verbose=False, htf_sma_period=50) is None


def test_none_after_already_signaled_this_session(monkeypatch):
    data = _session_orb_frame(
        last_time="2026-08-29 12:45",
        last_close=101.4,
        last_open=101.0,
        last_volume=5000.0,
        prior_break_close=101.0,
    )
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is None


def test_emits_false_when_close_returns_inside_range(monkeypatch):
    data = _session_orb_frame(
        last_time="2026-08-29 12:45",
        last_close=100.0,
        last_open=100.2,
        last_volume=1000.0,
        prior_break_close=101.0,
    )
    _patch_adx(monkeypatch)
    assert getOrbDayStrategy(data, **_buy_kwargs()) is False


def test_snapshot_exposes_yaml_args(monkeypatch):
    data = _session_orb_frame(last_time="2026-08-29 12:30")
    _patch_adx(monkeypatch)
    snapshot = get_orb_day_snapshot(data, htf_sma_period=0, adx_min=25.0)
    assert snapshot is not None
    assert snapshot["strategy"] == "ORB Day"
    assert snapshot["decision"] == "Comprar"
    assert snapshot["or_complete"] is True


def test_registry_defaults_match_function_signature():
    args = default_args_for("orb_day")
    assert args["session_start_utc"] == "12:00"
    assert args["session_end_utc"] == "20:00"
    assert args["opening_range_bars"] == 2
    assert args["adx_min"] == pytest.approx(25.0)
    assert args["volume_mult"] == pytest.approx(1.5)
    assert args["htf_sma_period"] == 50
    assert args["require_bullish_candle"] is True
    assert args["fee_round_trip_pct"] == pytest.approx(0.15)
    assert "verbose" not in args
    assert "stock_data" not in args
