import sys
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import app  # noqa: E402


def test_market_page_renders(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("FLASK_TOKEN", "")
    client = app.test_client()
    response = client.get("/market")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'class="nav-label">Market</span>' in body
    assert "Medo e ganância" in body
    assert "Criptomoedas" in body
    assert "page-market" in body
    assert "market-side" in body
    assert "Tendências" in body
    assert 'role="tablist"' in body
    assert 'data-side-tab="trending"' in body
    assert "fear-gauge" in body
    assert "function coinDetailHref" in body
    assert "market-coin-link" in body
    assert "safeHttpUrl" in body
    assert 'href="/market"' in body
    config_idx = body.find('class="nav-label">Config</span>')
    market_idx = body.find('class="nav-label">Market</span>')
    assert 0 <= market_idx < config_idx


def test_market_api_uses_service(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("FLASK_TOKEN", "")
    captured = {}

    def fake_overview(*, watched_symbols, refresh):
        captured["watched"] = list(watched_symbols)
        captured["refresh"] = refresh
        return {"quotes": {"ok": True, "coins": []}, "updated_at": "now"}

    settings = SimpleNamespace(
        assets=[SimpleNamespace(stock_code="BTC"), SimpleNamespace(stock_code="ETH")]
    )
    monkeypatch.setattr("routes.load_settings", lambda: (settings, None))
    monkeypatch.setattr("routes.build_market_overview", fake_overview)

    client = app.test_client()
    response = client.get("/api/market?refresh=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["quotes"]["ok"] is True
    assert captured["watched"] == ["BTC", "ETH"]
    assert captured["refresh"] is True
