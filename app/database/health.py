import os
from enum import Enum

from .connection import DatabaseConnectionManager
from .integrity import IntegrityChecker, IntegrityStatus
from .migrations import MigrationManager


class DatabaseHealthState(str, Enum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CORRUPT = "CORRUPT"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class DatabaseHealthChecker:
    def __init__(self, config, connection_manager: DatabaseConnectionManager, integrity_checker: IntegrityChecker, migrations: MigrationManager) -> None:
        self.config, self.conn_manager, self.integrity, self.migrations = config, connection_manager, integrity_checker, migrations

    def check_health(self) -> dict[str, str]:
        if not os.path.exists(self.config.db_path):
            return {"state": DatabaseHealthState.NOT_INITIALIZED.value, "message": "database file does not exist"}
        status = self.integrity.check_integrity()
        if status is IntegrityStatus.UNAVAILABLE: return {"state": DatabaseHealthState.UNAVAILABLE.value, "message": "database unavailable"}
        if status is IntegrityStatus.CORRUPT: return {"state": DatabaseHealthState.CORRUPT.value, "message": "database corrupt"}
        try:
            current = self.migrations.get_current_version()
            expected = self.migrations.current_supported_version
            if current != expected: return {"state": DatabaseHealthState.INCOMPATIBLE.value, "message": f"schema {current} != {expected}"}
        except Exception as error:
            return {"state": DatabaseHealthState.INCOMPATIBLE.value, "message": type(error).__name__}
        return {"state": DatabaseHealthState.DEGRADED.value if status is IntegrityStatus.DEGRADED else DatabaseHealthState.HEALTHY.value, "message": "database integrity and schema are valid"}
