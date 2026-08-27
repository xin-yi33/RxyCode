"""PhaseG-B9 git worktree lifecycle. Never auto-commits user code."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workspace import canonicalize, git_status
from .review import is_git_repo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class WorktreeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorktreeService:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._handoffs: dict[str, dict[str, Any]] = {}
        self._session_roots: dict[str, str] = {}

    def bind_session(self, session_id: str, workspace: Path) -> None:
        self._session_roots[session_id] = str(canonicalize(workspace))

    def session_root(self, session_id: str) -> str | None:
        return self._session_roots.get(session_id)

    def list(self, workspace: Path, *, session_id: str | None = None) -> list[dict[str, Any]]:
        root = canonicalize(workspace)
        if not is_git_repo(root):
            return []
        result = _git(root, "worktree", "list", "--porcelain")
        rows: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    rows.append(current)
                current = {"path": line.split(" ", 1)[1], "branch": None, "bare": False}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
            elif line == "bare":
                current["bare"] = True
        if current:
            rows.append(current)
        if session_id:
            owned = {
                canonicalize(item["path"])
                for item in self._records.values()
                if item.get("session_id") == session_id
            }
            bound = self._session_roots.get(session_id)
            rows = [
                row
                for row in rows
                if canonicalize(row["path"]) in owned
                or (bound is not None and canonicalize(row["path"]) == canonicalize(bound))
            ]
        return rows

    def _authorize(
        self,
        *,
        permission_store: Any,
        action: str,
        workspace: Path,
        session_id: str | None,
        confirm: bool = True,
    ) -> None:
        if not confirm:
            raise WorktreeError("CONFIRM_REQUIRED", f"{action} requires confirm")
        if permission_store is None:
            raise WorktreeError("PERMISSION_DENIED", "permission store required")
        verdict = permission_store.evaluate(
            action=action,
            actor="user",
            scope=str(canonicalize(workspace)),
            workspace=str(canonicalize(workspace)),
            session_id=session_id,
        )
        if verdict != "allow":
            raise WorktreeError("PERMISSION_DENIED", "destructive worktree action denied")

    def create(
        self,
        workspace: Path,
        *,
        dest: str,
        branch: str | None = None,
        session_id: str,
        permission_store: Any = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        root = canonicalize(workspace)
        self._authorize(
            permission_store=permission_store,
            action="worktree_create",
            workspace=root,
            session_id=session_id,
            confirm=confirm,
        )
        if not is_git_repo(root):
            raise WorktreeError("NOT_A_GIT_REPO", "not a git repository")
        target = canonicalize(dest)
        if target != root and root not in target.parents:
            raise WorktreeError("PATH_OUTSIDE_WORKSPACE", f"dest outside workspace: {target}")
        existed = target.exists()
        if existed:
            raise WorktreeError("WORKTREE_EXISTS", f"path exists: {target}")
        name = branch or f"wt-{uuid.uuid4().hex[:8]}"
        branch_existed = bool(_git(root, "branch", "--list", name).stdout.strip())
        result = _git(root, "worktree", "add", "-b", name, str(target))
        if result.returncode != 0:
            _git(root, "worktree", "remove", "--force", str(target))
            if not existed and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if not branch_existed:
                listed = _git(root, "branch", "--list", name)
                if listed.stdout.strip():
                    _git(root, "branch", "-D", name)
            raise WorktreeError("WORKTREE_CREATE_FAILED", result.stderr.strip() or "create failed")
        record = {
            "worktree_id": uuid.uuid4().hex[:12],
            "path": str(target),
            "branch": name,
            "source": str(root),
            "session_id": session_id,
            "created_at": _now(),
        }
        self._records[record["worktree_id"]] = record
        return dict(record)

    def close(
        self,
        workspace: Path,
        worktree_id: str,
        *,
        force: bool = False,
        confirm: bool = False,
        session_id: str | None = None,
        permission_store: Any = None,
    ) -> dict[str, Any]:
        self._authorize(
            permission_store=permission_store,
            action="worktree_close",
            workspace=workspace,
            session_id=session_id,
            confirm=confirm or force,
        )
        record = self._records.get(worktree_id)
        if record is None:
            raise WorktreeError("WORKTREE_NOT_FOUND", worktree_id)
        if session_id and record.get("session_id") != session_id:
            raise WorktreeError("SESSION_MISMATCH", "worktree belongs to another session")
        if canonicalize(record["source"]) != canonicalize(workspace):
            raise WorktreeError("SESSION_MISMATCH", "worktree belongs to another workspace")
        path = Path(record["path"])
        if path.exists() and git_status(path).get("is_git"):
            dirty = _git(path, "status", "--porcelain", "-uall")
            if dirty.stdout.strip() and not (force and confirm):
                raise WorktreeError("UNCOMMITTED_CHANGES", "refusing to remove worktree with uncommitted changes")
        result = _git(canonicalize(workspace), "worktree", "remove", *(["--force"] if force and confirm else []), str(path))
        if result.returncode != 0:
            raise WorktreeError("WORKTREE_REMOVE_FAILED", result.stderr.strip() or "remove failed")
        record["closed_at"] = _now()
        self._records.pop(worktree_id, None)
        return dict(record)

    def open(self, worktree_id: str, *, session_id: str) -> dict[str, Any]:
        record = self._records.get(worktree_id)
        if record is None:
            raise WorktreeError("WORKTREE_NOT_FOUND", worktree_id)
        if record.get("session_id") != session_id:
            raise WorktreeError("SESSION_MISMATCH", "worktree belongs to another session")
        self._session_roots[session_id] = str(record["path"])
        return dict(record)

    def prune(self, workspace: Path, *, confirm: bool = False, permission_store: Any = None, session_id: str | None = None) -> dict[str, Any]:
        self._authorize(
            permission_store=permission_store,
            action="worktree_prune",
            workspace=workspace,
            session_id=session_id,
            confirm=confirm,
        )
        root = canonicalize(workspace)
        result = _git(root, "worktree", "prune")
        if result.returncode != 0:
            raise WorktreeError("WORKTREE_PRUNE_FAILED", result.stderr.strip() or "prune failed")
        return {"ok": True, "pruned": True}

    def handoff(
        self,
        *,
        source_session: str,
        target_session: str,
        target_path: str,
        workspace: Path,
        permission_store: Any = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        root = canonicalize(workspace)
        if not target_session:
            raise WorktreeError("SESSION_MISMATCH", "target_session required")
        self._authorize(
            permission_store=permission_store,
            action="worktree_handoff",
            workspace=root,
            session_id=source_session,
            confirm=confirm,
        )
        dest = canonicalize(target_path)
        if not dest.exists():
            raise WorktreeError("PATH_NOT_FOUND", str(dest))
        owner = next(
            (
                item
                for item in self._records.values()
                if canonicalize(item["path"]) == dest and item.get("session_id") == source_session
            ),
            None,
        )
        if owner is None:
            raise WorktreeError("WORKTREE_NOT_FOUND", f"handoff target not a registered worktree: {dest}")
        previous_source = self._session_roots.get(source_session, str(root))
        previous_target = self._session_roots.get(target_session)
        hid = uuid.uuid4().hex[:12]
        record = {
            "handoff_id": hid,
            "source_session": source_session,
            "target_session": target_session,
            "source": previous_source,
            "target_previous": previous_target,
            "target": str(dest),
            "worktree_id": owner["worktree_id"],
            "created_at": _now(),
            "rolled_back": False,
        }
        self._handoffs[hid] = record
        owner["session_id"] = target_session
        self._session_roots[source_session] = previous_source if previous_source != str(dest) else str(root)
        if previous_source == str(dest):
            self._session_roots[source_session] = str(root)
        self._session_roots[target_session] = str(dest)
        return dict(record)

    def rollback_handoff(
        self,
        handoff_id: str,
        *,
        session_id: str,
        permission_store: Any = None,
        confirm: bool = True,
        workspace: Path | None = None,
    ) -> dict[str, Any]:
        record = self._handoffs.get(handoff_id)
        if record is None:
            raise WorktreeError("HANDOFF_NOT_FOUND", handoff_id)
        allowed = {record.get("source_session"), record.get("target_session")}
        if session_id not in allowed:
            raise WorktreeError("SESSION_MISMATCH", "handoff belongs to another session")
        if record.get("rolled_back"):
            return dict(record)
        root = workspace or Path(str(record.get("source") or "."))
        self._authorize(
            permission_store=permission_store,
            action="worktree_handoff_rollback",
            workspace=root,
            session_id=session_id,
            confirm=confirm,
        )
        source = str(record["source_session"])
        target = str(record.get("target_session") or "")
        self._session_roots[source] = str(record["source"])
        if target:
            previous = record.get("target_previous")
            if previous:
                self._session_roots[target] = str(previous)
            else:
                self._session_roots.pop(target, None)
        dest = canonicalize(record["target"])
        for item in self._records.values():
            if canonicalize(item["path"]) == dest:
                item["session_id"] = source
                break
        record["rolled_back"] = True
        record["rolled_back_at"] = _now()
        return dict(record)
