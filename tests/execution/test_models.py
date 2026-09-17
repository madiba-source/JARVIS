import pytest
from pydantic import ValidationError

from app.execution.models import ExecutionCode, ExecutionLimits, ExecutionResult
from app.execution.paths import PathPolicy, PathSafetyError
from app.execution.schemas import TerminalArgs, WriteFileArgs


def test_execution_limits_are_finite() -> None:
    limits = ExecutionLimits()
    assert limits.max_file_read_bytes > 0
    with pytest.raises(ValidationError):
        ExecutionLimits(max_stdout_bytes=0)


def test_typed_schemas_reject_extra_and_invalid_arguments() -> None:
    assert TerminalArgs(command_id="pwd").arguments == ()
    with pytest.raises(ValidationError):
        WriteFileArgs(path="x", content="data", unexpected=True)


def test_path_policy_containment_and_results(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert PathPolicy(root).resolve("file.txt") == root / "file.txt"
    with pytest.raises(PathSafetyError):
        PathPolicy(root).resolve("../outside")
    result = ExecutionResult(code=ExecutionCode.SUCCESS, message="ok")
    assert result.success