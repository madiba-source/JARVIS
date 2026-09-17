# Memory Operations

Phase 05 memory is local-first, SQLite-authoritative, and bounded. All code lives in `app/memory/`.

## Architecture

- `models.py` — frozen pydantic schemas at the trust boundary (`Candidate`, `MemoryRecord`, `Query`, `Retrieval`, `Provenance`, `Scope`). Extra fields are forbidden; timestamps must be timezone-aware and UTC-normalized; content is size- and control-character-bounded.
- `config.py` — `MemoryConfig` with finite validated limits (no unlimited values, no disable switch).
- `migration.py` — migration version 2 (registered through `DatabaseService(extension_migrations=...)`): `memories`, `memory_versions`, `memory_sources`, `memory_tags`, `memory_relationships`, and the `memory_fts` FTS5 lexical index.
- `store.py` — parameterized SQL only. Scope, status, and validity filters apply inside SQL before bounded candidate limits. Deletion writes a tombstone (identifiers only) and purges versions/sources/tags/relationships/FTS rows.
- `service.py` — governance: normalization, classification, validation, sensitivity checks, deduplication, persistence, indexing hooks, audit events, rate/concurrency limits.
- `index.py` — explicit single-job Qdrant synchronization (outbox pattern via `index_status`/`index_attempts`).
- `embeddings.py` — loopback-only Ollama MiniLM provider.
- `context.py` — bounded data-only context assembly and extractive conversation compression.
- `ingestion.py` — explicit, policy-gated document ingestion.
- `capabilities.py` — typed model-facing memory operations registered in the Phase 04 gateway.
- `transfer.py` — bounded JSON export/import.
- `runtime.py` — composition with graceful no-memory degradation.

## Memory types and lifecycle

Types: `working`, `conversation`, `project`, `preference`, `knowledge`, `episodic`, `semantic`, `procedural`.

- Working memory is in-process only, capped (`max_working_records`), TTL-expiring, never persisted.
- Conversation memory requires a matching conversation scope and carries a TTL ceiling.
- Project memory requires a project scope. Preference memory requires direct user provenance and confidence ≥ 0.8; derived preferences are discarded.
- Lifecycle states: `active`, `expired`, `archived`, `deleted`. Corrections create a new version (CAS on `expected_version`, capped at `max_versions`); the old version is retained in `memory_versions`. Deletion is a tombstone; deleted IDs can never be reused, so imports cannot resurrect deleted content.

## Governance

Every write passes: candidate → normalization → classification → validation → sensitivity check → deduplication → persistence → indexing → audit. Persistent writes require `approved=True`, supplied only by confirmation-backed executors or trusted UI; it is absent from model-facing schemas. Model-derived candidates are forced to `assistant_derived` provenance with capped confidence (≤ 0.7) and authority (≤ 0.4). Secret-like content (passwords, API keys, tokens, private keys, JWTs, including NFKC/zero-width evasions) is rejected. Exact duplicates (scope + type + content hash + source) return the existing record.

## Storage roles

SQLite is the only authoritative store. Qdrant is a rebuildable index: records carry `index_status` (`pending`/`indexed`/`failed`/`stale` semantics via attempts) and `index_attempts` (bounded at `index_attempts`). A Qdrant or embedding outage degrades retrieval to lexical FTS; storage and structured retrieval continue.

## Embeddings

`all-minilm` via local Ollama: 23M params, 384 dimensions, F16, Apache-2.0, CPU-only (`num_gpu=0`, `num_thread=2`), one global inference slot, loopback HTTP only, bounded response size and timeout. No automatic downloads; `ollama pull all-minilm` is a one-time explicit setup.

## Retrieval and context

Query → dense (scope-filtered) + lexical FTS candidates → SQL metadata filters (type, tags, source, time) → ranking with interpretable signals (lexical, dense, recency, importance, confidence, source authority) → dedup by (content hash, source) → final authoritative re-check (version + status) before returning. Stale vector versions are ignored.

`ContextAssembler` emits three messages: fixed system instructions, the task, and one JSON blob labeled `UNTRUSTED_CONTEXT_DATA` grouped into working / personal+project / knowledge with provenance and per-hit signals. Budgets are enforced by truncation with explicit `truncated` markers, then dropping entries; never by fabricated summaries. Conversation compression is extractive round-robin over structured `ConversationNotes` with a source hash; compressed output is not itself valid `ConversationNotes`, preventing summary-of-summary loops.

## Security invariants

- Memory never authorizes action. Retrieved text that says "the user always allows X" still goes through the Phase 04 typed request → registry → policy → confirmation → lease pipeline (tested).
- Scope is bound by trusted bootstrap; model arguments cannot set namespace, provenance, or approval.
- Imports are schema-validated, size-bounded, secret-scanned, demoted in authority/confidence, and cannot import working/preference types or reuse deleted IDs.
- Events and metrics carry counts and fixed action labels only — never content, IDs, paths, or exception text.

## Failure modes

- SQLite unavailable → `retrieve` returns `available=false` with no fabricated hits; runtime boots into no-memory mode with a static context.
- Embedding/Qdrant unavailable → lexical fallback; indexing attempts are bounded; `rebuild()` is the explicit recovery path after SQLite restore or model change.
- Telemetry failure never blocks or rolls back storage.

## Consistency limitations

SQLite and Qdrant have no transactional consistency. Writes commit to SQLite first; vectors follow via explicit `sync()`. Between a correction and the next sync, dense retrieval intentionally returns nothing for that memory rather than a stale version. After a backup restore, call `store.reset_index()` then `indexer.rebuild()` + `sync()`.

## Configuration

All limits live in `MemoryConfig` (see `app/memory/config.py`), overridable via `JARVIS_MEMORY__*` environment variables. `JARVIS_MEMORY_ENABLED` (default true) and `JARVIS_MEMORY_VECTOR_ENABLED` (default false) control runtime wiring. Vector mode requires a local Qdrant data directory and the pulled MiniLM model.