"""Snapshot bytes stay with the owning tenant. Unauthorized snapshots are not kept."""

from __future__ import annotations

import hashlib
import uuid


class SnapshotRefused(PermissionError):
    def __init__(self, snapshot_id: str, tenant_id: str) -> None:
        self.snapshot_id = snapshot_id
        self.tenant_id = tenant_id
        super().__init__(f"snapshot refused: {tenant_id} cannot read {snapshot_id}")


class SnapshotStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}

    def put(self, *, tenant_id: str, blob: bytes, authorized: bool) -> tuple[str, str]:
        digest = hashlib.sha256(blob).hexdigest()
        if not authorized:
            return "", digest
        snapshot_id = "snap-" + uuid.uuid4().hex[:12]
        self._rows[snapshot_id] = {"tenant_id": tenant_id, "blob": blob}
        return snapshot_id, digest

    def read(self, *, tenant_id: str, snapshot_id: str) -> bytes:
        row = self._rows.get(snapshot_id)
        if row is None or row["tenant_id"] != tenant_id:
            raise SnapshotRefused(snapshot_id, tenant_id)
        blob = row["blob"]
        assert isinstance(blob, bytes)
        return blob
