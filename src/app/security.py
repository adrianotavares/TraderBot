import hmac
import os

from flask import jsonify, request

LOCAL_BIND = frozenset({"127.0.0.1", "localhost", "::1"})
TOKEN_HEADER = "X-TraderBot-Token"
PROTECTED_PATHS = frozenset({"/update-config", "/get-config"})


def flask_token() -> str:
    return os.getenv("FLASK_TOKEN", "").strip()


def flask_bind_host() -> str:
    return (os.getenv("FLASK_HOST", "127.0.0.1") or "127.0.0.1").strip()


def is_local_bind(host: str) -> bool:
    return (host or "127.0.0.1").strip() in LOCAL_BIND


def assert_flask_bind_allowed(host: str, token: str) -> None:
    if not is_local_bind(host) and not (token or "").strip():
        raise SystemExit(
            f"FLASK_TOKEN is required when FLASK_HOST={host} (not localhost)."
        )


def is_protected_path(path: str) -> bool:
    return path.startswith("/api/") or path in PROTECTED_PATHS


def extract_request_token() -> str:
    header = request.headers.get(TOKEN_HEADER, "") or ""
    auth = request.headers.get("Authorization", "") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    query = request.args.get("token", "") or ""
    return (header or bearer or query).strip()


def tokens_match(provided: str, expected: str) -> bool:
    provided = provided or ""
    expected = expected or ""
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def enforce_token():
    token = flask_token()
    if not token or not is_protected_path(request.path):
        return None
    if tokens_match(extract_request_token(), token):
        return None
    return jsonify({"error": "Unauthorized"}), 401
