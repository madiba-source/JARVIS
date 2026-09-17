# Knowledge Ingestion Operations

Knowledge ingestion is explicit, approved, and policy-gated. It never runs automatically and never scans the home directory.

## Supported inputs

Local text files read through the Phase 04 `filesystem.read_file` gateway (workspace-contained, L0 read-only, audited): `.txt`, `.md`, `.py`, `.js`, `.ts`, `.json`, `.toml`, `.yaml`, `.yml`, `.rst`, `.csv`. Binary files are rejected.

## Required approval

`KnowledgeIngestor.ingest(path, approved=True)` — approval comes from a confirmation-backed executor or trusted UI, never from model arguments. Every read is a normal typed `ToolRequest`; if JARVIS execution is disabled or the path is outside the workspace, the gateway denies and ingestion raises `MemoryRejected`.

## Path screening

Rejected before any read: absolute paths, `..` traversal, unsupported extensions, dotfiles (`.env`), and path components containing `credentials`, `secrets`, `tokens`, `cookies`, `id_rsa`, `id_ed25519`. Content is additionally secret-scanned after read.

## Chunking

Documents are bounded by `max_document_bytes` (default 16 KiB) and `max_chunks` (default 32). Chunks are `chunk_chars` (default 1500) with `chunk_overlap` (default 150). Each chunk preserves `offset_start`/`offset_end`, the document hash, and a deterministic `uuid5` identity derived from (scope, path, document hash, offsets) — re-ingesting the same document is idempotent and returns identical IDs. Provenance records the source kind (`file`), document ID, timestamp, and SHA-256 content hash.

## Indexing

Ingested chunks are ordinary knowledge memories: they persist to SQLite immediately and enter the vector index through the same bounded outbox `sync()` as everything else. No automatic background ingestion of directories occurs; each call handles one explicit file.