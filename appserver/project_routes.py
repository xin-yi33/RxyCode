"""PhaseG-B4 project/workspace RPC. Flat * _routes.py per M2. Never chdir."""

from __future__ import annotations

from typing import Any

from .project_store import ProjectStore
from .workspace import PathBoundaryError, assert_inside_workspace, canonicalize, git_status


def _require_registered(store: ProjectStore, raw: str) -> str:
    root = str(canonicalize(raw))
    if store.get(root) is None:
        raise PathBoundaryError("PATH_OUTSIDE_WORKSPACE", f"unregistered workspace: {root}")
    return root


def handle_project_rpc(
    store: ProjectStore, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    if method == "project/list":
        return {"projects": store.list(), "active_id": store._data.get("active_id")}
    if method == "project/add":
        path = str(params.get("path") or "")
        display = params.get("display_name")
        project = store.add(path, display_name=str(display) if display else None)
        return {"project": project}
    if method == "project/remove":
        project_id = str(params.get("project_id") or "")
        store.remove(project_id)
        return {"ok": True, "deleted_files": False}
    if method == "project/set_active":
        project = store.set_active(str(params.get("project_id") or ""))
        return {"project": project}
    if method == "workspace/status":
        root = _require_registered(store, str(params.get("workspace_root") or ""))
        status = git_status(root)
        status["workspace_root"] = str(root)
        return status
    if method == "workspace/resolve":
        root = _require_registered(store, str(params.get("workspace_root") or ""))
        resolved = assert_inside_workspace(root, str(params.get("path") or ""))
        return {"path": str(resolved)}
    raise PathBoundaryError("UNSUPPORTED", f"unknown method {method}")
