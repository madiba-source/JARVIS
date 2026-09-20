#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION="${1:-$PROJECT_ROOT/data/backups/release-$(date -u +%Y%m%dT%H%M%SZ)}"
VENV_PYTHON="${VENV_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$VENV_PYTHON" ]] || VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '%s\n' "BLOCKED: missing project Python environment." >&2
    exit 1
fi

"$PROJECT_ROOT/scripts/jarvisctl.sh" stop
mkdir -p "$DESTINATION"
cd "$PROJECT_ROOT"
backup_path="$DESTINATION/jarvis.db"
"$VENV_PYTHON" - "$backup_path" <<'PY'
import sys
from app.calendar.migration import CALENDAR_MIGRATIONS
from app.core.config import Settings
from app.database.config import DatabaseConfig
from app.database.service import DatabaseService
from app.memory.migration import MEMORY_MIGRATIONS
from app.proactive.migration import PROACTIVE_MIGRATIONS

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
service = DatabaseService(
    DatabaseConfig(db_path=str(settings.data_dir / "jarvis.db"), backup_directory=sys.argv[1]),
    extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS + PROACTIVE_MIGRATIONS,
)
service.initialize()
print(service.backup(sys.argv[1]))
PY
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    cp -p "$PROJECT_ROOT/.env" "$DESTINATION/.env"
fi
sha256sum "$DESTINATION/jarvis.db" > "$DESTINATION/SHA256SUMS"
printf '%s\n' "$DESTINATION"