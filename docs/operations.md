# Operations Manual

All commands below run from the repository root. The control script stores only a PID and disabled marker under ignored `data/run/`.

## User operations

```bash
scripts/jarvisctl.sh start
scripts/jarvisctl.sh stop
scripts/jarvisctl.sh restart
scripts/jarvisctl.sh disable
scripts/jarvisctl.sh enable
scripts/jarvisctl.sh status
scripts/jarvisctl.sh health
```

`start` runs the foreground application under a managed background process. `stop` sends a graceful termination signal. `disable` stops JARVIS and prevents later starts until `enable` is run. `health` validates configuration imports, database integrity and schema, and HUD asset integrity; Ollama is reported as unavailable rather than treated as a reason to prevent optional startup.

View bounded host diagnostics with:

```bash
scripts/diagnostics.sh
tail -n 100 logs/jarvis.log
```

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

## Updates

Use the procedure in `docs/recovery.md`: create a backup, require a clean Git tree, update, run the complete tests, run the health check, smoke-test `status`, and only then start the new version. Keep the previous certified commit available for rollback.

## Known operational limits

- external cloud services are optional and not mandatory
- model availability depends on the local Ollama installation
- audio, browser, cloud, memory-vector, and HUD integrations are optional and degrade independently
