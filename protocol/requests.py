"""Client -> server JSON-RPC requests."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from protocol.types import JsonObject


class InitializeRequest(BaseModel):
    method: Literal["initialize"] = "initialize"
    client_name: str
    client_version: str
    protocol_version: str
    capabilities: JsonObject | None = None


class NewSessionRequest(BaseModel):
    method: Literal["session/new"] = "session/new"
    workspace_root: str
    model: str | None = None


class PromptRequest(BaseModel):
    method: Literal["session/prompt"] = "session/prompt"
    session_id: str
    text: str
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional wall-clock limit for this prompt (maps execution.tool_timeout_seconds semantics).",
    )


class InterruptRequest(BaseModel):
    method: Literal["session/interrupt"] = "session/interrupt"
    session_id: str


class ShutdownRequest(BaseModel):
    method: Literal["shutdown"] = "shutdown"
    reason: str | None = None


CLIENT_REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    InitializeRequest,
    NewSessionRequest,
    PromptRequest,
    InterruptRequest,
    ShutdownRequest,
)

ClientRequest = Annotated[
    Union[
        InitializeRequest,
        NewSessionRequest,
        PromptRequest,
        InterruptRequest,
        ShutdownRequest,
    ],
    Field(discriminator="method"),
]
