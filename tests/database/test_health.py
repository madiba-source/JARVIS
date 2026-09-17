from app.database.config import DatabaseConfig
from app.database.health import DatabaseHealthState
from app.database.service import DatabaseService


def test_health_uses_contiguous_authoritative_schema(tmp_path) -> None:
    service = DatabaseService(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))
    assert service.health()["state"] == DatabaseHealthState.NOT_INITIALIZED.value
    service.initialize(); assert service.health()["state"] == DatabaseHealthState.HEALTHY.value
    with service.connection_manager.connection() as conn:
        conn.execute("INSERT INTO schema_migrations(version,description) VALUES(3,'gap')"); conn.commit()
    assert service.health()["state"] == DatabaseHealthState.INCOMPATIBLE.value
