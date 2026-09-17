"""Provider state abstraction with no network dependency."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProviderState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ProviderState
    detail: str = ""


def unavailable_status(error: Exception | None = None) -> ProviderStatus:
    return ProviderStatus(state=ProviderState.UNAVAILABLE, detail=str(error or "provider unavailable"))