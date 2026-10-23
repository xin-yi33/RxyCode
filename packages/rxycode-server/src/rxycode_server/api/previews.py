"""Preview job API (UI-2026-10-22 §07 API-PREVIEW-01/02).

POST /artifacts/{id}/preview creates (or dedupes) a job; GET /previews/{id}
reports status; GET /previews/{id}/content serves the converted bytes behind
the session cookie. Converted HTML is always served under a CSP sandbox so an
artifact page cannot touch the app origin even if the iframe sandbox is
stripped.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.previews.service import (
    PreviewError,
    create_preview,
    get_preview,
    open_content,
    to_public,
)

router = APIRouter()

# Content is untrusted artifact output: sandbox it at the document level so the
# iframe origin guard is defense-in-depth, not the only wall.
_SANDBOX_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "style-src 'unsafe-inline'; img-src 'self' data: https:; "
    "font-src 'self' data:"
)


def _db(request: Request) -> Session:
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    request.state._preview_engine = engine
    return Session(engine)


def _close(request: Request) -> None:
    engine = getattr(request.state, "_preview_engine", None)
    if engine is not None:
        engine.dispose()
        request.state._preview_engine = None


class _CreateBody(BaseModel):
    artifact_id: str = Field(min_length=8, max_length=64)


@router.post("/api/v1/previews", status_code=201)
def create(body: _CreateBody, request: Request) -> dict:
    record = current_record(request)
    state = request.app.state
    db = _db(request)
    try:
        job = create_preview(
            db,
            artifact_id=body.artifact_id,
            tenant_id=record.tenant_id,
            s3_endpoint=getattr(state, "s3_endpoint", None),
            bucket=getattr(state, "s3_bucket", None),
            access_key=getattr(state, "s3_access_key", None),
            secret_key=getattr(state, "s3_secret_key", None),
        )
        return to_public(job)
    except PreviewError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    finally:
        db.close()
        _close(request)


@router.get("/api/v1/previews/{preview_id}")
def status(preview_id: str, request: Request) -> dict:
    record = current_record(request)
    db = _db(request)
    try:
        job = get_preview(db, preview_id, record.tenant_id)
        return to_public(job)
    except PreviewError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    finally:
        db.close()
        _close(request)


@router.get("/api/v1/previews/{preview_id}/content")
def content(preview_id: str, request: Request) -> StreamingResponse:
    record = current_record(request)
    state = request.app.state
    db = _db(request)
    try:
        job = get_preview(db, preview_id, record.tenant_id)
        opened = open_content(
            db,
            job=job,
            s3_endpoint=getattr(state, "s3_endpoint", None),
            bucket=getattr(state, "s3_bucket", None),
            access_key=getattr(state, "s3_access_key", None),
            secret_key=getattr(state, "s3_secret_key", None),
        )
    except PreviewError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    finally:
        db.close()
        _close(request)
    headers = {"X-Content-Type-Options": "nosniff"}
    if opened["sandboxed"]:
        headers["Content-Security-Policy"] = _SANDBOX_CSP
    return StreamingResponse(
        opened["stream"].iter_chunks(1024 * 128),
        media_type=str(opened["content_type"]),
        headers=headers,
    )
