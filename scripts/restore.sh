#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-}"
if [[ -z "$SOURCE" || ! -d "$SOURCE" ]]; then
    printf '%s\n' "Usage: $0 BACKUP_DIRECTORY" >&2
    exit 2
fi

"$PROJECT_ROOT/scripts/jarvisctl.sh" stop
mkdir -p "$PROJECT_ROOT/data"
if [[ -f "$SOURCE/jarvis.db" ]]; then
    cp -p "$SOURCE/jarvis.db" "$PROJECT_ROOT/data/jarvis.db"
fi
if [[ -f "$SOURCE/.env" ]]; then
    cp -p "$SOURCE/.env" "$PROJECT_ROOT/.env"
fi
"$PROJECT_ROOT/scripts/healthcheck.sh"