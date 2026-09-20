import numpy as np
import pandas as pd

from backtest.regime_gate import (
    VARIANTS,
    GateVariant,
    evaluate_variant,
    gate_signals,
    regime_stats,
    regime_timeline,
)


def _ohlc(prices) -> pd.DataFrame:
    rows = []
    for i, price in enumerate(prices):
        rows.append(
            {
                "close_price": float(price),
                "open_price": float(price) - 0.2,
                "high_price": float(price) + 0.5,
                "low_price": float(price) - 0.5,
                "volume": 1000,
                "open_time": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=4 * i),
            }
        )
    return pd.DataFrame(rows)


def test_timeline_pauses_only_while_warming_up_under_gray_trend():
    frame = _ohlc(np.linspace(100, 160, 120))
    timeline = regime_timeline(frame, GateVariant("gray=trend", "trend", False))
    assert all(row["action"] == "pause" for row in timeline[:60])
    assert all(row["regime"] is None for row in timeline[:60])
    evaluated = timeline[60:]
    assert evaluated
    # Numa alta limpa, nada de lateral: nenhuma barra avaliada deve pausar.
    assert all(row["action"] != "pause" for row in evaluated)


def test_gray_pause_variant_blocks_more_bars_than_gray_trend():
    frame = _ohlc(100 + 3 * np.sin(np.arange(200) / 5))
    paused = {}
    for variant in (
        GateVariant("pause", "pause", False),
        GateVariant("trend", "trend", False),
    ):
        timeline = regime_timeline(frame, variant)
        paused[variant.name] = regime_stats(timeline)["paused"]
    assert paused["pause"] >= paused["trend"]


def test_gate_signals_masks_paused_bars():
    signals = [True, False, True, None]
    timeline = [
        {"regime": "TREND", "action": "atr_trend"},
        {"regime": "GRAY", "action": "pause"},
        {"regime": "GRAY", "action": "pause"},
        {"regime": "TREND", "action": "atr_trend"},
    ]
    assert gate_signals(signals, timeline) == [True, None, None, None]


def test_regime_stats_ignores_warmup_bars():
    timeline = [
        {"regime": None, "action": "pause"},
        {"regime": "TREND", "action": "atr_trend"},
        {"regime": "GRAY", "action": "pause"},
    ]
    stats = regime_stats(timeline)
    assert stats["bars"] == 2
    assert stats["paused"] == 1
    assert stats["paused_pct"] == 50.0
    assert stats["trend_pct"] == 50.0


def test_evaluate_variant_reports_cost_against_ungated_run():
    frame = _ohlc(np.linspace(80, 200, 320))
    result = evaluate_variant(frame, VARIANTS[0])
    assert result["variant"] == VARIANTS[0].name
    names = {row["strategy"] for row in result["rows"]}
    assert {"ema_atr", "atr_trend"} <= names
    for row in result["rows"]:
        assert row["cost_pct"] == row["return_pct"] - row["ungated_return_pct"]
