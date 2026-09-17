"""Allowlisted argv-only terminal execution with bounded output."""

from __future__ import annotations

import os
import selectors
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .models import ExecutionCode, ExecutionLimits, ExecutionResult


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    executable: str
    allowed_arguments: tuple[str, ...] = ()


class TerminalExecutor:
    def __init__(self, working_directory: Path, limits: ExecutionLimits | None = None) -> None:
        self.working_directory = working_directory.resolve()
        self.limits = limits or ExecutionLimits()
        self._commands = self._build_commands()

    def _build_commands(self) -> dict[str, CommandSpec]:
        specs = {}
        for command_id, executable, args in (("pwd", "pwd", ()), ("whoami", "whoami", ()), ("uname", "uname", ("-s", "-r", "-m"))):
            path = shutil.which(executable)
            if path: specs[command_id] = CommandSpec(command_id, path, args)
        return specs

    def execute(self, arguments: dict) -> dict:
        command_id = arguments["command_id"]
        spec = self._commands.get(command_id)
        if spec is None: return ExecutionResult(code=ExecutionCode.DENIED, message="command is not allowlisted").model_dump()
        supplied = tuple(arguments.get("arguments", ()))
        if any(argument not in spec.allowed_arguments for argument in supplied): return ExecutionResult(code=ExecutionCode.DENIED, message="command arguments are not allowlisted").model_dump()
        argv = [spec.executable, *supplied]
        try:
            process = subprocess.Popen(argv, cwd=self.working_directory, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, close_fds=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
            stdout, stderr, exit_code = self._collect(process)
            code = ExecutionCode.SUCCESS if exit_code == 0 else ExecutionCode.EXECUTION_FAILED
            return ExecutionResult(code=code, message="command completed" if code is ExecutionCode.SUCCESS else "command failed", stdout=stdout, stderr=stderr, exit_code=exit_code).model_dump()
        except (OSError, ValueError) as error:
            return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=type(error).__name__).model_dump()

    def _collect(self, process: subprocess.Popen[bytes]) -> tuple[str, str, int]:
        selector = selectors.DefaultSelector()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        for stream in streams:
            if stream is not None: selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + self.limits.command_timeout_seconds
        truncated = False
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
                return "", "command timeout", -1
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj); key.fileobj.close(); continue
                buffer = streams[key.fileobj]
                limit = self.limits.max_stdout_bytes if key.fileobj is process.stdout else self.limits.max_stderr_bytes
                if len(buffer) < limit:
                    buffer.extend(chunk[: max(0, limit - len(buffer))])
                if len(chunk) > max(0, limit - len(buffer)):
                    truncated = True
        exit_code = process.wait(timeout=1)
        suffix = "\n[OUTPUT_TRUNCATED]" if truncated else ""
        return streams[process.stdout].decode("utf-8", "replace") + (suffix if truncated else ""), streams[process.stderr].decode("utf-8", "replace") + (suffix if truncated else ""), exit_code
