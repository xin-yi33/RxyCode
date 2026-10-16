"""Import a repo into a tenant sandbox. Checkout stays off the API host."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace

from rxycode_runner.sandbox.gvisor import GVisorSandbox
from rxycode_runner.sandbox.policy import launch, load_policy
from rxycode_runner.sandbox.workspace import (
    CheckoutFailed,
    adopt_checkout,
    discard_checkout,
    prepare_checkout,
    run_in_workspace,
    tree_bytes,
)
from rxycode_server.workspaces.snapshots import SnapshotRefused, SnapshotStore

_REPO = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$")
_REV = re.compile(r"^[0-9a-f]{40}$")


class RepoRefused(PermissionError):
    """The repo URL or revision is outside the allowlist."""

    def __init__(self, detail: str = "repo url refused") -> None:
        super().__init__(detail)


@dataclass(frozen=True)
class ImportedWorkspace:
    workspace_id: str
    sandbox_id: str
    container_id: str
    revision: str
    test_stdout: str
    log: str
    snapshot_id: str
    snapshot_sha256: str


class WorkspaceProvision:
    def __init__(self) -> None:
        self._store = SnapshotStore()
        self._rows: dict[str, dict[str, str]] = {}

    def import_repo(
        self,
        *,
        tenant_id: str,
        project_id: str,
        url: str,
        revision: str,
        bundle: bytes,
        token: str | None = None,
        authorize_snapshot: bool = False,
        ttl_seconds: int | None = None,
    ) -> ImportedWorkspace:
        redacted = _redact(url, token)
        if not _REPO.fullmatch(redacted) or ".." in redacted:
            raise RepoRefused("repo url refused")
        if not _REV.fullmatch(revision):
            raise RepoRefused("revision refused")
        if not bundle:
            raise RepoRefused("bundle refused")
        policy = load_policy()
        if ttl_seconds is not None:
            policy = replace(policy, ttl_seconds=ttl_seconds)
        git_name = prepare_checkout(bundle=bundle, revision=revision)
        handle = None
        try:
            handle = launch(
                tenant_id=tenant_id,
                workspace_id=project_id,
                policy=policy,
            )
            adopt_checkout(handle, git_name)
            code, stdout, stderr = run_in_workspace(
                handle,
                ["python", "/tmp/ws/test_sample.py"],
            )
            if code != 0:
                raise CheckoutFailed(_redact(stderr or "sandbox test failed", token))
            blob = tree_bytes(handle)
            blob = _redact_bytes(blob, token)
            snapshot_id, digest = self._store.put(
                tenant_id=tenant_id,
                blob=blob,
                authorized=authorize_snapshot,
            )
            workspace_id = "ws-" + uuid.uuid4().hex[:12]
            self._rows[workspace_id] = {
                "tenant_id": tenant_id,
                "sandbox_id": handle.sandbox_id,
                "container_id": handle.container_id,
            }
            log = _redact(f"imported {redacted} revision {revision}", token)
            return ImportedWorkspace(
                workspace_id=workspace_id,
                sandbox_id=handle.sandbox_id,
                container_id=handle.container_id,
                revision=revision,
                test_stdout=_redact(stdout, token),
                log=log,
                snapshot_id=snapshot_id,
                snapshot_sha256=digest,
            )
        except Exception:
            if handle is not None:
                GVisorSandbox().destroy(handle.sandbox_id, tenant_id=tenant_id)
            raise
        finally:
            discard_checkout(git_name)

    def read_snapshot(self, *, tenant_id: str, snapshot_id: str) -> bytes:
        return self._store.read(tenant_id=tenant_id, snapshot_id=snapshot_id)

    def cleanup(self, *, tenant_id: str, workspace_id: str) -> None:
        row = self._rows.get(workspace_id)
        if row is None or row["tenant_id"] != tenant_id:
            raise SnapshotRefused(workspace_id, tenant_id)
        GVisorSandbox().destroy(row["sandbox_id"], tenant_id=tenant_id)
        del self._rows[workspace_id]


def _redact(text: str, token: str | None = None) -> str:
    cleaned = re.sub(r"(https?://)[^/@\s]+@", r"\1", text)
    if token:
        cleaned = cleaned.replace(token, "[redacted]")
    return cleaned


def _redact_bytes(blob: bytes, token: str | None) -> bytes:
    if not token:
        return blob
    return blob.replace(token.encode(), b"[redacted]")
