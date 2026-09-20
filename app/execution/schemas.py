"""Strict per-operation argument models for Phase 04 capabilities."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefreshArgs(EmptyArgs):
    pass


class PathArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: StrictStr = Field(min_length=1, max_length=4096)


class ReadFileArgs(PathArgs):
    max_bytes: StrictInt | None = Field(default=None, ge=1, le=16_777_216)


class ListDirectoryArgs(PathArgs):
    pass


class SearchFilesArgs(PathArgs):
    pattern: StrictStr = Field(min_length=1, max_length=256)


class WriteFileArgs(PathArgs):
    content: StrictStr = Field(max_length=1_048_576)
    overwrite: StrictBool = False


class CreateFileArgs(PathArgs):
    content: StrictStr = Field(max_length=1_048_576)


class CopyMoveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: StrictStr = Field(min_length=1, max_length=4096)
    destination: StrictStr = Field(min_length=1, max_length=4096)
    overwrite: StrictBool = False


class DeleteFileArgs(PathArgs):
    pass


class TerminalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: StrictStr = Field(min_length=1, max_length=128)
    arguments: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=16)


class LaunchAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: StrictStr = Field(min_length=1, max_length=256)


class ObserveAppArgs(LaunchAppArgs):
    pass


class CloseAppArgs(LaunchAppArgs):
    pass


class ForceCloseAppArgs(LaunchAppArgs):
    pass
