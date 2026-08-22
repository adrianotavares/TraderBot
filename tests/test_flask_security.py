import pytest

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from security import assert_flask_bind_allowed, is_protected_path, tokens_match


def test_local_bind_allows_empty_token():
    assert_flask_bind_allowed("127.0.0.1", "")
    assert_flask_bind_allowed("localhost", "")
    assert_flask_bind_allowed("::1", "")


def test_public_bind_requires_token():
    with pytest.raises(SystemExit):
        assert_flask_bind_allowed("0.0.0.0", "")
    assert_flask_bind_allowed("0.0.0.0", "secret")


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
