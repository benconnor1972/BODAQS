"""One opportunistic worker with explicit foreground priority."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable


class IdleCacheWarmer:
    def __init__(self, adapter: Callable[[], Any], *, read_only: bool = False, idle_seconds: float = 5.0) -> None:
        self.adapter = adapter
        self.read_only = read_only
        self.enabled = not read_only
        self.idle_seconds = idle_seconds
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._foreground = 0
        self._last_activity = time.monotonic()
        self._running = False
        self._current: str | None = None
        self._completed = 0
        self._failed = 0
        self._error: str | None = None
        self._cursor = 0
        self._tasks: list[dict[str, Any]] = []
        self._plan_adapter: Any = None
        self._plan_time = 0.0

    def start(self) -> None:
        if self._thread is None and not self.read_only:
            self._thread = threading.Thread(target=self._loop, name="BODAQSCacheWarmer", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # Finish the current unit before disposal; never start another.
            self._thread.join()

    def set_enabled(self, enabled: bool) -> None:
        with self._condition:
            self.enabled = bool(enabled) and not self.read_only
            self._last_activity = time.monotonic()

    def status(self) -> dict[str, Any]:
        with self._condition:
            state = "warming" if self._running else "disabled" if not self.enabled else "waiting" if self._foreground else "idle"
            return {"enabled": self.enabled, "read_only": self.read_only, "state": state,
                    "current": self._current, "completed_units": self._completed,
                    "failed_units": self._failed, "last_error": self._error,
                    "foreground_count": self._foreground, "idle_seconds": self.idle_seconds}

    def _arrive(self) -> None:
        with self._condition:
            self._foreground += 1
            self._last_activity = time.monotonic()
            self._condition.notify_all()

    def _leave(self) -> None:
        with self._condition:
            self._foreground -= 1
            self._last_activity = time.monotonic()
            self._condition.notify_all()

    @asynccontextmanager
    async def foreground(self):
        self._arrive()
        try:
            while True:
                with self._condition:
                    running = self._running
                if not running:
                    break
                await asyncio.sleep(0.01)
            yield
        finally:
            self._leave()

    @contextmanager
    def foreground_sync(self):
        self._arrive()
        try:
            with self._condition:
                self._condition.wait_for(lambda: not self._running)
            yield
        finally:
            self._leave()

    def run_one(self) -> bool:
        with self._condition:
            if self._stop.is_set() or not self.enabled or self._foreground or self._running or time.monotonic() - self._last_activity < self.idle_seconds:
                return False
            self._running = True
        try:
            adapter = self.adapter()
            if adapter is not self._plan_adapter or (self._cursor >= len(self._tasks) and time.monotonic() - self._plan_time >= 60):
                self._tasks = adapter.cache_warming_tasks()
                self._cursor = 0
                self._plan_time = time.monotonic()
                self._plan_adapter = adapter
            if self._cursor >= len(self._tasks):
                return False
            with self._condition:
                if self._foreground or not self.enabled or self._stop.is_set():
                    return False
            task = self._tasks[self._cursor]
            self._cursor += 1
            with self._condition:
                self._current = task["kind"]
            outcome = adapter.warm_cache_task(task)
            if outcome == "built":
                with self._condition:
                    self._completed += 1
            return True
        except Exception as exc:
            with self._condition:
                self._failed += 1
                self._error = str(exc)
                self._last_activity = time.monotonic()
            return False
        finally:
            with self._condition:
                self._running = False
                self._current = None
                self._condition.notify_all()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            self.run_one()
