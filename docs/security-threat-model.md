# Security Threat Model

## Security boundary

Untrusted user text, voice transcripts, model output, browser content, documents, OCR, screenshots, terminal output, memory retrieval, and external network content are data. They flow through typed parsing and schema validation, deterministic policy evaluation, confirmation where required, resource admission, typed execution, observation, verification, and audit. No model output or observation authorizes an action.

The trusted boundary consists of the policy engine, typed tool catalog, argument validators, confirmation and permit mechanisms, execution leases, resource budgets, verification, audit storage, and trusted configuration. The operating system remains outside Jarvis authority and is reached only through typed, allow-listed executors.

## Major controls

- Filesystem paths are workspace-contained and reject unsafe symlinks and traversal.
- Terminal execution uses an executable allowlist, argv arrays, `shell=False`, bounded output, and timeouts.
- Browser URLs require HTTP(S), reject credentials, and reject local/private/link-local/reserved targets.
- Browser, document, OCR, vision, memory, and terminal observations are untrusted external data.
- Plans are typed, DAG-validated, catalog-validated, bounded, cancellable, idempotent, and policy-checked per step.
- Confirmations bind to operation, arguments, session, policy, expiration, and single-use tokens.
- Health recovery is allow-listed and cannot execute arbitrary commands.
- Logs, traces, metrics, checkpoints, and performance samples are bounded and redacted.
- Global disable cancels agent, interaction, health, performance, voice, and multimodal work.

## Security status

The repository contains focused regression coverage for policy permits, forged tokens, filesystem safety, terminal allowlisting, browser schemes and private targets, memory poisoning, untrusted multimodal content, confirmation replay, plan validation, resource limits, disable behavior, telemetry bounds, and recovery allowlists.

This document records design controls; it is not a claim that every external dependency or host configuration has been independently certified. Dynamic network, hardware, privilege, and supply-chain testing require the target deployment environment.
