import json

import pytest
from pydantic import ValidationError

from app.model.provider import ProviderState, ProviderStatus
from app.model.validation import ModelMetadata, StructuredModelResponse
from scripts.benchmark_model import BenchmarkConfig, validate_model_installed


def test_model_metadata_and_structured_response_validation() -> None:
    metadata = ModelMetadata(name="Qwen", tag="qwen2.5:1.5b", parameters="1.54B", quantization="Q4_K_M", license="Apache-2.0", size_mb=986, context_length=32768)
    assert metadata.tag == "qwen2.5:1.5b"
    response = StructuredModelResponse(
        intent="open_application",
        action="propose_open_firefox",
        requires_confirmation=True,
        risk_level="L1",
    )
    assert response.risk_level == "L1"
    assert json.loads(response.model_dump_json())["requires_confirmation"] is True


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(ValidationError):
        StructuredModelResponse.model_validate_json('{"intent": "missing fields"}')


def test_offline_provider_states_are_explicit() -> None:
    assert ProviderStatus(state=ProviderState.OFFLINE).state == ProviderState.OFFLINE
    assert ProviderStatus(state=ProviderState.TIMEOUT).state == ProviderState.TIMEOUT


def test_benchmark_configuration_is_finite() -> None:
    assert BenchmarkConfig(max_prompts=5).max_output_tokens == 128
    with pytest.raises(ValidationError):
        BenchmarkConfig(max_prompts=6)
    with pytest.raises(ValidationError):
        BenchmarkConfig(request_timeout_seconds=0)


def test_model_not_installed_is_rejected_before_inference() -> None:
    with pytest.raises(ValueError, match="model is not installed"):
        validate_model_installed("missing:tag", ["qwen2.5:1.5b"])