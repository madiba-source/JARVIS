# Operations Manual

## Start-up and environment

The project is designed to run in a local, local-first Python environment. It is explicitly compatible with an offline or cloud-disabled configuration.

## Normal operations

- run local model and policy checks
- execute local tool workflows through the typed gateway
- use memory and retrieval as governed local resources
- use the agent runtime with bounded plans and validation
- use optional hybrid cloud routing only when explicitly enabled and allowed by policy

## Disable and emergency behavior

`JarvisCore.disable()` is the single application-level delegation for managed
work. It invalidates agent execution and the Phase 04 policy state, stops voice
and calendar scheduling, and leaves the underlying Linux desktop untouched.
`JarvisCore.enable()` restores those managed services without constructing a
second runtime.

## Offline behavior

The project remains useful with cloud disabled and with a disconnected network. Local services continue to be the default path.

## Degraded behavior

Optional services degrade safely:

- cloud unavailable → local fallback or safe failure
- browser/vision unavailable → typed failure or degraded operation
- audio devices unavailable → bounded fallback and safe shutdown
- memory backend unavailable → degraded local operation without silent escalation

## Known operational limits

- external cloud services are optional and not mandatory
- production certification still needs the final git-certification step
- no claim of complete production certification should be made until the final repo state is committed and verified
