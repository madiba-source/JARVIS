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

## Permit authentication repair

The desktop-phase audit identified a foundation defect: lease admission checked
permit contents without authenticating the issuing evaluator. The retained
regression test uses only a fake executor; it performs no filesystem deletion.
Desktop implementation remains paused while this focused foundation repair is
validated.

Each evaluator now generates a private, random 32-byte key at construction.
Issued permits carry an HMAC-SHA256 signature over their JSON-serialized fields
(excluding the signature), with sorted keys, compact separators, and non-finite
numbers rejected. Lease admission checks the signature using constant-time
comparison before checking active state, generation, and action binding.

Compatibility and scope:

- `ExecutionPermit` adds a `signature` field. Its empty default permits parsing
  older objects, but unsigned permits are rejected at lease admission.
- Permits issued by another evaluator, including one created after a restart,
  are rejected. Keys are neither persisted nor exported by a supported API.
- JSON round-tripped permits remain usable by their issuing evaluator.
- Normal confirmed actions continue through the existing confirmation mechanism.
- Disable/re-enable does not restore permits from an earlier generation.

Remaining limitations:

- Authentication does not make execution permits single-use. A valid permit
  can be reused within its active generation; confirmation tokens remain
  single-use, but that alone does not prevent permit replay.
- `issued_at` is authenticated metadata, not an enforced expiration deadline.
- This is an application boundary, not isolation from arbitrary Python code
  running inside the process. Private attributes are not an OS security boundary.
- The repair does not add resource reservation, cancellation, OS sandboxing,
  or desktop execution capabilities.
- The public permit's nested resource-budget mapping is not deeply immutable.
  Lease admission now copies the permit before authenticating and using it;
  subsequent caller mutation does not change that lease's budget.

Future consequential executors must address permit consumption and lifecycle
requirements before desktop-phase acceptance. Passing this repair's tests does
not establish the complete Phase 04 security contract.

## Authorized argument ownership repair

The gateway previously validated caller-owned arguments at lease admission and
then read them again for executor dispatch. A frozen Pydantic request does not
freeze its nested dictionaries or lists. That second read could therefore use
a different argument set from the one authorized.

Authorization now deep-copies request arguments before trusted schema validation.
The normalized Python-mode model output is captured as an immutable serialized
`OwnedArgumentsSnapshot`. Confirmation validation and the action hash use values
materialized from this snapshot. The permit includes the snapshot string as
`argument_snapshot`, covered by the existing evaluator-specific HMAC together
with all other permit fields.

Lease admission deep-copies the permit, authenticates that owned copy, checks
active state and generation under the existing lock, and checks request ID,
tool ID, and operation identity. It verifies the action hash against the permit
snapshot, not against caller arguments. The execution gateway obtains a fresh
executor-owned dictionary only from the lease snapshot. It does not reread
`request.arguments` or rerun a tool's schema validators.

### Compatibility and serialization

- `execute_with_permit(request, permit)` retains its signature. Request identity
  fields must still match the permit. Changing request arguments after admission
  does **not** request a new action: execution uses the original authorized data.
  A different action requires new policy evaluation and confirmation as required.
- Snapshot encoding preserves dictionaries, lists, tuples, and canonical scalar
  values. It uses JSON with explicit collection tags, not pickle. It does not
  expand the existing canonical value domain: sets, non-string mapping keys,
  non-finite numbers, and unsupported Python objects are rejected.
- Each executor payload is newly materialized. Executor mutation cannot change
  the immutable snapshot or another materialization.
- JSON permit round-trips preserve execution data for the issuing evaluator.
  A permit from another evaluator remains invalid; no HMAC key is serialized.
- **Serialized permits now contain argument data.** They are sensitive bearer
  capabilities, not safe logging payloads. HMAC authenticates but does not encrypt.
  The snapshot is hidden from normal model representation (`repr`), not from
  explicit JSON/dictionary serialization. Existing policy audit records do not
  serialize permits or snapshots.
- Old permits without a snapshot cannot authorize execution with this version.
- Confirmation preparation takes an owned copy of its input request before its
  existing pending-decision and token-generation flow. It remains separate from
  execution; the permit snapshot is created during the subsequent evaluation.

### Concurrency and scope of the guarantee

Tests synchronize mutation during schema validation (after the input copy) and
after lease admission (before dispatch), and compare the entire executed payload
to the originally authorized arguments. Nested dictionaries/lists and tuple
round-trips are covered, as are independent materializations and normalization
that must not run twice during execution.

The initial copy is not an atomic transaction across arbitrary caller-owned
containers. Callers should not mutate input during that copy. Copy/validation
failure denies admission; if a copy succeeds while input changes, the captured
values are what undergo validation, authentication, and execution. This repair
guarantees binding to the captured authorization data, not a simultaneous view
of all caller state before capture.

There is no payload-size/depth admission limit added by this repair. Permit
replay and expiration limitations remain as documented above. Trusted schemas,
validators, and arbitrary Python code inside this process are outside the
untrusted-data boundary. No OS sandbox, desktop executor, or general in-process
isolation is introduced. Phase 04 remains paused pending a fresh entry audit.

## Confirmation

Confirmation tokens bind the request ID, tool, operation, canonical arguments, authoritative authorization level, and effective resource constraints. Canonicalization rejects non-string object keys, non-finite numbers, and unsupported Python objects. Tokens are single-use, expire, and are stored in a bounded, pruned store.

Argument validation failures expose only the fixed reason `Request argument validation failed`. Raw validator exceptions, rejected argument values, serialized arguments, and caller metadata are not copied into `PolicyDecision` or `AuditEvent`; redaction remains defense-in-depth rather than the primary privacy boundary.

## Audit

Audit events contain policy metadata only. Arguments, metadata payloads, credentials, tokens, and secrets are not recorded. Sensitive substrings in operation, reason, and subsystem fields are redacted.

Execution permits are bearer capabilities authenticated with evaluator-held HMAC-SHA256 signatures. HMAC authenticates but does not encrypt permit contents. Argument snapshots remain owned by the permit and are the only payload source used by the execution lease. Phase 03 remains an application admission boundary, not an OS sandbox; runtime resource enforcement remains a later execution-runtime responsibility.
