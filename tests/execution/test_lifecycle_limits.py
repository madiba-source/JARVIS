import subprocess
import time
from pathlib import Path

from app.execution.apps import ApplicationManager, ApplicationRecord
from app.execution.models import ExecutionCode, ExecutionLimits
from app.execution.terminal import TerminalExecutor


def test_application_lifecycle_uses_discovered_record_only(monkeypatch) -> None:
    manager = ApplicationManager()
    record = ApplicationRecord(application_id="safe-test", display_name="safe-test", executable="/bin/true", desktop_file="/tmp/safe.desktop", argv=("/bin/true",))
    monkeypatch.setattr(manager, "_records", lambda: {"safe-test": record})
    launched = manager._launch({"application_id": "safe-test"})
    assert launched["code"] == ExecutionCode.SUCCESS
    time.sleep(0.02)
    observed = manager._observe({"application_id": "safe-test"})
    assert observed["data"]["running"] is False
    assert manager._close({"application_id": "safe-test"})["code"] == ExecutionCode.SUCCESS


def test_terminal_collection_terminates_timed_out_owned_process(tmp_path: Path) -> None:
    executor = TerminalExecutor(tmp_path, ExecutionLimits(command_timeout_seconds=0.05))
    process = subprocess.Popen(["/bin/sleep", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    stdout, stderr, exit_code = executor._collect(process)
    assert exit_code == -1
    assert "timeout" in stderr
    assert process.poll() is not None
