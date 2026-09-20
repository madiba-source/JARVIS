from pathlib import Path

from app.execution.policy import Phase04PolicyService
from app.policy.enums import AuthorizationLevel
from app.policy.models import ToolRequest


def request(tool: str, operation: str, arguments: dict, level: AuthorizationLevel, request_id: str = "request") -> ToolRequest:
    return ToolRequest(request_id=request_id, tool_name=tool, operation=operation, authorization_level=level, arguments=arguments, originating_subsystem="phase04-test")


def test_read_write_and_delete_policy_flow(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    result = service.execute(request("filesystem", "list_directory", {"path": "."}, AuthorizationLevel.L0_READ_ONLY))
    assert result.success

    write_request = request("filesystem_write", "write_file", {"path": "note.txt", "content": "hello", "overwrite": False}, AuthorizationLevel.L2_USER_DATA_MODIFICATION, "write")
    assert service.execute(write_request).code.value == "confirmation_required"
    token = service.issue_confirmation(write_request)
    confirmed = write_request.model_copy(update={"confirmation_token": token})
    written = service.execute(confirmed)
    assert written.success
    assert (tmp_path / "note.txt").read_text() == "hello"

    delete_request = request("filesystem_delete", "delete_file", {"path": "note.txt"}, AuthorizationLevel.L3_DESTRUCTIVE, "delete")
    assert service.execute(delete_request).code.value == "confirmation_required"
    delete_token = service.issue_confirmation(delete_request)
    deleted = service.execute(delete_request.model_copy(update={"confirmation_token": delete_token}))
    assert deleted.success
    assert not (tmp_path / "note.txt").exists()


def test_path_traversal_and_unknown_capability_denied(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    assert not hasattr(service, "filesystem")
    assert not hasattr(service, "terminal")
    assert not hasattr(service, "applications")
    traversal = request("filesystem", "read_file", {"path": "../outside"}, AuthorizationLevel.L0_READ_ONLY)
    result = service.execute(traversal)
    assert not result.success
    unknown = request("unknown", "run", {}, AuthorizationLevel.L0_READ_ONLY)
    assert service.execute(unknown).code.value == "denied"


def test_discovery_capabilities_are_typed_read_only_and_disable_aware(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    discovery = request("kali_capabilities", "discover", {}, AuthorizationLevel.L0_READ_ONLY, "kali")
    result = service.execute(discovery)
    assert result.success
    assert isinstance(result.data["capabilities"], list)
    assert service.execute(discovery.model_copy(update={"arguments": {"unexpected": True}})).code.value == "denied"

    service.set_jarvis_active(False)
    assert service.execute(discovery).code.value == "denied"


def test_emergency_stop_blocks_new_execution_without_touching_workspace(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    service.set_jarvis_active(False)
    request_to_read = request("filesystem", "list_directory", {"path": "."}, AuthorizationLevel.L0_READ_ONLY)
    result = service.execute(request_to_read)
    assert result.code.value == "denied"
    assert list(tmp_path.iterdir()) == []


def test_copy_move_and_read_output_limits(tmp_path: Path) -> None:
    service = Phase04PolicyService(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("source")
    copy_request = request("filesystem_write", "copy_file", {"source": "source.txt", "destination": "copy.txt", "overwrite": False}, AuthorizationLevel.L2_USER_DATA_MODIFICATION, "copy")
    copy_token = service.issue_confirmation(copy_request)
    assert service.execute(copy_request.model_copy(update={"confirmation_token": copy_token})).success
    move_request = request("filesystem_write", "move_file", {"source": "copy.txt", "destination": "moved.txt", "overwrite": False}, AuthorizationLevel.L2_USER_DATA_MODIFICATION, "move")
    move_token = service.issue_confirmation(move_request)
    assert service.execute(move_request.model_copy(update={"confirmation_token": move_token})).success
    (tmp_path / "large.txt").write_text("x" * 20_000)
    read_request = request("filesystem", "read_file", {"path": "large.txt", "max_bytes": 20_000}, AuthorizationLevel.L0_READ_ONLY, "large-read")
    assert service.execute(read_request).code.value == "resource_limit"
