"""Replaceable cloud sandbox types.

The provider life cycle is create, attach, stop, destroy, and health. It is
not a Run. A missing isolation runtime fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AttachRefused(PermissionError):
    """Another tenant, or an unknown sandbox, cannot attach."""

    def __init__(self, sandbox_id: str, tenant_id: str) -> None:
        self.sandbox_id = sandbox_id
        self.tenant_id = tenant_id
        super().__init__(f"attach refused: {tenant_id} cannot attach {sandbox_id}")


class IsolationUnavailable(RuntimeError):
    """The named target has no isolation capability."""

    def __init__(self, target: str, detail: str) -> None:
        self.target = target
        self.detail = detail
        super().__init__(f"target unavailable: {target}: {detail}")


@dataclass(frozen=True)
class SandboxHandle:
    sandbox_id: str
    container_id: str
    tenant_id: str
    workspace_id: str
    runtime: str
    retain: bool
    status: str


@dataclass(frozen=True)
class ExecResult:
    sandbox_id: str
    container_id: str
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(Protocol):
    """One isolation backend. A VM provider can replace the container adapter."""

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        retain: bool = True,
    ) -> SandboxHandle:
        """Start an isolated sandbox. This does not open a Run."""

    def attach(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        """Return the sandbox only when the caller owns it."""

    def stop(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        """Stop the sandbox and keep its record."""

    def destroy(self, sandbox_id: str, *, tenant_id: str) -> None:
        """Remove the sandbox."""

    def health(self, sandbox_id: str, *, tenant_id: str) -> dict[str, str]:
        """Report status for the owning tenant."""

    def exec(
        self,
        sandbox_id: str,
        *,
        tenant_id: str,
        argv: list[str],
        timeout: float = 60,
    ) -> ExecResult:
        """Run argv inside the sandbox. Never on the server host."""
