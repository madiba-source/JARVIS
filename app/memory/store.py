"""Parameterized structured persistence behind DatabaseService.

All mutation transactions acquire a SQLite write reservation before checking
quotas/versions. Tombstones retain identifiers, not deleted content.
"""

from __future__ import annotations

import re
from uuid import UUID

from app.database.service import DatabaseService

from .config import MemoryConfig
from .models import IndexStatus, MemoryRecord, Query, Relationship, Scope, Status, now


def scope_key(scope: Scope) -> str:
    return scope.model_dump_json()


class MemoryStore:
    def __init__(self, database: DatabaseService, config: MemoryConfig) -> None:
        self.database, self.config = database, config

    @staticmethod
    def decode(row) -> MemoryRecord | None:
        if row is None or row["record"] is None:
            return None
        record = MemoryRecord.model_validate_json(row["record"])
        return MemoryRecord.model_validate({
            **record.model_dump(), "status": row["status"],
            "index_status": row["index_status"],
        })

    def get(self, scope: Scope, memory_id: UUID) -> MemoryRecord | None:
        with self.database.transaction() as conn:
            return self.decode(conn.execute(
                "SELECT * FROM memories WHERE memory_id=? AND scope=? AND status!='deleted'",
                (str(memory_id), scope_key(scope)),
            ).fetchone())

    @staticmethod
    def _save(conn, record: MemoryRecord) -> None:
        identity = str(record.memory_id)
        conn.execute(
            """INSERT INTO memories(memory_id,scope,memory_type,content_hash,source_id,
               fact_key,status,version,valid_from,valid_until,updated_at,record,index_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(memory_id) DO UPDATE SET
               memory_type=excluded.memory_type,content_hash=excluded.content_hash,
               source_id=excluded.source_id,fact_key=excluded.fact_key,
               status=excluded.status,version=excluded.version,
               valid_from=excluded.valid_from,valid_until=excluded.valid_until,
               updated_at=excluded.updated_at,record=excluded.record,
               index_status='pending',index_attempts=0""",
            (identity, scope_key(record.scope), record.memory_type.value, record.content_hash,
             record.provenance.source_id, record.fact_key, record.status.value, record.version,
             record.valid_from.isoformat(), record.valid_until.isoformat() if record.valid_until else None,
             record.updated_at.isoformat(), record.model_dump_json(), record.index_status.value),
        )
        conn.execute("INSERT OR REPLACE INTO memory_sources VALUES(?,?)",
                     (identity, record.provenance.model_dump_json()))
        conn.execute("DELETE FROM memory_tags WHERE memory_id=?", (identity,))
        conn.executemany("INSERT INTO memory_tags VALUES(?,?)", [(identity, tag) for tag in sorted(set(record.tags))])
        conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (identity,))
        if record.status is Status.ACTIVE:
            conn.execute("INSERT INTO memory_fts VALUES(?,?)", (identity, record.normalized_content))

    def put(self, record: MemoryRecord, expected_version: int | None = None) -> MemoryRecord:
        with self.database.transaction() as conn:
            # TransactionContext already starts a transaction; force a write lock.
            conn.execute("UPDATE memories SET version=version WHERE memory_id=?", (str(record.memory_id),))
            old_row = conn.execute("SELECT * FROM memories WHERE memory_id=?", (str(record.memory_id),)).fetchone()
            if expected_version is not None:
                if (old_row is None or old_row["status"] != "active"
                        or old_row["scope"] != scope_key(record.scope)
                        or old_row["version"] != expected_version):
                    raise ValueError("stale or inaccessible memory version")
                if record.version != expected_version + 1 or record.version > self.config.max_versions:
                    raise ValueError("version limit")
                conn.execute("INSERT INTO memory_versions VALUES(?,?,?)",
                             (str(record.memory_id), expected_version, old_row["record"]))
            else:
                if old_row is not None:
                    # Never resurrect a tombstone through import or document reingestion.
                    if old_row["status"] == "deleted":
                        raise ValueError("deleted identifier cannot be reused")
                    old = self.decode(old_row)
                    if old.scope == record.scope and old.content_hash == record.content_hash:
                        return old
                    raise ValueError("duplicate identifier conflict")
                duplicate = conn.execute(
                    """SELECT * FROM memories WHERE scope=? AND memory_type=? AND content_hash=?
                       AND source_id=? AND status='active' AND
                       (valid_until IS NULL OR valid_until>?) LIMIT 1""",
                    (scope_key(record.scope), record.memory_type.value, record.content_hash,
                     record.provenance.source_id, now().isoformat()),
                ).fetchone()
                if duplicate:
                    return self.decode(duplicate)
                if conn.execute("SELECT count(*) FROM memories").fetchone()[0] >= self.config.max_records:
                    raise ValueError("memory capacity reached")
            self._save(conn, record)
            if record.fact_key:
                conflicts = conn.execute(
                    """SELECT memory_id FROM memories WHERE scope=? AND fact_key=?
                       AND memory_id!=? AND status='active' AND content_hash!=?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (scope_key(record.scope), record.fact_key, str(record.memory_id),
                     record.content_hash, self.config.max_relationships),
                ).fetchall()
                for row in conflicts:
                    conn.execute("INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?)",
                                 (str(record.memory_id), row[0], "contradicts"))
            return record

    def list(self, scope: Scope, limit: int, status: Status = Status.ACTIVE) -> tuple[MemoryRecord, ...]:
        limit = min(max(1, limit), self.config.max_transfer_records)
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE scope=? AND status=? ORDER BY updated_at DESC,memory_id LIMIT ?",
                (scope_key(scope), status.value, limit),
            ).fetchall()
            return tuple(record for row in rows if (record := self.decode(row)) is not None)

    def candidates(self, scope: Scope, query: Query, dense_ids: tuple[str, ...]) -> tuple[MemoryRecord, ...]:
        tokens = re.findall(r"\w+", query.text.casefold())[:32]
        match = " OR ".join('"' + token + '"' for token in tokens)
        clauses = ["m.scope=?", "m.status='active'", "m.valid_from<=?",
                   "(m.valid_until IS NULL OR m.valid_until>?)"]
        current = now().isoformat()
        parameters = [scope_key(scope), current, current]
        if query.types:
            clauses.append("m.memory_type IN (" + ",".join("?" for _ in query.types) + ")")
            parameters.extend(item.value for item in query.types)
        if query.source_id:
            clauses.append("m.source_id=?")
            parameters.append(query.source_id)
        if query.since:
            clauses.append("m.updated_at>=?")
            parameters.append(query.since.isoformat())
        if query.until:
            clauses.append("m.updated_at<=?")
            parameters.append(query.until.isoformat())
        for tag in query.tags:
            clauses.append("EXISTS(SELECT 1 FROM memory_tags t WHERE t.memory_id=m.memory_id AND t.tag=?)")
            parameters.append(tag)
        where = " AND ".join(clauses)
        with self.database.transaction() as conn:
            # All lexical filters apply before the bounded candidate LIMIT.
            rows = []
            if match:
                rows = conn.execute(
                    f"""SELECT m.* FROM memory_fts JOIN memories m ON m.memory_id=memory_fts.memory_id
                       WHERE memory_fts MATCH ? AND {where}
                       ORDER BY bm25(memory_fts),m.updated_at DESC LIMIT ?""",
                    (match, *parameters, self.config.max_candidates),
                ).fetchall()
            ids = tuple(dict.fromkeys(dense_ids[:self.config.max_candidates]))
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows += conn.execute(
                    f"SELECT m.* FROM memories m WHERE {where} AND m.memory_id IN ({placeholders})",
                    (*parameters, *ids),
                ).fetchall()
            unique = {}
            for row in rows:
                record = self.decode(row)
                if record is not None:
                    unique[str(record.memory_id)] = record
            return tuple(unique.values())[:self.config.max_candidates * 2]

    def transition(self, scope: Scope, memory_id: UUID, status: Status) -> bool:
        if status is Status.ACTIVE:
            raise ValueError("reactivation requires an explicit new candidate")
        with self.database.transaction() as conn:
            conn.execute("UPDATE memories SET version=version WHERE memory_id=?", (str(memory_id),))
            row = conn.execute("SELECT * FROM memories WHERE memory_id=? AND scope=? AND status!='deleted'",
                               (str(memory_id), scope_key(scope))).fetchone()
            if row is None:
                return False
            record = self.decode(row)
            conn.execute(
                """UPDATE memories SET status=?,record=?,updated_at=?,index_status='pending',
                   index_attempts=0 WHERE memory_id=?""",
                (status.value, None if status is Status.DELETED else record.model_dump_json(),
                 now().isoformat(), str(memory_id)),
            )
            conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (str(memory_id),))
            if status is Status.DELETED:
                for table in ("memory_versions", "memory_sources", "memory_tags"):
                    conn.execute(f"DELETE FROM {table} WHERE memory_id=?", (str(memory_id),))
                conn.execute("DELETE FROM memory_relationships WHERE source=? OR target=?",
                             (str(memory_id), str(memory_id)))
            return True

    def relate(self, scope: Scope, relationship: Relationship) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE memories SET version=version WHERE memory_id=?", (str(relationship.source),))
            for identity in (relationship.source, relationship.target):
                if conn.execute("SELECT 1 FROM memories WHERE memory_id=? AND scope=? AND status='active'",
                                (str(identity), scope_key(scope))).fetchone() is None:
                    raise ValueError("relationship endpoint inaccessible")
            count = conn.execute("SELECT count(*) FROM memory_relationships WHERE source=?",
                                 (str(relationship.source),)).fetchone()[0]
            if count >= self.config.max_relationships:
                raise ValueError("relationship limit")
            conn.execute("INSERT OR IGNORE INTO memory_relationships VALUES(?,?,?)",
                         (str(relationship.source), str(relationship.target), relationship.kind.value))

    def relationships(self, scope: Scope, memory_id: UUID) -> tuple[Relationship, ...]:
        if self.get(scope, memory_id) is None:
            return ()
        with self.database.transaction() as conn:
            return tuple(Relationship(source=row[0], target=row[1], kind=row[2]) for row in conn.execute(
                "SELECT source,target,kind FROM memory_relationships WHERE source=? OR target=? LIMIT ?",
                (str(memory_id), str(memory_id), self.config.max_relationships),
            ))

    def pending(self) -> tuple:
        with self.database.transaction() as conn:
            return tuple(conn.execute(
                """SELECT * FROM memories WHERE index_status!='indexed' AND index_attempts<?
                   ORDER BY index_attempts,updated_at,memory_id LIMIT ?""",
                (self.config.index_attempts, self.config.index_batch),
            ).fetchall())

    def index_result(self, memory_id: str, version: int, status: str, success: bool) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                """UPDATE memories SET index_status=?,index_attempts=index_attempts+1
                   WHERE memory_id=? AND version=? AND status=?""",
                ("indexed" if success else "failed", memory_id, version, status),
            )

    def reset_index(self) -> None:
        """Trusted maintenance only. Caller must first clear/recreate its index."""
        with self.database.transaction() as conn:
            conn.execute("UPDATE memories SET index_status='pending',index_attempts=0")

    def expire(self) -> int:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT memory_id FROM memories WHERE status='active' AND valid_until<=? LIMIT ?",
                (now().isoformat(), self.config.index_batch),
            ).fetchall()
            for row in rows:
                conn.execute("UPDATE memories SET status='expired',index_status='pending',index_attempts=0 WHERE memory_id=?", (row[0],))
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (row[0],))
            return len(rows)