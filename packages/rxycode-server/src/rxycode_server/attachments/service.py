"""Attachment lifecycle: create → stream bytes → ready → bind to a run.

Contract: UI-2026-10-22 §07 API-FILE-01..06. Rows are the durable state;
bytes live in the attachment blob store keyed under ``tenants/{id}/``.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rxycode_server.persistence.models import Attachment

from .store import BlobStore

MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_ATTACHMENTS_PER_RUN = 10
ATTACHMENT_TTL = timedelta(hours=24)
_UPLOAD_TTL_SECONDS = 900

_FINAL_STATES = {"failed", "cancelled", "deleted", "expired"}
_BINDABLE_STATE = "ready"


class AttachmentError(Exception):
    def __init__(self, http_status: int, code: str, reason: str = "") -> None:
        super().__init__(reason or code)
        self.http_status = http_status
        self.code = code
        self.reason = reason or code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


def _parse(moment: str | None) -> datetime | None:
    if not moment:
        return None
    try:
        return datetime.fromisoformat(moment)
    except ValueError:
        return None


def _safe_name(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if base in {"", ".", ".."}:
        return "attachment.bin"
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in base)
    return (cleaned.strip() or "attachment.bin")[:200]


def to_public(row: Attachment) -> dict[str, object]:
    return {
        "attachment_id": row.id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": int(row.size_bytes or 0),
        "sha256": row.sha256,
        "state": row.state,
        "stage": row.stage,
        "received_bytes": int(row.received_bytes or 0),
        "progress": (
            round(int(row.received_bytes or 0) / int(row.size_bytes), 4)
            if row.size_bytes
            else 0.0
        ),
        "error_code": row.error_code,
        "reason": row.reason,
        "revision": int(row.revision or 0),
        "expires_at": row.expires_at,
    }


def _get_owned(db: Session, attachment_id: str, tenant_id: str, owner_user_id: str) -> Attachment:
    row = db.get(Attachment, attachment_id)
    if row is None or row.tenant_id != tenant_id:
        raise AttachmentError(404, "ATTACHMENT_NOT_FOUND")
    if row.owner_user_id != owner_user_id:
        raise AttachmentError(404, "ATTACHMENT_NOT_FOUND")
    if row.state == "deleted":
        raise AttachmentError(404, "ATTACHMENT_NOT_FOUND")
    return row


def create_attachment(
    db: Session,
    *,
    tenant_id: str,
    owner_user_id: str,
    session_id: str | None,
    filename: str,
    content_type: str,
    declared_size: int | None,
    request_id: str | None,
) -> dict[str, object]:
    """Mint one staged attachment. Idempotent on (owner, request_id)."""
    filename = _safe_name(filename)
    if content_type and len(content_type) > 128:
        raise AttachmentError(400, "ATTACHMENT_INVALID", "content_type too long")
    if declared_size is not None and (declared_size < 0 or declared_size > MAX_ATTACHMENT_BYTES):
        raise AttachmentError(413, "ATTACHMENT_TOO_LARGE")
    if request_id:
        found = db.scalars(
            select(Attachment).where(
                Attachment.owner_user_id == owner_user_id,
                Attachment.request_id == request_id,
            )
        ).one_or_none()
        if found is not None:
            if found.filename != filename or found.state in _FINAL_STATES - {"deleted"}:
                raise AttachmentError(409, "REQUEST_CONFLICT")
            return {
                **to_public(found),
                "upload_url": f"/api/v1/attachments/{found.id}/content",
            }

    attachment_id = uuid.uuid4().hex
    now = _now()
    row = Attachment(
        id=attachment_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        session_id=session_id,
        run_id=None,
        request_id=request_id or None,
        filename=filename,
        content_type=(content_type or "application/octet-stream")[:128],
        declared_size=declared_size,
        size_bytes=declared_size or 0,
        received_bytes=0,
        sha256=None,
        state="created",
        stage="upload",
        object_key=f"tenants/{tenant_id}/attachments/{attachment_id}/{filename}",
        revision=0,
        expires_at=_stamp(now + ATTACHMENT_TTL),
        created_at=_stamp(now),
        updated_at=_stamp(now),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if request_id:
            found = db.scalars(
                select(Attachment).where(
                    Attachment.owner_user_id == owner_user_id,
                    Attachment.request_id == request_id,
                )
            ).one_or_none()
            if found is not None:
                return {
                    **to_public(found),
                    "upload_url": f"/api/v1/attachments/{found.id}/content",
                }
        raise AttachmentError(409, "REQUEST_CONFLICT") from exc
    return {
        **to_public(row),
        "upload_url": f"/api/v1/attachments/{attachment_id}/content",
    }


class _HashingLimiter:
    """Count + hash bytes as the store pulls them; abort past the bound."""

    def __init__(self, inner: BinaryIO, limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self.count = 0
        self._hash = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._inner.read(size)
        if not data:
            return b""
        self.count += len(data)
        if self.count > self._limit:
            raise AttachmentError(413, "ATTACHMENT_TOO_LARGE")
        self._hash.update(data)
        return data

    @property
    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def receive_content(
    db: Session,
    store: BlobStore,
    *,
    tenant_id: str,
    owner_user_id: str,
    attachment_id: str,
    stream: BinaryIO,
    expected_bytes: int | None,
) -> dict[str, object]:
    """Stream the upload into the store, then mark the row ready.

    Byte count and sha are recomputed from the wire — the client's declared
    size is a hint, not the truth.
    """
    row = _get_owned(db, attachment_id, tenant_id, owner_user_id)
    if row.state == "ready":
        return to_public(row)
    if row.state in {"failed", "cancelled", "deleted", "expired"}:
        raise AttachmentError(409, "ATTACHMENT_STATE", f"state={row.state}")
    if expected_bytes is not None and expected_bytes > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(413, "ATTACHMENT_TOO_LARGE")

    row.state = "uploading"
    row.stage = "upload"
    row.revision = int(row.revision or 0) + 1
    row.updated_at = _stamp(_now())
    db.flush()

    limiter = _HashingLimiter(stream, MAX_ATTACHMENT_BYTES)
    try:
        store.put_stream(row.object_key, limiter, content_type=row.content_type)
    except AttachmentError:
        store.delete(row.object_key)
        _fail(db, row, "ATTACHMENT_TOO_LARGE", "declared stream exceeded the size bound")
        raise
    except Exception as exc:
        store.delete(row.object_key)
        _fail(db, row, "STORAGE_UNAVAILABLE", str(exc)[:200])
        raise AttachmentError(503, "STORAGE_UNAVAILABLE") from exc

    if expected_bytes is not None and limiter.count != expected_bytes:
        store.delete(row.object_key)
        _fail(
            db,
            row,
            "ATTACHMENT_SIZE_MISMATCH",
            f"received {limiter.count} bytes, expected {expected_bytes}",
        )
        raise AttachmentError(400, "ATTACHMENT_SIZE_MISMATCH")
    if row.declared_size is not None and row.declared_size != limiter.count:
        store.delete(row.object_key)
        _fail(
            db,
            row,
            "ATTACHMENT_SIZE_MISMATCH",
            f"received {limiter.count} bytes, declared {row.declared_size}",
        )
        raise AttachmentError(400, "ATTACHMENT_SIZE_MISMATCH")

    row.state = "ready"
    row.stage = None
    row.size_bytes = limiter.count
    row.received_bytes = limiter.count
    row.sha256 = limiter.hexdigest
    row.revision = int(row.revision or 0) + 1
    row.updated_at = _stamp(_now())
    db.flush()
    return to_public(row)


def _fail(db: Session, row: Attachment, code: str, reason: str) -> None:
    row.state = "failed"
    row.stage = None
    row.error_code = code
    row.reason = reason
    row.revision = int(row.revision or 0) + 1
    row.updated_at = _stamp(_now())
    db.flush()


def get_attachment(
    db: Session, *, tenant_id: str, owner_user_id: str, attachment_id: str
) -> dict[str, object]:
    return to_public(_get_owned(db, attachment_id, tenant_id, owner_user_id))


def cancel_attachment(
    db: Session,
    store: BlobStore,
    *,
    tenant_id: str,
    owner_user_id: str,
    attachment_id: str,
) -> dict[str, object]:
    row = _get_owned(db, attachment_id, tenant_id, owner_user_id)
    if row.state in {"created", "uploading", "processing"}:
        row.state = "cancelled"
        row.stage = None
        row.revision = int(row.revision or 0) + 1
        row.updated_at = _stamp(_now())
        if row.object_key:
            store.delete(row.object_key)
    return to_public(row)


def delete_attachment(
    db: Session,
    store: BlobStore,
    *,
    tenant_id: str,
    owner_user_id: str,
    attachment_id: str,
) -> None:
    row = _get_owned(db, attachment_id, tenant_id, owner_user_id)
    if row.state in {"deleted"}:
        return
    if row.object_key:
        store.delete(row.object_key)
    row.state = "deleted"
    row.stage = None
    row.revision = int(row.revision or 0) + 1
    row.updated_at = _stamp(_now())
    db.flush()


def bind_for_run(
    db: Session,
    *,
    tenant_id: str,
    owner_user_id: str,
    session_id: str,
    run_id: str,
    attachment_ids: list[str],
) -> list[Attachment]:
    """Attach ready rows to a run. Called inside the run-creation transaction
    so a refusal rolls back the run as well."""
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_RUN:
        raise AttachmentError(400, "ATTACHMENT_LIMIT")
    bound: list[Attachment] = []
    seen: set[str] = set()
    for attachment_id in attachment_ids:
        if attachment_id in seen:
            raise AttachmentError(400, "ATTACHMENT_DUPLICATE")
        seen.add(attachment_id)
        row = db.get(Attachment, attachment_id)
        if row is None or row.tenant_id != tenant_id or row.state == "deleted":
            raise AttachmentError(400, "ATTACHMENT_NOT_FOUND", attachment_id)
        if row.owner_user_id != owner_user_id:
            raise AttachmentError(403, "ATTACHMENT_FORBIDDEN", attachment_id)
        if row.state != _BINDABLE_STATE:
            raise AttachmentError(409, "ATTACHMENT_STATE", f"{attachment_id}:{row.state}")
        if row.session_id and row.session_id != session_id:
            raise AttachmentError(409, "ATTACHMENT_SESSION_MISMATCH", attachment_id)
        expiry = _parse(row.expires_at)
        if expiry is not None and expiry <= _now():
            raise AttachmentError(410, "ATTACHMENT_EXPIRED", attachment_id)
        row.session_id = session_id
        row.run_id = run_id
        row.revision = int(row.revision or 0) + 1
        row.updated_at = _stamp(_now())
        bound.append(row)
    return bound


def import_manifest(rows: list[Attachment]) -> list[dict[str, object]]:
    """The run.created payload slice the worker consumes."""
    return [
        {
            "attachment_id": row.id,
            "filename": row.filename,
            "content_type": row.content_type,
            "size_bytes": int(row.size_bytes or 0),
            "sha256": row.sha256 or "",
            "object_key": row.object_key,
        }
        for row in rows
    ]

