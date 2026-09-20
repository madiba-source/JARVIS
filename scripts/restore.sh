#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-}"
VENV_PYTHON="${VENV_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$VENV_PYTHON" ]] || VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
if [[ -z "$SOURCE" || ! -d "$SOURCE" ]]; then
    printf '%s\n' "Usage: $0 BACKUP_DIRECTORY" >&2
    exit 2
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '%s\n' "BLOCKED: missing project Python environment." >&2
    exit 1
fi
if [[ -f "$SOURCE/SHA256SUMS" ]] && ! (cd "$SOURCE" && sha256sum --check SHA256SUMS); then
    printf '%s\n' 'BLOCKED: backup checksum verification failed.' >&2
    exit 1
fi

"$PROJECT_ROOT/scripts/jarvisctl.sh" stop
mkdir -p "$PROJECT_ROOT/data"
if [[ ! -f "$SOURCE/jarvis.db" ]]; then
    printf '%s\n' 'BLOCKED: backup does not contain jarvis.db.' >&2
    exit 1
fi
cd "$PROJECT_ROOT"
"$VENV_PYTHON" - "$SOURCE/jarvis.db" <<'PY'
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
    DatabaseConfig(db_path=str(settings.data_dir / "jarvis.db"), backup_directory=str(settings.data_dir / "backups")),
    extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS + PROACTIVE_MIGRATIONS,
)
service.initialize()
service.restore(sys.argv[1])
PY
if [[ -f "$SOURCE/.env" ]]; then
    cp -p "$SOURCE/.env" "$PROJECT_ROOT/.env"
fi
"$PROJECT_ROOT/scripts/healthcheck.sh"