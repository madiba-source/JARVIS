# Security Model

## Fundamental rule

The model is never the security boundary.

All privileged operations pass through the same local deterministic path:

1. typed request
2. schema validation
3. catalog / tool lookup
4. policy evaluation
5. confirmation when required
6. resource admission and execution lease
7. safe executor
8. verification and audit

## Security controls in the current repo

The existing repository contains explicit controls for:

- deterministic authorization decisions
- action-bound confirmation tokens
- bounded execution budgets
- shutdown and disable signals
- deterministic sensitive-term rejection in cloud payloads and governed memory handling
- local-first routing through typed provider contracts
- bounded cloud request validation

## Defensive patterns currently present

The repo includes protections against common failure modes such as:

- invalid argument shapes
- oversized inputs
- malformed model output
- unauthorized tool use
- disabled-runtime rejection
- sensitive prompt blocking in local-preferred routing and provider-level sensitive-term rejection
- invalid cloud URL / payload rejection

## Read-only security review

A read-only grep review of the active application code did not uncover direct use of the unrestricted patterns targeted in the Phase 12 review, including:

- `shell=True`
- `os.system`
- `eval(`
- `exec(`
- `pickle`
- unrestricted `sudo`

The current codebase instead relies on typed, policy-bound execution and structured validation.

## Remaining certification requirement

The repo-level security model is present and active. Sensitive-term matching is
not a substitute for complete data-loss prevention; callers must continue to
provide only typed, policy-approved context to optional cloud providers.
