# Troubleshooting

## Tests and compile validation

The current repository has been validated with:

- `./venv/bin/python -m pytest -q`
- `./venv/bin/python -m compileall app`

Both succeeded in the current workspace.

## If a local model is unavailable

The runtime is designed to fail closed and use typed unavailable states instead of crashing. Local-first operation remains the default path.

## If cloud is unavailable

Cloud failures are bounded. The system falls back to local operation or returns a safe typed failure result.

## If JARVIS is disabled

Agent execution and policy checks are invalidated. The repo design is to stop JARVIS work while leaving the user environment usable.

## If an operation is blocked

The normal behavior is a deterministic failure state rather than an implicit privilege escalation.

## Final certification note

The repo is functionally green for the code and test layer, but final Phase 12 certification remains incomplete until the final git certification commit and final documentation state are completed.
