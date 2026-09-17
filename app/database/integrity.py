import sqlite3
from enum import Enum

from .connection import DatabaseConnectionManager


class IntegrityStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CORRUPT = "CORRUPT"
    UNAVAILABLE = "UNAVAILABLE"


class IntegrityChecker:
    def __init__(self, connection_manager: DatabaseConnectionManager) -> None:
        self.conn_manager = connection_manager

    def check_integrity(self) -> IntegrityStatus:
        try:
            with self.conn_manager.connection() as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    return IntegrityStatus.CORRUPT
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    return IntegrityStatus.DEGRADED
                return IntegrityStatus.HEALTHY
        except (sqlite3.Error, OSError):
            return IntegrityStatus.UNAVAILABLE
