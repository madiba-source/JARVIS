# Terminal Control Operations

Phase 04 does not expose a shell. The terminal capability contains a fixed allowlist of diagnostic command IDs (`pwd`, `whoami`, and `uname` when installed), resolved to executable paths at startup.

Execution uses argv-style `subprocess.Popen(..., shell=False)` with a minimal environment, bounded stdout/stderr collection, a wall-clock timeout, a controlled process group, and no stdin. Unknown commands, arbitrary arguments, shell metacharacters, pipelines, redirects, command substitution, and sudo are unavailable.

The allowlist is intentionally small. Expanding it requires a typed command specification, policy classification, output/time limits, and adversarial tests.
