# Observability

JARVIS observability is local-first and bounded. Structured logs, metrics, traces, audit events, health records, and performance samples remain separate data types.

## Modes

`TelemetryMode.OFF` records no performance samples. `LOCAL` records bounded samples in memory. `DEBUG` is reserved for explicit diagnostic use and remains subject to the same operation, correlation, and sample limits. No external collector is required.

## Privacy and retention

Log and trace payloads pass through deterministic redaction before persistence. Correlation accepts only fixed identifiers such as request, task, goal, plan, step, tool-call, and trace IDs. Performance data stores timings, resource snapshots, and safe identifiers, never prompts, credentials, audio, screenshots, or document contents.

Existing logging, metrics, tracing, SQLite retention, audit, and health components remain authoritative. Metrics have bounded series cardinality; traces, events, database rows, and performance samples have configured caps.

## Measurements

`PerformanceRecorder` measures operation duration, RSS, CPU time, thread count, and process ID using local process counters. It does not claim CPU temperature, system-wide CPU utilization, or hardware-safe thresholds. Actual machine benchmarks must be run separately and recorded with their environment and sample count.

Diagnostic interfaces are read-only. Telemetry never invokes tools, changes policy, or performs recovery.
