from pathlib import Path

from app.execution.policy import Phase04PolicyService
from app.policy.enums import AuthorizationLevel
from app.policy.models import ToolRequest


def test_allowlisted_terminal_command_and_injection_denial(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    safe = ToolRequest(request_id="pwd", tool_name="terminal", operation="execute", authorization_level=AuthorizationLevel.L0_READ_ONLY, arguments={"command_id": "pwd", "arguments": ()}, originating_subsystem="test")
    result = service.execute(safe)
    assert result.success
    assert str(tmp_path) in result.stdout

    injected = safe.model_copy(update={"request_id": "inject", "arguments": {"command_id": "pwd", "arguments": (";", "whoami")}})
    assert service.execute(injected).code.value == "denied"


def test_unknown_command_is_denied(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    request = ToolRequest(request_id="unknown", tool_name="terminal", operation="execute", authorization_level=AuthorizationLevel.L0_READ_ONLY, arguments={"command_id": "sh", "arguments": ()}, originating_subsystem="test")
    assert service.execute(request).code.value == "denied"
