"""Tenant to workspace map and the sandboxd tool endpoint.

A Run id only records billing. The sandbox stays up when retain is set, and
close destroys it otherwise. An unavailable runtime blocks the tool.
"""

from __future__ import annotations

import time
import uuid

from rxycode_runner.sandbox.provider import (
    AttachRefused,
    ExecResult,
    IsolationUnavailable,
    SandboxHandle,
    SandboxProvider,
)


class ToolBlocked(RuntimeError):
    """The tool did not start. The target is unavailable."""

    def __init__(self, target: str, detail: str) -> None:
        self.target = target
        self.detail = detail
        super().__init__(f"tool blocked: target unavailable: {target}: {detail}")


class SandboxControl:
    """Maps each tenant to its workspaces and talks to one SandboxProvider."""

    def __init__(self, provider: SandboxProvider) -> None:
        self._provider = provider
        self._workspaces: dict[str, dict[str, str]] = {}
        self._runs: dict[str, dict[str, object]] = {}
        self._started: dict[str, float] = {}
        self._ledger: list[dict[str, object]] = []

    def derive_target(self, tenant_id: str, workspace_id: str) -> str:
        return f"cloud:{tenant_id}:{workspace_id}"

    def workspaces(self, tenant_id: str) -> dict[str, str]:
        return dict(self._workspaces.get(tenant_id, {}))

    def ledger(self) -> list[dict[str, object]]:
        return [dict(row) for row in self._ledger]

    def create_sandbox(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        retain: bool = True,
    ) -> SandboxHandle:
        target = self.derive_target(tenant_id, workspace_id)
        try:
            handle = self._provider.create(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                retain=retain,
            )
        except IsolationUnavailable as exc:
            self._record(
                "blocked",
                sandbox_id="",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                target=target,
                runtime_seconds=0.0,
            )
            raise ToolBlocked(target, str(exc)) from exc
        self._workspaces.setdefault(tenant_id, {})[handle.sandbox_id] = workspace_id
        self._started[handle.sandbox_id] = time.monotonic()
        self._record(
            "start",
            sandbox_id=handle.sandbox_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target=target,
            runtime_seconds=0.0,
        )
        return handle

    def sandboxd_exec(
        self,
        *,
        tenant_id: str,
        argv: list[str],
        sandbox_id: str | None = None,
        workspace_id: str | None = None,
        timeout: float = 60,
    ) -> ExecResult:
        if sandbox_id is None:
            if not workspace_id:
                raise ToolBlocked("cloud:missing", "workspace is required")
            created = self.create_sandbox(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                retain=True,
            )
            sandbox_id = created.sandbox_id
            workspace_id = created.workspace_id
        try:
            return self._provider.exec(
                sandbox_id,
                tenant_id=tenant_id,
                argv=argv,
                timeout=timeout,
            )
        except IsolationUnavailable as exc:
            workspace = workspace_id or self._workspace_of(tenant_id, sandbox_id)
            target = self.derive_target(tenant_id, workspace or "unknown")
            self._record(
                "blocked",
                sandbox_id=sandbox_id,
                tenant_id=tenant_id,
                workspace_id=workspace or "",
                target=target,
                runtime_seconds=0.0,
            )
            raise ToolBlocked(target, str(exc)) from exc

    def open_run(self, *, tenant_id: str, sandbox_id: str) -> str:
        handle = self._provider.attach(sandbox_id, tenant_id=tenant_id)
        run_id = "run-" + uuid.uuid4().hex[:12]
        self._runs[run_id] = {
            "tenant_id": tenant_id,
            "sandbox_id": sandbox_id,
            "workspace_id": handle.workspace_id,
            "retain": handle.retain,
        }
        return run_id

    def close_run(self, *, tenant_id: str, run_id: str) -> None:
        row = self._runs.get(run_id)
        if row is None or row["tenant_id"] != tenant_id:
            raise AttachRefused(run_id, tenant_id)
        sandbox_id = str(row["sandbox_id"])
        workspace_id = str(row["workspace_id"])
        self._record(
            "bill",
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target=self.derive_target(tenant_id, workspace_id),
            runtime_seconds=self._elapsed(sandbox_id),
        )
        del self._runs[run_id]
        if row["retain"] is not True:
            self.destroy(tenant_id=tenant_id, sandbox_id=sandbox_id)

    def stop(self, *, tenant_id: str, sandbox_id: str) -> None:
        self._provider.stop(sandbox_id, tenant_id=tenant_id)

    def destroy(self, *, tenant_id: str, sandbox_id: str) -> None:
        handle = self._provider.attach(sandbox_id, tenant_id=tenant_id)
        self._provider.destroy(sandbox_id, tenant_id=tenant_id)
        self._workspaces.get(tenant_id, {}).pop(sandbox_id, None)
        self._record(
            "destroy",
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            workspace_id=handle.workspace_id,
            target=self.derive_target(tenant_id, handle.workspace_id),
            runtime_seconds=self._elapsed(sandbox_id),
        )

    def health(self, *, tenant_id: str, sandbox_id: str) -> dict[str, str]:
        return self._provider.health(sandbox_id, tenant_id=tenant_id)

    def _workspace_of(self, tenant_id: str, sandbox_id: str) -> str:
        return self._workspaces.get(tenant_id, {}).get(sandbox_id, "")

    def _elapsed(self, sandbox_id: str) -> float:
        started = self._started.get(sandbox_id)
        if started is None:
            return 0.0
        return max(0.0, time.monotonic() - started)

    def _record(
        self,
        kind: str,
        *,
        sandbox_id: str,
        tenant_id: str,
        workspace_id: str,
        target: str,
        runtime_seconds: float,
    ) -> None:
        self._ledger.append(
            {
                "kind": kind,
                "sandbox_id": sandbox_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "target": target,
                "runtime_seconds": runtime_seconds,
            }
        )
