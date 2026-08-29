import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import app  # noqa: E402
from persistence.state_store import StateStore  # noqa: E402


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    store_path = tmp_path / "actions.db"
    monkeypatch.setattr("routes.StateStore", lambda: StateStore(store_path))
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("FLASK_TOKEN", "")
    return {"client": app.test_client(), "store_path": store_path}


def test_cycles_control_roundtrip(api_env):
    client = api_env["client"]
    assert client.get("/api/cycles/control").get_json() == {
        "operator_hold": False,
        "action_hold": False,
    }
    held = client.post("/api/cycles/control", json={"hold": True})
    assert held.status_code == 200
    assert held.get_json()["operator_hold"] is True
    assert client.get("/api/cycles/control").get_json()["operator_hold"] is True
    released = client.post("/api/cycles/control", json={"hold": False})
    assert released.status_code == 200
    assert released.get_json()["operator_hold"] is False


def test_tracking_page_has_operator_hold_controls(api_env):
    html = api_env["client"].get("/").get_data(as_text=True)
    assert 'id="cycle-start-btn"' in html
    assert 'id="cycle-hold-btn"' in html
    assert 'id="operator-hold-banner"' in html
    assert "/api/cycles/control" in html
    assert 'data-range="4h"' in html
    assert 'data-range="8h"' in html
    assert 'data-range="12h"' in html
    assert "defaultRangeKey" in html
    response = api_env["client"].post("/api/cycles/control", json={})
    assert response.status_code == 400


def test_operator_hold_does_not_clear_action_hold(api_env):
    from routes import StateStore as RoutedStore

    store = RoutedStore()
    store.set_action_hold(True)
    response = api_env["client"].post("/api/cycles/control", json={"hold": True})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["operator_hold"] is True
    assert payload["action_hold"] is True
    assert api_env["client"].post(
        "/api/cycles/control", json={"hold": False}
    ).get_json()["action_hold"] is True
