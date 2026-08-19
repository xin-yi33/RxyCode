"""PhaseG-B7 permission profiles, approval audit, auto-review."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import PathBoundaryError, canonicalize

PROFILES = {
    "read_only": {
        "selectable": True,
        "writable": False,
        "ask": True,
        "mode": "read_only",
    },
    "workspace_write": {
        "selectable": True,
        "writable": True,
        "ask": False,
        "mode": "workspace",
    },
    "ask_for_each_risky_action": {
        "selectable": True,
        "writable": True,
        "ask": True,
        "mode": "ask",
    },
    "allow_scoped_actions": {
        "selectable": True,
        "writable": True,
        "ask": False,
        "mode": "scoped",
    },
    "full_access": {
        "selectable": False,
        "writable": True,
        "ask": False,
        "mode": "full",
    },
}

READ_ACTIONS = frozenset({"read", "list"})
REJECT_THRESHOLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _same_project(stored: Any, requested: Any) -> bool:
    left = "" if stored is None else str(stored).strip()
    right = "" if requested is None else str(requested).strip()
    if not left and not right:
        return True
    if not left or not right:
        return False
    return left == right


def _scope_compatible(stored: Any, requested: Any) -> bool:
    if stored in (None, "") and requested in (None, ""):
        return True
    if stored in (None, "") or requested in (None, ""):
        return False
    try:
        root = canonicalize(str(stored))
        target = canonicalize(str(requested))
        target.relative_to(root)
        return True
    except (PathBoundaryError, ValueError, OSError):
        return str(stored) == str(requested)


class PermissionStore:
    def __init__(self, path: Path | None = None, *, persistent: bool = True) -> None:
        self.persistent = persistent
        self.path = path or Path(os.environ.get("RXYCODE_DATA_DIR", ".")) / "desktop" / "permissions.json"
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_audit: list[dict[str, Any]] = []
        self._data: dict[str, Any] = {
            "profile_id": "ask_for_each_risky_action",
            "policy_version": 1,
            "scopes": [],
            "writable_roots": [],
            "sandbox": True,
            "network": False,
            "audit": [],
        }
        self._reject_streak: dict[str, int] = {}
        self._last_decision: dict[str, Any] | None = None
        self._live: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.persistent:
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(value, dict):
            value = dict(value)
            value.pop("reject_streak", None)
            self._data.update(value)
            if not isinstance(self._data.get("scopes"), list):
                self._data["scopes"] = []
            if not isinstance(self._data.get("writable_roots"), list):
                self._data["writable_roots"] = []
            if not isinstance(self._data.get("audit"), list):
                self._data["audit"] = []
            for item in self._data["audit"]:
                if isinstance(item, dict):
                    item["consumed"] = True
            self._live = {}

    def _save(self) -> None:
        if not self.persistent:
            return
        persisted = dict(self._data)
        persisted["audit"] = []
        for item in self._data.get("audit") or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["consumed"] = True
            persisted["audit"].append(row)
        payload = json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(prefix="perm-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def snapshot(self) -> dict[str, Any]:
        profile_id = str(self._data.get("profile_id") or "ask_for_each_risky_action")
        return {
            "profile_id": profile_id,
            "selectable": bool(PROFILES.get(profile_id, {}).get("selectable")),
            "policy_version": int(self._data.get("policy_version") or 1),
            "scopes": [dict(item) for item in (self._data.get("scopes") or []) if isinstance(item, dict)],
            "writable_roots": list(self._data.get("writable_roots") or []),
            "sandbox": bool(self._data.get("sandbox", True)),
            "network": bool(self._data.get("network", False)),
            "profiles": [
                {
                    "profile_id": key,
                    "selectable": bool(meta["selectable"]),
                    "description": key,
                }
                for key, meta in PROFILES.items()
            ],
        }

    def set_profile(
        self,
        profile_id: str,
        scopes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if profile_id not in PROFILES:
            raise ValueError("unknown profile")
        if not PROFILES[profile_id]["selectable"]:
            raise PermissionError("full_access is not selectable")
        self._data["profile_id"] = profile_id
        self._data["policy_version"] = int(self._data.get("policy_version") or 1) + 1
        if scopes is not None:
            self._data["scopes"] = [dict(item) for item in scopes]
        self._save()
        return self.snapshot()

    def grant_scope(
        self,
        *,
        action: str,
        scope: str | None,
        project_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "action": action,
            "scope": scope,
            "project_id": project_id,
            "expires_at": expires_at,
        }
        self._data.setdefault("scopes", []).append(entry)
        self._data["policy_version"] = int(self._data.get("policy_version") or 1) + 1
        self._save()
        return dict(entry)

    def _scope_granted(self, action: str, scope: str | None, project_id: str | None) -> bool:
        now = _now()
        for item in self._data.get("scopes") or []:
            if not isinstance(item, dict):
                continue
            granted_action = item.get("action")
            if granted_action not in (None, "", action, "*"):
                continue
            if not _same_project(item.get("project_id"), project_id):
                continue
            expires_at = item.get("expires_at")
            if expires_at and str(expires_at) < now:
                continue
            if _scope_compatible(item.get("scope"), scope):
                return True
        return False

    def _auto_review_expands(
        self,
        *,
        actor: str,
        expand_sandbox: bool = False,
        expand_writable_roots: bool = False,
        expand_network: bool = False,
        writable_roots: list[str] | None = None,
        network: bool | None = None,
    ) -> bool:
        if actor != "auto_review":
            return False
        if expand_sandbox or expand_writable_roots or expand_network:
            return True
        if network is True and not bool(self._data.get("network")):
            return True
        requested = [str(item) for item in (writable_roots or []) if item]
        if not requested:
            return False
        current = [str(item) for item in (self._data.get("writable_roots") or [])]
        if not current:
            return True
        for root in requested:
            if not any(_scope_compatible(allowed, root) for allowed in current):
                return True
        return False

    def decide(
        self,
        *,
        session_id: str,
        action: str,
        actor: str = "user",
        scope: str | None = None,
        decision: str,
        expires_at: str | None = None,
        turn_id: str | None = None,
        project_id: str | None = None,
        reviewer_id: str | None = None,
        reason: str | None = None,
        original_approval_id: str | None = None,
        expand_sandbox: bool = False,
        expand_writable_roots: bool = False,
        expand_network: bool = False,
        consumed: bool = False,
    ) -> dict[str, Any]:
        if decision not in {"allow", "reject"}:
            raise ValueError("decision must be allow or reject")
        profile_id = str(self._data.get("profile_id") or "ask_for_each_risky_action")
        profile = PROFILES[profile_id]
        if decision == "allow" and not profile["writable"] and action not in READ_ACTIONS:
            decision = "reject"
        if actor == "auto_review" and decision == "allow":
            if action not in READ_ACTIONS or self._auto_review_expands(
                actor=actor,
                expand_sandbox=expand_sandbox,
                expand_writable_roots=expand_writable_roots,
                expand_network=expand_network,
            ):
                decision = "reject"
        record = {
            "approval_id": uuid.uuid4().hex[:12],
            "session_id": session_id,
            "action": action,
            "actor": actor,
            "scope": scope,
            "project_id": project_id,
            "turn_id": turn_id or session_id,
            "trace_id": uuid.uuid4().hex,
            "decision": decision,
            "profile_id": profile_id,
            "policy_version": int(self._data.get("policy_version") or 1),
            "created_at": _now(),
            "expires_at": expires_at,
            "revoked": False,
            "consumed": consumed,
            "reviewer_id": reviewer_id or (actor if actor == "auto_review" else None),
            "reason": reason,
            "original_approval_id": original_approval_id,
            "expand_sandbox": expand_sandbox,
            "expand_writable_roots": expand_writable_roots,
            "expand_network": expand_network,
        }
        self._memory_audit.append(record)
        self._data.setdefault("audit", []).append(dict(record))
        if not consumed and decision == "allow":
            self._live[str(record["approval_id"])] = record
        if decision == "reject":
            self._reject_streak[session_id] = int(self._reject_streak.get(session_id) or 0) + 1
        else:
            self._reject_streak[session_id] = 0
        record["interrupt_turn"] = int(self._reject_streak.get(session_id) or 0) >= REJECT_THRESHOLD
        self._data["audit"][-1]["interrupt_turn"] = record["interrupt_turn"]
        self._last_decision = dict(record)
        self._save()
        return dict(record)

    def last_decision(self) -> dict[str, Any] | None:
        return None if self._last_decision is None else dict(self._last_decision)

    def revoke(self, approval_id: str) -> dict[str, Any]:
        self._live.pop(approval_id, None)
        for item in self._data.get("audit") or []:
            if item.get("approval_id") == approval_id:
                item["revoked"] = True
                item["consumed"] = True
                item["revoked_at"] = _now()
                self._save()
                return dict(item)
        raise KeyError(approval_id)

    def _trace_verdict(
        self,
        *,
        verdict: str,
        action: str,
        actor: str,
        session_id: str | None,
        turn_id: str | None,
        scope: str | None,
        project_id: str | None,
        reason: str | None,
        approval_id: str | None = None,
    ) -> str:
        self.decide(
            session_id=session_id or "unbound",
            action=action,
            actor=actor,
            scope=scope,
            decision=verdict,
            turn_id=turn_id,
            project_id=project_id,
            reason=reason,
            original_approval_id=approval_id,
            consumed=True,
        )
        return verdict

    def evaluate(
        self,
        *,
        action: str,
        actor: str = "system",
        approval_id: str | None = None,
        scope: str | None = None,
        project_id: str | None = None,
        workspace: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        expand_sandbox: bool = False,
        expand_writable_roots: bool = False,
        expand_network: bool = False,
        writable_roots: list[str] | None = None,
        network: bool | None = None,
    ) -> str:
        """No UI still enforces: risky actions reject unless profile/scope allows."""
        expands = self._auto_review_expands(
            actor=actor,
            expand_sandbox=expand_sandbox,
            expand_writable_roots=expand_writable_roots,
            expand_network=expand_network,
            writable_roots=writable_roots,
            network=network,
        )
        if workspace and not scope:
            return self._trace_verdict(
                verdict="reject",
                action=action,
                actor=actor,
                session_id=session_id,
                turn_id=turn_id,
                scope=scope,
                project_id=project_id,
                reason="scope_required",
                approval_id=approval_id,
            )
        if workspace and scope and not _scope_compatible(workspace, scope):
            return self._trace_verdict(
                verdict="reject",
                action=action,
                actor=actor,
                session_id=session_id,
                turn_id=turn_id,
                scope=scope,
                project_id=project_id,
                reason="workspace_mismatch",
                approval_id=approval_id,
            )
        if approval_id:
            match = self._live.get(str(approval_id))
            if match is None:
                match = next(
                    (
                        item
                        for item in self._data.get("audit") or []
                        if item.get("approval_id") == approval_id
                    ),
                    None,
                )
            reason = None
            if match is None or match.get("revoked") or match.get("consumed"):
                reason = "approval_unavailable"
            elif match.get("decision") != "allow":
                reason = "approval_not_allow"
            elif match.get("action") != action:
                reason = "action_mismatch"
            elif int(match.get("policy_version") or 0) != int(self._data.get("policy_version") or 1):
                reason = "policy_version_mismatch"
            elif match.get("expires_at") and match["expires_at"] < _now():
                reason = "expired"
            elif session_id is None or str(match.get("session_id") or "") != str(session_id):
                reason = "session_mismatch"
            elif turn_id is not None and str(match.get("turn_id") or "") != str(turn_id):
                reason = "turn_mismatch"
            elif not _scope_compatible(match.get("scope"), scope):
                reason = "scope_mismatch"
            elif not _same_project(match.get("project_id"), project_id):
                reason = "project_mismatch"
            elif str(match.get("actor") or "") != str(actor):
                reason = "actor_mismatch"
            elif workspace and match.get("scope") and not _scope_compatible(workspace, match.get("scope")):
                reason = "workspace_mismatch"
            elif workspace and scope and not _scope_compatible(workspace, scope):
                reason = "workspace_mismatch"
            elif actor == "auto_review" and (action not in READ_ACTIONS or expands):
                reason = "auto_review_readonly"
            if reason:
                return self._trace_verdict(
                    verdict="reject",
                    action=action,
                    actor=actor,
                    session_id=session_id,
                    turn_id=turn_id,
                    scope=scope,
                    project_id=project_id,
                    reason=reason,
                    approval_id=approval_id,
                )
            match["consumed"] = True
            self._live.pop(str(approval_id), None)
            for item in self._data.get("audit") or []:
                if item.get("approval_id") == approval_id:
                    item["consumed"] = True
            if session_id:
                self._reject_streak[str(session_id)] = 0
            self._save()
            self._last_decision = dict(match)
            return "allow"
        if actor == "auto_review" and (action not in READ_ACTIONS or expands):
            return self._trace_verdict(
                verdict="reject",
                action=action,
                actor=actor,
                session_id=session_id,
                turn_id=turn_id,
                scope=scope,
                project_id=project_id,
                reason="auto_review_readonly",
            )
        if action in READ_ACTIONS:
            return self._trace_verdict(
                verdict="allow",
                action=action,
                actor=actor,
                session_id=session_id,
                turn_id=turn_id,
                scope=scope,
                project_id=project_id,
                reason="read_action",
            )
        profile = PROFILES.get(str(self._data.get("profile_id")), PROFILES["ask_for_each_risky_action"])
        mode = str(profile.get("mode") or "ask")
        verdict = "reject"
        reason = "ask_required"
        if mode == "ask" or profile.get("ask"):
            verdict, reason = "reject", "ask_required"
        elif mode == "read_only" or not profile["writable"]:
            verdict, reason = "reject", "read_only"
        elif mode == "workspace":
            root = workspace or scope
            if root and _scope_compatible(root, scope or root):
                verdict, reason = "allow", "workspace_write"
            else:
                verdict, reason = "reject", "outside_workspace"
        elif mode == "scoped":
            if self._scope_granted(action, scope, project_id):
                verdict, reason = "allow", "scoped_grant"
            else:
                verdict, reason = "reject", "scope_not_granted"
        elif mode == "full":
            verdict, reason = "allow", "full_access"
        return self._trace_verdict(
            verdict=verdict,
            action=action,
            actor=actor,
            session_id=session_id,
            turn_id=turn_id,
            scope=scope,
            project_id=project_id,
            reason=reason,
        )

    def audit(self, session_id: str | None = None) -> list[dict[str, Any]]:
        values = list(self._data.get("audit") or [])
        if session_id:
            values = [item for item in values if item.get("session_id") == session_id]
        return values

    def auto_review_capability(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "read_only": True,
            "expands_sandbox": False,
            "expands_writable_roots": False,
            "expands_network": False,
        }
