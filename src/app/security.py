import hmac
import os
import secrets
import threading
import time
from collections import deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRET_KEY_FILE = PROJECT_ROOT / "data" / ".flask_secret"

LOCAL_BIND = frozenset({"127.0.0.1", "localhost", "::1"})
TOKEN_HEADER = "X-TraderBot-Token"
CSRF_HEADER = "X-TraderBot-CSRF"
PROTECTED_PATHS = frozenset({"/update-config", "/get-config"})
PUBLIC_ENDPOINTS = frozenset({"static", "routes.login", "routes.logout", "routes.healthz"})
SESSION_LIFETIME = timedelta(hours=12)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_login_lock = threading.Lock()
_login_attempts: dict[str, deque] = {}


def flask_token() -> str:
    return os.getenv("FLASK_TOKEN", "").strip()


def password_hash() -> str:
    return os.getenv("DASHBOARD_PASSWORD_HASH", "").strip()


def session_auth_enabled() -> bool:
    return bool(password_hash())


def flask_bind_host() -> str:
    return (os.getenv("FLASK_HOST", "127.0.0.1") or "127.0.0.1").strip()


def cookie_secure() -> bool:
    raw = os.getenv("FLASK_COOKIE_SECURE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_local_bind(host: str) -> bool:
    return (host or "127.0.0.1").strip() in LOCAL_BIND


def assert_flask_bind_allowed(host: str, token: str = "", pwd_hash: str = "") -> None:
    """A non-local bind requires password auth.

    A shared token deliberately does not satisfy this: it cannot authenticate a
    browser without being embedded in the page, which is what used to expose it
    to anonymous visitors. Only a session login protects the HTML pages.
    """
    if is_local_bind(host):
        return
    if (pwd_hash or "").strip():
        return
    raise SystemExit(
        f"DASHBOARD_PASSWORD_HASH is required when FLASK_HOST={host} (not localhost).\n"
        f"Generate one with: python src/app/hash_password.py\n"
        f"FLASK_TOKEN alone is not enough: it cannot authenticate a browser "
        f"session, only scripted API calls."
    )


def weak_config_warning(token: str = "", pwd_hash: str = "") -> str:
    """Explain the one combination where the UI loads but cannot fetch data."""
    if (pwd_hash or "").strip() or not (token or "").strip():
        return ""
    return (
        "FLASK_TOKEN is set without DASHBOARD_PASSWORD_HASH. The dashboard pages "
        "will load but cannot read the API, because the token is no longer "
        "embedded in the HTML. Set DASHBOARD_PASSWORD_HASH "
        "(python src/app/hash_password.py) to log in from the browser."
    )


def resolve_secret_key() -> bytes:
    """Return a stable signing key, generating and persisting one if needed.

    Sessions must survive a restart, so the generated key is stored under
    data/ with owner-only permissions instead of being kept in memory.
    """
    from_env = os.getenv("FLASK_SECRET_KEY", "").strip()
    if from_env:
        return from_env.encode("utf-8")

    if SECRET_KEY_FILE.exists():
        existing = SECRET_KEY_FILE.read_bytes().strip()
        if existing:
            return existing

    generated = secrets.token_hex(32).encode("utf-8")
    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(SECRET_KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(generated)
    return generated


def is_protected_path(path: str) -> bool:
    """Paths that the legacy token mode guards. Session mode guards everything."""
    return path.startswith("/api/") or path in PROTECTED_PATHS


def extract_request_token() -> str:
    header = request.headers.get(TOKEN_HEADER, "") or ""
    auth = request.headers.get("Authorization", "") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return (header or bearer).strip()


def tokens_match(provided: str, expected: str) -> bool:
    provided = provided or ""
    expected = expected or ""
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def token_request_authorized() -> bool:
    token = flask_token()
    return bool(token) and tokens_match(extract_request_token(), token)


def verify_password(password: str) -> bool:
    stored = password_hash()
    if not stored or not password:
        return False
    try:
        return check_password_hash(stored, password)
    except (ValueError, TypeError):
        return False


def client_key() -> str:
    return request.remote_addr or "unknown"


def _recent_attempts(key: str, now: float) -> deque:
    attempts = _login_attempts.setdefault(key, deque())
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def login_blocked_for(key: str) -> int:
    """Seconds the caller must wait, or 0 when another attempt is allowed."""
    now = time.time()
    with _login_lock:
        attempts = _recent_attempts(key, now)
        if len(attempts) < LOGIN_MAX_ATTEMPTS:
            return 0
        return max(1, int(LOGIN_WINDOW_SECONDS - (now - attempts[0])))


def register_failed_login(key: str) -> None:
    now = time.time()
    with _login_lock:
        _recent_attempts(key, now).append(now)


def reset_login_attempts(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)


def is_authenticated() -> bool:
    return session.get("auth") is True


def start_session() -> None:
    session.clear()
    session["auth"] = True
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True


def end_session() -> None:
    session.clear()


def ensure_csrf_token() -> str:
    """Create a CSRF token even before login, so the login form is protected."""
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def session_csrf_token() -> str:
    if not is_authenticated():
        return ""
    return ensure_csrf_token()


def csrf_valid() -> bool:
    expected = session.get("csrf") or ""
    if not expected:
        return False
    provided = request.headers.get(CSRF_HEADER, "") or ""
    if not provided and request.form:
        provided = request.form.get("csrf_token", "") or ""
    return tokens_match(provided.strip(), expected)


def safe_redirect_target(candidate: str | None, fallback_endpoint: str = "routes.dashboard") -> str:
    """Only allow same-site relative redirects, so ?next= cannot bounce off-site."""
    default = url_for(fallback_endpoint)
    if not candidate:
        return default
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return default
    if candidate.startswith("//"):
        return default
    return candidate


def wants_json() -> bool:
    if request.path.startswith("/api/") or request.path in PROTECTED_PATHS:
        return True
    accept = request.headers.get("Accept", "") or ""
    return "application/json" in accept and "text/html" not in accept


def _unauthorized():
    if wants_json():
        return jsonify({"error": "Unauthorized"}), 401
    target = request.full_path.rstrip("?") or "/"
    return redirect(url_for("routes.login", next=target))


def _enforce_legacy_token():
    token = flask_token()
    if not token or not is_protected_path(request.path):
        return None
    if tokens_match(extract_request_token(), token):
        return None
    return jsonify({"error": "Unauthorized"}), 401


def enforce_auth():
    """before_request guard.

    With DASHBOARD_PASSWORD_HASH set, every endpoint outside PUBLIC_ENDPOINTS
    requires a session cookie or the API token. Without it, the older
    token-only behaviour is kept so existing setups do not break.
    """
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session_auth_enabled():
        return _enforce_legacy_token()
    if token_request_authorized():
        return None
    if not is_authenticated():
        return _unauthorized()
    if request.method not in SAFE_METHODS and not csrf_valid():
        return jsonify({"error": "CSRF token inválido. Recarregue a página."}), 403
    return None


# Kept as an alias so older imports keep working.
enforce_token = enforce_auth


def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    if request.path.startswith("/api/") or request.path in PROTECTED_PATHS:
        response.headers.setdefault("Cache-Control", "no-store")
    return response
