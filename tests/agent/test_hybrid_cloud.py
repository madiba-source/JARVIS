import pytest

from app.agent.cloud import MAX_CLOUD_RESPONSE_BYTES, CloudProvider
from app.agent.config import AgentConfig
from app.agent.model import ModelRequest
from app.agent.providers import StaticProvider
from app.agent.router import ModelRouter


def test_router_honors_offline_only_privacy_mode() -> None:
    config = AgentConfig(cloud_enabled=True, privacy_mode="offline_only")
    router = ModelRouter(
        config,
        local=StaticProvider(["local answer"], name="local"),
        cloud=CloudProvider(endpoint="https://api.example.com/v1/chat/completions", api_key="secret", model="gpt-small"),
    )

    response = router.generate(ModelRequest(prompt="hello"))

    assert response.ok is True
    assert response.provider == "local"
    assert router.cloud_available() is False


def test_router_uses_local_fallback_when_cloud_policy_blocks() -> None:
    config = AgentConfig(cloud_enabled=True, privacy_mode="local_preferred")
    router = ModelRouter(
        config,
        local=StaticProvider(["local answer"], name="local"),
        cloud=CloudProvider(endpoint="https://api.example.com/v1/chat/completions", api_key="secret", model="gpt-small"),
    )

    response = router.generate(ModelRequest(prompt="sensitive secret payload"))

    assert response.ok is True
    assert response.provider == "local"


def test_cloud_provider_rejects_invalid_host_and_oversized_payload() -> None:
    provider = CloudProvider(endpoint="https://api.example.com/v1/chat/completions", api_key="secret", model="gpt-small")

    with pytest.raises(ValueError):
        provider.validate_request("not a url", {"text": "x"})

    with pytest.raises(ValueError):
        provider.validate_request("https://api.example.com/v1/chat/completions", {"text": "x" * 100_000})


def test_cloud_provider_describe_does_not_expose_secrets() -> None:
    provider = CloudProvider(endpoint="https://api.example.com/v1/chat/completions", api_key="super-secret", model="gpt-small")

    info = provider.describe()

    assert info["configured"] is True
    assert "super-secret" not in str(info)


def test_cloud_provider_rejects_sensitive_payloads() -> None:
    provider = CloudProvider(endpoint="https://api.example.com/v1/chat/completions",
                             api_key="secret", model="gpt-small")

    with pytest.raises(ValueError):
        provider.validate_request(provider.endpoint, {
            "messages": [{"role": "user", "content": "send this password"}],
        })


def test_cloud_provider_rejects_oversized_responses(monkeypatch) -> None:
    class Response:
        status_code = 200
        content = b"x" * (MAX_CLOUD_RESPONSE_BYTES + 1)

        def json(self):
            return {"choices": [{"message": {"content": "ignored"}}]}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: Client())
    provider = CloudProvider(endpoint="https://api.example.com/v1/chat/completions",
                             api_key="secret", model="gpt-small")

    response = provider.generate(ModelRequest(prompt="hello"))

    assert response.state.value == "oversized"
