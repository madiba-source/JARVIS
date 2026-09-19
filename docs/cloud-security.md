# Cloud Security Boundary

## Purpose

The hybrid cloud capability exists as an optional extension of JARVIS. It does not become the security boundary. The local deterministic policy and execution gateway remain authoritative.

## Data classification and exclusion

The cloud provider rejects outbound requests containing the following obvious
sensitive terms. This is a deterministic guard, not a complete DLP system:

- API keys
- passwords
- tokens
- HMAC secrets
- private credentials
- `.env` data when represented by a matched credential term
- raw filesystem state, browser content, memory content, microphone data, or
	screen data are not automatically classified by this provider and must be
	excluded by the caller's typed context/policy path.

Cloud requests use bounded, typed payloads only.

## Authorization boundary

Cloud responses are never treated as authoritative execution instructions. They are processed as structured data and then passed through the same trusted runtime and policy validation stack that governs local tools.

The following actions remain local and policy-controlled:

- filesystem access
- terminal execution
- memory writes
- browser automation
- desktop control
- enable/disable state
- confirmation enforcement
- schedule changes

## Prompt injection handling

All remote or cloud-derived output is treated as untrusted. The runtime preserves the existing model-is-not-the-boundary principle and never permits prompt injection to bypass local policy or confirmation paths.

## Network policy

The cloud provider rejects invalid destinations, malformed calls, oversized
requests/responses, matched sensitive terms, and requests beyond its bounded
concurrency gate. This is not a general-purpose content-loss-prevention system.

## Observability rules

Telemetry is intentionally content-free. It records only bounded metadata such as provider name, status, latency, and failure category. It never logs prompts, credentials, tokens, secrets, full content payloads, or raw sensitive data.

## Failure behavior

Cloud failures fail closed into typed error states. The router may use the cloud
provider only after local unavailability and only when explicit privacy
configuration permits it. No cloud response can authorize or execute a tool.
