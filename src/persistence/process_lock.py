import fcntl
import json
import os
from pathlib import Path


def lock_path_for(db_path: Path) -> Path:
    return Path(db_path).with_suffix(".lock")


class ProcessLockHeld(RuntimeError):
    def __init__(self, path: Path, holder: str, environment: str):
        self.path = Path(path)
        self.holder = holder
        self.environment = environment
        super().__init__(
            f"TraderBot already running ({environment}): lock {self.path} "
            f"held by {holder}. Stop the other process before starting another."
        )


class ProcessLock:
    """Exclusive process lock via flock. The OS releases it if the process dies."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self, environment: str) -> None:
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            holder = handle.read().strip() or "unknown"
            handle.close()
            raise ProcessLockHeld(self.path, holder, environment) from exc
        handle.seek(0)
        handle.truncate()
        payload = {"pid": os.getpid(), "environment": environment}
        handle.write(json.dumps(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        self._fh = handle

    def release(self) -> None:
        handle = self._fh
        if handle is None:
            return
        self._fh = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
