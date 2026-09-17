# RAG Operations

Phase 05 retrieval-augmented generation is local, bounded, and injection-resistant.

## Pipeline

```
query normalization
  → query embedding (local MiniLM, optional)
  → dense retrieval (Qdrant, scope-filtered)
  → sparse/lexical retrieval (SQLite FTS5, always available)
  → SQL metadata filtering (type, tags, source, time, scope, validity)
  → candidate merge (bounded at max_candidates × 2)
  → reranking (interpretable weighted signals)
  → deduplication (content hash + source)
  → authoritative re-check (SQLite version/status)
  → context assembly (bounded, data-labeled)
```

## Hybrid behavior

Dense and lexical candidates are merged; a record needs either lexical overlap or dense similarity ≥ `dense_threshold` (default 0.35). Exact identifiers, filenames, commands, and error strings are covered by FTS5 lexical matching even when embeddings are unavailable. If the embedding provider or Qdrant is unavailable, retrieval continues lexically and `Retrieval.dense_available` is false.

## Ranking signals

Each hit carries a `Signals` record: `lexical`, `dense`, `recency` (30-day half-life style decay), `importance`, `extraction_confidence`, `source_authority`, and the combined `score` (0.5 lexical + 0.3 dense + 0.08 recency + 0.05 importance + 0.03 confidence + 0.04 authority). No cross-encoder inference is used; ranking is deterministic and explainable.

## Context assembly

See `docs/operations/memory.md` ("Retrieval and context"). Retrieved data is JSON-escaped into a single labeled user message; it can never introduce new message roles. System instructions are fixed and state that retrieved content is untrusted data with no authority.

## Injection defense

Documents and memories containing "ignore previous instructions", fake `{"role":"system"}` JSON, or permission claims are stored as data and returned as data. Tests assert:

- injected instructions never appear in system instructions,
- permission-like memory text still requires Phase 04 confirmation for any action,
- poisoned scope/provenance arguments from the model are rejected,
- stale vector versions cannot surface old content after correction.

## Resource bounds

`max_candidates` (dense + lexical), `max_context_chars`, `max_embedding_batch`, single embedding slot, single index job, bounded response bytes and timeouts. Evaluation (`tests/memory/test_evaluation.py`) measures top-1 success, latency, and context size on a deterministic dataset including project isolation, recency/correction, and deleted-memory cases.