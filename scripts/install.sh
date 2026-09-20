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
for command_name in git; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'BLOCKED: required command missing: %s\n' "$command_name" >&2
        exit 1
    }
done

cd "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/preflight.sh"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"
if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e '.[dev]'
mkdir -p data/backups data/run logs config cache models backups
scripts/healthcheck.sh
printf '%s\n' 'Installation complete.'