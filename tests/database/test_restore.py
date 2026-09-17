import threading
import time

import pytest

from app.database.config import DatabaseConfig
from app.database.errors import DatabaseLockTimeoutError, DatabaseRestoreError
from app.database.service import DatabaseService


def build_service(tmp_path):
    return DatabaseService(DatabaseConfig(db_path=str(tmp_path / "active.sqlite"), backup_directory=str(tmp_path / "backups"), maintenance_timeout_seconds=2))


def test_backup_restore_and_rollback(tmp_path) -> None:
    service = build_service(tmp_path); service.initialize()
    with service.transaction() as conn:
        conn.execute("CREATE TABLE items(value TEXT)"); conn.execute("INSERT INTO items VALUES('original')")
    backup = service.backup()
    with service.transaction() as conn: conn.execute("UPDATE items SET value='changed'")
    assert service.restore(backup)
    with service.transaction() as conn: assert conn.execute("SELECT value FROM items").fetchone()[0] == "original"
    with pytest.raises(DatabaseRestoreError): service.restore(str(tmp_path / "missing.db"))


def test_unique_staging_ignores_stale_state(tmp_path) -> None:
    service = build_service(tmp_path); service.initialize(); backup = service.backup()
    stale = tmp_path / "restore-staging" / "stale"; stale.mkdir(parents=True); (stale / "active.sqlite").write_text("stale")
    assert service.restore(backup)
    assert stale.exists()


def test_new_transaction_rejected_during_restore_gate(tmp_path) -> None:
    service = build_service(tmp_path); service.initialize()
    entered = threading.Event(); release = threading.Event()
    def hold():
        with service.transaction():
            entered.set(); release.wait(2)
    worker = threading.Thread(target=hold); worker.start(); assert entered.wait(1)
    result = {}
    entered_maintenance = threading.Event(); release_maintenance = threading.Event()
    def restore():
        try:
            with service.connection_manager.maintenance():
                entered_maintenance.set(); release_maintenance.wait(2)
        except Exception as error: result["error"] = error
    restore_thread = threading.Thread(target=restore); restore_thread.start()
    deadline = time.monotonic() + 1
    while not service.connection_manager.restoring and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.connection_manager.restoring
    with pytest.raises(DatabaseLockTimeoutError):
        with service.connection_manager.connection(): pass
    release.set(); worker.join(2); assert entered_maintenance.wait(1); release_maintenance.set(); restore_thread.join(2)
    assert "error" not in result


def test_simultaneous_restore_is_rejected(tmp_path) -> None:
    service = build_service(tmp_path); service.initialize(); backup = service.backup()
    with service.connection_manager.maintenance():
        with pytest.raises(DatabaseLockTimeoutError):
            with service.connection_manager.maintenance(): pass
