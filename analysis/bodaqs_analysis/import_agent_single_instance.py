from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional


_HELD_LOCK_PATHS: set[Path] = set()


def single_instance_lock_path(app_config_path: str | Path) -> Path:
    """Return the per-config lock path used by the desktop import manager."""

    config_path = Path(app_config_path).expanduser().resolve()
    return config_path.with_suffix(config_path.suffix + ".lock")


def _lock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform.startswith("win"):
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform.startswith("win"):
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass
class SingleInstanceLock:
    """Best-effort exclusive lock for one Import Manager config."""

    app_config_path: Path
    lock_path: Path
    _handle: Optional[BinaryIO] = None

    @classmethod
    def for_app_config(cls, app_config_path: str | Path) -> "SingleInstanceLock":
        config_path = Path(app_config_path).expanduser().resolve()
        return cls(app_config_path=config_path, lock_path=single_instance_lock_path(config_path))

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        if self.lock_path in _HELD_LOCK_PATHS:
            return False

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        try:
            _lock_file(handle)
        except OSError:
            handle.close()
            return False

        metadata = {
            "pid": os.getpid(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "app_config_path": str(self.app_config_path),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(metadata, indent=2).encode("utf-8"))
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass

        self._handle = handle
        _HELD_LOCK_PATHS.add(self.lock_path)
        return True

    def release(self) -> None:
        if self._handle is None:
            return

        handle = self._handle
        self._handle = None
        _HELD_LOCK_PATHS.discard(self.lock_path)
        try:
            _unlock_file(handle)
        finally:
            handle.close()

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise RuntimeError(f"BODAQS Import Manager is already running for {self.app_config_path}")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()
