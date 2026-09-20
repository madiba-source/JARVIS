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


def test_application_record_exposes_safe_metadata(tmp_path: Path, monkeypatch) -> None:
    desktop = tmp_path / "browser.desktop"
    desktop.write_text("Type=Application\nName=Browser\nExec=/bin/true\nCategories=Network;WebBrowser;\nKeywords=web;browse;\n")
    manager = ApplicationManager()
    monkeypatch.setattr(manager, "_scan", lambda: {"browser": manager._parse(desktop)})

    result = manager.discover()

    record = result["data"]["applications"][0]
    assert record["display_name"] == "Browser"
    assert record["aliases"] == ("web", "browse")
    assert record["risk_level"] == 1
    assert record["requires_privileges"] is False


def test_application_refresh_invalidates_registry_cache(monkeypatch) -> None:
    manager = ApplicationManager()
    calls = []
    monkeypatch.setattr(manager, "_scan", lambda: calls.append(1) or {})

    manager.discover()
    manager.discover()
    manager.refresh()

    assert len(calls) == 2
