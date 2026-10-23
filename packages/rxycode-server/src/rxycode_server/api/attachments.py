"""Attachment staging endpoints (API-FILE-01..06). Owner+tenant scoped."""

from __future__ import annotations

import tempfile

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.attachments import service
from rxycode_server.attachments.store import BlobConfig, open_store

router = APIRouter()


class _AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=400)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, min_length=8, max_length=64)


def _db(request: Request) -> Session:
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    request.state._attachment_engine = engine
    return Session(engine)


def _close(request: Request) -> None:
    engine = getattr(request.state, "_attachment_engine", None)
    if engine is not None:
        engine.dispose()
        request.state._attachment_engine = None


def _store(request: Request):
    config: BlobConfig = request.app.state.attachment_blobs
    return open_store(config)


def _map(exc: service.AttachmentError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)


@router.post("/api/v1/attachments", status_code=201)
def create(body: _AttachmentIn, request: Request) -> dict:
    record = current_record(request)
    db = _db(request)
    try:
        return service.create_attachment(
            db,
            tenant_id=record.tenant_id,
            owner_user_id=record.user_id,
            session_id=body.session_id,
            filename=body.filename,
            content_type=body.content_type,
            declared_size=body.size_bytes,
            request_id=body.request_id,
        )
    except service.AttachmentError as exc:
        db.rollback()
        raise _map(exc) from exc
    finally:
        db.commit()
        db.close()
        _close(request)


@router.put("/api/v1/attachments/{attachment_id}/content")
async def put_content(attachment_id: str, request: Request) -> dict:
    record = current_record(request)
    length = request.headers.get("content-length")
    expected = int(length) if length and length.isdigit() else None
    if expected is not None and expected > service.MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="ATTACHMENT_TOO_LARGE")
    # Spool the async body to disk so memory stays bounded on large uploads.
    with tempfile.TemporaryFile(prefix="rxy-att-") as spool:
        async for chunk in request.stream():
            spool.write(chunk)
        spool.seek(0)
        db = _db(request)
        store = _store(request)
        try:
            result = service.receive_content(
                db,
                store,
                tenant_id=record.tenant_id,
                owner_user_id=record.user_id,
                attachment_id=attachment_id,
                stream=spool,
                expected_bytes=expected,
            )
            db.commit()
            return result
        except service.AttachmentError as exc:
            # The service marks the row failed/cancelled before raising —
            # persist that truth instead of rolling it back to "created".
            try:
                db.commit()
            except Exception:
                db.rollback()
            raise _map(exc) from exc
        finally:
            db.close()
            _close(request)


@router.get("/api/v1/attachments/{attachment_id}")
def status(attachment_id: str, request: Request) -> dict:
    record = current_record(request)
    db = _db(request)
    try:
        return service.get_attachment(
            db,
            tenant_id=record.tenant_id,
            owner_user_id=record.user_id,
            attachment_id=attachment_id,
        )
    except service.AttachmentError as exc:
        raise _map(exc) from exc
    finally:
        db.close()
        _close(request)


@router.post("/api/v1/attachments/{attachment_id}/cancel")
def cancel(attachment_id: str, request: Request) -> dict:
    record = current_record(request)
    db = _db(request)
    store = _store(request)
    try:
        return service.cancel_attachment(
            db,
            store,
            tenant_id=record.tenant_id,
            owner_user_id=record.user_id,
            attachment_id=attachment_id,
        )
    except service.AttachmentError as exc:
        db.rollback()
        raise _map(exc) from exc
    finally:
        db.commit()
        db.close()
        _close(request)


@router.delete("/api/v1/attachments/{attachment_id}", status_code=204)
def delete(attachment_id: str, request: Request) -> None:
    record = current_record(request)
    db = _db(request)
    store = _store(request)
    try:
        service.delete_attachment(
            db,
            store,
            tenant_id=record.tenant_id,
            owner_user_id=record.user_id,
            attachment_id=attachment_id,
        )
    except service.AttachmentError as exc:
        db.rollback()
        raise _map(exc) from exc
    finally:
        db.commit()
        db.close()
        _close(request)
