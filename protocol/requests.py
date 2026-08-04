"""Client -> server JSON-RPC requests."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .types import JsonObject


class InitializeRequest(BaseModel):
    """JSON-RPC handshake on connect (future ``python -m appserver``).

    ``client_name`` / ``client_version`` identify the OpenTUI or Desktop client;
    ``protocol_version`` must equal ``protocol.version.PROTOCOL_VERSION``;
    ``capabilities`` is an optional client feature manifest (unused in HTTP mode).
    """

    method: Literal["initialize"] = "initialize"
    client_name: str
    client_version: str
    protocol_version: str
    capabilities: JsonObject | None = None


class NewSessionRequest(BaseModel):
    """Bind a workspace and chat namespace (maps ``_activate_session`` in api_server.py).

    ``workspace_root`` is the repo root passed to AgentV2 tools (today ``Path.cwd()``);
    ``model`` optionally overrides the default from ``config/settings.py``.
    """

    method: Literal["session/new"] = "session/new"
    workspace_root: str
    model: str | None = None


class PromptRequest(BaseModel):
    """One user turn (maps ``POST /chat`` ``ChatRequest`` in api_server.py).

    ``session_id`` uses ``memory.long_term.validate_session_id``; ``text`` is
    ``ChatRequest.message``; ``timeout_seconds`` mirrors execution tool timeout
    semantics when appserver enforces wall-clock limits.
    ``mode`` selects AgentV2 run mode; ``thinking_expanded`` gates reasoning
    stream emission on ``ProtocolTui``.
    """

    method: Literal["session/prompt"] = "session/prompt"
    session_id: str
    text: str
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional wall-clock limit for this prompt (maps execution.tool_timeout_seconds semantics).",
    )
    mode: str | None = Field(
        default=None,
        description="Agent run mode (build/plan/compose); defaults to build.",
    )
    thinking_expanded: bool | None = Field(
        default=None,
        description="When true, ProtocolTui emits event/reasoning_snapshot chunks.",
    )


class InterruptRequest(BaseModel):
    """Cancel the in-flight run (maps ``POST /cancel`` + ``Session.interrupt`` in api_server.py).

    ``session_id`` matches the active ``ChatRequest.session_id`` namespace.
    """

    method: Literal["session/interrupt"] = "session/interrupt"
    session_id: str


class SetThinkingExpandedRequest(BaseModel):
    """Sync OpenTUI /thinking expand state into appserver ProtocolTui.

    ``expanded`` mirrors the client Thought panel; when a prompt is in flight the
    bound worker TUI is updated so mid-run expand can push an accumulated snapshot.
    """

    method: Literal["session/set_thinking_expanded"] = "session/set_thinking_expanded"
    session_id: str
    expanded: bool


class WarmSessionRequest(BaseModel):
    """Pre-bootstrap AgentV2 for a session so the first prompt is not cold-start.

    Maps appserver ``AgentHost.ensure_bootstrapped`` without running a user turn.
    """

    method: Literal["session/warm"] = "session/warm"
    session_id: str
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional wall-clock limit for bootstrap (defaults to appserver warm timeout).",
    )


class ShutdownRequest(BaseModel):
    """Graceful appserver shutdown (future ``appserver`` lifespan teardown).

    ``reason`` is logged on stderr only; HTTP ``api_server`` mode ignores this today.
    """

    method: Literal["shutdown"] = "shutdown"
    reason: str | None = None


CLIENT_REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    InitializeRequest,
    NewSessionRequest,
    PromptRequest,
    InterruptRequest,
    SetThinkingExpandedRequest,
    WarmSessionRequest,
    ShutdownRequest,
)

ClientRequest = Annotated[
    Union[
        InitializeRequest,
        NewSessionRequest,
        PromptRequest,
        InterruptRequest,
        SetThinkingExpandedRequest,
        WarmSessionRequest,
        ShutdownRequest,
    ],
    Field(discriminator="method"),
]
