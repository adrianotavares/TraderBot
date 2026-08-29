import pandas as pd
import pytest

from strategies import vwap_scalp
from strategies.registry import default_args_for
from strategies.vwap_scalp import getVwapScalpStrategy, get_vwap_scalp_snapshot


def _make_ohlc(n: int, *, close: float = 100.0, volume: float = 1000.0) -> pd.DataFrame:
    times = pd.date_range("2026-08-29 13:00", periods=n, freq="5min", tz="UTC")
    rows = []
    for open_time in times:
        price = close
        rows.append(
            {
                "close_price": price,
                "open_price": price,
                "high_price": price + 0.4,
                "low_price": price - 0.4,
                "volume": volume,
                "open_time": open_time,
            }
        )
    return pd.DataFrame(rows)


def _patch_filters(monkeypatch, *, vwap=100.0, atr=2.0, adx=15.0, rsi_value=25.0):
    monkeypatch.setattr(
        vwap_scalp,
        "session_vwap",
        lambda df, *a, **k: pd.Series([vwap] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        vwap_scalp,
        "atr",
        lambda df, window=14: pd.Series([atr] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        vwap_scalp,
        "adx",
        lambda df, period=14: pd.Series([adx] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        vwap_scalp,
        "rsi",
        lambda series, window, last_only: (
            rsi_value
            if last_only
            else pd.Series([rsi_value] * len(series), index=series.index)
        ),
    )


def test_returns_none_with_insufficient_data():
    data = _make_ohlc(10)
    assert getVwapScalpStrategy(data, verbose=False) is None


def test_emits_true_when_stretch_volume_and_filters_pass(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=15.0, rsi_value=25.0)
    assert getVwapScalpStrategy(data, verbose=False) is True


def test_blocks_long_when_adx_is_high(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=40.0, rsi_value=25.0)
    assert getVwapScalpStrategy(data, verbose=False) is None


def test_blocks_long_when_atr_cannot_cover_fees(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=0.02, adx=15.0, rsi_value=25.0)
    assert getVwapScalpStrategy(data, verbose=False) is None


def test_emits_false_when_close_returns_to_vwap(monkeypatch):
    data = _make_ohlc(40, close=100.5)
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=15.0, rsi_value=40.0)
    assert getVwapScalpStrategy(data, verbose=False) is False


def test_emits_false_outside_session(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data["open_time"] = pd.Timestamp("2026-08-29 03:00", tz="UTC")
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=15.0, rsi_value=25.0)
    assert getVwapScalpStrategy(data, verbose=False) is False


def test_rsi_buy_threshold_comes_from_args(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=15.0, rsi_value=25.0)
    assert getVwapScalpStrategy(data, verbose=False, rsi_buy=10.0) is None


def test_empty_session_args_disable_time_filter(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data["open_time"] = pd.Timestamp("2026-08-29 03:00", tz="UTC")
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch, vwap=100.0, atr=2.0, adx=15.0, rsi_value=25.0)
    assert (
        getVwapScalpStrategy(
            data, verbose=False, session_start_utc="", session_end_utc=""
        )
        is True
    )


def test_snapshot_exposes_yaml_args(monkeypatch):
    data = _make_ohlc(40, close=96.0)
    data.loc[data.index[-1], "volume"] = 5000
    _patch_filters(monkeypatch)
    snapshot = get_vwap_scalp_snapshot(data, adx_max=18.0, fee_round_trip_pct=0.2)
    assert snapshot is not None
    assert snapshot["strategy"] == "VWAP Scalp"
    assert snapshot["decision"] == "Comprar"


def test_registry_defaults_match_function_signature():
    args = default_args_for("vwap_scalp")
    assert args["session_start_utc"] == "12:00"
    assert args["session_end_utc"] == "20:00"
    assert args["atr_period"] == 14
    assert args["fee_round_trip_pct"] == pytest.approx(0.15)
    assert "verbose" not in args
    assert "stock_data" not in args
