from app.database.config import DatabaseConfig
from app.database.connection import DatabaseConnectionManager
from app.database.integrity import IntegrityChecker, IntegrityStatus


def test_integrity_check(tmp_path) -> None:
    manager = DatabaseConnectionManager(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))
    manager.initialize()
    assert IntegrityChecker(manager).check_integrity() is IntegrityStatus.HEALTHY
