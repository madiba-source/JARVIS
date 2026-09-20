#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf '%s\n' "BLOCKED: $PYTHON_BIN is required." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)'; then
    printf '%s\n' 'BLOCKED: Python 3.14 or newer is required.' >&2
    exit 1
fi
for command_name in git curl; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'BLOCKED: required command missing: %s\n' "$command_name" >&2
        exit 1
    }
done

cd "$PROJECT_ROOT"
if [[ ! -d venv ]]; then
    "$PYTHON_BIN" -m venv venv
fi
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -e '.[dev]'
mkdir -p data/backups data/run logs
scripts/healthcheck.sh
printf '%s\n' 'Installation complete.'