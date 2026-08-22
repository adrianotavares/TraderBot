import multiprocessing
from pathlib import Path

import pytest

from persistence.process_lock import ProcessLock, ProcessLockHeld, lock_path_for


def _hold_lock(path: str, ready, release):
    lock = ProcessLock(Path(path))
    lock.acquire("testnet")
    ready.set()
    release.wait(timeout=10)
    lock.release()


def test_lock_path_for_db():
    assert lock_path_for(Path("/tmp/traderbot.db")) == Path("/tmp/traderbot.lock")


def test_second_process_cannot_acquire(tmp_path):
    path = tmp_path / "traderbot.lock"
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    holder = multiprocessing.Process(
        target=_hold_lock, args=(str(path), ready, release)
    )
    holder.start()
    try:
        assert ready.wait(5)
        lock = ProcessLock(path)
        with pytest.raises(ProcessLockHeld) as exc:
            lock.acquire("mainnet")
        assert "testnet" in str(exc.value)
        assert "pid=" in exc.value.holder or "pid" in exc.value.holder
    finally:
        release.set()
        holder.join(timeout=5)
        assert holder.exitcode == 0


def test_acquire_after_release(tmp_path):
    path = tmp_path / "traderbot.lock"
    first = ProcessLock(path)
    first.acquire("testnet")
    first.release()
    second = ProcessLock(path)
    second.acquire("testnet")
    second.release()
