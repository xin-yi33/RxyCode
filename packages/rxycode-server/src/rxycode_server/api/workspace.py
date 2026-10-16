"""Workspace tree, git diff, and hunk review. Paths stay inside the project root."""

from __future__ import annotations

import hashlib
import os
import re
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
    raw = str(config.get("workspace_root") or "").strip()
    base_raw = os.environ.get("RXYCODE_WORKSPACE_BASE", "").strip()
    if row is None or not raw or not base_raw:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    root = Path(raw).resolve()
    base = Path(base_raw).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
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


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _spec(root: Path, relative: str) -> tuple[Path, str]:
    top_text = _git(root, "rev-parse", "--show-toplevel").strip()
    if not top_text:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    top = Path(top_text).resolve()
    workspace = root.resolve()
    try:
        prefix = workspace.relative_to(top).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
    spec = relative if prefix in {"", "."} else f"{prefix}/{relative}"
    try:
        (top / spec).resolve().relative_to(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
    return top, spec


def _sides(hunk: dict[str, object]) -> tuple[list[str], list[str], int, int]:
    header = str(hunk["header"])
    match = _HUNK.match(header)
    raw_lines = hunk["lines"]
    if match is None or not isinstance(raw_lines, list):
        raise HTTPException(status_code=409, detail="CONFLICT")
    new_start = int(match.group(3))
    new_count = int(match.group(4) if match.group(4) is not None else "1")
    old_lines: list[str] = []
    new_lines: list[str] = []
    for raw in raw_lines:
        text = str(raw)
        if text.startswith("+"):
            new_lines.append(text[1:])
        elif text.startswith("-"):
            old_lines.append(text[1:])
        elif text.startswith(" "):
            old_lines.append(text[1:])
            new_lines.append(text[1:])
    return old_lines, new_lines, new_start, new_count


def _reject_at(text: str, hunk: dict[str, object]) -> str:
    old_lines, new_lines, new_start, new_count = _sides(hunk)
    lines = text.splitlines()
    start = new_start - 1
    end = start + new_count
    if start < 0 or end > len(lines) or lines[start:end] != new_lines:
        raise HTTPException(status_code=409, detail="CONFLICT")
    return "\n".join([*lines[:start], *old_lines, *lines[end:]]) + ("\n" if text.endswith("\n") else "")


def _lock(handle) -> None:
    if os.name != "nt":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    import msvcrt

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)


def _unlock(handle) -> None:
    if os.name != "nt":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


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
        top, spec = _spec(root, relative)
        data = target.read_bytes()
        before = _git(top, "show", f"HEAD:{spec}")
        diff_text = _git(top, "diff", "HEAD", "--unified=3", "--", spec)
        return {
            "path": relative,
            "target_id": target_id,
            "base_revision": hashlib.sha256(data).hexdigest(),
            "before": before,
            "after": data.decode("utf-8"),
            "hunks": _hunks(diff_text),
            "changed": bool(diff_text.strip()),
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
        relative = target.relative_to(root.resolve()).as_posix()
        top, spec = _spec(root, relative)
        with target.open("r+b") as handle:
            _lock(handle)
            try:
                data = handle.read()
                if hashlib.sha256(data).hexdigest() != payload.base_revision:
                    raise HTTPException(status_code=409, detail="CONFLICT")
                hunks = _hunks(_git(top, "diff", "HEAD", "--unified=3", "--", spec))
                chosen = next((item for item in hunks if item["id"] == payload.hunk_id), None)
                if chosen is None:
                    raise HTTPException(status_code=409, detail="CONFLICT")
                text = data.decode("utf-8")
                if payload.decision == "reject":
                    updated = _reject_at(text, chosen).encode("utf-8")
                    handle.seek(0)
                    handle.write(updated)
                    handle.truncate()
                    revised = hashlib.sha256(updated).hexdigest()
                else:
                    revised = hashlib.sha256(data).hexdigest()
            finally:
                _unlock(handle)
        return {"status": payload.decision, "base_revision": revised}
    finally:
        engine.dispose()
