# Production Deployment

## Layout

The application root is the directory containing the repository and installer. For a user installation, place the repository at `$HOME/JARVIS` or another explicitly selected path. Set `VENV_DIR` when the virtual environment must live elsewhere. Application files live under the installation root. Configuration is `config/`, durable state is `data/`, logs are `logs/`, caches are `cache/`, optional models are `models/`, runtime state is `data/run/`, and backups are `backups/`.

## Install and preflight

Run `scripts/preflight.sh`, then `scripts/install.sh`. The installer checks Linux, Python 3.14+, free disk, and write access. It creates a project-local `.venv` and installs the declared package plus development test dependencies. It does not install system packages, download models, or require network services during normal startup.

## Control

Use `scripts/jarvisctl.sh start|stop|restart|status|health|disable|enable`. Disable stops Jarvis-managed work and leaves the desktop untouched. `health` invokes the existing runtime health architecture through the control interface.

The optional user service template is `packaging/jarvis.service.in`. Copy it to `~/.config/systemd/user/jarvis.service`, adjust `WorkingDirectory` if needed, then use `systemctl --user daemon-reload`, `enable --now jarvis`, `status jarvis`, and `disable --now jarvis`. It is user-level and does not require root.

## Configuration and data

Runtime configuration remains governed by the existing `Settings` and `.env` mechanism. Keep secrets outside source control. Do not overwrite existing configuration or databases during upgrades. Back up `data/` and `backups/` before migrations or destructive operations. The application version is defined once in `app/version.py` and exposed by `python -m app.main --version`.

## Upgrade, rollback, uninstall

Stop Jarvis, verify a backup, install the new source, run migrations through the existing database service, run health, and restart. If validation fails, keep the previous application tree and restore only through the existing backup/restore procedures.

Run `scripts/uninstall.sh` to remove the application environment while preserving data, configuration, logs, models, caches, and backups. `scripts/uninstall.sh --purge-data` requires typing `PURGE` and is the only path that removes those directories; review backups first.

## Offline and asset checks

Dependency installation can use a local package cache or wheelhouse with pip options supplied by the operator. Models are optional and are never downloaded automatically. The approved HUD asset is verified by `app.deployment.verify_approved_asset` against the documented SHA-256; a mismatch fails the verification and never replaces the asset.
