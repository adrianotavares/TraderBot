import pytest
from pydantic import ValidationError

from config.settings import RegimeConfig, TradingSettings, apply_dashboard_update, load_settings


def test_load_settings_validates_assets():
    with pytest.raises(ValidationError):
        TradingSettings.model_validate(
            {
                "environment": "testnet",
                "strategy": {
                    "main": "moving_average",
                    "fallback": "moving_average",
                },
                "risk": {},
                "timing": {},
                "assets": [],
            }
        )


def test_apply_dashboard_update_legacy_keys():
    settings = TradingSettings.model_validate(
        {
            "environment": "testnet",
            "strategy": {"main": "weapon_candle", "fallback": "moving_average"},
            "risk": {"acceptable_loss_pct": 1.0, "stop_loss_pct": 0.5},
            "timing": {"tempo_entre_trades": 300, "delay_entre_ordens": 300},
            "assets": [
                {
                    "stock_code": "BTC",
                    "operation_code": "BTCUSDT",
                    "traded_quantity": 0.001,
                }
            ],
        }
    )
    updated = apply_dashboard_update(
        settings,
        {
            "MAIN_STRATEGY": "vortex",
            "STOP_LOSS_PERCENTAGE": 2.5,
            "stocks_traded_list": [
                {"stockCode": "ETH", "operationCode": "ETHUSDT", "tradedQuantity": 0.01}
            ],
        },
    )
    assert updated.strategy.main == "vortex"
    assert updated.risk.stop_loss_pct == 2.5
    assert updated.assets[0].operation_code == "ETHUSDT"


def test_config_file_exists():
    settings, env = load_settings()
    assert settings.environment in ("testnet", "mainnet")
    assert len(settings.assets) >= 1


def test_regime_hold_cash_is_accepted():
    cfg = RegimeConfig(action_in_lateral="hold_cash")
    assert cfg.action_in_lateral == "hold_cash"
