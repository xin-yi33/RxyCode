"""Preview jobs (UI-2026-10-22 §07 API-PREVIEW-01/02).

A preview turns one registered deliverable into something the split pane can
render. Classification is delegated to the shared taxonomy
(:func:`rxycode_server.previews.kinds.preview_kind_for`) so the artifact
manifest and the conversion job can never disagree about what a file is:

- ``image`` / ``media`` — no conversion: the content endpoint streams the
  original bytes with the artifact's content type, so the browser renders
  images and plays audio/video natively.
- ``frontend_static`` — HTML is served as-is; every other text-family file is
  decoded and HTML-escaped into a ``<pre>`` page.
- ``pdf`` / ``office`` / ``archive`` / ``binary`` — converted to a
  self-contained, fully escaped HTML document by
  :mod:`rxycode_server.previews.converters` and stored beside the artifacts in
  the same private bucket.

Conversion runs inline and is bounded (``_MAX_SOURCE_BYTES`` for converted
kinds). A converter failure lands as a ``failed`` job with a real reason —
never a stuck spinner. The queued/running states stay in the contract for when
an async render queue exists.
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.artifacts.service import _client, _ensure_private_bucket
from rxycode_server.persistence.models import Artifact, PreviewJob, Run
from rxycode_server.previews import converters
from rxycode_server.previews.kinds import (
    FRONTEND_STATIC,
    IMAGE,
    MEDIA,
    preview_kind_for,
)

#: Converted sources are read fully into memory; images/media are streamed
#: through untouched and are not subject to this cap.
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_TTL_HOURS = 24

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_HTML_EXTS = (".html", ".htm", ".xhtml")

#: Kinds whose preview content is the original artifact bytes (streamed).
_STREAMED_KINDS = (IMAGE, MEDIA)


class PreviewError(Exception):
    def __init__(self, http_status: int, code: str, reason: str = "") -> None:
        super().__init__(reason or code)
        self.http_status = http_status
        self.code = code
        self.reason = reason


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


def _classify(artifact: Artifact) -> str:
    """One shared classification for both the manifest and this job."""
    return preview_kind_for(
        artifact.filename or artifact.relative_path or "",
        artifact.content_type or "",
    )


def _logical_name(artifact: Artifact) -> str:
    return artifact.filename or artifact.relative_path or ""


def _is_html(artifact: Artifact) -> bool:
    ctype = (artifact.content_type or "").split(";")[0].strip().lower()
    name = _logical_name(artifact).lower()
    return ctype in _HTML_TYPES or name.endswith(_HTML_EXTS)


def _stream_content_type(artifact: Artifact) -> str:
    """Content type for streamed image/media bytes.

    The browser only renders/plays the response when the type is specific; a
    generic ``application/octet-stream`` registration would download instead
    (``X-Content-Type-Options: nosniff`` is always set), so fall back to the
    filename guess the same way the classifier did.
    """
    declared = (artifact.content_type or "").split(";")[0].strip()
    if declared and declared.lower() != "application/octet-stream":
        return artifact.content_type or declared
    guessed, _encoding = mimetypes.guess_type(_logical_name(artifact))
    return guessed or "application/octet-stream"


def to_public(row: PreviewJob) -> dict[str, object]:
    return {
        "preview_id": row.id,
        "artifact_id": row.artifact_id,
        "kind": row.kind,
        "status": row.status,
        "entrypoint": row.entrypoint,
        "preview_url": row.preview_url,
        "error_code": row.error_code,
        "reason": row.reason,
        "revision": int(row.revision),
        "expires_at": row.expires_at,
    }


def _get_owned_artifact(db: Session, artifact_id: str, tenant_id: str) -> tuple[Artifact, Run]:
    row = db.get(Artifact, artifact_id)
    if row is None:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "artifact does not exist")
    run = db.get(Run, row.run_id)
    if run is None or run.tenant_id != tenant_id:
        raise PreviewError(403, "PREVIEW_FORBIDDEN", "")
    return row, run


def _live_job(db: Session, artifact: Artifact) -> PreviewJob | None:
    """Reuse a still-fresh job for the exact bytes already converted."""
    rows = db.scalars(
        select(PreviewJob)
        .where(
            PreviewJob.artifact_id == artifact.id,
            PreviewJob.sha256 == artifact.sha256,
            PreviewJob.status.in_(("queued", "running", "ready")),
        )
        .order_by(PreviewJob.created_at.desc())
    ).all()
    for row in rows:
        expiry = _parse(row.expires_at)
        if expiry is None or expiry > _now():
            return row
    return None


def _read_source(
    *,
    artifact: Artifact,
    s3_endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> bytes | None:
    """Fetch the artifact bytes for conversion; ``None`` when over the cap."""
    client = _client(s3_endpoint, access_key, secret_key)
    body = client.get_object(Bucket=bucket, Key=artifact.object_key)["Body"]
    source = body.read(_MAX_SOURCE_BYTES + 1)
    if len(source) > _MAX_SOURCE_BYTES:
        return None
    return source


def _build_document(
    *,
    artifact: Artifact,
    kind: str,
    source: bytes,
) -> bytes:
    """Turn artifact bytes into the HTML document stored for a preview job."""
    name = _logical_name(artifact)
    if kind == FRONTEND_STATIC:
        if _is_html(artifact):
            # HTML documents are served as-is; the CSP sandbox on the content
            # endpoint is the wall, exactly as before.
            return source
        return converters.convert_text(
            source, filename=name, content_type=artifact.content_type or ""
        )
    return converters.convert(kind, source, filename=name, content_type=artifact.content_type or "")


def _fail(
    db: Session,
    job: PreviewJob,
    *,
    code: str,
    reason: str,
) -> PreviewJob:
    job.status = "failed"
    job.error_code = code
    job.reason = reason
    db.commit()
    db.refresh(job)
    return job


def create_preview(
    db: Session,
    *,
    artifact_id: str,
    tenant_id: str,
    s3_endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> PreviewJob:
    artifact, run = _get_owned_artifact(db, artifact_id, tenant_id)
    if (artifact.availability or "available") != "available":
        raise PreviewError(409, "PREVIEW_NOT_READY", "artifact is not finalized")
    existing = _live_job(db, artifact)
    if existing is not None:
        return existing

    kind = _classify(artifact)
    job = PreviewJob(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        run_id=run.id,
        artifact_id=artifact.id,
        sha256=artifact.sha256,
        kind=kind,
        status="running",
        entrypoint=_logical_name(artifact),
        expires_at=_stamp(_now() + timedelta(hours=_TTL_HOURS)),
        created_at=_stamp(_now()),
    )
    db.add(job)

    if kind in _STREAMED_KINDS:
        # No conversion: the content endpoint streams the original bytes.
        job.status = "ready"
        job.preview_url = f"/api/v1/previews/{job.id}/content"
        db.commit()
        db.refresh(job)
        return job

    if not all([s3_endpoint, bucket, access_key, secret_key]):
        return _fail(
            db,
            job,
            code="preview_unconfigured",
            reason="preview storage is not configured",
        )

    try:
        source = _read_source(
            artifact=artifact,
            s3_endpoint=s3_endpoint or None,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
        )
        if source is None:
            return _fail(
                db,
                job,
                code="preview_too_large",
                reason=f"源文件超过预览上限（{_MAX_SOURCE_BYTES // (1024 * 1024)}MB）",
            )
        try:
            document = _build_document(artifact=artifact, kind=kind, source=source)
        except converters.ConverterError as exc:
            # Honest failed job with the converter's real reason.
            return _fail(db, job, code="preview_failed", reason=exc.reason)
        key = f"tenants/{tenant_id}/previews/{job.id}.html"
        client = _client(s3_endpoint, access_key, secret_key)
        _ensure_private_bucket(client, bucket)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=document,
            ContentType="text/html; charset=utf-8",
            ACL="private",
            Metadata={"sha256": hashlib.sha256(document).hexdigest()},
        )
        job.status = "ready"
        job.preview_url = f"/api/v1/previews/{job.id}/content"
        db.commit()
    except Exception as exc:  # storage/IO failures are honest job failures
        return _fail(
            db,
            job,
            code="preview_failed",
            reason=f"{type(exc).__name__}: {exc}"[:300],
        )
    db.refresh(job)
    return job


def get_preview(db: Session, preview_id: str, tenant_id: str) -> PreviewJob:
    row = db.get(PreviewJob, preview_id)
    if row is None or row.tenant_id != tenant_id:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "")
    expiry = _parse(row.expires_at)
    if row.status in ("queued", "running", "ready") and expiry and expiry <= _now():
        row.status = "expired"
        row.revision += 1
        db.commit()
        db.refresh(row)
    return row


def open_content(
    db: Session,
    *,
    job: PreviewJob,
    s3_endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> dict[str, object]:
    """Return the content stream for a ready job.

    Images and media stream the original artifact bytes with a specific
    content type (``sandboxed=False``); every converted kind streams the stored
    HTML document under the sandbox CSP (``sandboxed=True``).
    """
    if job.status != "ready" or not job.preview_url:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "preview is not ready")
    artifact = db.get(Artifact, job.artifact_id)
    if artifact is None:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "")
    if job.kind in _STREAMED_KINDS:
        if not all([s3_endpoint, bucket, access_key, secret_key]):
            raise PreviewError(503, "PREVIEW_UNCONFIGURED", "")
        client = _client(s3_endpoint, access_key, secret_key)
        stream = client.get_object(Bucket=bucket, Key=artifact.object_key)["Body"]
        return {
            "stream": stream,
            "content_type": _stream_content_type(artifact),
            "sandboxed": False,
        }
    if not all([s3_endpoint, bucket, access_key, secret_key]):
        raise PreviewError(503, "PREVIEW_UNCONFIGURED", "")
    key = f"tenants/{job.tenant_id}/previews/{job.id}.html"
    client = _client(s3_endpoint, access_key, secret_key)
    try:
        stream = client.get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as exc:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "converted bytes missing") from exc
    return {
        "stream": stream,
        "content_type": "text/html; charset=utf-8",
        "sandboxed": True,
    }
