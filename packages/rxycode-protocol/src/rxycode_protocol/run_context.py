"""Explicit run scope. The server fills it. The client body does not."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass

_CURRENT: ContextVar[RunContext | None] = ContextVar("rxycode_run_context", default=None)

_IDENTITY_FIELDS = (
    "tenant_id",
    "actor_id",
    "project_id",
    "session_id",
    "target_id",
    "permission_profile",
    "deadline_at",
    "trace_id",
)
_FORBIDDEN = ("api_key", "device_token", "authorization", "token")


@dataclass(frozen=True)
class RunContext:
    """One run inside one session. Frozen so callers cannot swap tenant later."""

    tenant_id: str
    actor_id: str
    project_id: str
    session_id: str
    run_id: str
    target_id: str
    permission_profile: str
    deadline_at: str
    trace_id: str

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}

    @classmethod
    def from_authenticated(
        cls,
        authenticated: Mapping[str, object],
        claimed: Mapping[str, object] | None = None,
    ) -> RunContext:
        """Build a run from the authenticated identity.

        ``claimed`` is the client body. Its tenant id and secrets are ignored.
        ``run_id`` is always minted here, never copied from either mapping.
        """
        del claimed
        for key in _FORBIDDEN:
            if key in authenticated:
                raise ValueError(f"RunContext refuses {key}")
        values: dict[str, str] = {}
        for field in _IDENTITY_FIELDS:
            raw = authenticated.get(field)
            if raw is None or str(raw) == "":
                raise ValueError(f"RunContext missing {field}")
            values[field] = str(raw)
        values["run_id"] = uuid.uuid4().hex
        return cls(**values)


def bind_run_context(context: RunContext | None) -> Token[RunContext | None]:
    """Bind one run for the current task. Callers reset the returned token."""
    return _CURRENT.set(context)


def reset_run_context(token: Token[RunContext | None]) -> None:
    _CURRENT.reset(token)


def current_run_context() -> RunContext | None:
    return _CURRENT.get()
