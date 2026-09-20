# Recovery

## Backup and restore

User state is the SQLite database under `data/jarvis.db` and the local `.env` configuration. The database contains calendar, memory, and application state where those services are enabled. Backups exclude logs, model caches, virtual environments, generated files, and temporary state.

Create a backup outside the repository when possible:

```bash
scripts/backup.sh /secure/path/jarvis-backup
```

Restore a previously created backup:

```bash
scripts/restore.sh /secure/path/jarvis-backup
scripts/jarvisctl.sh health
```

The restore stops JARVIS, replaces only the database and `.env` files present in the backup, validates schema and integrity, and leaves the backup directory unchanged.

## Failure recovery

1. Run `scripts/jarvisctl.sh status` and inspect the last 100 lines of `logs/jarvis.log`.
2. Run `scripts/jarvisctl.sh health`.
3. Run `scripts/jarvisctl.sh restart` after an interrupted process.
4. If the model is unavailable, verify `ollama list`; JARVIS keeps policy, calendar, memory, and other local services isolated where possible.
5. If audio, browser, network, or HUD startup fails, the corresponding optional runtime is logged and JARVIS continues without granting extra permissions.
6. If configuration is malformed, move `.env` aside, run health, and reintroduce validated settings one at a time.
7. If the database is unavailable or corrupt, stop JARVIS and restore a verified backup. Do not delete the active database before preserving it.

For a safe update: backup, verify `git status --short` is empty, fetch and review, update, run `venv/bin/python -m compileall -q app tests`, run `venv/bin/python -m pytest -q`, run health, smoke-test status, then start. Retain the previous certified commit and return to it only through a reviewed, non-destructive Git operation.