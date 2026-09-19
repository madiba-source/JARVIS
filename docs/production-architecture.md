# Production Architecture

## Scope

This document describes the repository as it exists in the current workspace. It is intentionally limited to the actual implementation and validation evidence present in the codebase and tests.

## Core architecture

JARVIS is implemented as a local-first desktop assistant with a deterministic policy layer and an execution gateway. The core flow remains:

```
user input
  → runtime control / session state
  → structured request validation
  → agent planning
  → tool catalog lookup
  → deterministic policy evaluation
  → confirmation when required
  → resource admission and execution lease
  → safe executor
  → observation and verification
  → audit record
```

This preserves the model-as-data design: the model is not the security boundary.

## Local-first runtime

The project is designed to operate without mandatory cloud services. Local capabilities include:

- agent runtime and state machine
- planner / validation / recovery
- local model provider abstraction
- deterministic router
- memory and RAG
- filesystem / terminal / policy execution boundaries
- browser and vision contracts
- audio and voice components
- calendar and workflow capabilities
- observability and diagnostics

## Hybrid cloud layer

A hybrid provider/route layer exists as an optional capability. It is explicitly disabled by default and remains subordinate to the local deterministic policy boundary. Cloud routing is gated by:

- `cloud_enabled`
- privacy mode
- prompt sensitivity checks
- payload size validation
- URL validation
- response size, retry, and concurrency limits

Cloud is optional and not required for normal offline operation.

## Security boundary

The implemented security model remains the same regardless of cloud capability:

- local deterministic policy is authoritative
- tool calls are typed and cataloged
- model output is not direct execution
- confirmation remains mandatory for sensitive operations
- JARVIS disable remains authoritative across execution and routing

`JarvisCore.disable()` delegates to the existing agent control, policy service,
voice runtime, and calendar scheduler. It is idempotent at the managed-service
boundaries and does not control ordinary desktop access.

## Offline behavior

The codebase explicitly supports local-only mode and cloud-disabled operation. Offline behavior is not merely tolerated; it is the default operating mode.

## Known limitations

- Cloud capability is optional and intentionally bounded.
- The default application bootstrap does not configure cloud credentials or a
  cloud endpoint; cloud requires explicit provider configuration.
- Full production certification requires the final repo-level documentation and git certification step to be completed.
- Some platform-dependent services (for example browser, voice, and vision) remain optional and degrade safely when unavailable.

## Evidence in the repository

This description is supported by the active implementation in:

- `app/agent/`
- `app/execution/`
- `app/policy/`
- `app/memory/`
- `app/audio/`
- `app/vision/`
- `app/browser/`
- `app/calendar/`
- `app/observability/`

The current repo also includes targeted tests validating the runtime and the hybrid cloud admission layer.
