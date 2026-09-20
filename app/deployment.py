"""Pure deployment metadata and preflight helpers."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .version import __version__

APPROVED_HUD_SHA256 = "10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65"


@dataclass(frozen=True)
class InstallPaths:
    application: Path
    config: Path
    data: Path
    logs: Path
    cache: Path
    models: Path
    runtime: Path
    backups: Path

    @classmethod
    def for_home(cls, home: Path | None = None) -> "InstallPaths":
        root = (home or Path.home()) / "JARVIS"
        return cls(root, root / "config", root / "data", root / "logs", root / "cache", root / "models", root / "run", root / "backups")


def asset_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_approved_asset(path: Path) -> bool:
    try:
        return asset_sha256(path) == APPROVED_HUD_SHA256
    except OSError:
        return False


def release_metadata(*, commit: str = "") -> dict[str, str]:
    return {"version": __version__, "commit": commit[:64], "python": platform.python_version(), "platform": platform.platform(aliased=True), "architecture": platform.machine()}


def preflight(*, minimum_python: tuple[int, int] = (3, 14), minimum_disk_mb: int = 1024) -> list[str]:
    failures: list[str] = []
    if sys.version_info < minimum_python:
        failures.append(f"Python {minimum_python[0]}.{minimum_python[1]} or newer is required")
    if platform.system() != "Linux":
        failures.append("Linux is required")
    if shutil.disk_usage(Path.cwd()).free < minimum_disk_mb * 1024 * 1024:
        failures.append("insufficient free disk space")
    if not os.access(Path.cwd(), os.W_OK):
        failures.append("current directory is not writable")
    return failures
