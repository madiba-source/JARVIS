"""Memory migration: SQLite is authoritative; vector work is a durable outbox."""

import sqlite3


def memory_schema(conn: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE memories (
            memory_id TEXT PRIMARY KEY, scope TEXT NOT NULL,
            memory_type TEXT NOT NULL, content_hash TEXT NOT NULL,
            source_id TEXT NOT NULL, fact_key TEXT,
            status TEXT NOT NULL, version INTEGER NOT NULL,
            valid_from TEXT NOT NULL, valid_until TEXT, updated_at TEXT NOT NULL,
            record TEXT,
            index_status TEXT NOT NULL DEFAULT 'pending',
            index_attempts INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX memory_scope_status ON memories(scope,status,updated_at)",
        "CREATE INDEX memory_duplicate ON memories(scope,memory_type,content_hash,source_id)",
        "CREATE INDEX memory_pending ON memories(index_status,index_attempts)",
        """CREATE TABLE memory_versions (
            memory_id TEXT NOT NULL REFERENCES memories(memory_id),
            version INTEGER NOT NULL, record TEXT NOT NULL,
            PRIMARY KEY(memory_id,version))""",
        """CREATE TABLE memory_sources (
            memory_id TEXT PRIMARY KEY REFERENCES memories(memory_id),
            provenance TEXT NOT NULL)""",
        """CREATE TABLE memory_tags (
            memory_id TEXT NOT NULL REFERENCES memories(memory_id),
            tag TEXT NOT NULL, PRIMARY KEY(memory_id,tag))""",
        "CREATE INDEX memory_tag_lookup ON memory_tags(tag,memory_id)",
        """CREATE TABLE memory_relationships (
            source TEXT NOT NULL REFERENCES memories(memory_id),
            target TEXT NOT NULL REFERENCES memories(memory_id),
            kind TEXT NOT NULL, PRIMARY KEY(source,target,kind),
            CHECK(source != target))""",
        """CREATE VIRTUAL TABLE memory_fts USING fts5(
            memory_id UNINDEXED, content, tokenize='unicode61')""",
    )
    for statement in statements:
        conn.execute(statement)


MEMORY_MIGRATIONS = [(2, "memory metadata and bounded vector outbox", memory_schema)]