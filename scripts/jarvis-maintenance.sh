#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${VENV_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$VENV_PYTHON" ]] || VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '%s\n' 'BLOCKED: install the application first.' >&2
    exit 1
fi
cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" -m app.maintenance.cli --root "$PROJECT_ROOT" "$@"
