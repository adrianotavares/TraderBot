import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, get_args, get_origin

import yaml
from binance.client import Client
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from Models.StockStartModel import StockStartModel
from strategies.registry import list_strategies, resolve_strategy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "trading.yaml"
CONFIG_HISTORY_DIR = PROJECT_ROOT / "config" / "history"
CONFIG_HISTORY_KEEP = 20

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
    at: float = Field(
        description="Lucro acumulado (%) que dispara a realização parcial", gt=0
    )
    amount: float = Field(
        description="Percentual da posição vendido neste nível", gt=0, le=100
    )


class AssetConfig(BaseModel):
    stock_code: str = Field(description="Símbolo do ativo, ex.: BTC")
    operation_code: str = Field(description="Par negociado na Binance, ex.: BTCUSDT")
    traded_quantity: float = Field(
        default=0.0,
        ge=0,
        description="Quantidade fixa por ordem. Use 0 para dimensionar por percentual",
    )
    traded_percentage: float = Field(
        default=100.0,
        ge=0,
        le=100,
        description="Percentual do saldo disponível alocado a este ativo",
    )
    breakout_price: float = Field(
        default=0.0,
        ge=0,
        description="Preço de rompimento que reativa a estratégia de tendência",
    )

    @field_validator("stock_code", "operation_code")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class StrategyConfig(BaseModel):
    main: str = Field(description="Estratégia principal")
    main_args: Dict[str, Any] = Field(
        default_factory=dict, description="Parâmetros da estratégia principal"
    )
    fallback: str = Field(
        default="moving_average",
        description="Estratégia usada quando a principal não produz decisão",
    )
    fallback_args: Dict[str, Any] = Field(
        default_factory=dict, description="Parâmetros da estratégia de fallback"
    )
    fallback_enabled: bool = Field(
        default=True, description="Habilita o uso da estratégia de fallback"
    )

    @field_validator("main", "fallback")
    @classmethod
    def known_strategy(cls, value: str) -> str:
        resolve_strategy(value)
        return value


class RiskConfig(BaseModel):
    acceptable_loss_pct: float = Field(
        default=0.5,
        ge=0,
        le=100,
        description="Perda tolerada (%) antes de considerar a saída da posição",
    )
    stop_loss_pct: float = Field(
        default=3.5,
        ge=0,
        le=100,
        description="Stop loss (%) medido a partir do preço de compra",
    )
    take_profit: List[TakeProfitLevel] = Field(
        default_factory=list, description="Escada de realização parcial de lucro"
    )
    max_daily_loss_usdt: float = Field(
        default=100.0,
        ge=0,
        description="Perda diária máxima em USDT antes de bloquear novas ordens",
    )
    max_trades_per_day: int = Field(
        default=50, ge=0, description="Número máximo de trades por dia"
    )
    max_open_orders: int = Field(
        default=5, ge=0, description="Ordens abertas simultâneas permitidas"
    )
    max_grid_trades_per_day: int = Field(
        default=20, ge=0, description="Trades de grid permitidos por dia"
    )


class TimingConfig(BaseModel):
    candle_period: str = Field(
        default="15m", description="Intervalo dos candles analisados"
    )
    tempo_entre_trades: int = Field(
        default=1800, ge=1, description="Segundos entre ciclos de análise"
    )
    delay_entre_ordens: int = Field(
        default=3600, ge=0, description="Segundos mínimos entre ordens do mesmo ativo"
    )

    @field_validator("candle_period")
    @classmethod
    def known_candle_period(cls, value: str) -> str:
        if value not in CANDLE_INTERVALS:
            raise ValueError(
                f"Unknown candle_period '{value}'. "
                f"Use one of: {', '.join(sorted(CANDLE_INTERVALS))}"
            )
        return value

    def candle_interval(self) -> str:
        return CANDLE_INTERVALS[self.candle_period]


class OperationConfig(BaseModel):
    cancel_orders_on_shutdown: bool = Field(
        default=False, description="Cancela ordens abertas ao encerrar o bot"
    )
    circuit_breaker_errors: int = Field(
        default=5, ge=1, description="Erros consecutivos que acionam a pausa protetiva"
    )
    circuit_breaker_pause_seconds: int = Field(
        default=300, ge=0, description="Duração da pausa protetiva em segundos"
    )


class AlertsConfig(BaseModel):
    enabled: bool = Field(default=False, description="Envia alertas para o webhook")
    webhook_url: str = Field(default="", description="URL do webhook de alertas")


class RegimeConfig(BaseModel):
    enabled: bool = Field(
        default=True, description="Habilita a detecção de regime de mercado"
    )
    adx_period: int = Field(default=14, ge=2, description="Período do ADX")
    adx_lateral_threshold: float = Field(
        default=20.0, ge=0, description="ADX abaixo deste valor indica mercado lateral"
    )
    adx_trend_threshold: float = Field(
        default=25.0, ge=0, description="ADX acima deste valor indica tendência"
    )
    rsi_period: int = Field(default=14, ge=2, description="Período do RSI")
    rsi_low: float = Field(
        default=40.0, ge=0, le=100, description="Piso da faixa neutra do RSI"
    )
    rsi_high: float = Field(
        default=60.0, ge=0, le=100, description="Teto da faixa neutra do RSI"
    )
    ema_fast: int = Field(default=20, ge=1, description="Período da EMA rápida")
    ema_slow: int = Field(default=50, ge=1, description="Período da EMA lenta")
    ema_compression_pct: float = Field(
        default=0.5,
        ge=0,
        description="Distância máxima (%) entre EMAs para considerar compressão",
    )
    range_lookback: int = Field(
        default=60, ge=2, description="Candles analisados na busca de suporte e resistência"
    )
    min_touches: int = Field(
        default=3, ge=1, description="Toques mínimos para validar o canal lateral"
    )
    touch_tolerance_pct: float = Field(
        default=0.3, ge=0, description="Tolerância (%) para considerar um toque no canal"
    )
    min_lateral_signals: int = Field(
        default=3, ge=1, description="Sinais mínimos para classificar como lateral"
    )
    min_candles: int = Field(
        default=60, ge=2, description="Candles mínimos para rodar a detecção"
    )
    action_in_lateral: Literal["pause", "grid", "hold_cash"] = Field(
        default="pause", description="Ação adotada quando o mercado está lateral"
    )

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.rsi_low >= self.rsi_high:
            raise ValueError("rsi_low must be lower than rsi_high")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be lower than ema_slow")
        if self.adx_lateral_threshold > self.adx_trend_threshold:
            raise ValueError(
                "adx_lateral_threshold must not exceed adx_trend_threshold"
            )
        return self


class GridConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilita o grid spot")
    levels: int = Field(default=6, ge=2, description="Número de níveis do grid")
    capital_pct: float = Field(
        default=30.0, ge=0, le=100, description="Percentual do saldo USDT alocado ao grid"
    )
    min_channel_width_pct: float = Field(
        default=1.5, ge=0, description="Largura mínima (%) do canal para ativar o grid"
    )
    max_channel_width_pct: float = Field(
        default=8.0, ge=0, description="Largura máxima (%) do canal para ativar o grid"
    )
    min_profit_per_level_pct: float = Field(
        default=0.35, ge=0, description="Lucro mínimo (%) exigido por nível"
    )
    max_open_orders: int = Field(
        default=10, ge=1, description="Ordens abertas simultâneas do grid"
    )

    @model_validator(mode="after")
    def validate_channel(self):
        if self.min_channel_width_pct > self.max_channel_width_pct:
            raise ValueError(
                "min_channel_width_pct must not exceed max_channel_width_pct"
            )
        return self


class BreakoutConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilita a detecção de rompimento")
    adx_period: int = Field(default=14, ge=2, description="Período do ADX")
    adx_min: float = Field(
        default=25.0, ge=0, description="ADX mínimo para confirmar o rompimento"
    )
    adx_rising_bars: int = Field(
        default=2, ge=1, description="Candles consecutivos com ADX em alta"
    )
    volume_multiplier: float = Field(
        default=1.5, ge=0, description="Volume exigido como múltiplo da média"
    )
    volume_sma_period: int = Field(
        default=20, ge=2, description="Período da média de volume"
    )
    require_bullish_candle: bool = Field(
        default=True, description="Exige candle de alta para confirmar o rompimento"
    )
    cooldown_candles: int = Field(
        default=3, ge=0, description="Candles de espera antes de voltar ao grid"
    )
    reentry_adx_max: float = Field(
        default=22.0, ge=0, description="ADX máximo para permitir o retorno ao grid"
    )


class TradingSettings(BaseModel):
    environment: Literal["testnet", "mainnet"] = Field(
        default="testnet", description="Ambiente da Binance usado para operar"
    )
    thread_lock: bool = Field(
        default=True, description="Serializa os ciclos das threads de cada ativo"
    )
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
        duplicates = {
            asset.operation_code
            for asset in self.assets
            if [a.operation_code for a in self.assets].count(asset.operation_code) > 1
        }
        if duplicates:
            raise ValueError(
                f"Duplicated operation_code: {', '.join(sorted(duplicates))}"
            )
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


def env_file_path() -> Path:
    """Path of the .env to load. Overridable so tests and multi-env setups
    do not depend on the repository root file."""
    raw = os.getenv("TRADERBOT_ENV_FILE", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / ".env"


def _load_env() -> EnvSettings:
    load_dotenv(env_file_path())
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


def environment_override() -> Optional[str]:
    """Return the .env value that shadows YAML `environment`, when present."""
    raw = os.getenv("TRADING_ENV") or os.getenv("ENVIRONMENT")
    if not raw:
        return None
    value = raw.strip().lower()
    return value if value in ("testnet", "mainnet") else None


def yaml_environment(config_path: Optional[Path] = None) -> Optional[str]:
    """Read `environment` straight from the YAML, ignoring the .env override."""
    env = _load_env()
    path = config_path or env.config_path
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    value = raw.get("environment")
    return str(value) if value else None


def load_settings(config_path: Optional[Path] = None) -> tuple[TradingSettings, EnvSettings]:
    env = _load_env()
    path = config_path or env.config_path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = TradingSettings.model_validate(raw)

    # .env TRADING_ENV overrides YAML when explicitly set
    if environment_override():
        settings = settings.model_copy(update={"environment": env.trading_env})

    return settings, env


def backup_config(
    config_path: Optional[Path] = None,
    history_dir: Optional[Path] = None,
    keep: Optional[int] = None,
) -> Optional[Path]:
    """Copy the current YAML byte-for-byte before it is overwritten.

    Copying the raw file (instead of re-dumping the model) is what preserves
    comments and commented-out blocks that `yaml.safe_dump` would discard.
    """
    env = _load_env()
    source = config_path or env.config_path
    if not source.exists():
        return None

    target_dir = history_dir or CONFIG_HISTORY_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = target_dir / f"{source.stem}-{stamp}.yaml"
    shutil.copy2(source, target)

    limit = CONFIG_HISTORY_KEEP if keep is None else keep
    if limit > 0:
        for stale in list_config_backup_paths(target_dir)[limit:]:
            stale.unlink(missing_ok=True)
    return target


def list_config_backup_paths(history_dir: Optional[Path] = None) -> List[Path]:
    target_dir = history_dir or CONFIG_HISTORY_DIR
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.yaml"), key=lambda p: p.name, reverse=True)


def list_config_backups(history_dir: Optional[Path] = None) -> List[dict]:
    entries = []
    for path in list_config_backup_paths(history_dir):
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "saved_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return entries


def _resolve_backup(name: str, history_dir: Optional[Path] = None) -> Path:
    target_dir = history_dir or CONFIG_HISTORY_DIR
    candidate = (target_dir / name).resolve()
    if candidate.parent != target_dir.resolve() or not candidate.is_file():
        raise ValueError(f"Unknown config backup: {name}")
    return candidate


def restore_config_backup(
    name: str,
    config_path: Optional[Path] = None,
    history_dir: Optional[Path] = None,
) -> TradingSettings:
    """Validate a backup and write it back as the active config."""
    source = _resolve_backup(name, history_dir)
    content = source.read_text(encoding="utf-8")
    settings = TradingSettings.model_validate(yaml.safe_load(content) or {})

    env = _load_env()
    target = config_path or env.config_path
    backup_config(target, history_dir)
    _atomic_write(target, content)
    return settings


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def save_settings(
    settings: TradingSettings,
    config_path: Optional[Path] = None,
    backup: bool = True,
    history_dir: Optional[Path] = None,
) -> Path:
    env = _load_env()
    path = config_path or env.config_path
    if backup:
        backup_config(path, history_dir)

    data = settings.model_dump(mode="python")
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    _atomic_write(path, content)
    return path


def settings_to_dashboard_dict(settings: TradingSettings) -> dict:
    return settings.model_dump(mode="python")


# Dicts whose contents are strategy-defined; merging them key-by-key would make
# removing a parameter impossible, so the payload always replaces them.
_OPAQUE_DICT_FIELDS = frozenset({"main_args", "fallback_args"})


def _deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if (
            isinstance(value, dict)
            and isinstance(current, dict)
            and key not in _OPAQUE_DICT_FIELDS
        ):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def apply_config_payload(settings: TradingSettings, payload: dict) -> TradingSettings:
    """Merge a nested payload into current settings and re-validate the whole tree."""
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    unknown = set(payload) - set(TradingSettings.model_fields)
    if unknown:
        raise ValueError(f"Unsupported config fields: {', '.join(sorted(unknown))}")
    merged = _deep_merge(settings.model_dump(mode="python"), payload)
    return TradingSettings.model_validate(merged)


def validation_field_errors(exc: ValidationError) -> List[dict]:
    """Flatten Pydantic errors into per-field entries the UI can highlight."""
    errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        errors.append(
            {
                "field": ".".join(location),
                "message": error.get("msg", "invalid value"),
                "type": error.get("type", ""),
            }
        )
    return errors


def apply_dashboard_update(
    settings: TradingSettings, payload: dict
) -> TradingSettings:
    """Merge partial dashboard updates into validated settings.

    Kept for the legacy `/update-config` contract, which uses UPPER_SNAKE
    aliases instead of the nested field names.
    """
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

# Section order and labels drive the generated config form.
CONFIG_SECTIONS = (
    ("", "Geral", None),
    ("strategy", "Estratégia", StrategyConfig),
    ("risk", "Risco", RiskConfig),
    ("timing", "Tempo", TimingConfig),
    ("regime", "Regime de mercado", RegimeConfig),
    ("grid", "Grid spot", GridConfig),
    ("breakout", "Rompimento", BreakoutConfig),
    ("operation", "Operação", OperationConfig),
    ("alerts", "Alertas", AlertsConfig),
)

_ROOT_SECTION_FIELDS = ("environment", "thread_lock")
# Changing these can move real money, so the UI asks for explicit confirmation.
SENSITIVE_CONFIG_FIELDS = frozenset(
    {
        "environment",
        "assets.traded_quantity",
        "assets.traded_percentage",
        "risk.max_daily_loss_usdt",
        "risk.stop_loss_pct",
    }
)


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _field_constraints(field) -> dict:
    constraints: dict = {}
    for meta in field.metadata:
        for attr in ("ge", "gt", "le", "lt"):
            value = getattr(meta, attr, None)
            if value is not None:
                constraints[attr] = value
    return constraints


def _describe_field(name: str, field, path: str) -> Optional[dict]:
    annotation = field.annotation
    origin = get_origin(annotation)
    descriptor: dict = {
        "name": name,
        "path": path,
        "label": field.title or _humanize(name),
        "description": field.description or "",
        "sensitive": path in SENSITIVE_CONFIG_FIELDS,
    }

    if origin is Literal:
        descriptor["type"] = "select"
        descriptor["options"] = [str(option) for option in get_args(annotation)]
    elif annotation is bool:
        descriptor["type"] = "bool"
    elif annotation is int:
        descriptor["type"] = "int"
        descriptor["step"] = 1
    elif annotation is float:
        descriptor["type"] = "float"
        descriptor["step"] = "any"
    elif annotation is str:
        descriptor["type"] = "text"
    elif origin is dict:
        descriptor["type"] = "json"
    else:
        return None

    descriptor.update(_field_constraints(field))

    if path == "timing.candle_period":
        descriptor["type"] = "select"
        descriptor["options"] = list(CANDLE_INTERVALS)
    elif path in ("strategy.main", "strategy.fallback"):
        descriptor["type"] = "select"
        descriptor["options"] = list_strategies()

    return descriptor


def _model_fields(model, prefix: str, only: Optional[tuple] = None) -> List[dict]:
    fields = []
    for name, field in model.model_fields.items():
        if only is not None and name not in only:
            continue
        path = f"{prefix}.{name}" if prefix else name
        descriptor = _describe_field(name, field, path)
        if descriptor is not None:
            fields.append(descriptor)
    return fields


def config_schema() -> dict:
    """Describe every editable setting so the UI can render itself.

    Labels, help text, bounds and option lists all come from the Pydantic
    models, so the form and the server-side validation cannot drift apart.
    """
    sections = []
    for key, title, model in CONFIG_SECTIONS:
        if model is None:
            fields = _model_fields(TradingSettings, "", only=_ROOT_SECTION_FIELDS)
        else:
            fields = _model_fields(model, key)
        sections.append({"key": key, "title": title, "fields": fields})

    return {
        "sections": sections,
        "assets": {
            "title": "Ativos negociados",
            "fields": _model_fields(AssetConfig, "assets"),
        },
        "take_profit": {
            "title": "Realização de lucro",
            "fields": _model_fields(TakeProfitLevel, "risk.take_profit"),
        },
        "sensitive_fields": sorted(SENSITIVE_CONFIG_FIELDS),
    }
