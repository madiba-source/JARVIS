"""SQLite connections behind a reader/maintenance gate."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DatabaseConfig
from .errors import DatabaseConfigurationError, DatabaseConnectionError, DatabaseLockTimeoutError


class DatabaseConnectionManager:
    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or DatabaseConfig()
        self._condition = threading.Condition(threading.RLock())
        self._active_connections = 0
        self._restoring = False
        self._maintenance_owner: int | None = None
        self._initialized = False

    @property
    def active_connections(self) -> int:
        with self._condition:
            return self._active_connections

    @property
    def restoring(self) -> bool:
        with self._condition:
            return self._restoring

    def initialize(self) -> None:
        with self._condition:
            if self._initialized:
                return
            path = Path(self.config.db_path)
            if not str(path):
                raise DatabaseConfigurationError("database path is empty")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._initialized = True

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn: sqlite3.Connection | None = None
        with self._condition:
            if self._restoring:
                raise DatabaseLockTimeoutError("database maintenance is active")
            self.initialize()
            self._active_connections += 1
        try:
            conn = sqlite3.connect(self.config.db_path, timeout=self.config.busy_timeout_ms / 1000, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            if self.config.enable_foreign_keys:
                conn.execute("PRAGMA foreign_keys=ON")
            if self.config.enable_wal:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={self.config.busy_timeout_ms}")
            yield conn
        except sqlite3.Error as error:
            if conn:
                conn.rollback()
            raise DatabaseConnectionError(str(error)) from error
        finally:
            if conn:
                conn.close()
            with self._condition:
                self._active_connections -= 1
                self._condition.notify_all()

    @contextmanager
    def maintenance(self) -> Iterator[None]:
        current = threading.get_ident()
        with self._condition:
            if self._restoring:
                raise DatabaseLockTimeoutError("another maintenance operation is active")
            self._restoring = True
            self._maintenance_owner = current
            end = time.monotonic() + self.config.maintenance_timeout_seconds
            while self._active_connections:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    self._restoring = False
                    self._maintenance_owner = None
                    self._condition.notify_all()
                    raise DatabaseLockTimeoutError("timed out waiting for active database connections")
                self._condition.wait(remaining)
        try:
            yield
        finally:
            with self._condition:
                self._restoring = False
                self._maintenance_owner = None
                self._condition.notify_all()
