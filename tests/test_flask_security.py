import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import security  # noqa: E402
from app import app  # noqa: E402
from security import (  # noqa: E402
    assert_flask_bind_allowed,
    is_protected_path,
    tokens_match,
)

PASSWORD = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    security._login_attempts.clear()
    yield
    security._login_attempts.clear()


@pytest.fixture
def password_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", generate_password_hash(PASSWORD))
    monkeypatch.delenv("FLASK_TOKEN", raising=False)
    return PASSWORD


def _login(client, password=PASSWORD):
    with client.session_transaction() as session:
        session["csrf"] = "test-csrf-token"
    return client.post(
        "/login",
        data={"password": password, "csrf_token": "test-csrf-token"},
    )


def test_local_bind_allows_empty_token():
    assert_flask_bind_allowed("127.0.0.1", "")
    assert_flask_bind_allowed("localhost", "")
    assert_flask_bind_allowed("::1", "")


def test_public_bind_requires_password_hash():
    with pytest.raises(SystemExit):
        assert_flask_bind_allowed("0.0.0.0", "")
    # A token cannot authenticate a browser, so it does not unlock a public bind.
    with pytest.raises(SystemExit):
        assert_flask_bind_allowed("0.0.0.0", "secret")
    assert_flask_bind_allowed("0.0.0.0", "", "pbkdf2:sha256:600000$abc$def")


def test_weak_config_warning_targets_token_without_password():
    assert security.weak_config_warning("secret", "")
    assert not security.weak_config_warning("", "")
    assert not security.weak_config_warning("secret", "hash")


def test_protected_paths():
    assert is_protected_path("/api/logs")
    assert is_protected_path("/api/portfolio")
    assert is_protected_path("/update-config")
    assert is_protected_path("/get-config")
    assert not is_protected_path("/")
    assert not is_protected_path("/profit")


def test_tokens_match():
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
    assert not tokens_match("", "abc")


def test_query_param_token_is_rejected(monkeypatch):
    monkeypatch.setenv("FLASK_TOKEN", "secret")
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    client = app.test_client()
    assert client.get("/api/logs?token=secret").status_code == 401
    assert client.get("/api/logs", headers={"X-TraderBot-Token": "secret"}).status_code == 200


def test_token_is_never_rendered_in_html(monkeypatch):
    monkeypatch.setenv("FLASK_TOKEN", "token-que-nao-deve-vazar")
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    client = app.test_client()
    for path in ("/", "/profit", "/config"):
        body = client.get(path).get_data(as_text=True)
        assert "token-que-nao-deve-vazar" not in body


def test_html_pages_require_login(password_env):
    client = app.test_client()
    for path in ("/", "/profit", "/config"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


def test_api_requires_login_with_401(password_env):
    client = app.test_client()
    assert client.get("/api/logs").status_code == 401
    assert client.get("/get-config").status_code == 401


def test_healthz_is_public(password_env):
    client = app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_static_assets_are_public_so_login_page_is_styled(password_env):
    client = app.test_client()
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert b".login-card" in response.data


def test_login_success_grants_access(password_env):
    client = app.test_client()
    response = _login(client)
    assert response.status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/api/logs").status_code == 200


def test_login_rejects_wrong_password(password_env):
    client = app.test_client()
    assert _login(client, "senha-errada").status_code == 401
    assert client.get("/").status_code == 302


def test_login_requires_csrf(password_env):
    client = app.test_client()
    response = client.post("/login", data={"password": PASSWORD})
    assert response.status_code == 400


def test_login_is_rate_limited(password_env):
    client = app.test_client()
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        assert _login(client, "senha-errada").status_code == 401
    blocked = _login(client, "senha-errada")
    assert blocked.status_code == 429
    # The correct password is refused too while the window is open.
    assert _login(client).status_code == 429


def test_logout_clears_session(password_env):
    client = app.test_client()
    _login(client)
    assert client.get("/").status_code == 200
    with client.session_transaction() as session:
        csrf = session["csrf"]
    logout = client.post("/logout", data={"csrf_token": csrf})
    assert logout.status_code == 302
    assert client.get("/").status_code == 302


def test_state_changing_request_requires_csrf(password_env):
    client = app.test_client()
    _login(client)
    denied = client.post("/api/config/validate", json={})
    assert denied.status_code == 403

    with client.session_transaction() as session:
        csrf = session["csrf"]
    allowed = client.post(
        "/api/config/validate", json={}, headers={"X-TraderBot-CSRF": csrf}
    )
    assert allowed.status_code == 200


def test_api_token_bypasses_session_and_csrf(monkeypatch, password_env):
    monkeypatch.setenv("FLASK_TOKEN", "token-de-script")
    client = app.test_client()
    headers = {"X-TraderBot-Token": "token-de-script"}
    assert client.get("/api/logs", headers=headers).status_code == 200
    assert client.post("/api/config/validate", json={}, headers=headers).status_code == 200


def test_security_headers_are_applied(password_env):
    client = app.test_client()
    response = client.get("/healthz")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_login_redirect_target_stays_on_site(password_env):
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "t"
    response = client.post(
        "/login?next=https://evil.example.com/x",
        data={"password": PASSWORD, "csrf_token": "t"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
