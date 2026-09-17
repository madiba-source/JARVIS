from app.core import JarvisCore
from app.core.config import Settings


def test_settings_load_without_cloud_credentials() -> None:
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.ollama_host == "http://127.0.0.1:11434"


def test_core_starts_and_shuts_down_cleanly() -> None:
    core = JarvisCore(Settings())
    assert not core.is_running
    core.start()
    assert core.is_running
    core.shutdown()
    assert not core.is_running


def test_core_lifecycle_is_idempotent() -> None:
    core = JarvisCore(Settings())
    core.start()
    core.start()
    core.shutdown()
    core.shutdown()
    assert not core.is_running
