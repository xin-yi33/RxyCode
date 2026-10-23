"""Local Remote Full grants. The cloud permission string is not authority."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

_STORES: dict[str, "GrantStore"] = {}
_SENDERS: dict[str, Callable[[tuple[int, int]], None]] = {}


class GrantStore:
    """Grants this machine confirmed. Expiry and revoke are checked on each call."""

    def __init__(self, directory: Path, clock: Callable[[], float] | None = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._clock = clock or time.time

    def clock(self) -> float:
        return float(self._clock())

    def confirmed_count(self) -> int:
        return sum(1 for item in self._read_grants() if item.get("confirmed") is True)

    def latest_grant_id(self) -> str:
        confirmed = [item for item in self._read_grants() if item.get("confirmed") is True]
        if not confirmed:
            raise LookupError("no confirmed grant")
        return str(confirmed[-1]["grant_id"])

    def confirm(self, request: dict[str, Any]) -> dict[str, Any]:
        expires_at = float(request["expires_at"])
        if self.clock() >= expires_at:
            raise PermissionError("GRANT_EXPIRED")
        record = {
            "grant_id": "gr_" + uuid4().hex,
            "device_id": str(request.get("device_id") or ""),
            "session_id": str(request.get("session_id") or ""),
            "run_id": str(request.get("run_id") or ""),
            "workspace": str(request.get("workspace") or ""),
            "capabilities": [str(item) for item in request.get("capabilities") or []],
            "expires_at": expires_at,
            "revoke_epoch": self._epoch(),
            "confirmed": True,
        }
        grants = self._read_grants()
        grants.append(record)
        self._write_grants(grants)
        return record

    def revoke(self, grant_id: str) -> int:
        return self.revoke_all(grant_id)

    def revoke_all(self, grant_id: str = "") -> int:
        epoch = self._epoch() + 1
        (self.directory / "epoch.txt").write_text(str(epoch), encoding="utf-8")
        grants = self._read_grants()
        for item in grants:
            if not grant_id or item.get("grant_id") == grant_id:
                item["confirmed"] = False
        self._write_grants(grants)
        return epoch

    def evaluate(self, call: dict[str, Any]) -> tuple[bool, str]:
        reason = self._reason(call)
        self._audit(
            {
                "permission": str(call.get("permission") or ""),
                "allowed": reason == "",
                "reason": reason or "granted",
                "session_id": str(call.get("session_id") or ""),
                "run_id": str(call.get("run_id") or ""),
                "capability": str(call.get("capability") or ""),
                "workspace": str(call.get("workspace") or ""),
            }
        )
        return reason == "", reason

    def audit_entries(self) -> list[dict[str, Any]]:
        path = self.directory / "audit.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _reason(self, call: dict[str, Any]) -> str:
        grants = self._read_grants()
        if not grants:
            return "GRANT_REQUIRED"
        session_id = str(call.get("session_id") or "")
        matched = [item for item in grants if item.get("session_id") == session_id]
        if not matched:
            return "SESSION_MISMATCH"
        grant = matched[-1]
        stored_epoch = grant.get("revoke_epoch")
        if stored_epoch is None or int(stored_epoch) != self._epoch() or grant.get("confirmed") is not True:
            return "GRANT_REVOKED"
        if self.clock() >= float(grant.get("expires_at") or 0):
            return "GRANT_EXPIRED"
        if str(call.get("run_id") or "") != str(grant.get("run_id") or ""):
            return "RUN_MISMATCH"
        capability = str(call.get("capability") or "")
        if capability not in {str(item) for item in grant.get("capabilities") or []}:
            return "CAPABILITY_MISMATCH"
        root = str(grant.get("workspace") or "")
        workspace = str(call.get("workspace") or "")
        workdir = str(call.get("workdir") or workspace)
        if not _within(root, workspace) or not _within(root, workdir):
            return "WORKSPACE_MISMATCH"
        return ""

    def _epoch(self) -> int:
        path = self.directory / "epoch.txt"
        if not path.exists():
            return 0
        return int(path.read_text(encoding="utf-8").strip() or "0")

    def _read_grants(self) -> list[dict[str, Any]]:
        path = self.directory / "grants.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write_grants(self, grants: list[dict[str, Any]]) -> None:
        (self.directory / "grants.json").write_text(
            json.dumps(grants, ensure_ascii=False),
            encoding="utf-8",
        )

    def _audit(self, row: dict[str, Any]) -> None:
        path = self.directory / "audit.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def confirm_from_local_ui(store: GrantStore, request: dict[str, Any]) -> dict[str, Any]:
    """Trusted local confirm. A cloud permission string is not a confirm."""
    return store.confirm(request)


def install_grant_store(device_id: str, store: GrantStore) -> None:
    _STORES[device_id] = store


def installed_stores() -> list[GrantStore]:
    return list(_STORES.values())


def clear_grant_store(device_id: str) -> None:
    _STORES.pop(device_id, None)
    _SENDERS.pop(device_id, None)


def bind_click_sender(device_id: str, sender: Callable[[tuple[int, int]], None]) -> None:
    _SENDERS[device_id] = sender


def click_sender_for(device_id: str) -> Callable[[tuple[int, int]], None] | None:
    return _SENDERS.get(device_id)


def store_for(device_id: str) -> GrantStore:
    existing = _STORES.get(device_id)
    if existing is not None:
        return existing
    from RxyCode.RxyCode1_1_0.config.settings import get_data_dir

    store = GrantStore(get_data_dir() / "device-grants" / device_id)
    _STORES[device_id] = store
    return store


def _within(root: str, candidate: str) -> bool:
    if not root or not candidate:
        return False
    base = Path(root).resolve()
    target = Path(candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True
