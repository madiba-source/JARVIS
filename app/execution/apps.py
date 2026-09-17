"""Read-only desktop discovery and process lifecycle for discovered apps."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .models import ExecutionCode, ExecutionResult


@dataclass(frozen=True)
class ApplicationRecord:
    application_id: str
    display_name: str
    executable: str
    desktop_file: str
    argv: tuple[str, ...]
    categories: tuple[str, ...] = ()
    terminal: bool = False


class ApplicationManager:
    def __init__(self, max_applications: int = 1_000) -> None:
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.RLock()
        self._max_applications = max_applications

    def discover(self) -> dict:
        records: dict[str, ApplicationRecord] = {}
        directories = [Path.home() / ".local/share/applications", Path("/usr/share/applications")]
        for directory in directories:
            if len(records) >= self._max_applications: break
            if not directory.is_dir(): continue
            for desktop_file in sorted(directory.glob("*.desktop")):
                record = self._parse(desktop_file)
                if record and record.application_id not in records: records[record.application_id] = record
                if len(records) >= self._max_applications: break
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="applications discovered", data={"applications": [record.__dict__ for record in records.values()]}).model_dump()

    def _parse(self, path: Path) -> ApplicationRecord | None:
        try: lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except OSError: return None
        values: dict[str, str] = {}
        for line in lines:
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1); values.setdefault(key.strip(), value.strip())
        if values.get("Type") != "Application" or values.get("NoDisplay", "false").lower() == "true" or values.get("Terminal", "false").lower() == "true": return None
        raw_exec = values.get("Exec", "")
        if any(token in raw_exec for token in ("%", "&&", ";", "|", "`", "$", ">", "<")): return None
        try: argv = tuple(shlex.split(raw_exec))
        except ValueError: return None
        if not argv: return None
        if Path(argv[0]).name in {"sh", "bash", "dash", "zsh", "fish", "csh", "ksh"} or "-c" in argv[1:]: return None
        executable = shutil.which(argv[0])
        if not executable or not os.access(executable, os.X_OK): return None
        application_id = path.name.removesuffix(".desktop")
        return ApplicationRecord(application_id=application_id, display_name=values.get("Name", application_id), executable=str(Path(executable).resolve()), desktop_file=str(path.resolve()), argv=(str(Path(executable).resolve()), *argv[1:]), categories=tuple(filter(None, values.get("Categories", "").split(";"))), terminal=values.get("Terminal", "false").lower() == "true")

    def _launch(self, arguments: dict) -> dict:
        with self._lock:
            records = self._records()
            record = records.get(arguments["application_id"])
            if record is None: return ExecutionResult(code=ExecutionCode.UNAVAILABLE, message="application is not discovered").model_dump()
            existing = self._processes.get(record.application_id)
            if existing and existing.poll() is None: return ExecutionResult(code=ExecutionCode.SUCCESS, message="application already running", data={"pid": existing.pid, "application_id": record.application_id}).model_dump()
            try:
                process = subprocess.Popen(list(record.argv), shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
                self._processes[record.application_id] = process
                return ExecutionResult(code=ExecutionCode.SUCCESS, message="application launched", data={"pid": process.pid, "application_id": record.application_id}).model_dump()
            except OSError as error: return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=type(error).__name__).model_dump()

    def _close(self, arguments: dict) -> dict:
        with self._lock:
            process = self._processes.get(arguments["application_id"])
            if process is None or process.poll() is not None: return ExecutionResult(code=ExecutionCode.SUCCESS, message="application is not running").model_dump()
            try:
                process.terminate(); process.wait(timeout=3)
                return ExecutionResult(code=ExecutionCode.SUCCESS if process.poll() is not None else ExecutionCode.VERIFICATION_FAILED, message="application closed").model_dump()
            except (OSError, subprocess.TimeoutExpired) as error: return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=type(error).__name__).model_dump()

    def _force_close(self, arguments: dict) -> dict:
        with self._lock:
            process = self._processes.get(arguments["application_id"])
            if process is None or process.poll() is not None: return ExecutionResult(code=ExecutionCode.SUCCESS, message="application is not running").model_dump()
            try:
                process.kill(); process.wait(timeout=1)
                return ExecutionResult(code=ExecutionCode.SUCCESS if process.poll() is not None else ExecutionCode.VERIFICATION_FAILED, message="application force-terminated").model_dump()
            except (OSError, subprocess.TimeoutExpired) as error: return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=type(error).__name__).model_dump()

    def _observe(self, arguments: dict) -> dict:
        with self._lock:
            process = self._processes.get(arguments["application_id"])
            running = process is not None and process.poll() is None
            return ExecutionResult(code=ExecutionCode.SUCCESS, message="application observed", data={"application_id": arguments["application_id"], "running": running, "pid": process.pid if process else None}).model_dump()

    def _records(self) -> dict[str, ApplicationRecord]:
        result: dict[str, ApplicationRecord] = {}
        directories = [Path.home() / ".local/share/applications", Path("/usr/share/applications")]
        for directory in directories:
            if len(result) >= self._max_applications: break
            if directory.is_dir():
                for desktop_file in sorted(directory.glob("*.desktop")):
                    record = self._parse(desktop_file)
                    if record: result.setdefault(record.application_id, record)
                    if len(result) >= self._max_applications: break
        return result
