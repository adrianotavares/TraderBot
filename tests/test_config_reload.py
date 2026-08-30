import time

import yaml

from config.reload import SettingsWatch, classify_settings_delta
from config.settings import TradingSettings, load_settings
from persistence.state_store import StateStore
from services.risk_manager import RiskManager


def _base_payload(**overrides):
    payload = {
        "environment": "testnet",
        "thread_lock": True,
        "strategy": {
            "main": "atr_trend",
            "fallback": "moving_average",
            "main_args": {"atr_period": 14},
            "fallback_enabled": True,
        },
        "risk": {
            "acceptable_loss_pct": 1.5,
            "stop_loss_pct": 2.0,
            "max_daily_loss_usdt": 50.0,
            "max_trades_per_day": 5,
        },
        "timing": {
            "candle_period": "4h",
            "tempo_entre_trades": 150,
            "delay_entre_ordens": 7200,
        },
        "assets": [
            {
                "stock_code": "BTC",
                "operation_code": "BTCUSDT",
                "traded_percentage": 10,
                "breakout_price": 78000,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _settings(**overrides) -> TradingSettings:
    return TradingSettings.model_validate(_base_payload(**overrides))


def test_risk_change_is_soft():
    old = _settings()
    new = _settings(risk={**_base_payload()["risk"], "max_daily_loss_usdt": 20.0})
    hard, soft = classify_settings_delta(old, new)
    assert hard == []
    assert "risk" in soft


def test_strategy_main_is_hard():
    old = _settings()
    payload = _base_payload()
    payload["strategy"] = {**payload["strategy"], "main": "moving_average"}
    new = TradingSettings.model_validate(payload)
    hard, soft = classify_settings_delta(old, new)
    assert "strategy.main" in hard
    assert "risk" not in soft


def test_asset_identity_is_hard_sizing_is_soft():
    old = _settings()
    payload = _base_payload()
    payload["assets"] = [
        {
            "stock_code": "ETH",
            "operation_code": "ETHUSDT",
            "traded_percentage": 10,
        }
    ]
    new = TradingSettings.model_validate(payload)
    hard, _soft = classify_settings_delta(old, new)
    assert "assets" in hard

    payload = _base_payload()
    payload["assets"][0]["traded_percentage"] = 25
    sized = TradingSettings.model_validate(payload)
    hard, soft = classify_settings_delta(old, sized)
    assert hard == []
    assert "asset_sizing" in soft


def test_candle_period_is_hard():
    old = _settings()
    payload = _base_payload()
    payload["timing"] = {**payload["timing"], "candle_period": "1h"}
    new = TradingSettings.model_validate(payload)
    hard, _soft = classify_settings_delta(old, new)
    assert "timing.candle_period" in hard


def test_watch_polls_mtime_and_bumps_generation(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    path = tmp_path / "trading.yaml"
    path.write_text(yaml.safe_dump(_base_payload()), encoding="utf-8")
    settings, _env = load_settings(path)
    watch = SettingsWatch(path, settings)
    assert watch.poll() is None

    payload = _base_payload()
    payload["risk"]["max_daily_loss_usdt"] = 12.0
    time.sleep(0.02)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    event = watch.poll()
    assert event is not None
    assert "risk" in event.soft
    assert event.hard == []
    assert event.settings.risk.max_daily_loss_usdt == 12.0
    assert watch.generation == 1


def test_apply_config_keeps_daily_counters(tmp_path):
    store = StateStore(tmp_path / "test.db")
    risk = RiskManager(
        acceptable_loss_pct=1.0,
        stop_loss_pct=2.0,
        take_profit_at=[],
        take_profit_amount=[],
        max_daily_loss_usdt=50.0,
        max_trades_per_day=5,
        state_store=store,
        operation_code="BTCUSDT",
    )
    risk.record_trade_pnl(-12.5)
    risk.apply_config(
        acceptable_loss_pct=1.5,
        stop_loss_pct=3.0,
        take_profit_at=[7],
        take_profit_amount=[100],
        max_daily_loss_usdt=20.0,
        max_trades_per_day=3,
        max_open_orders=2,
        max_grid_trades_per_day=10,
        max_grid_open_orders=8,
        circuit_breaker_errors=4,
        circuit_breaker_pause_seconds=60,
        trailing_stop_loss=True,
    )
    assert risk._daily_loss_usdt == 12.5
    assert risk._daily_trades == 1
    assert risk.max_daily_loss_usdt == 20.0
    assert risk.stop_loss_pct == 0.03
    assert risk.trailing_stop_loss is True
