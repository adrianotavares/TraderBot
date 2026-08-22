from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyDecision:
    """True=buy, False=sell, None=hold. Strategies may still return a raw bool."""

    side: bool | None
    source: str = "main"
    reason: str = ""

    @classmethod
    def from_raw(cls, value, *, source: str = "main", reason: str = "") -> "StrategyDecision":
        if isinstance(value, StrategyDecision):
            return cls(
                side=value.side,
                source=value.source or source,
                reason=value.reason or reason,
            )
        if value is True:
            return cls(True, source=source, reason=reason or "buy")
        if value is False:
            return cls(False, source=source, reason=reason or "sell")
        return cls(None, source=source, reason=reason or "inconclusive")
