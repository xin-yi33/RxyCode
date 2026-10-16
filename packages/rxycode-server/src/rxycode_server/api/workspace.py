"""Workspace tree, git diff, and hunk review. Paths stay inside the project root."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Project

router = APIRouter()


class ReviewIn(BaseModel):
    path: str
    hunk_id: str
    decision: str
    base_revision: str


def _project(db: Session, tenant_id: str, project_id: str) -> tuple[Project, Path, str]:
    row = db.scalars(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    ).one_or_none()
    config = dict(row.repo_config or {}) if row is not None else {}
    root = Path(str(config.get("workspace_root") or ""))
    if row is None or not root.is_dir():
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return row, root, str(config.get("target_id") or "")


def _inside(root: Path, raw: str) -> Path:
    if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN")
    try:
        candidate = (root / raw).resolve()
        candidate.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
    return candidate


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _hunks(diff_text: str) -> list[dict[str, object]]:
    hunks: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = {"id": f"h{len(hunks) + 1}", "header": line, "lines": []}
            continue
        if current is None:
            continue
        if line.startswith(("+", "-", " ")) and not line.startswith(("+++", "---")):
            lines = current["lines"]
            assert isinstance(lines, list)
            lines.append(line)
    if current is not None:
        hunks.append(current)
    return hunks


def _hunk_text(hunk: dict[str, object], marker: str) -> str:
    lines = hunk["lines"]
    assert isinstance(lines, list)
    kept = [str(line)[1:] for line in lines if str(line).startswith((marker, " "))]
    return "\n".join(kept)


@router.get("/api/v1/workspaces/{project_id}/tree")
def workspace_tree(project_id: str, request: Request, path: str = "") -> dict[str, object]:
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            _row, root, target_id = _project(db, record.tenant_id, project_id)
        directory = _inside(root, path or ".")
        if not directory.is_dir():
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
        entries = []
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if child.name == ".git":
                continue
            entries.append(
                {"name": child.name, "type": "dir" if child.is_dir() else "file"}
            )
        porcelain = _git(root, "status", "--porcelain")
        changes = [line[3:].strip() for line in porcelain.splitlines() if len(line) > 3]
        return {
            "target_id": target_id,
            "path": path,
            "entries": entries,
            "changes": changes,
            "pr_status": "none",
        }
    finally:
        engine.dispose()


@router.get("/api/v1/workspaces/{project_id}/diff")
def workspace_diff(project_id: str, request: Request, path: str) -> dict[str, object]:
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            _row, root, target_id = _project(db, record.tenant_id, project_id)
        target = _inside(root, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
        relative = target.relative_to(root.resolve()).as_posix()
        before = _git(root, "show", f"HEAD:{relative}")
        after = target.read_text(encoding="utf-8")
        diff_text = _git(root, "diff", "--unified=3", "--", relative)
        status = _git(root, "status", "--porcelain", "--", relative)
        return {
            "path": relative,
            "target_id": target_id,
            "base_revision": _revision(target),
            "before": before,
            "after": after,
            "hunks": _hunks(diff_text),
            "changed": bool(status.strip()),
        }
    finally:
        engine.dispose()


@router.post("/api/v1/workspaces/{project_id}/review")
def review_hunk(project_id: str, payload: ReviewIn, request: Request) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    if payload.decision not in {"accept", "reject"}:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            _row, root, _target = _project(db, record.tenant_id, project_id)
        target = _inside(root, payload.path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
        current = _revision(target)
        if current != payload.base_revision:
            raise HTTPException(status_code=409, detail="CONFLICT")
        relative = target.relative_to(root.resolve()).as_posix()
        hunks = _hunks(_git(root, "diff", "--unified=3", "--", relative))
        chosen = next((item for item in hunks if item["id"] == payload.hunk_id), None)
        if chosen is None:
            raise HTTPException(status_code=409, detail="CONFLICT")
        if payload.decision == "reject":
            new_text = _hunk_text(chosen, "+")
            old_text = _hunk_text(chosen, "-")
            file_text = target.read_text(encoding="utf-8")
            if new_text not in file_text:
                raise HTTPException(status_code=409, detail="CONFLICT")
            target.write_text(file_text.replace(new_text, old_text, 1), encoding="utf-8", newline="\n")
        return {"status": payload.decision, "base_revision": _revision(target)}
    finally:
        engine.dispose()
