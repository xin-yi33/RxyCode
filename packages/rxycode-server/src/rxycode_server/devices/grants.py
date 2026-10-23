"""Cloud-side Remote Full requests. This mirror cannot confirm a local grant."""

from __future__ import annotations

from typing import Any


class GrantMirror:
    """What the browser is allowed to see while the runner keeps the real grant."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def request_remote_full(
        self,
        *,
        device_id: str,
        session_id: str,
        run_id: str,
        workspace: str,
        capabilities: list[str],
        expires_at: float,
    ) -> dict[str, Any]:
        row = {
            "device_id": device_id,
            "session_id": session_id,
            "run_id": run_id,
            "workspace": workspace,
            "capabilities": list(capabilities),
            "expires_at": expires_at,
            "status": "waiting_for_local_confirmation",
            "permission": None,
            "grant_id": None,
        }
        self.rows[device_id] = row
        return dict(row)

    def forge_full(self, device_id: str) -> dict[str, Any]:
        row = self.rows.setdefault(
            device_id,
            {
                "device_id": device_id,
                "status": "waiting_for_local_confirmation",
                "permission": None,
            },
        )
        row["permission"] = "full"
        return dict(row)

    def ack(self, device_id: str, *, grant_id: str, revoke_epoch: int) -> dict[str, Any]:
        row = self.rows[device_id]
        row["status"] = "granted"
        row["grant_id"] = grant_id
        row["revoke_epoch"] = revoke_epoch
        row["permission"] = None
        return dict(row)

    def view(self, device_id: str) -> dict[str, Any]:
        row = self.rows.get(device_id)
        if row is None:
            return {"device_id": device_id, "status": "waiting_for_local_confirmation"}
        return dict(row)
