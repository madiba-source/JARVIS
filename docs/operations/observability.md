# JARVIS Observability Operations

Phase 04 provides passive, local-first observability. It does not authorize tools, change policy, or enforce operating-system resource limits.

## Pipeline

`EventBus` publishes lifecycle/application events to `ObservabilityAdapter`. The adapter creates one canonical sanitized representation and sends it to structured logging, bounded local metrics, a bounded local tracer, and SQLite persistence.

Sensitive values are redacted before serialization. SQLite therefore does not receive the raw event representation. Metadata snapshots are recursively immutable after event construction, and circular structures are represented safely.

## Bounds

- Event fields have explicit length limits; serialized payloads are limited by `max_event_payload_bytes`.
- Metrics reject new series after `max_metric_series`; label names/counts and values are bounded.
- Traces retain at most `max_trace_count` traces and `max_spans_per_trace` spans per trace. Span attributes/events and value sizes are bounded.
- SQLite retention is row-bounded by `max_sqlite_rows`. SQLite uses WAL during operation and truncates the WAL on close. This is not a hard disk-size guarantee; `sqlite_max_bytes` is configuration metadata for the later storage runtime and is not claimed as enforced here.
- Log files use rotating handlers with configured size and backup limits.

## Failure isolation

Sink failures return a degraded result or increment an adapter failure counter; they do not propagate into the JARVIS core. The implementation makes no zero-loss guarantee. Diagnostics reports logging, metrics, tracing, SQLite, dropped-event, series, trace, and disk state without dumping environment variables, prompts, credentials, audio, or screenshots.

## Tracing

`TracerProtocol` is the application boundary. `LocalTracer` is the offline implementation and `NullTracer` is the disabled implementation. Nested spans restore their parent context, so sibling spans remain siblings. OpenTelemetry is intentionally optional and disabled by default.

## Privacy defaults

Raw prompts, raw model outputs, microphone recordings, screenshots, browser cookies, environment dumps, and credentials are not recorded by this phase.