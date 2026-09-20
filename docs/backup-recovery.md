# Backup, Recovery, Migration, and Update

## Backup policy

`app.maintenance.BackupManager` creates versioned ZIP backups with a JSON manifest and SHA-256 for every regular file. Default components are `config` and `data`; caches, logs, runtime files, and temporary files are excluded. Models are excluded unless explicitly added by a future bounded component policy. Secrets are not collected by the backup layer.

Backups are staged in the configured backup root and published only after manifest and checksum verification. File count, byte count, path length, and retention are bounded. Symlinks, absolute paths, traversal paths, duplicate manifest entries, malformed manifests, and checksum mismatches fail closed.

## Commands

Use `scripts/jarvis-maintenance.sh create`, `list`, `inspect <archive>`, or `verify <archive>`. Inspection and verification are read-only. Restore requires both a selected mode and `--confirm`:

```text
scripts/jarvis-maintenance.sh restore data/backups/jarvis-ID.zip --target . --mode full --confirm
```

Restore modes are `full`, `selective`, `config_only`, and `user_data_only`. Restore data is copied through a staging directory and never executes archive contents. Live database restoration must still use the existing database backup/restore and migration services while connections are quiesced.

## Recovery and updates

Before destructive restore or update, stop Jarvis, disable automation, create a verified safety backup, validate compatibility, stage the new state, and run health checks before resuming. Invalid or interrupted operations leave the original source untouched where the operation supports atomic staging. Do not apply artifacts from model output, webpages, or arbitrary URLs.

Database migrations remain sequential and transactional through `MigrationManager`; downgrades are rejected. Automation must remain disabled after data restoration until explicitly reactivated. Keep the prior application tree for rollback and retain the pre-change backup.

All backup, restore, migration, and update actions must be audited by the operational caller. This module does not bypass policy or confirmation and contains no shell execution mechanism.

## Offline operation

Backup, inspection, verification, restore staging, and migration are local operations. Update checking is intentionally not implemented as an implicit network action; release artifacts must be supplied through an explicitly trusted deployment process.
