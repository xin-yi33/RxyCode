"""Initialize result and capability snapshot (PhaseG-B2). Additive only."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .types import JsonObject
from .version import APPSERVER_VERSION, PROTOCOL_VERSION, PROTOCOL_VERSION_MAX, PROTOCOL_VERSION_MIN


class CapabilitySnapshot(BaseModel):
    """Honest capability flags. False means not implemented yet, not hidden."""

    model_config = ConfigDict(populate_by_name=True)

    threads: bool = True
    thread_fork: bool = True
    background_turns: bool = False
    background_tasks: bool = True
    command_execution: bool = True
    file_changes: bool = True
    review: bool = True
    review_comments: bool = True
    checkpoint: bool = True
    git_hunk_actions: bool = True
    worktree: bool = True
    file_preview: bool = True
    settings: bool = True
    browser: bool = False
    mcp: bool = True
    skills: bool = True
    multi_agent: bool = True
    multi_model: bool = True
    vision: bool = False
    approval_auto_review: bool = Field(
        default=True,
        alias="approval.auto_review",
        description="Wire name approval.auto_review.",
    )


class ModelProviderSummary(BaseModel):
    provider_id: str
    model_id: str | None = None
    model_context_window: int | None = None
    model_max_output_tokens: int | None = None
    limit_source: str | None = None
    is_fallback: bool = False
    warning: str | None = None


class ModelSummary(BaseModel):
    """PhaseG-B10 model limit summary. limit_source is the Phase 3 resolver source."""

    provider_id: str
    model_id: str
    model_context_window: int | None = None
    model_max_output_tokens: int | None = None
    resolved_max_tokens: int | None = None
    limit_source: str | None = None
    is_fallback: bool = False
    warning: str | None = None
    matched_catalog_key: str | None = None
    known_model: bool = False
    family_pattern: str | None = None


class PermissionProfileSummary(BaseModel):
    profile_id: str
    selectable: bool
    description: str


class InitializeResult(BaseModel):
    """Additive initialize response. Old clients ignore unknown keys."""

    protocol_version: str = PROTOCOL_VERSION
    protocol_min: str = PROTOCOL_VERSION_MIN
    protocol_max: str = PROTOCOL_VERSION_MAX
    server_name: str = "rxycode-appserver"
    server_version: str = APPSERVER_VERSION
    capabilities: JsonObject
    capability_snapshot: CapabilitySnapshot
    model_providers: list[ModelProviderSummary]
    permission_profiles: list[PermissionProfileSummary]


HANDSHAKE_MODELS: tuple[type[BaseModel], ...] = (
    CapabilitySnapshot,
    ModelProviderSummary,
    ModelSummary,
    PermissionProfileSummary,
    InitializeResult,
)
