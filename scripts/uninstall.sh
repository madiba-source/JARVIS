#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP_DATA="${KEEP_DATA:-1}"

if [[ "${1:-}" == "--purge-data" ]]; then
    KEEP_DATA=0
fi

if [[ "$KEEP_DATA" != "0" ]]; then
    printf '%s\n' "Preserving configuration, data, logs, models, and backups."
else
    printf '%s\n' 'BLOCKED: --purge-data requires explicit confirmation: type PURGE.' >&2
    read -r confirmation
    [[ "$confirmation" == "PURGE" ]] || { printf '%s\n' 'Aborted; no user data removed.' >&2; exit 1; }
    rm -rf -- "$PROJECT_ROOT/data" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/config" "$PROJECT_ROOT/cache" "$PROJECT_ROOT/models" "$PROJECT_ROOT/backups"
fi
rm -rf -- "$PROJECT_ROOT/.venv" "$PROJECT_ROOT/venv" "$PROJECT_ROOT/jarvis.egg-info"
printf '%s\n' 'Application environment removed; preserved user data remains unless explicitly purged.'
