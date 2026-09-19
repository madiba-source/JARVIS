# Hybrid Cloud Architecture

## Overview

JARVIS remains local-first by default. The hybrid cloud layer is optional and is intentionally gated by the existing deterministic runtime and policy boundary. Cloud access is never a privileged execution path; it is a bounded model-routing option that only runs when the configuration explicitly permits it.

## Architecture

The runtime uses a single local-first model router with the following order:

1. local provider
2. optional cloud provider only when allowed by policy and configuration
3. bounded local fallback when cloud is unavailable or rejected

The routing decision is made by deterministic logic, not by model-generated provider selection. The model may propose work, but the final routing decision remains in the local runtime.

## Provider abstraction

The provider seam presents typed request/response contracts through the model layer. The current implementation includes:

- `LocalProvider` semantics via the local runtime and `StaticProvider` / `OllamaProvider` adapters
- `CloudProvider` for explicit outbound HTTP requests
- an extension seam for future providers through the same typed contract model

Each provider exposes bounded availability and generation behavior. Failures are returned as typed states rather than uncaught exceptions.

## Privacy modes

The runtime supports three explicit privacy modes:

- `offline_only`: cloud routing is disabled entirely
- `local_preferred`: local execution is preferred, and cloud is only considered when the prompt is not classified as sensitive and the runtime is explicitly configured for hybrid use
- `hybrid`: cloud is allowed under the same deterministic policy checks and bounded resource limits

These modes are enforced in the router and remain authoritative.

## Cloud safety boundary

Every cloud request must pass through deterministic validation before leaving the machine:

- privacy policy evaluation
- payload classification
- deterministic sensitive-term rejection
- URL validation
- payload size validation
- timeout and bounded retry checks
- bounded concurrency admission
- provider availability gate

The cloud layer never receives the Phase 04 authorization secret, HMAC secret, or local credential material.

## Network policy

The cloud provider validates:

- HTTP/HTTPS scheme only
- non-empty host
- bounded JSON payload size
- bounded response size
- explicit timeout bounds
- bounded retries and backoff
- no background worker that outlives disable or shutdown

The model is never allowed to choose arbitrary network destinations.

## Fallback behavior

When local inference is unavailable and the configured privacy mode permits it,
the router may attempt the bounded cloud provider. Cloud failures return typed
failure states; the provider never executes tools or changes policy.

## Resource safety

The hybrid layer uses admission limits for:

- local model concurrency
- cloud request concurrency
- model timeout
- request and response size
- retry count
- bounded provider state

These limits are consistent with the existing project constraint that the machine must remain local-first and safe under resource pressure.

## Offline certification

The project is explicitly designed to operate with cloud disabled. Offline operation remains a supported state and is not dependent on cloud access.

## Current implementation status

The current repo includes a local-first model router, typed provider contracts,
explicit privacy modes, bounded cloud request/response validation, sensitive
term rejection, bounded concurrency, and bounded retries. Cloud endpoint and
credentials are not configured by the default application bootstrap; explicit
provider injection/configuration is required for cloud use.
