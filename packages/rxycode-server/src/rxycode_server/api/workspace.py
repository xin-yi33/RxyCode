"""Workspace tree, git diff, and hunk review. Paths stay inside the project root."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Project

router = APIRouter()
_REVIEW_GUARD = threading.Lock()
_REVIEW_LOCKS: dict[str, threading.Lock] = {}


def _review_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _REVIEW_GUARD:
        lock = _REVIEW_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _REVIEW_LOCKS[key] = lock
        return lock


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
        if line[:1] in {"+", "-", " ", "\\"}:
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


def _sides(hunk: dict[str, object]) -> tuple[list[str], list[str], int, int, bool, bool]:
    header = str(hunk["header"])
    match = _HUNK.match(header)
    raw_lines = hunk["lines"]
    if match is None or not isinstance(raw_lines, list):
        raise HTTPException(status_code=409, detail="CONFLICT")
    new_start = int(match.group(3))
    new_count = int(match.group(4) if match.group(4) is not None else "1")
    old_lines: list[str] = []
    new_lines: list[str] = []
    old_missing = False
    new_missing = False
    last_side = ""
    for raw in raw_lines:
        text = str(raw)
        if text.startswith("\\"):
            if last_side in {"old", "both"}:
                old_missing = True
            if last_side in {"new", "both"}:
                new_missing = True
            continue
        if text.startswith("+"):
            new_lines.append(text[1:])
            last_side = "new"
        elif text.startswith("-"):
            old_lines.append(text[1:])
            last_side = "old"
        elif text.startswith(" "):
            old_lines.append(text[1:])
            new_lines.append(text[1:])
            last_side = "both"
    return old_lines, new_lines, new_start, new_count, old_missing, new_missing


def _reject_at(text: str, hunk: dict[str, object]) -> str:
    old_lines, new_lines, new_start, new_count, old_missing, _new_missing = _sides(hunk)
    newline = "\r\n" if "\r\n" in text else "\n"
    ends = text.endswith("\n")
    lines = text.splitlines()
    if new_count == 0:
        start = 0 if new_start == 0 else new_start - 1
        end = start
    else:
        start = max(new_start - 1, 0)
        end = start + new_count
    if start < 0 or end > len(lines) or lines[start:end] != new_lines:
        raise HTTPException(status_code=409, detail="CONFLICT")
    merged = [*lines[:start], *old_lines, *lines[end:]]
    at_end = end == len(lines)
    body = newline.join(merged)
    if at_end:
        if merged and not old_missing:
            body += newline
    elif ends and merged:
        body += newline
    return body


def _snapshot_diff(top: Path, spec: str, data: bytes) -> str:
    import tempfile

    before = _git(top, "show", f"HEAD:{spec}")
    with tempfile.TemporaryDirectory(prefix="w3c04-diff-") as folder:
        base = Path(folder) / "before"
        current = Path(folder) / "after"
        base.write_bytes(before.encode("utf-8"))
        current.write_bytes(data)
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--unified=3", "--", base.name, current.name],
            cwd=folder,
            text=True,
            capture_output=True,
            check=False,
        )
    if proc.returncode not in {0, 1}:
        return ""
    return proc.stdout


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
        diff_text = _snapshot_diff(top, spec, data)
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
        with _review_lock(target):
            data = target.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != payload.base_revision:
                raise HTTPException(status_code=409, detail="CONFLICT")
            hunks = _hunks(_snapshot_diff(top, spec, data))
            chosen = next((item for item in hunks if item["id"] == payload.hunk_id), None)
            if chosen is None:
                raise HTTPException(status_code=409, detail="CONFLICT")
            updated = data
            if payload.decision == "reject":
                updated = _reject_at(data.decode("utf-8"), chosen).encode("utf-8")
            again = target.read_bytes()
            if hashlib.sha256(again).hexdigest() != digest:
                raise HTTPException(status_code=409, detail="CONFLICT")
            if updated != again:
                target.write_bytes(updated)
        return {"status": payload.decision, "base_revision": hashlib.sha256(updated).hexdigest()}
    finally:
        engine.dispose()
