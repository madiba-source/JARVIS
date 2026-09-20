from app.core import JarvisCore
from app.core.config import Settings
from app.audio.config import AudioConfig
from app.agent.config import AgentConfig
from app.agent.providers import StaticProvider
from app.agent.router import ModelRouter
from app.policy.service import PolicyEngineService


def test_settings_load_without_cloud_credentials() -> None:
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.ollama_host == "http://127.0.0.1:11434"


def test_hud_asset_integrity() -> None:
    import hashlib

    from app.hud.runtime import ASSET_PATH, ASSET_SHA256, HudRuntime

    assert HudRuntime.verify_asset(ASSET_PATH)
    assert hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest() == ASSET_SHA256


def test_core_starts_and_shuts_down_cleanly() -> None:
    config = AgentConfig()
    router = ModelRouter(config, local=StaticProvider())
    core = JarvisCore(Settings(), agent_config=config, agent_router=router,
                      policy_service=PolicyEngineService())
    assert not core.is_running
    core.start()
    assert core.is_running
    assert core.agent_runtime is not None
    assert core.agent_runtime.router is router
    core.shutdown()
    assert not core.is_running
    assert core.agent_runtime is None


def test_core_lifecycle_is_idempotent() -> None:
    config = AgentConfig()
    router = ModelRouter(config, local=StaticProvider())
    core = JarvisCore(Settings(), agent_config=config, agent_router=router,
                      policy_service=PolicyEngineService())
    core.start()
    runtime = core.agent_runtime
    core.start()
    assert core.agent_runtime is runtime
    core.shutdown()
    core.shutdown()
    assert not core.is_running


def test_agent_runtime_startup_failure_isolated_from_core(monkeypatch) -> None:
    class FailingRuntime:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("startup failed")

    monkeypatch.setattr("app.agent.coordinator.AgentRuntime", FailingRuntime)
    config = AgentConfig()
    core = JarvisCore(Settings(), agent_config=config,
                      agent_router=ModelRouter(config, local=StaticProvider()),
                      policy_service=PolicyEngineService())

    core.start()

    assert core.is_running
    assert core.agent_runtime is None
    assert core.agent_runtime_error == "RuntimeError"
    core.shutdown()


def test_default_core_runtime_uses_phase04_capabilities(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, memory_enabled=False)
    core = JarvisCore(settings)

    core.start()

    assert core.agent_runtime is not None
    assert "terminal" in core.agent_runtime.gateway.catalog.tool_ids
    assert "filesystem" in core.agent_runtime.gateway.catalog.tool_ids
    core.shutdown()


def test_core_disable_and_enable_delegate_to_managed_services(tmp_path) -> None:
    core = JarvisCore(Settings(data_dir=tmp_path, memory_enabled=False))
    core.start()

    core.disable()
    assert core.agent_runtime is not None
    assert core.autonomy_runtime is not None
    assert core.agent_runtime.status().control_state == "disabled"
    assert core.agent_runtime.gateway.evaluate is not None

    core.enable()
    assert core.agent_runtime.status().control_state == "enabled"
    core.shutdown()


def test_core_hud_lifecycle_is_safe(tmp_path) -> None:
    core = JarvisCore(Settings(data_dir=tmp_path, memory_enabled=False, hud_enabled=True))
    core.start()
    assert core.hud_runtime is not None
    core.disable()
    if core.hud_runtime.available:
        assert not core.hud_runtime.enabled
    core.shutdown()
    assert core.hud_runtime is None


def test_core_proactive_scheduler_follows_global_disable(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, memory_enabled=False, hud_enabled=False,
                        automation_enabled=True, calendar={"enabled": False})
    core = JarvisCore(settings)

    core.start()
    assert core.proactive_runtime is not None
    assert core.proactive_runtime.running

    core.disable()
    assert not core.proactive_runtime.running
    assert not core.proactive_runtime.enabled

    core.enable()
    assert core.proactive_runtime.running
    assert core.proactive_runtime.enabled
    core.shutdown()


def test_voice_startup_failure_isolated_from_core(tmp_path, monkeypatch) -> None:
    class FailingVoiceRuntime:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("audio unavailable")

    monkeypatch.setattr("app.audio.runtime.VoiceRuntime", FailingVoiceRuntime)
    settings = Settings(data_dir=tmp_path, memory_enabled=False, voice=AudioConfig(enabled=True))
    core = JarvisCore(settings)

    core.start()

    assert core.is_running
    assert core.voice_runtime is None
    core.shutdown()
