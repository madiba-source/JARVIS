import os

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "fastapi",
        "structlog",
        "PySide6",
        "pygame",
        "ollama",
    ],
)
def test_required_imports(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if module_name == "PySide6":
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    __import__(module_name)


def test_qt_application_initializes_headlessly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    assert application is not None
    application.quit()


def test_environment_does_not_require_cloud_credentials() -> None:
    assert not os.environ.get("JARVIS_OPENAI_API_KEY")
    assert not os.environ.get("JARVIS_GEMINI_API_KEY")
