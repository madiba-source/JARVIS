# Phase 03 Policy Boundary

Phase 03 is deterministic policy admission and typed authorization. It is not an operating-system sandbox and it does not claim to enforce CPU, RAM, process, timeout, disk, or network limits during arbitrary callback execution.

## Admission

The registry owns immutable tool snapshots. Each operation has a closed Pydantic argument model. The evaluator derives the authoritative authorization level from the registry, validates the operation and arguments, checks the JARVIS active state, validates resource admission, consumes an action-bound confirmation token when required, and issues a generation-bound execution permit.

Requested resource values are caps. They must be finite, non-negative, within system maxima, and cannot be below a tool's static requirement. The effective permit records the tool requirement for constrained resources. Admission does not reserve or enforce those resources.

## Execution lease

The execution gateway acquires a lease while holding the same state lock used by `set_jarvis_active`. This makes the active-state and generation check atomic with admission:

- no new lease can be acquired after disable;
- permits issued before disable fail when they have not acquired a lease;
- an executor already holding a lease may finish cooperatively;
- arbitrary Python callbacks are not claimed to be forcibly killable.

A later runtime layer must enforce actual timeouts and OS resource limits, and should provide cooperative cancellation for long-running operations. Disabling JARVIS remains an application-layer control and does not disable the user's normal desktop.

## Confirmation

Confirmation tokens bind the request ID, tool, operation, canonical arguments, authoritative authorization level, and effective resource constraints. Canonicalization rejects non-string object keys, non-finite numbers, and unsupported Python objects. Tokens are single-use, expire, and are stored in a bounded, pruned store.

## Audit

Audit events contain policy metadata only. Arguments, metadata payloads, credentials, tokens, and secrets are not recorded. Sensitive substrings in operation, reason, and subsystem fields are redacted.
