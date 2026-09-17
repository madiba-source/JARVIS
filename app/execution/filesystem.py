"""Bounded, workspace-contained filesystem operations."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .models import ExecutionCode, ExecutionLimits, ExecutionResult
from .paths import PathPolicy, PathSafetyError


class FilesystemExecutor:
    def __init__(self, root: Path, limits: ExecutionLimits | None = None) -> None:
        self.policy = PathPolicy(root)
        self.limits = limits or ExecutionLimits()

    def _failure(self, code: ExecutionCode, message: str) -> dict:
        return ExecutionResult(code=code, message=message).model_dump()

    def list_directory(self, arguments: dict) -> dict:
        try:
            path = self.policy.resolve(arguments["path"], must_exist=True)
            if not path.is_dir(): return self._failure(ExecutionCode.INVALID_REQUEST, "path is not a directory")
            entries = []
            for index, entry in enumerate(sorted(path.iterdir(), key=lambda item: item.name)):
                if index >= self.limits.max_directory_entries: return self._failure(ExecutionCode.RESOURCE_LIMIT, "directory entry limit exceeded")
                entries.append({"name": entry.name, "is_dir": entry.is_dir(), "is_file": entry.is_file()})
            return ExecutionResult(code=ExecutionCode.SUCCESS, message="directory listed", data={"path": str(path), "entries": entries}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def stat_path(self, arguments: dict) -> dict:
        try:
            path = self.policy.resolve(arguments["path"], must_exist=True)
            stat = path.stat()
            return ExecutionResult(code=ExecutionCode.SUCCESS, message="path observed", data={"path": str(path), "is_file": path.is_file(), "is_dir": path.is_dir(), "size": stat.st_size, "mode": stat.st_mode}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def read_file(self, arguments: dict) -> dict:
        try:
            path = self.policy.resolve(arguments["path"], must_exist=True)
            if not path.is_file(): return self._failure(ExecutionCode.INVALID_REQUEST, "path is not a file")
            max_bytes = min(arguments.get("max_bytes") or self.limits.max_file_read_bytes, self.limits.max_file_read_bytes)
            with path.open("rb") as handle:
                content = handle.read(max_bytes + 1)
            if len(content) > max_bytes: return self._failure(ExecutionCode.RESOURCE_LIMIT, "file read limit exceeded")
            if len(content) > 16_384: return self._failure(ExecutionCode.RESOURCE_LIMIT, "file output limit exceeded")
            digest = hashlib.sha256(content).hexdigest()
            try: text = content.decode("utf-8")
            except UnicodeDecodeError: return ExecutionResult(code=ExecutionCode.SUCCESS, message="binary file read", data={"path": str(path), "sha256": digest, "binary": True, "size": len(content)}).model_dump()
            return ExecutionResult(code=ExecutionCode.SUCCESS, message="file read", data={"path": str(path), "sha256": digest, "binary": False, "size": len(content)}, stdout=text).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def search_files(self, arguments: dict) -> dict:
        try:
            root = self.policy.resolve(arguments["path"], must_exist=True)
            if not root.is_dir(): return self._failure(ExecutionCode.INVALID_REQUEST, "search root is not a directory")
            results = []
            for current, directories, files in os.walk(root, followlinks=False):
                directories[:] = sorted(directory for directory in directories if not (Path(current) / directory).is_symlink())
                for name in sorted(files):
                    if Path(name).match(arguments["pattern"]):
                        results.append(str(Path(current) / name))
                        if len(results) >= self.limits.max_search_results: return self._failure(ExecutionCode.RESOURCE_LIMIT, "search result limit exceeded")
            return ExecutionResult(code=ExecutionCode.SUCCESS, message="search complete", data={"results": results}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def write_file(self, arguments: dict) -> dict:
        try:
            path = self.policy.resolve(arguments["path"])
            content = arguments["content"].encode("utf-8")
            if len(content) > self.limits.max_file_write_bytes: return self._failure(ExecutionCode.RESOURCE_LIMIT, "write limit exceeded")
            if path.exists() and not arguments["overwrite"]: return self._failure(ExecutionCode.DENIED, "overwrite is not authorized")
            if path.parent.exists() is False or path.parent.is_symlink(): return self._failure(ExecutionCode.DENIED, "unsafe parent directory")
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as handle: handle.write(content); handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            verified = path.is_file() and path.stat().st_size == len(content)
            return ExecutionResult(code=ExecutionCode.SUCCESS if verified else ExecutionCode.VERIFICATION_FAILED, message="file written" if verified else "write verification failed", data={"path": str(path), "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def copy_file(self, arguments: dict) -> dict:
        try:
            source = self.policy.resolve(arguments["source"], must_exist=True)
            destination = self.policy.resolve(arguments["destination"])
            if not source.is_file() or source.is_symlink(): return self._failure(ExecutionCode.DENIED, "source must be a regular file")
            if destination.exists() and not arguments["overwrite"]: return self._failure(ExecutionCode.DENIED, "destination exists")
            if destination.parent.is_symlink() or not destination.parent.exists(): return self._failure(ExecutionCode.DENIED, "unsafe destination parent")
            if source.stat().st_size > self.limits.max_file_write_bytes: return self._failure(ExecutionCode.RESOURCE_LIMIT, "copy size limit exceeded")
            shutil.copyfile(source, destination)
            verified = destination.is_file() and destination.stat().st_size == source.stat().st_size
            return ExecutionResult(code=ExecutionCode.SUCCESS if verified else ExecutionCode.VERIFICATION_FAILED, message="file copied" if verified else "copy verification failed", data={"source": str(source), "destination": str(destination)}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def move_file(self, arguments: dict) -> dict:
        try:
            source = self.policy.resolve(arguments["source"], must_exist=True)
            destination = self.policy.resolve(arguments["destination"])
            if not source.is_file() or source.is_symlink(): return self._failure(ExecutionCode.DENIED, "source must be a regular file")
            if destination.exists() and not arguments["overwrite"]: return self._failure(ExecutionCode.DENIED, "destination exists")
            if destination.parent.is_symlink() or not destination.parent.exists(): return self._failure(ExecutionCode.DENIED, "unsafe destination parent")
            os.replace(source, destination)
            verified = not source.exists() and destination.is_file()
            return ExecutionResult(code=ExecutionCode.SUCCESS if verified else ExecutionCode.VERIFICATION_FAILED, message="file moved" if verified else "move verification failed", data={"source": str(source), "destination": str(destination)}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)

    def delete_file(self, arguments: dict) -> dict:
        try:
            path = self.policy.resolve(arguments["path"], must_exist=True)
            if not path.is_file() or path.is_symlink(): return self._failure(ExecutionCode.DENIED, "only regular files may be deleted")
            path.unlink()
            return ExecutionResult(code=ExecutionCode.SUCCESS if not path.exists() else ExecutionCode.VERIFICATION_FAILED, message="file deleted", data={"path": str(path)}).model_dump()
        except (OSError, PathSafetyError) as error:
            return self._failure(ExecutionCode.EXECUTION_FAILED, type(error).__name__)
