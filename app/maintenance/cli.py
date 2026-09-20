"""Read-only and explicitly confirmed maintenance CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backup import BackupError, BackupManager, RestoreMode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe JARVIS maintenance operations")
    parser.add_argument("command", choices=("create", "list", "inspect", "verify", "restore"))
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--root", default=".")
    parser.add_argument("--backup-root", default="data/backups")
    parser.add_argument("--target", default=".")
    parser.add_argument("--mode", choices=[mode.value for mode in RestoreMode], default=RestoreMode.FULL.value)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    manager = BackupManager(Path(args.root), Path(args.backup_root))
    try:
        if args.command == "create":
            print(manager.create())
        elif args.command == "list":
            for item in sorted(Path(args.backup_root).glob("jarvis-*.zip")):
                print(item)
        elif not args.archive:
            parser.error("archive is required")
        elif args.command == "inspect":
            print(json.dumps(manager.inspect(Path(args.archive)).to_dict(), indent=2, sort_keys=True))
        elif args.command == "verify":
            print(json.dumps(manager.verify(Path(args.archive)).to_dict(), indent=2, sort_keys=True))
        elif args.command == "restore":
            if not args.confirm:
                parser.error("restore requires --confirm")
            print(json.dumps(manager.restore(Path(args.archive), Path(args.target), mode=RestoreMode(args.mode))))
        return 0
    except BackupError as error:
        print(f"BACKUP INVALID: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
