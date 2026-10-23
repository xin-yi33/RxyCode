"""Artifact list and download. The tenant comes from the session.

Contract: UI-2026-10-22 §07 API-ART-01/02 — every item carries filename,
relative_path, availability, partial, preview_kind, a signed download_url,
and expires_at; the list is wrapped in a manifest envelope so the UI can
tell a still-growing run's manifest from a complete one.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.artifacts.service import (
    ArtifactForbidden,
    _RETENTION_DAYS,
    issue_download,
    stream_download,
)
from rxycode_server.persistence.models import Artifact, Run, RunEvent

router = APIRouter()

_PAGE_SIZE = 50
_LIVE_STATUSES = {"pending", "leased", "running", "waiting_approval", "cancel_requested"}
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _manifest(
    database_url: str, run_id: str, after: str
) -> tuple[Run, list[Artifact], int, bool] | None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.get(Run, run_id)
            if run is None:
                return None
            query = select(Artifact).where(Artifact.run_id == run.id).order_by(Artifact.id)
            if after:
                query = query.where(Artifact.id > after)
            found = db.scalars(query.limit(_PAGE_SIZE + 1)).all()
            items = list(found)
            has_more = len(items) > _PAGE_SIZE
            items = items[:_PAGE_SIZE]
            max_seq = db.scalar(
                select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id)
            ) or 0
            return run, items, int(max_seq), has_more
    finally:
        engine.dispose()


def _item_json(
    row: Artifact, request: Request, tenant_id: str, ttl: int = 900
) -> dict[str, object]:
    """One manifest entry — the download URL is minted per request so the
    listing stays short-lived and the signature never lands in a stored row."""
    signed = issue_download(row, tenant_id=tenant_id, signing_key=request.app.state.secret, ttl_seconds=ttl)
    expires_at = ""
    if row.created_at:
        try:
            expires_at = (
                datetime.fromisoformat(row.created_at) + timedelta(days=_RETENTION_DAYS)
            ).isoformat()
        except ValueError:
            expires_at = ""
    return {
        "artifact_id": row.id,
        "filename": row.filename or "",
        "relative_path": row.relative_path or "",
        "availability": row.availability or "available",
        "partial": bool(row.partial),
        "preview_kind": row.preview_kind,
        "sha256": row.sha256,
        "size": int(row.size),
        "content_type": row.content_type,
        "expires_at": expires_at,
        "download_url": (
            f"/api/v1/runs/{row.run_id}/artifacts/{row.id}"
            f"?expires={signed['expires']}&signature={signed['signature']}"
        ),
    }


@router.get("/api/v1/runs/{run_id}/artifacts")
def list_artifacts(run_id: str, request: Request, after: str = "") -> dict:
    record = current_record(request)
    loaded = _manifest(request.app.state.database_url, run_id, after)
    if loaded is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    run, items, max_seq, has_more = loaded
    if run.tenant_id != record.tenant_id:
        raise HTTPException(status_code=403, detail="ARTIFACT_FORBIDDEN")
    try:
        entries = [_item_json(row, request, run.tenant_id) for row in items]
    except ArtifactForbidden as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    return {
        "run_id": run.id,
        "manifest_status": "partial" if run.status in _LIVE_STATUSES else "complete",
        "manifest_revision": max_seq,
        "next_cursor": items[-1].id if has_more and items else None,
        "artifacts": entries,
    }


def _parse_range(header: str) -> tuple[int | None, int | None] | None:
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    start_s, end_s = match.group(1), match.group(2)
    if not start_s and not end_s:
        return None
    if not start_s:  # suffix: bytes=-N
        return None, int(end_s)
    return int(start_s), (int(end_s) if end_s else None)


@router.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact(
    run_id: str,
    artifact_id: str,
    request: Request,
    expires: str = "",
    signature: str = "",
) -> Response:
    record = current_record(request)
    state = request.app.state
    try:
        opened = stream_download(
            state.database_url,
            tenant_id=record.tenant_id,
            artifact_id=artifact_id,
            expires=expires,
            signature=signature,
            signing_key=state.secret,
            s3_endpoint=getattr(state, "s3_endpoint", None),
            bucket=getattr(state, "s3_bucket", None),
            access_key=getattr(state, "s3_access_key", None),
            secret_key=getattr(state, "s3_secret_key", None),
            run_id=run_id,
            byte_range=_parse_range(request.headers.get("range", ""))
            if request.headers.get("range")
            else None,
        )
    except ArtifactForbidden as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    row = opened["row"]
    filename = row.filename or "artifact.bin"
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", filename) or "artifact.bin"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Content-Length": str(opened["content_length"]),
        "Accept-Ranges": "bytes",
    }
    if opened["content_range"]:
        headers["Content-Range"] = opened["content_range"]
    return StreamingResponse(
        opened["body"].iter_chunks(1024 * 256),
        status_code=int(opened["status"]),
        media_type=row.content_type or "application/octet-stream",
        headers=headers,
    )
