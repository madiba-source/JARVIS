# Security Operations

The model is not the security boundary. Tool calls pass through typed validation, policy evaluation, confirmation where required, resource admission, safe execution, verification, and bounded audit paths.

## Release checks

Run:

```bash
venv/bin/python -m pytest -q tests/policy tests/execution tests/computer_use tests/browser tests/agent/test_hybrid_cloud.py tests/database/test_security.py tests/memory/test_security.py tests/observability/test_security.py
```

The security-sensitive paths cover subprocess and terminal execution, filesystem and symlink handling, browser actions, downloads, model-generated calls, cloud requests, path traversal, privilege boundaries, and redaction. The release does not add a new execution path.

Phase 14 discovery adds only read-only registry operations. Application launch
continues to use the existing discovered-record manager and `shell=False`; Kali
discovery checks executable availability without invoking tools. Both paths are
registered at L0 and remain subject to the global policy active gate.

## Secrets and logs

`.env`, databases, logs, caches, virtual environments, model files, and temporary files are ignored. Logs contain bounded metadata and diagnostics, not prompts, credentials, tokens, raw microphone/screen data, or unnecessary personal content. Review `git diff --cached` before every release commit.

## Resource governance

Existing limits remain authoritative: bounded runtime, tool calls, agent steps, network/download bytes, process counts, memory/swap/disk observations, concurrency gates, and bounded model outputs. `scripts/diagnostics.sh` reports host resource state; it does not raise limits or install services.