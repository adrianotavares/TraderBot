import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config.settings import TradingSettings, load_settings
from modules.logging_setup import log_event


@dataclass
class ReloadEvent:
    settings: TradingSettings
    soft: list[str] = field(default_factory=list)
    hard: list[str] = field(default_factory=list)
    generation: int = 0


def _asset_identity(settings: TradingSettings) -> list[tuple[str, str]]:
    return [(asset.stock_code, asset.operation_code) for asset in settings.assets]


def classify_settings_delta(
    old: TradingSettings, new: TradingSettings
) -> tuple[list[str], list[str]]:
    """Return (hard_fields, soft_fields) that differ."""
    hard: list[str] = []
    soft: list[str] = []

    if old.environment != new.environment:
        hard.append("environment")
    if old.strategy.main != new.strategy.main:
        hard.append("strategy.main")
    if _asset_identity(old) != _asset_identity(new):
        hard.append("assets")
    if old.timing.candle_period != new.timing.candle_period:
        hard.append("timing.candle_period")

    if old.risk != new.risk:
        soft.append("risk")
    if old.alerts != new.alerts:
        soft.append("alerts")
    if old.regime != new.regime:
        soft.append("regime")
    if old.grid != new.grid:
        soft.append("grid")
    if old.breakout != new.breakout:
        soft.append("breakout")
    if old.operation != new.operation:
        soft.append("operation")
    if old.thread_lock != new.thread_lock:
        soft.append("thread_lock")
    if (
        old.timing.tempo_entre_trades != new.timing.tempo_entre_trades
        or old.timing.delay_entre_ordens != new.timing.delay_entre_ordens
    ):
        soft.append("timing")
    if (
        old.strategy.fallback != new.strategy.fallback
        or old.strategy.fallback_enabled != new.strategy.fallback_enabled
        or old.strategy.main_args != new.strategy.main_args
        or old.strategy.fallback_args != new.strategy.fallback_args
    ):
        soft.append("strategy.args")

    old_by_op = {asset.operation_code: asset for asset in old.assets}
    for asset in new.assets:
        previous = old_by_op.get(asset.operation_code)
        if previous is None:
            continue
        if (
            previous.traded_quantity != asset.traded_quantity
            or previous.traded_percentage != asset.traded_percentage
            or previous.breakout_price != asset.breakout_price
        ):
            if "asset_sizing" not in soft:
                soft.append("asset_sizing")
            break

    return hard, soft


class SettingsWatch:
    """Process-wide YAML watcher. Soft fields apply on the next cycle."""

    def __init__(self, path: Path, settings: TradingSettings):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._settings = settings
        self._mtime = self._stat_mtime()
        self._force = False
        self.generation = 0

    def _stat_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    @property
    def settings(self) -> TradingSettings:
        with self._lock:
            return self._settings

    def request_reload(self) -> None:
        with self._lock:
            self._force = True

    def snapshot(self) -> tuple[int, TradingSettings]:
        with self._lock:
            return self.generation, self._settings

    def poll(self) -> Optional[ReloadEvent]:
        with self._lock:
            mtime = self._stat_mtime()
            force = self._force
            self._force = False
            if not force and mtime == self._mtime:
                return None
            try:
                loaded, _env = load_settings(self.path)
            except Exception as exc:
                log_event(
                    logging.ERROR,
                    f"Config reload failed: {exc}",
                    event="config_reload_failed",
                    path=str(self.path),
                )
                return None
            hard, soft = classify_settings_delta(self._settings, loaded)
            self._settings = loaded
            self._mtime = mtime
            self.generation += 1
            event = ReloadEvent(
                settings=loaded,
                soft=soft,
                hard=hard,
                generation=self.generation,
            )
            if soft:
                log_event(
                    logging.INFO,
                    "Config reloaded",
                    event="config_reloaded",
                    fields=soft,
                    generation=self.generation,
                )
            if hard:
                log_event(
                    logging.WARNING,
                    "Config requires restart",
                    event="config_requires_restart",
                    fields=hard,
                    generation=self.generation,
                )
            return event
