import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import app  # noqa: E402
from persistence.state_store import StateStore  # noqa: E402
from services.portfolio_actions import PortfolioActionError  # noqa: E402

ASSETS = [
    SimpleNamespace(stock_code="BTC", operation_code="BTCUSDT"),
    SimpleNamespace(stock_code="ETH", operation_code="ETHUSDT"),
]


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    settings = SimpleNamespace(environment="testnet", assets=ASSETS)
    client = MagicMock()
    store_path = tmp_path / "actions.db"

    monkeypatch.setattr(
        "routes._spot_client_for_settings",
        lambda: (settings, client),
    )
    monkeypatch.setattr("routes.StateStore", lambda: StateStore(store_path))
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("FLASK_TOKEN", "")
    return {"client": app.test_client(), "settings": settings, "spot": client}


def test_balance_page_renders(api_env):
    response = api_env["client"].get("/balance")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Balancear" in body
    assert "Liquidate" in body
    assert "traded_percentage" in body


def test_rebalance_preview_returns_400_on_bad_weights(api_env, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PortfolioActionError("Soma dos pesos deve ser 100%", blockers=["sum"])

    monkeypatch.setattr("routes.preview_rebalance", boom)
    response = api_env["client"].post(
        "/api/portfolio/rebalance/preview",
        json={"weights": {"BTCUSDT": 90}},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["blockers"] == ["sum"]


def test_liquidate_preview_empty_list_400(api_env, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PortfolioActionError("Selecione pelo menos um par para liquidar", blockers=["symbols"])

    monkeypatch.setattr("routes.preview_liquidate", boom)
    response = api_env["client"].post(
        "/api/portfolio/liquidate/preview",
        json={"symbols": []},
    )
    assert response.status_code == 400


def test_execute_requires_confirm(api_env, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PortfolioActionError("Confirmação inválida (digite LIQUIDATE)", blockers=["confirm"])

    monkeypatch.setattr("routes.execute_liquidate", boom)
    response = api_env["client"].post(
        "/api/portfolio/liquidate",
        json={"symbols": ["ETHUSDT"]},
    )
    assert response.status_code == 400
    assert api_env["client"].get("/api/portfolio/hold").get_json()["hold"] is False


def test_hold_release(api_env):
    from routes import StateStore as RoutedStore

    RoutedStore().set_action_hold(True)
    assert api_env["client"].get("/api/portfolio/hold").get_json()["hold"] is True
    released = api_env["client"].post("/api/portfolio/hold", json={"hold": False})
    assert released.status_code == 200
    assert released.get_json()["hold"] is False
    assert api_env["client"].get("/api/portfolio/hold").get_json()["hold"] is False
