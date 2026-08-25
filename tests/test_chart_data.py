import numpy as np
import pandas as pd
import pytest

from persistence.state_store import StateStore
from services.chart_data import (
    build_chart_payload,
    candle_period_seconds,
    candle_times,
    candles_to_series,
    compute_levels,
    is_closed,
    order_markers,
    parse_iso_seconds,
    regime_series,
    snap_to_candle,
    trailing_stop_series,
)
from services.regime_detector import RegimeDetector

PERIOD = 4 * 3600
FIRST_OPEN = 1_700_000_000 - (1_700_000_000 % PERIOD)


def _frame(n: int = 80, base: float = 100.0, amplitude: float = 2.0, step: float = 0.0):
    """Candles on a 4h grid, localized like MarketDataService.normalize_klines."""
    rows = []
    for i in range(n):
        price = base + amplitude * np.sin(i / 4) + step * i
        rows.append(
            {
                "close_price": price,
                "open_time": FIRST_OPEN + i * PERIOD,
                "open_price": price - 0.2,
                "high_price": price + 0.5,
                "low_price": price - 0.5,
                "volume": 1000.0,
            }
        )
    frame = pd.DataFrame(rows)
    frame["open_time"] = (
        pd.to_datetime(frame["open_time"], unit="s")
        .dt.tz_localize("UTC")
        .dt.tz_convert("America/Sao_Paulo")
    )
    return frame


class _Risk:
    def __init__(self, take_profit=None, stop_loss_pct=2.0, acceptable_loss_pct=1.5):
        self.take_profit = take_profit if take_profit is not None else [_Level(7.0, 100.0)]
        self.stop_loss_pct = stop_loss_pct
        self.acceptable_loss_pct = acceptable_loss_pct


class _Level:
    def __init__(self, at, amount):
        self.at = at
        self.amount = amount


@pytest.fixture
def detector():
    return RegimeDetector(enabled=True, min_candles=60, range_lookback=60)


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "chart.db")


# --- period parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "period,expected",
    [("1m", 60), ("15m", 900), ("1h", 3600), ("4h", 14400), ("1d", 86400), ("1w", 604800)],
)
def test_candle_period_seconds(period, expected):
    assert candle_period_seconds(period) == expected


@pytest.mark.parametrize("period", ["", "h", "4x", "0h", "-1h", "abc"])
def test_candle_period_seconds_rejects_garbage(period):
    with pytest.raises(ValueError):
        candle_period_seconds(period)


# --- candle conversion ----------------------------------------------------


def test_candle_times_are_utc_epoch_seconds_despite_sao_paulo_column():
    frame = _frame(3)
    assert candle_times(frame) == [FIRST_OPEN, FIRST_OPEN + PERIOD, FIRST_OPEN + 2 * PERIOD]


def test_candles_to_series_shape():
    series = candles_to_series(_frame(3))
    assert [candle["time"] for candle in series] == candle_times(_frame(3))
    assert set(series[0]) == {"time", "open", "high", "low", "close"}
    assert series[0]["high"] >= series[0]["close"] >= series[0]["low"]


def test_candles_to_series_skips_incomplete_rows():
    frame = _frame(4)
    frame.loc[2, "high_price"] = np.nan
    series = candles_to_series(frame)
    assert len(series) == 3
    assert FIRST_OPEN + 2 * PERIOD not in [candle["time"] for candle in series]


def test_candles_to_series_handles_empty():
    assert candles_to_series(pd.DataFrame()) == []
    assert candle_times(pd.DataFrame()) == []


# --- snapping and closure -------------------------------------------------


def test_snap_to_candle_finds_containing_candle():
    times = [0, PERIOD, 2 * PERIOD]
    assert snap_to_candle(PERIOD, times) == PERIOD
    assert snap_to_candle(PERIOD + 1, times) == PERIOD
    assert snap_to_candle(2 * PERIOD - 1, times) == PERIOD


def test_snap_to_candle_drops_timestamps_before_window():
    assert snap_to_candle(PERIOD - 1, [PERIOD, 2 * PERIOD]) is None
    assert snap_to_candle(10, []) is None


def test_is_closed():
    assert is_closed(0, PERIOD, now=PERIOD) is True
    assert is_closed(0, PERIOD, now=PERIOD - 1) is False


def test_parse_iso_seconds_accepts_utc_forms():
    assert parse_iso_seconds("1970-01-01T00:00:00+00:00") == 0
    assert parse_iso_seconds("1970-01-01T00:00:00Z") == 0
    assert parse_iso_seconds("1970-01-01T00:00:00") == 0  # naive is treated as UTC
    assert parse_iso_seconds("") is None
    assert parse_iso_seconds("not-a-date") is None


# --- regime ---------------------------------------------------------------


def test_regime_series_covers_closed_candles(detector, store):
    frame = _frame(80)
    times = candle_times(frame)
    window = times[-10:]
    now = times[-1] + PERIOD  # every candle closed
    series, current = regime_series(
        frame,
        window,
        detector=detector,
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
        now=now,
    )
    assert [row["time"] for row in series] == window
    assert all(row["regime"] in {"TREND", "LATERAL", "GRAY"} for row in series)
    assert current["provisional"] is False


def test_regime_series_persists_backfill_and_reuses_it(detector, store):
    frame = _frame(80)
    times = candle_times(frame)
    window = times[-5:]
    now = times[-1] + PERIOD

    regime_series(
        frame,
        window,
        detector=detector,
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
        now=now,
    )
    stored = store.list_regime("BTCUSDT")
    assert [row["candle_time"] for row in stored] == window
    assert {row["source"] for row in stored} == {"backfill"}
    assert store.missing_regime_candles("BTCUSDT", window) == []


def test_regime_series_prefers_live_rows_over_recomputing(detector, store):
    frame = _frame(80)
    times = candle_times(frame)
    window = times[-3:]
    now = times[-1] + PERIOD

    store.save_regime("BTCUSDT", window[0], "LATERAL", score=4, source="live")
    series, _ = regime_series(
        frame,
        window,
        detector=detector,
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
        now=now,
    )
    assert series[0]["regime"] == "LATERAL"
    assert series[0]["score"] == 4


def test_regime_series_does_not_persist_the_forming_candle(detector, store):
    frame = _frame(80)
    times = candle_times(frame)
    window = times[-4:]
    now = times[-1] + 60  # last candle still forming

    series, current = regime_series(
        frame,
        window,
        detector=detector,
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
        now=now,
    )
    assert [row["time"] for row in series] == window
    assert current["provisional"] is True
    assert window[-1] not in [row["candle_time"] for row in store.list_regime("BTCUSDT")]


def test_regime_series_disabled_detector_returns_nothing(store):
    frame = _frame(80)
    series, current = regime_series(
        frame,
        candle_times(frame)[-5:],
        detector=RegimeDetector(enabled=False),
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
    )
    assert series == []
    assert current is None


def test_regime_series_bounds_backfill_per_request(detector, store):
    """A cold window must not block one request with the whole recompute."""
    frame = _frame(120)
    times = candle_times(frame)
    window = times[-40:]
    now = times[-1] + PERIOD

    series, _ = regime_series(
        frame,
        window,
        detector=detector,
        period_seconds=PERIOD,
        store=store,
        operation_code="BTCUSDT",
        now=now,
        max_backfill=10,
    )
    # Newest candles fill first, so the right edge of the ribbon is never empty.
    assert [row["time"] for row in series] == window[-10:]


def test_regime_series_backfill_completes_across_requests(detector, store):
    frame = _frame(120)
    times = candle_times(frame)
    window = times[-30:]
    now = times[-1] + PERIOD

    for _ in range(3):
        series, _ = regime_series(
            frame,
            window,
            detector=detector,
            period_seconds=PERIOD,
            store=store,
            operation_code="BTCUSDT",
            now=now,
            max_backfill=10,
        )
    assert [row["time"] for row in series] == window
    assert store.missing_regime_candles("BTCUSDT", window) == []


def test_regime_series_works_without_a_store(detector):
    frame = _frame(80)
    times = candle_times(frame)
    series, _ = regime_series(
        frame,
        times[-5:],
        detector=detector,
        period_seconds=PERIOD,
        now=times[-1] + PERIOD,
    )
    assert len(series) == 5


# --- trailing stop --------------------------------------------------------


def test_trailing_stop_series_only_covers_the_window():
    frame = _frame(80, step=0.5)
    window = candle_times(frame)[-10:]
    series = trailing_stop_series(frame, window, atr_period=14, atr_multiplier=2.5)
    assert [row["time"] for row in series] == window
    assert all(row["value"] > 0 for row in series)


def test_trailing_stop_series_skips_warmup_nans():
    frame = _frame(20)
    window = candle_times(frame)
    series = trailing_stop_series(frame, window, atr_period=14, atr_multiplier=2.5)
    assert len(series) < len(window)


def test_trailing_stop_series_handles_empty():
    assert trailing_stop_series(pd.DataFrame(), []) == []


# --- levels ---------------------------------------------------------------


def test_compute_levels_derives_tp_and_sl_from_entry():
    levels = compute_levels(
        entry_price=100.0,
        position_open=True,
        stop_loss_pct=2.0,
        acceptable_loss_pct=1.5,
        take_profit=[_Level(7.0, 100.0)],
    )
    assert levels["entry"] == 100.0
    assert levels["take_profit"]["price"] == 107.0
    assert levels["take_profit"]["pct"] == 7.0
    assert levels["stop_loss"]["price"] == 98.0
    assert levels["min_sell"]["price"] == 98.5


def test_compute_levels_returns_none_when_flat():
    """last_buy_price survives a sell, so a flat asset must show no levels."""
    assert (
        compute_levels(
            entry_price=100.0,
            position_open=False,
            stop_loss_pct=2.0,
            acceptable_loss_pct=1.5,
            take_profit=[_Level(7.0, 100.0)],
        )
        is None
    )


def test_compute_levels_returns_none_without_entry_price():
    assert (
        compute_levels(
            entry_price=0.0,
            position_open=True,
            stop_loss_pct=2.0,
            acceptable_loss_pct=1.5,
            take_profit=[_Level(7.0, 100.0)],
        )
        is None
    )


def test_compute_levels_follows_the_take_profit_ladder():
    take_profit = [_Level(3.0, 50.0), _Level(7.0, 100.0)]
    first = compute_levels(
        entry_price=100.0,
        position_open=True,
        stop_loss_pct=2.0,
        acceptable_loss_pct=1.5,
        take_profit=take_profit,
        take_profit_index=0,
    )
    second = compute_levels(
        entry_price=100.0,
        position_open=True,
        stop_loss_pct=2.0,
        acceptable_loss_pct=1.5,
        take_profit=take_profit,
        take_profit_index=1,
    )
    assert first["take_profit"]["price"] == 103.0
    assert first["take_profit"]["total"] == 2
    assert second["take_profit"]["price"] == 107.0


def test_compute_levels_exhausted_ladder_has_no_take_profit():
    levels = compute_levels(
        entry_price=100.0,
        position_open=True,
        stop_loss_pct=2.0,
        acceptable_loss_pct=1.5,
        take_profit=[_Level(7.0, 100.0)],
        take_profit_index=1,
    )
    assert levels["take_profit"] is None
    assert levels["stop_loss"]["price"] == 98.0


# --- markers --------------------------------------------------------------


def test_order_markers_snap_to_candles_and_filter_by_symbol():
    window = [FIRST_OPEN, FIRST_OPEN + PERIOD]
    orders = [
        {
            "operation_code": "BTCUSDT",
            "side": "BUY",
            "price": 100.0,
            "quantity": 1.0,
            "created_at": "1970-01-01T00:00:00+00:00",
        },
        {
            "operation_code": "ETHUSDT",
            "side": "BUY",
            "price": 200.0,
            "quantity": 2.0,
            "created_at": "1970-01-01T00:00:00+00:00",
        },
    ]
    # Put the BTC order inside the second candle.
    orders[0]["created_at"] = (
        pd.Timestamp(FIRST_OPEN + PERIOD + 5, unit="s", tz="UTC").isoformat()
    )
    markers = order_markers(orders, "BTCUSDT", window)
    assert len(markers) == 1
    assert markers[0]["time"] == FIRST_OPEN + PERIOD
    assert markers[0]["side"] == "BUY"


def test_order_markers_drop_orders_older_than_the_window():
    window = [FIRST_OPEN, FIRST_OPEN + PERIOD]
    orders = [
        {
            "operation_code": "BTCUSDT",
            "side": "SELL",
            "created_at": pd.Timestamp(FIRST_OPEN - 10, unit="s", tz="UTC").isoformat(),
        }
    ]
    assert order_markers(orders, "BTCUSDT", window) == []


def test_order_markers_are_sorted_ascending():
    window = candle_times(_frame(5))
    orders = [
        {
            "operation_code": "BTCUSDT",
            "side": "SELL",
            "created_at": pd.Timestamp(window[3] + 1, unit="s", tz="UTC").isoformat(),
        },
        {
            "operation_code": "BTCUSDT",
            "side": "BUY",
            "created_at": pd.Timestamp(window[1] + 1, unit="s", tz="UTC").isoformat(),
        },
    ]
    markers = order_markers(orders, "BTCUSDT", window)
    assert [marker["time"] for marker in markers] == [window[1], window[3]]


def test_order_markers_ignore_non_trade_sides():
    window = candle_times(_frame(3))
    orders = [
        {
            "operation_code": "BTCUSDT",
            "side": "",
            "created_at": pd.Timestamp(window[1], unit="s", tz="UTC").isoformat(),
        }
    ]
    assert order_markers(orders, "BTCUSDT", window) == []


# --- full payload ---------------------------------------------------------


def test_build_chart_payload_assembles_everything(detector, store):
    frame = _frame(80)
    times = candle_times(frame)
    payload = build_chart_payload(
        frame,
        stock_code="BTC",
        operation_code="BTCUSDT",
        candle_period="4h",
        risk=_Risk(),
        position={"open": True, "quantity": 0.5, "entry_price": 100.0},
        detector=detector,
        store=store,
        strategy_main="atr_trend",
        strategy_args={"atr_period": 14, "atr_multiplier": 2.5},
        bars=20,
        now=times[-1] + 60,
    )
    assert payload["stock_code"] == "BTC"
    assert len(payload["candles"]) == 20
    assert payload["candles"][-1]["time"] == times[-1]
    assert len(payload["regime"]) == 20
    assert payload["current_regime"]["provisional"] is True
    assert payload["trailing_stop"]
    assert payload["levels"]["take_profit"]["price"] == 107.0
    assert payload["error"] is None


def test_build_chart_payload_without_position_has_no_levels(detector, store):
    frame = _frame(80)
    payload = build_chart_payload(
        frame,
        stock_code="BTC",
        operation_code="BTCUSDT",
        candle_period="4h",
        risk=_Risk(),
        position={"open": False, "entry_price": 100.0},
        detector=detector,
        store=store,
        bars=10,
        now=candle_times(frame)[-1] + PERIOD,
    )
    assert payload["levels"] is None


def test_build_chart_payload_omits_trailing_stop_for_other_strategies(detector, store):
    frame = _frame(80)
    payload = build_chart_payload(
        frame,
        stock_code="BTC",
        operation_code="BTCUSDT",
        candle_period="4h",
        risk=_Risk(),
        detector=detector,
        store=store,
        strategy_main="moving_average",
        bars=10,
        now=candle_times(frame)[-1] + PERIOD,
    )
    assert payload["trailing_stop"] == []
