"""Schemas used to validate untrusted local-model output."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class StructuredModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1)
    action: str = Field(min_length=1)
    requires_confirmation: bool
    risk_level: RiskLevel


class ModelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    parameters: str = Field(min_length=1)
    quantization: str = Field(min_length=1)
    license: str = Field(min_length=1)
    size_mb: int = Field(gt=0)
    context_length: int = Field(gt=0)