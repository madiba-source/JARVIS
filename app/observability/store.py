"""Local SQLite persistence using the canonical sanitized event payload."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .config import ObservabilityConfig
from .events import StructuredEvent
from .logging import event_to_dict
from .redaction import redact_sensitive_data


class SQLiteEventStore:
    def __init__(self, config: ObservabilityConfig | None = None) -> None:
        self.config = config or ObservabilityConfig()
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        if self.config.sqlite_path:
            self.config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.config.sqlite_path, check_same_thread=False, timeout=5)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL)")
            self._conn.commit()

    def store_event(self, event: StructuredEvent, safe_payload: dict[str, Any] | None = None) -> bool:
        if self._conn is None:
            return False
        try:
            payload = safe_payload or redact_sensitive_data(event_to_dict(event), max_bytes=self.config.max_event_payload_bytes)
            encoded = json.dumps(payload, sort_keys=True, default=str, allow_nan=False)
            if len(encoded.encode()) > self.config.max_event_payload_bytes:
                return False
            with self._lock:
                self._conn.execute("INSERT OR REPLACE INTO events(event_id,timestamp,event_type,payload) VALUES(?,?,?,?)", (event.event_id, event.timestamp.isoformat(), event.event_type.value, encoded))
                self._conn.execute("DELETE FROM events WHERE rowid NOT IN (SELECT rowid FROM events ORDER BY timestamp DESC LIMIT ?)", (self.config.max_sqlite_rows,))
                self._conn.commit()
            return True
        except (sqlite3.Error, ValueError, TypeError):
            return False

    def query_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM events ORDER BY timestamp DESC LIMIT ?", (min(limit, self.config.max_sqlite_rows),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def health(self) -> str:
        if self._conn is None:
            return "disabled"
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return "ok"
        except sqlite3.Error:
            return "failed"

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.close(); self._conn = None
