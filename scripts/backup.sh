#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION="${1:-$PROJECT_ROOT/data/backups/release-$(date -u +%Y%m%dT%H%M%SZ)}"

"$PROJECT_ROOT/scripts/jarvisctl.sh" stop
mkdir -p "$DESTINATION"
if [[ -f "$PROJECT_ROOT/data/jarvis.db" ]]; then
    cp -p "$PROJECT_ROOT/data/jarvis.db" "$DESTINATION/jarvis.db"
fi
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    cp -p "$PROJECT_ROOT/.env" "$DESTINATION/.env"
fi
printf '%s\n' "$DESTINATION"