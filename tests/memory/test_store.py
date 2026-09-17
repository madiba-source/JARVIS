from datetime import timedelta
from uuid import uuid4

import pytest

from app.database.config import DatabaseConfig
from app.database.errors import DatabaseTransactionError
from app.database.service import DatabaseService
from app.memory.config import MemoryConfig
from app.memory.migration import MEMORY_MIGRATIONS
from app.memory.models import Candidate, MemoryRecord, Provenance, Query, Scope, Status, digest, normalize, now
from app.memory.store import MemoryStore


def build(tmp_path, **limits):
    database = DatabaseService(DatabaseConfig(db_path=str(tmp_path / "memory.sqlite"),
                                              backup_directory=str(tmp_path / "backups")),
                               extension_migrations=MEMORY_MIGRATIONS)
    database.initialize()
    return MemoryStore(database, MemoryConfig(**limits))


def record(content="Architecture uses SQLite", scope=None, **kwargs):
    candidate = Candidate(content=content, memory_type="project",
                          provenance=Provenance(kind="user_statement", source_id="user", source_timestamp=now()),
                          **kwargs)
    return MemoryRecord(**candidate.model_dump(), scope=scope or Scope(namespace="project", project_id="jarvis"),
                        normalized_content=normalize(content), content_hash=digest(normalize(content)))


def test_storage_search_dedup_and_scope(tmp_path):
    store = build(tmp_path)
    item = store.put(record())
    assert store.put(record()).memory_id == item.memory_id
    assert store.get(item.scope, item.memory_id) == item
    assert store.get(Scope(namespace="other"), item.memory_id) is None
    assert store.candidates(item.scope, Query(text="SQLite"), ()) == (item,)
    assert store.candidates(Scope(namespace="other"), Query(text="SQLite"), ()) == ()


def test_delete_purges_history_and_prevents_resurrection(tmp_path):
    store = build(tmp_path)
    item = store.put(record())
    assert store.transition(item.scope, item.memory_id, Status.DELETED)
    assert store.get(item.scope, item.memory_id) is None
    assert store.candidates(item.scope, Query(text="SQLite"), (str(item.memory_id),)) == ()
    with pytest.raises(DatabaseTransactionError):
        store.put(item)
    with store.database.transaction() as conn:
        assert conn.execute("SELECT record FROM memories").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM memory_sources").fetchone()[0] == 0


def test_version_cas_and_quota(tmp_path):
    store = build(tmp_path, max_records=1)
    item = store.put(record())
    replacement = record("Architecture uses WAL")
    replacement = MemoryRecord.model_validate({
        **replacement.model_dump(), "memory_id": item.memory_id, "version": 2,
        "created_at": item.created_at,
    })
    assert store.put(replacement, expected_version=1).version == 2
    with pytest.raises(DatabaseTransactionError):
        store.put(replacement, expected_version=1)
    with pytest.raises(DatabaseTransactionError):
        store.put(record("different"))


def test_backup_rebuild_and_expiry(tmp_path):
    store = build(tmp_path)
    item = store.put(record(valid_from=now() - timedelta(hours=2), valid_until=now() - timedelta(hours=1)))
    backup = store.database.backup()
    assert store.expire() == 1
    assert store.get(item.scope, item.memory_id).status is Status.EXPIRED
    assert store.database.restore(backup)
    store.reset_index()
    assert len(store.pending()) == 1


@pytest.mark.parametrize("updates", [
    {"content": "x" * 8193}, {"content": "\x00"},
    {"memory_type": "authority"}, {"valid_from": "2026-01-01"},
    {"tags": ("../../secrets",)}, {"importance": float("nan")},
])
def test_invalid_candidates(updates):
    with pytest.raises(ValueError):
        Candidate.model_validate({
            "content": "fact", "memory_type": "semantic",
            "provenance": {"kind": "user_statement", "source_id": "user", "source_timestamp": now()},
            **updates,
        })