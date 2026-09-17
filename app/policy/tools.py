"""Safe fake tools used only by Phase 03 policy tests and bootstrap."""

from typing import Any, Callable


def create_fake_tool_executor(tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def fake_executor(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success", "tool": tool_name, "executed_mock_action": True, "received_arguments": arguments}

    return fake_executor
