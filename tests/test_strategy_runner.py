from types import SimpleNamespace

from modules.StrategyRunner import StrategyRunner
from strategies.decision import StrategyDecision


def test_from_raw_bool_and_none():
    assert StrategyDecision.from_raw(True).side is True
    assert StrategyDecision.from_raw(False).side is False
    assert StrategyDecision.from_raw(None).side is None
    nested = StrategyDecision.from_raw(True, source="main", reason="buy")
    assert StrategyDecision.from_raw(nested).source == "main"


def test_runner_uses_fallback_when_main_is_none():
    bot = SimpleNamespace(fallback_activated=True)
    decision = StrategyRunner.execute(
        bot,
        main_strategy=lambda **_k: None,
        fallback_strategy=lambda **_k: True,
        stock_data=None,
        verbose=False,
    )
    assert decision.side is True
    assert decision.source == "fallback"
    assert "inconclusive" in decision.reason


def test_runner_skips_fallback_when_disabled():
    bot = SimpleNamespace(fallback_activated=False)
    decision = StrategyRunner.execute(
        bot,
        main_strategy=lambda **_k: None,
        fallback_strategy=lambda **_k: True,
        stock_data=None,
        verbose=False,
    )
    assert decision.side is None
    assert decision.source == "main"
