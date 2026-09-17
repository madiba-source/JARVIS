import pytest
from pydantic import ValidationError

from app.database.config import DatabaseConfig


def test_config_defaults_and_normalization() -> None:
    assert DatabaseConfig().db_path == "data/jarvis.db"
    assert DatabaseConfig(db_path="  test.db ").db_path == "test.db"
    with pytest.raises(ValidationError): DatabaseConfig(db_path="   ")
    with pytest.raises(ValidationError): DatabaseConfig(db_path="x\x00y")
    with pytest.raises(ValidationError): DatabaseConfig(backup_directory="data")
    with pytest.raises(ValidationError): DatabaseConfig(maintenance_timeout_seconds=0)
