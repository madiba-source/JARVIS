import threading
import time

from app.policy import AuthorizationLevel, PolicyEngineService, ToolRequest


def test_in_flight_execution_can_finish_but_disable_blocks_new_admission() -> None:
    service = PolicyEngineService()
    request = ToolRequest(request_id="lease", tool_name="fake_read_status", operation="read", authorization_level=AuthorizationLevel.L0_READ_ONLY, arguments={"format": "json"}, originating_subsystem="test")
    decision, permit = service.process_request(request)
    assert permit is not None and decision.decision.value == "ALLOW"
    started = threading.Event()
    release = threading.Event()
    original = service.registry._invoke_for_gateway

    def delayed(tool_id, arguments):
        started.set()
        release.wait(timeout=1)
        return original(tool_id, arguments)

    service.registry._invoke_for_gateway = delayed
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("value", service.execute_with_permit(request, permit)))
    worker.start()
    assert started.wait(timeout=1)
    service.set_jarvis_active(False)
    release.set()
    worker.join(timeout=1)
    assert result["value"]["status"] == "success"
    denied, new_permit = service.process_request(request.model_copy(update={"request_id": "new"}))
    assert denied.decision.value == "SYSTEM_DISABLED"
    assert new_permit is None
