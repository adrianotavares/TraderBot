from unittest.mock import MagicMock, patch

from modules.BinanceClient import BinanceClient


def test_sync_failure_does_not_retry_every_request():
    client = BinanceClient.__new__(BinanceClient)
    client.sync = True
    client.verbose = False
    client.sync_interval = 30000
    client.last_sync_time = 0
    client._sync_failures = 0
    client.timestamp_offset = 0
    client.get_server_time = MagicMock(side_effect=ConnectionError("network down"))

    assert client.sync_time_offset(force=True) is False
    assert client._sync_failures == 1
    assert client.last_sync_time > 0

    calls_before = client.get_server_time.call_count
    assert client.sync_time_offset(force=False) is False
    assert client.get_server_time.call_count == calls_before


def test_sync_success_resets_failures():
    client = BinanceClient.__new__(BinanceClient)
    client.sync = True
    client.verbose = False
    client.sync_interval = 30000
    client.last_sync_time = 0
    client._sync_failures = 2
    client.timestamp_offset = 0
    client.get_server_time = MagicMock(return_value={"serverTime": 1_000_000})

    with patch("modules.BinanceClient.time.time", return_value=1_000):
        assert client.sync_time_offset(force=True) is True

    assert client._sync_failures == 0
    assert client.timestamp_offset == 0
