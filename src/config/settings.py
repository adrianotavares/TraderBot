import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from binance.client import Client
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

from Models.StockStartModel import StockStartModel
from strategies.registry import resolve_strategy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "trading.yaml"

CANDLE_INTERVALS = {
    "1m": Client.KLINE_INTERVAL_1MINUTE,
    "3m": Client.KLINE_INTERVAL_3MINUTE,
    "5m": Client.KLINE_INTERVAL_5MINUTE,
    "15m": Client.KLINE_INTERVAL_15MINUTE,
    "30m": Client.KLINE_INTERVAL_30MINUTE,
    "1h": Client.KLINE_INTERVAL_1HOUR,
    "2h": Client.KLINE_INTERVAL_2HOUR,
    "4h": Client.KLINE_INTERVAL_4HOUR,
    "6h": Client.KLINE_INTERVAL_6HOUR,
    "8h": Client.KLINE_INTERVAL_8HOUR,
    "12h": Client.KLINE_INTERVAL_12HOUR,
    "1d": Client.KLINE_INTERVAL_1DAY,
    "3d": Client.KLINE_INTERVAL_3DAY,
    "1w": Client.KLINE_INTERVAL_1WEEK,
}


class TakeProfitLevel(BaseModel):
    at: float
    amount: float


class AssetConfig(BaseModel):
    stock_code: str
    operation_code: str
    traded_quantity: float = 0.0
    traded_percentage: float = 100.0
    breakout_price: float = 0.0

    @field_validator("stock_code", "operation_code")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class StrategyConfig(BaseModel):
    main: str
    main_args: Dict[str, Any] = Field(default_factory=dict)
    fallback: str = "moving_average"
    fallback_args: Dict[str, Any] = Field(default_factory=dict)
    fallback_enabled: bool = True


class RiskConfig(BaseModel):
    acceptable_loss_pct: float = 0.5
    stop_loss_pct: float = 3.5
    take_profit: List[TakeProfitLevel] = Field(default_factory=list)
    max_daily_loss_usdt: float = 100.0
    max_trades_per_day: int = 50
    max_open_orders: int = 5
    max_grid_trades_per_day: int = 20


class TimingConfig(BaseModel):
    candle_period: str = "15m"
    tempo_entre_trades: int = 1800
    delay_entre_ordens: int = 3600

    def candle_interval(self) -> str:
        if self.candle_period not in CANDLE_INTERVALS:
            raise ValueError(
                f"Unknown candle_period '{self.candle_period}'. "
                f"Use one of: {', '.join(sorted(CANDLE_INTERVALS))}"
            )
        return CANDLE_INTERVALS[self.candle_period]


class OperationConfig(BaseModel):
    cancel_orders_on_shutdown: bool = False
    circuit_breaker_errors: int = 5
    circuit_breaker_pause_seconds: int = 300


class AlertsConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class RegimeConfig(BaseModel):
    enabled: bool = True
    adx_period: int = 14
    adx_lateral_threshold: float = 20.0
    adx_trend_threshold: float = 25.0
    rsi_period: int = 14
    rsi_low: float = 40.0
    rsi_high: float = 60.0
    ema_fast: int = 20
    ema_slow: int = 50
    ema_compression_pct: float = 0.5
    range_lookback: int = 60
    min_touches: int = 3
    touch_tolerance_pct: float = 0.3
    min_lateral_signals: int = 3
    min_candles: int = 60
    action_in_lateral: Literal["pause", "grid", "hold_cash"] = "pause"


class GridConfig(BaseModel):
    enabled: bool = True
    levels: int = 6
    capital_pct: float = 30.0
    min_channel_width_pct: float = 1.5
    max_channel_width_pct: float = 8.0
    min_profit_per_level_pct: float = 0.35
    max_open_orders: int = 10


class BreakoutConfig(BaseModel):
    enabled: bool = True
    adx_period: int = 14
    adx_min: float = 25.0
    adx_rising_bars: int = 2
    volume_multiplier: float = 1.5
    volume_sma_period: int = 20
    require_bullish_candle: bool = True
    cooldown_candles: int = 3
    reentry_adx_max: float = 22.0


class TradingSettings(BaseModel):
    environment: Literal["testnet", "mainnet"] = "testnet"
    thread_lock: bool = True
    strategy: StrategyConfig
    risk: RiskConfig
    timing: TimingConfig
    assets: List[AssetConfig]
    operation: OperationConfig = Field(default_factory=OperationConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    grid: GridConfig = Field(default_factory=GridConfig)
    breakout: BreakoutConfig = Field(default_factory=BreakoutConfig)

    @model_validator(mode="after")
    def validate_assets(self):
        if not self.assets:
            raise ValueError("At least one asset must be configured")
        return self

    def build_stock_models(self) -> List[StockStartModel]:
        main_fn = resolve_strategy(self.strategy.main)
        fallback_fn = resolve_strategy(self.strategy.fallback)
        candle = self.timing.candle_interval()
        tp_at = [level.at for level in self.risk.take_profit]
        tp_amount = [level.amount for level in self.risk.take_profit]

        return [
            StockStartModel(
                stockCode=asset.stock_code,
                operationCode=asset.operation_code,
                tradedQuantity=asset.traded_quantity,
                tradedPercentage=asset.traded_percentage,
                candlePeriod=candle,
                fallBackActivated=self.strategy.fallback_enabled,
                mainStrategy=main_fn,
                mainStrategyArgs=dict(self.strategy.main_args),
                fallbackStrategy=fallback_fn,
                fallbackStrategyArgs=dict(self.strategy.fallback_args),
                acceptableLossPercentage=self.risk.acceptable_loss_pct,
                stopLossPercentage=self.risk.stop_loss_pct,
                takeProfitAtPercentage=tp_at,
                takeProfitAmountPercentage=tp_amount,
                tempoEntreTrades=self.timing.tempo_entre_trades,
                delayEntreOrdens=self.timing.delay_entre_ordens,
            )
            for asset in self.assets
        ]


class EnvSettings(BaseModel):
    api_key: str
    secret_key: str
    trading_env: Literal["testnet", "mainnet"] = "testnet"
    log_level: str = "INFO"
    config_path: Path = DEFAULT_CONFIG_PATH


def _load_env() -> EnvSettings:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    secret_key = os.getenv("BINANCE_SECRET_KEY", "").strip()
    trading_env = os.getenv("TRADING_ENV", os.getenv("ENVIRONMENT", "testnet")).strip().lower()
    if trading_env not in ("testnet", "mainnet"):
        raise ValueError("TRADING_ENV must be 'testnet' or 'mainnet'")

    config_path = Path(os.getenv("TRADING_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    return EnvSettings(
        api_key=api_key,
        secret_key=secret_key,
        trading_env=trading_env,  # type: ignore[arg-type]
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        config_path=config_path,
    )


def load_settings(config_path: Optional[Path] = None) -> tuple[TradingSettings, EnvSettings]:
    env = _load_env()
    path = config_path or env.config_path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = TradingSettings.model_validate(raw)

    # .env TRADING_ENV overrides YAML when explicitly set
    if os.getenv("TRADING_ENV") or os.getenv("ENVIRONMENT"):
        settings = settings.model_copy(update={"environment": env.trading_env})

    return settings, env


def save_settings(settings: TradingSettings, config_path: Optional[Path] = None) -> Path:
    env = _load_env()
    path = config_path or env.config_path
    path.parent.mkdir(parents=True, exist_ok=True)

    data = settings.model_dump(mode="python")
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return path


def settings_to_dashboard_dict(settings: TradingSettings) -> dict:
    return settings.model_dump(mode="python")


def apply_dashboard_update(
    settings: TradingSettings, payload: dict
) -> TradingSettings:
    """Merge partial dashboard updates into validated settings."""
    data = settings.model_dump(mode="python")

    if "MAIN_STRATEGY" in payload:
        data["strategy"]["main"] = payload["MAIN_STRATEGY"]
    if "strategy" in payload and isinstance(payload["strategy"], dict):
        data["strategy"].update(payload["strategy"])
    if "FALLBACK_ACTIVATED" in payload:
        data["strategy"]["fallback_enabled"] = bool(payload["FALLBACK_ACTIVATED"])
    if "ACCEPTABLE_LOSS_PERCENTAGE" in payload:
        data["risk"]["acceptable_loss_pct"] = float(payload["ACCEPTABLE_LOSS_PERCENTAGE"])
    if "STOP_LOSS_PERCENTAGE" in payload:
        data["risk"]["stop_loss_pct"] = float(payload["STOP_LOSS_PERCENTAGE"])
    if "TEMPO_ENTRE_TRADES" in payload:
        data["timing"]["tempo_entre_trades"] = int(payload["TEMPO_ENTRE_TRADES"])
    if "DELAY_ENTRE_ORDENS" in payload:
        data["timing"]["delay_entre_ordens"] = int(payload["DELAY_ENTRE_ORDENS"])
    if "stocks_traded_list" in payload:
        assets = []
        for stock in payload["stocks_traded_list"]:
            assets.append(
                {
                    "stock_code": stock.get("stockCode", stock.get("stock_code")),
                    "operation_code": stock.get("operationCode", stock.get("operation_code")),
                    "traded_quantity": float(stock.get("tradedQuantity", stock.get("traded_quantity", 0))),
                    "traded_percentage": float(
                        stock.get("tradedPercentage", stock.get("traded_percentage", 100))
                    ),
                }
            )
        data["assets"] = assets
    if "risk" in payload and isinstance(payload["risk"], dict):
        data["risk"].update(payload["risk"])
    if "timing" in payload and isinstance(payload["timing"], dict):
        data["timing"].update(payload["timing"])
    if "assets" in payload:
        data["assets"] = payload["assets"]

    return TradingSettings.model_validate(data)


UPDATABLE_DASHBOARD_KEYS = {
    "MAIN_STRATEGY",
    "FALLBACK_ACTIVATED",
    "ACCEPTABLE_LOSS_PERCENTAGE",
    "STOP_LOSS_PERCENTAGE",
    "TEMPO_ENTRE_TRADES",
    "DELAY_ENTRE_ORDENS",
    "stocks_traded_list",
    "strategy",
    "risk",
    "timing",
    "assets",
}
