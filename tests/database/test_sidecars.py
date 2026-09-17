import shutil

import pytest

from app.database.config import DatabaseConfig
from app.database.errors import DatabaseRestoreError
from app.database.service import DatabaseService


def test_restore_failure_rolls_back_wal_and_shm_sidecars(tmp_path, monkeypatch) -> None:
    db = tmp_path / "active.sqlite"
    service = DatabaseService(DatabaseConfig(db_path=str(db), backup_directory=str(tmp_path / "backups")))
    service.initialize()
    backup = service.backup()
    wal = db.with_name(f"{db.name}-wal")
    shm = db.with_name(f"{db.name}-shm")
    wal.write_text("wal-state")
    shm.write_text("shm-state")

    def fail_copy(source, destination):
        raise OSError("injected copy failure")

    monkeypatch.setattr(shutil, "copy2", fail_copy)
    with pytest.raises(DatabaseRestoreError):
        service.restore(backup)
    assert wal.read_text() == "wal-state"
    assert shm.read_text() == "shm-state"
