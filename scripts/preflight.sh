#!/usr/bin/env bash
set -u

PYTHON_BIN="${PYTHON_BIN:-python3}"
MIN_DISK_MB="${MIN_DISK_MB:-1024}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf '%s\n' "BLOCKED: missing Python executable: $PYTHON_BIN" >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)'; then
    printf '%s\n' 'BLOCKED: Python 3.14 or newer is required.' >&2
    exit 1
fi
if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' 'BLOCKED: Linux is required.' >&2
    exit 1
fi
free_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
if [[ -z "$free_kb" || "$free_kb" -lt $((MIN_DISK_MB * 1024)) ]]; then
    printf 'BLOCKED: at least %s MiB of free disk is required.\n' "$MIN_DISK_MB" >&2
    exit 1
fi
if [[ ! -w . ]]; then
    printf '%s\n' 'BLOCKED: installation directory is not writable.' >&2
    exit 1
fi
printf '%s\n' 'Preflight passed.'
