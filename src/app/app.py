import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask
from routes import routes
from security import (
    SESSION_LIFETIME,
    apply_security_headers,
    assert_flask_bind_allowed,
    cookie_secure,
    enforce_auth,
    flask_bind_host,
    flask_token,
    is_authenticated,
    password_hash,
    resolve_secret_key,
    session_auth_enabled,
    session_csrf_token,
    weak_config_warning,
)

from config.settings import environment_override, load_settings

app = Flask(__name__)
app.secret_key = resolve_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=cookie_secure(),
    SESSION_COOKIE_NAME="traderbot_session",
    PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
    MAX_CONTENT_LENGTH=512 * 1024,
)
app.register_blueprint(routes)
app.before_request(enforce_auth)
app.after_request(apply_security_headers)


@app.context_processor
def inject_layout_context():
    """Expose auth state and the active environment to every template.

    The API token is deliberately absent here: browser requests authenticate
    with the session cookie, so the token never reaches the page source.
    """
    environment = "unknown"
    try:
        settings, _ = load_settings()
        environment = settings.environment
    except Exception:
        pass
    return {
        "csrf_token": session_csrf_token(),
        "auth_enabled": session_auth_enabled(),
        "authenticated": is_authenticated(),
        "environment": environment,
        "environment_source": ".env" if environment_override() else "trading.yaml",
    }


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def serve() -> None:
    host = flask_bind_host()
    port = int(os.getenv("FLASK_PORT", "5000"))
    assert_flask_bind_allowed(host, flask_token(), password_hash())

    warning = weak_config_warning(flask_token(), password_hash())
    if warning:
        logging.getLogger("traderbot").warning(warning)

    if _truthy("FLASK_DEV_SERVER"):
        app.run(debug=True, host=host, port=port)
        return

    from waitress import serve as waitress_serve

    logging.getLogger("waitress").setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    waitress_serve(
        app,
        host=host,
        port=port,
        threads=int(os.getenv("WSGI_THREADS", "8")),
        ident="TraderBot",
    )


if __name__ == "__main__":
    serve()
