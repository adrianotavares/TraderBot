"""
Mede o custo do roteador de regime: quantos ciclos ele pausa e quanto isso
tira do retorno de cada estrategia.

O gate real do `TradingEngine` ignora a estrategia no ciclo pausado, mas SL/TP
continuam valendo. Aqui isso e reproduzido mascarando o sinal para None nas
barras pausadas e deixando o overlay de risco do runner ativo.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.signals import signals_for
from backtest.confirm import STRATEGIES, run_strategy_window
from services.regime_detector import RegimeDetector
from services.regime_router import resolve_regime_action


@dataclass(frozen=True)
class GateVariant:
    name: str
    action_in_gray: str
    require_range_bound_for_lateral: bool


VARIANTS = (
    # "antigo" e o comportamento anterior a este branch, mantido para comparacao.
    GateVariant("antigo (GRAY pausa)", "pause", False),
    GateVariant("atual (GRAY -> tendencia)", "trend", False),
    GateVariant("canal exigido p/ lateral", "trend", True),
)


def _detector(variant: GateVariant, **overrides) -> RegimeDetector:
    kwargs = {
        "enabled": True,
        "min_candles": 60,
        "action_in_lateral": "grid",
        "action_in_gray": variant.action_in_gray,
        "require_range_bound_for_lateral": variant.require_range_bound_for_lateral,
    }
    kwargs.update(overrides)
    return RegimeDetector(**kwargs)


def regime_timeline(frame: pd.DataFrame, variant: GateVariant) -> list[dict]:
    """Regime e acao por barra, do jeito que o engine resolveria."""
    detector = _detector(variant)
    timeline: list[dict] = []
    for index in range(len(frame)):
        if index < detector.min_candles:
            timeline.append({"regime": None, "action": "pause"})
            continue
        regime = detector.evaluate(frame.iloc[: index + 1])
        action = resolve_regime_action(
            regime,
            None,
            regime_detector=detector,
            # Sem grid no backtest: o canal congelado e as ordens abertas do
            # grid nao existem aqui, entao lateral virar grid seria ficcao.
            grid_manager=None,
            breakout_detector=None,
            breakout_cooldown_candles=0,
        )
        timeline.append({"regime": regime.regime, "action": action})
    return timeline


def gate_signals(signals: list, timeline: list[dict]) -> list:
    return [
        None if timeline[index]["action"] == "pause" else signals[index]
        for index in range(len(signals))
    ]


def regime_stats(timeline: list[dict]) -> dict:
    evaluated = [row for row in timeline if row["regime"] is not None]
    total = len(evaluated) or 1
    paused = sum(1 for row in evaluated if row["action"] == "pause")
    counts = {"TREND": 0, "LATERAL": 0, "GRAY": 0}
    for row in evaluated:
        counts[row["regime"]] = counts.get(row["regime"], 0) + 1
    return {
        "bars": len(evaluated),
        "paused": paused,
        "paused_pct": paused / total * 100,
        "trend_pct": counts["TREND"] / total * 100,
        "lateral_pct": counts["LATERAL"] / total * 100,
        "gray_pct": counts["GRAY"] / total * 100,
    }


def evaluate_variant(
    frame: pd.DataFrame,
    variant: GateVariant,
    *,
    strategies=STRATEGIES,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
) -> dict:
    timeline = regime_timeline(frame, variant)
    stats = regime_stats(timeline)
    rows = []
    for name, fn, kwargs in strategies:
        raw = signals_for(name, frame, kwargs)
        if raw is None:
            continue
        gated = gate_signals(raw, timeline)
        result = run_strategy_window(
            frame,
            strategy_name=name,
            strategy_fn=fn,
            strategy_kwargs=kwargs,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        gated_result = run_strategy_window(
            frame,
            strategy_name=name,
            strategy_fn=fn,
            strategy_kwargs=kwargs,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            signals=gated,
        )
        rows.append(
            {
                "strategy": name,
                "ungated_return_pct": result["profit_percentage"],
                "ungated_trades": result["trades"],
                "return_pct": gated_result["profit_percentage"],
                "trades": gated_result["trades"],
                "max_drawdown_pct": gated_result["max_drawdown_pct"],
                "cost_pct": gated_result["profit_percentage"]
                - result["profit_percentage"],
            }
        )
    return {"variant": variant.name, "stats": stats, "rows": rows}
