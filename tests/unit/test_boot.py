from app.core import JarvisCore
from app.core.config import Settings
from app.agent.config import AgentConfig
from app.agent.providers import StaticProvider
from app.agent.router import ModelRouter
from app.policy.service import PolicyEngineService


def test_settings_load_without_cloud_credentials() -> None:
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.ollama_host == "http://127.0.0.1:11434"


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
