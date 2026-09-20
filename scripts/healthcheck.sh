#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
EXPECTED_HUD_SHA256="10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65"

if [[ ! -x "$VENV_PYTHON" ]]; then
    printf '%s\n' "BLOCKED: missing $VENV_PYTHON" >&2
    exit 1
fi

cd "$PROJECT_ROOT"
"$VENV_PYTHON" - <<'PY'
import hashlib
import importlib
import sys
from pathlib import Path

from app.core.config import Settings
from app.calendar.migration import CALENDAR_MIGRATIONS
from app.database.config import DatabaseConfig
from app.database.service import DatabaseService
from app.hud.runtime import ASSET_PATH, ASSET_SHA256
from app.memory.migration import MEMORY_MIGRATIONS
from app.version import CONFIG_SCHEMA_VERSION, RELEASE_NAME, __version__

required = ("pydantic", "pydantic_settings", "sqlalchemy", "httpx", "structlog")
for module in required:
    importlib.import_module(module)

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
service = DatabaseService(DatabaseConfig(
    db_path=str(settings.data_dir / "jarvis.db"),
    backup_directory=str(settings.data_dir / "backups"),
), extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS)
service.initialize()
health = service.health()
asset_hash = hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest()
print(f"release: {RELEASE_NAME} ({__version__})")
print(f"python: {sys.version.split()[0]}")
print(f"config_schema: {CONFIG_SCHEMA_VERSION}")
print(f"database: {health['state']} ({health['message']})")
print(f"hud_asset: {asset_hash}")
if asset_hash != ASSET_SHA256:
    raise SystemExit("HUD asset hash mismatch")
if health["state"] != "HEALTHY":
    raise SystemExit(f"database health is {health['state']}")
PY

if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
        printf '%s\n' 'ollama: reachable (local endpoint)'
    else
        printf '%s\n' 'ollama: unavailable (optional startup degradation)'
    fi
else
    printf '%s\n' 'ollama: unchecked (curl unavailable)'
fi