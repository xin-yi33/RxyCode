"""Session-workspace file browsing + download (W12).

The confined turn writes into ``{workspaces_root}/{tenant}/{session}`` on the
shared ``worker-data`` volume; the api mounts that volume read-only at
``RXYCODE_WORKSPACES_ROOT`` so users can list and fetch the files their agent
produced — the Notion/ChatGPT-style "files the agent worked on" surface.

Hidden/dot entries (``.turn-result.json`` et al.) are never listed or served.
Downloads refuse symlinks and cap at 32 MiB; paths must resolve inside the
session workspace.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.persistence.models import SessionRow

router = APIRouter()

_MAX_DOWNLOAD = 32 * 1024 * 1024
_MAX_ENTRIES = 2000


def _root(request: Request) -> Path:
    raw = os.environ.get("RXYCODE_WORKSPACES_ROOT", "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="WORKSPACE_NOT_FOUND")
    return Path(raw)


def _session_dir(root: Path, tenant_id: str, session_id: str) -> Path:
    base = (root / tenant_id / session_id).resolve()
    try:
        base.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
    return base


def _authorize(request: Request, session_id: str) -> str:
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(SessionRow, session_id)
            if row is None or row.tenant_id != record.tenant_id:
                raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
            return record.tenant_id
    finally:
        engine.dispose()


def _safe_member(base: Path, rel: str) -> Path:
    if not rel or rel.startswith(("/", "\\")) or (len(rel) >= 2 and rel[1] == ":"):
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN")
    try:
        candidate = (base / rel).resolve()
        candidate.relative_to(base)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="WORKSPACE_FORBIDDEN") from exc
    return candidate


def _visible(path: Path) -> bool:
    return not any(part.startswith(".") for part in path.parts)


@router.get("/api/v1/sessions/{session_id}/files")
def list_files(session_id: str, request: Request) -> dict:
    tenant_id = _authorize(request, session_id)
    base = _session_dir(_root(request), tenant_id, session_id)
    if not base.is_dir():
        return {"files": []}
    files = []
    for path in sorted(base.rglob("*")):
        if len(files) >= _MAX_ENTRIES:
            break
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(base)
        if not _visible(rel):
            continue
        stat = path.stat()
        files.append(
            {
                "path": rel.as_posix(),
                "size": int(stat.st_size),
                "mtime": int(stat.st_mtime),
            }
        )
    return {"files": files}


@router.get("/api/v1/sessions/{session_id}/files/download")
def download_file(session_id: str, request: Request, path: str = "") -> FileResponse:
    tenant_id = _authorize(request, session_id)
    base = _session_dir(_root(request), tenant_id, session_id)
    candidate = _safe_member(base, path)
    rel = candidate.relative_to(base)
    if not _visible(rel) or candidate.is_symlink() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="FILE_NOT_FOUND")
    if candidate.stat().st_size > _MAX_DOWNLOAD:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    media = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=media, filename=candidate.name)
