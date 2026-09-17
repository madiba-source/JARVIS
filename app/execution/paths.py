"""Filesystem path safety for bounded workspace operations."""

from __future__ import annotations

import os
from pathlib import Path


class PathSafetyError(ValueError):
    pass


class PathPolicy:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def resolve(self, raw_path: str, *, must_exist: bool = False, allow_symlink: bool = False) -> Path:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        if not allow_symlink and any(part.is_symlink() for part in self._existing_parts(candidate)):
            raise PathSafetyError("symlink path components are not allowed")
        resolved = candidate.resolve(strict=False)
        if os.path.commonpath((str(self.root), str(resolved))) != str(self.root):
            raise PathSafetyError("path is outside the authorized root")
        if must_exist and not resolved.exists():
            raise PathSafetyError("path does not exist")
        return resolved

    @staticmethod
    def _existing_parts(path: Path) -> list[Path]:
        parts: list[Path] = []
        current = path
        while current != current.parent:
            if current.exists() or current.is_symlink():
                parts.append(current)
            current = current.parent
        return parts
