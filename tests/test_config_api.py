import sys
from pathlib import Path

import pytest
import yaml

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config.settings as settings_module  # noqa: E402
from app import app  # noqa: E402

BASE_YAML = """\
environment: testnet
thread_lock: true

strategy:
  main: atr_trend
  main_args:
    atr_period: 14
  fallback: moving_average
  fallback_enabled: true

risk:
  acceptable_loss_pct: 1.5
  stop_loss_pct: 2.0
  take_profit:
    - at: 7
      amount: 100
#    - at: 10
#      amount: 50
  max_daily_loss_usdt: 50.0

timing:
  candle_period: 4h
  tempo_entre_trades: 150
  delay_entre_ordens: 7200

assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0
    traded_percentage: 50
"""


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    config_path = tmp_path / "trading.yaml"
    config_path.write_text(BASE_YAML, encoding="utf-8")
    history_dir = tmp_path / "history"

    # Keep the developer's real .env out of these assertions.
    monkeypatch.setenv("TRADERBOT_ENV_FILE", str(tmp_path / "empty.env"))
    monkeypatch.setenv("TRADING_CONFIG", str(config_path))
    monkeypatch.delenv("TRADING_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("FLASK_TOKEN", "")
    monkeypatch.setattr(settings_module, "CONFIG_HISTORY_DIR", history_dir)

    return {"path": config_path, "history": history_dir, "client": app.test_client()}


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_schema_exposes_sections_and_bounds(config_env):
    schema = config_env["client"].get("/api/config/schema").get_json()
    keys = [section["key"] for section in schema["sections"]]
    assert keys == [
        "",
        "strategy",
        "risk",
        "timing",
        "regime",
        "grid",
        "breakout",
        "operation",
        "alerts",
    ]

    by_path = {
        field["path"]: field
        for section in schema["sections"]
        for field in section["fields"]
    }
    assert by_path["environment"]["type"] == "select"
    assert by_path["environment"]["options"] == ["testnet", "mainnet"]
    assert by_path["timing.candle_period"]["type"] == "select"
    assert "4h" in by_path["timing.candle_period"]["options"]
    assert "atr_trend" in by_path["strategy.main"]["options"]
    assert "vwap_scalp" in by_path["strategy.main"]["options"]
    assert by_path["risk.stop_loss_pct"]["le"] == 100
    assert by_path["strategy.main_args"]["type"] == "json"
    assert by_path["risk.stop_loss_pct"]["description"]
    assert schema["strategy_defaults"]["vwap_scalp"]["session_start_utc"] == "12:00"
    assert schema["strategy_defaults"]["atr_trend"]["atr_period"] == 14

    assert [f["name"] for f in schema["assets"]["fields"]][:2] == [
        "stock_code",
        "operation_code",
    ]
    assert [f["name"] for f in schema["take_profit"]["fields"]] == ["at", "amount"]


def test_get_config_reports_environment_source(config_env):
    payload = config_env["client"].get("/api/config").get_json()
    assert payload["config"]["timing"]["candle_period"] == "4h"
    assert payload["environment"]["source"] == "trading.yaml"
    assert payload["environment"]["conflict"] is False


def test_env_override_is_reported_as_conflict(config_env, monkeypatch):
    monkeypatch.setenv("TRADING_ENV", "mainnet")
    payload = config_env["client"].get("/api/config").get_json()
    assert payload["environment"]["override"] == "mainnet"
    assert payload["environment"]["yaml"] == "testnet"
    assert payload["environment"]["conflict"] is True
    # The form still edits the file's own value, not the override.
    assert payload["config"]["environment"] == "testnet"


def test_validate_classifies_soft_change(config_env):
    response = config_env["client"].post(
        "/api/config/validate", json={"risk": {"stop_loss_pct": 3.0}}
    )
    result = response.get_json()
    assert result["valid"] is True
    assert result["changed"] is True
    assert "risk" in result["soft"]
    assert result["hard"] == []


def test_validate_classifies_hard_change(config_env):
    response = config_env["client"].post(
        "/api/config/validate", json={"strategy": {"main": "rsi"}}
    )
    result = response.get_json()
    assert result["valid"] is True
    assert "strategy.main" in result["hard"]


def test_validate_reports_no_change(config_env):
    current = config_env["client"].get("/api/config").get_json()["config"]
    result = config_env["client"].post("/api/config/validate", json=current).get_json()
    assert result["valid"] is True
    assert result["changed"] is False


def test_validate_returns_field_level_errors(config_env):
    result = (
        config_env["client"]
        .post("/api/config/validate", json={"risk": {"stop_loss_pct": 900}})
        .get_json()
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "risk.stop_loss_pct"

    nested = (
        config_env["client"]
        .post(
            "/api/config/validate",
            json={"assets": [{"stock_code": "", "operation_code": "BTCUSDT"}]},
        )
        .get_json()
    )
    assert nested["valid"] is False
    assert nested["errors"][0]["field"] == "assets.0.stock_code"


def test_validate_rejects_unknown_section(config_env):
    result = (
        config_env["client"]
        .post("/api/config/validate", json={"nao_existe": 1})
        .get_json()
    )
    assert result["valid"] is False
    assert "nao_existe" in result["errors"][0]["message"]


def test_save_writes_yaml_and_reports_impact(config_env):
    response = config_env["client"].post(
        "/api/config", json={"risk": {"stop_loss_pct": 4.25}}
    )
    assert response.status_code == 200
    result = response.get_json()
    assert result["saved"] is True
    assert "risk" in result["soft"]
    assert read_yaml(config_env["path"])["risk"]["stop_loss_pct"] == 4.25


def test_save_rejects_invalid_payload_without_touching_file(config_env):
    before = config_env["path"].read_text(encoding="utf-8")
    response = config_env["client"].post(
        "/api/config", json={"timing": {"candle_period": "13h"}}
    )
    assert response.status_code == 400
    assert response.get_json()["errors"][0]["field"] == "timing.candle_period"
    assert config_env["path"].read_text(encoding="utf-8") == before


def test_save_keeps_a_backup_with_original_comments(config_env):
    config_env["client"].post("/api/config", json={"risk": {"stop_loss_pct": 3.0}})

    backups = config_env["client"].get("/api/config/history").get_json()["backups"]
    assert len(backups) == 1

    saved = config_env["path"].read_text(encoding="utf-8")
    archived = (config_env["history"] / backups[0]["name"]).read_text(encoding="utf-8")
    # yaml.safe_dump drops comments, so the byte-for-byte backup is what preserves them.
    assert "#    - at: 10" in archived
    assert "#    - at: 10" not in saved


def test_revert_restores_previous_version(config_env):
    client = config_env["client"]
    client.post("/api/config", json={"strategy": {"main": "rsi"}})
    assert read_yaml(config_env["path"])["strategy"]["main"] == "rsi"

    backups = client.get("/api/config/history").get_json()["backups"]
    response = client.post("/api/config/revert", json={"name": backups[0]["name"]})
    assert response.status_code == 200
    assert "strategy.main" in response.get_json()["hard"]

    restored = config_env["path"].read_text(encoding="utf-8")
    assert read_yaml(config_env["path"])["strategy"]["main"] == "atr_trend"
    assert "#    - at: 10" in restored


def test_revert_rejects_path_traversal(config_env):
    response = config_env["client"].post(
        "/api/config/revert", json={"name": "../../.env"}
    )
    assert response.status_code == 400


def test_history_is_pruned_to_the_limit(config_env, monkeypatch):
    monkeypatch.setattr(settings_module, "CONFIG_HISTORY_KEEP", 3)
    for index in range(5):
        config_env["client"].post(
            "/api/config", json={"risk": {"stop_loss_pct": 2.0 + index * 0.5}}
        )
    backups = config_env["client"].get("/api/config/history").get_json()["backups"]
    assert len(backups) == 3


def test_status_reports_config_and_bot(config_env):
    status = config_env["client"].get("/api/status").get_json()
    assert status["environment"]["effective"] == "testnet"
    assert status["config"]["modified_at"]
    assert isinstance(status["bot"]["running"], bool)
    assert "last_reload" in status["events"]
    assert "server_time" in status
    assert isinstance(status["cycles"], list)


def test_status_includes_cycle_heartbeats(config_env, tmp_path, monkeypatch):
    import routes
    from datetime import datetime, timedelta, timezone

    from persistence.state_store import StateStore

    store = StateStore(tmp_path / "cycles.db")
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    store.save_cycle_heartbeat(
        "BTCUSDT",
        "sleeping",
        cycle_finished_at=now.isoformat(),
        sleep_seconds=600,
        next_cycle_at=(now + timedelta(seconds=600)).isoformat(),
        sleep_reason="interval",
    )
    store.save_cycle_heartbeat(
        "LINKUSDT",
        "sleeping",
        cycle_finished_at=now.isoformat(),
        sleep_seconds=30,
        next_cycle_at=(now + timedelta(seconds=30)).isoformat(),
        sleep_reason="interval",
    )
    monkeypatch.setattr(routes, "StateStore", lambda *a, **k: store)
    status = config_env["client"].get("/api/status").get_json()
    assert [row["operation_code"] for row in status["cycles"]] == ["BTCUSDT"]
    assert status["cycles"][0]["operation_code"] == "BTCUSDT"
    assert status["cycles"][0]["phase"] == "sleeping"
    assert status["cycles"][0]["sleep_seconds"] == 600
    assert status["cycles"][0]["sleep_reason"] == "interval"


def test_status_survives_heartbeat_read_failure(config_env, monkeypatch):
    import routes

    class Boom:
        def list_cycle_heartbeats(self):
            raise RuntimeError("disk full")

    monkeypatch.setattr(routes, "StateStore", lambda *a, **k: Boom())
    status = config_env["client"].get("/api/status").get_json()
    assert status["cycles"] == []
    assert "bot" in status


def test_legacy_update_config_still_works(config_env):
    response = config_env["client"].post(
        "/update-config", json={"STOP_LOSS_PERCENTAGE": 5.5}
    )
    assert response.status_code == 200
    assert read_yaml(config_env["path"])["risk"]["stop_loss_pct"] == 5.5
