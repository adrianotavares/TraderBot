import logging
import time

from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger(__name__)


class BinanceClient(Client):
    RETRYABLE_CODES = {-1003, -1006, -1007, -1021, -1099}
    DEFAULT_RECV_WINDOW = 10000

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        requests_params=None,
        tld="com",
        base_endpoint=Client.BASE_ENDPOINT_DEFAULT,
        testnet=False,
        private_key=None,
        private_key_pass=None,
        sync=True,
        ping=True,
        verbose=False,
        sync_interval=60000,
        max_retries=3,
        retry_backoff=1.0,
    ):
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            requests_params=requests_params,
            tld=tld,
            base_endpoint=base_endpoint,
            testnet=testnet,
            private_key=private_key,
            private_key_pass=private_key_pass,
        )

        self.sync = sync
        self.verbose = verbose
        self.sync_interval = sync_interval
        self.last_sync_time = 0
        self._sync_failures = 0
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.testnet = testnet

        if self.sync:
            self._sync_time_offset_with_retry()

        if ping:
            self.ping()

    def _sync_time_offset_with_retry(self):
        for attempt in range(1, self.max_retries + 1):
            if self.sync_time_offset(force=True):
                return
            if attempt < self.max_retries:
                time.sleep(self.retry_backoff * attempt)

    def sync_time_offset(self, force=False) -> bool:
        current_time = int(time.time() * 1000)
        if not force and self._sync_failures > 0:
            backoff_ms = min(self._sync_failures * 5000, self.sync_interval)
            if current_time - self.last_sync_time < backoff_ms:
                return False

        if force or (current_time - self.last_sync_time >= self.sync_interval):
            try:
                server_time = self.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.timestamp_offset = server_time - local_time
                self.last_sync_time = current_time
                self._sync_failures = 0
                if self.verbose:
                    logger.info("Time offset synced: %sms", self.timestamp_offset)
                return True
            except Exception as e:
                self._sync_failures += 1
                self.last_sync_time = current_time
                logger.warning(
                    "Failed to sync time offset (failure %s): %s",
                    self._sync_failures,
                    e,
                )
                return False
        return False

    def _request(self, method, uri: str, signed: bool, force_params: bool = False, **kwargs):
        if signed:
            current_time = int(time.time() * 1000)
            if self.sync and (
                self.timestamp_offset is None or abs(self.timestamp_offset) > 1000
            ):
                self.sync_time_offset(force=True)
            elif self.sync and (current_time - self.last_sync_time >= self.sync_interval):
                self.sync_time_offset()

            kwargs.setdefault("data", {})
            kwargs["data"].setdefault("recvWindow", self.DEFAULT_RECV_WINDOW)
            kwargs["data"]["timestamp"] = int(time.time() * 1000 + self.timestamp_offset)

        attempt = 0
        while True:
            try:
                return super()._request(method, uri, signed, force_params, **kwargs)
            except BinanceAPIException as e:
                if e.code == -1021:
                    self.sync_time_offset(force=True)
                    if signed:
                        kwargs["data"]["timestamp"] = int(
                            time.time() * 1000 + self.timestamp_offset
                        )
                    attempt += 1
                    if attempt > self.max_retries:
                        raise
                    time.sleep(self.retry_backoff * attempt)
                    continue
                if e.code in self.RETRYABLE_CODES and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self.retry_backoff * attempt)
                    continue
                raise
