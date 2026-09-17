from pathlib import Path

from app.execution.apps import ApplicationManager


def test_application_discovery_is_read_only(tmp_path: Path) -> None:
    manager = ApplicationManager()
    result = manager.discover()
    assert result["code"] == "success"
    assert isinstance(result["data"]["applications"], list)
    assert not list(tmp_path.iterdir())


def test_malformed_desktop_exec_is_not_accepted(tmp_path: Path) -> None:
    desktop = tmp_path / "unsafe.desktop"
    desktop.write_text("Type=Application\nName=Unsafe\nExec=sh -c 'echo unsafe'\n")
    record = ApplicationManager()._parse(desktop)
    assert record is None
