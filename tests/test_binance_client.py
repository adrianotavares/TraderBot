from unittest.mock import MagicMock, patch

import threading
import time

import requests
from binance.client import Client

from modules.BinanceClient import BinanceClient


def _make_client(**overrides):
    client = BinanceClient.__new__(BinanceClient)
    client.sync = True
    client.verbose = False
    client.sync_interval = 300_000
    client.last_sync_time = 0
    client._sync_failures = 0
    client.timestamp_offset = 0
    client.max_retries = 3
    client.retry_backoff = 0
    client._reset_session = MagicMock()
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def test_sync_failure_does_not_retry_every_request():
    client = _make_client(
        get_server_time=MagicMock(
            side_effect=requests.exceptions.ConnectionError("network down")
        ),
    )

    assert client.sync_time_offset(force=True) is False
    assert client._sync_failures == 1
    assert client.last_sync_time > 0
    assert client.get_server_time.call_count == client.max_retries

    calls_before = client.get_server_time.call_count
    assert client.sync_time_offset(force=False) is False
    assert client.get_server_time.call_count == calls_before


def test_sync_success_resets_failures():
    client = _make_client(
        _sync_failures=2,
        get_server_time=MagicMock(return_value={"serverTime": 1_000_000}),
    )

    with patch("modules.BinanceClient.time.time", return_value=1_000):
        assert client.sync_time_offset(force=True) is True

    assert client._sync_failures == 0
    assert client.timestamp_offset == 0


def test_sync_retries_connection_error_then_succeeds():
    client = _make_client(
        get_server_time=MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError(
                    "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
                ),
                {"serverTime": 1_000_150},
            ]
        ),
    )

    with patch("modules.BinanceClient.time.time", return_value=1_000):
        assert client.sync_time_offset(force=True) is True

    assert client._sync_failures == 0
    assert client.timestamp_offset == 150
    assert client.get_server_time.call_count == 2
    client._reset_session.assert_called_once()


def test_signed_requests_are_serialized():
    client = _make_client(
        last_sync_time=int(time.time() * 1000),
        sync_interval=10**12,
        timestamp_offset=0,
        _request_lock=threading.RLock(),
    )
    in_flight = 0
    max_in_flight = 0
    guard = threading.Lock()

    def fake_request(*_args, **_kwargs):
        nonlocal in_flight, max_in_flight
        with guard:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with guard:
            in_flight -= 1
        return {"ok": True}

    with patch.object(Client, "_request", fake_request):
        threads = [
            threading.Thread(
                target=lambda: client._request("GET", "/api/v3/account", True, data={})
            )
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert max_in_flight == 1
