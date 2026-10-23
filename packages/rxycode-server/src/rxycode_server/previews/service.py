"""Preview jobs (UI-2026-10-22 §07 API-PREVIEW-01/02).

A preview converts an artifact into something a sandboxed iframe can render:

- ``image/*`` artifacts need no conversion — the content endpoint streams the
  original bytes and the job goes straight to ``ready`` (kind=image).
- HTML and text-family artifacts convert to a static HTML document stored
  beside the artifacts in the same private bucket (kind=frontend). Text is
  HTML-escaped into a ``<pre>`` block — never injected raw.
- Everything else fails honestly with ``preview_unsupported`` so the UI can
  show a truthful "no preview" state instead of a spinner that never lands.

Conversion runs inline and is bounded (input capped at _MAX_SOURCE_BYTES) —
no async render queue exists yet; the queued/running states stay in the
contract for when one does.
"""

from __future__ import annotations

import hashlib
import html
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.artifacts.service import _client, _ensure_private_bucket
from rxycode_server.persistence.models import Artifact, PreviewJob, Run

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_TTL_HOURS = 24

_IMAGE_PREFIX = "image/"
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_HTML_EXTS = (".html", ".htm")
_TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
    "application/toml",
    "application/x-sh",
)
_TEXT_EXTS = (
    ".md", ".markdown", ".txt", ".log", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".xml", ".svg", ".py", ".js", ".jsx", ".ts",
    ".tsx", ".css", ".scss", ".less", ".sh", ".bash", ".zsh", ".ps1",
    ".java", ".c", ".h", ".cpp", ".hpp", ".go", ".rs", ".rb", ".php",
    ".sql", ".ini", ".cfg", ".conf", ".env", ".diff", ".patch",
)


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


def _classify(artifact: Artifact) -> str | None:
    ctype = (artifact.content_type or "").split(";")[0].strip().lower()
    name = (artifact.filename or artifact.relative_path or "").lower()
    if ctype.startswith(_IMAGE_PREFIX):
        return "image"
    if ctype in _HTML_TYPES or name.endswith(_HTML_EXTS):
        return "frontend"
    if any(ctype.startswith(prefix) for prefix in _TEXT_TYPES) or name.endswith(
        _TEXT_EXTS
    ):
        return "frontend"
    return None


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


def _get_owned_artifact(
    db: Session, artifact_id: str, tenant_id: str
) -> tuple[Artifact, Run]:
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
        kind=kind or "none",
        status="running",
        entrypoint=artifact.filename or artifact.relative_path or "",
        expires_at=_stamp(_now() + timedelta(hours=_TTL_HOURS)),
        created_at=_stamp(_now()),
    )
    db.add(job)

    if kind is None:
        job.status = "failed"
        job.error_code = "preview_unsupported"
        job.reason = f"{artifact.content_type or 'this type'} 暂不支持预览"
        db.commit()
        db.refresh(job)
        return job

    if kind == "image":
        # No conversion: the content endpoint streams the original bytes.
        job.status = "ready"
        job.preview_url = f"/api/v1/previews/{job.id}/content"
        db.commit()
        db.refresh(job)
        return job

    if not all([s3_endpoint, bucket, access_key, secret_key]):
        job.status = "failed"
        job.error_code = "preview_unconfigured"
        job.reason = "preview storage is not configured"
        db.commit()
        db.refresh(job)
        return job

    try:
        client = _client(s3_endpoint, access_key, secret_key)
        body = client.get_object(Bucket=bucket, Key=artifact.object_key)["Body"]
        source = body.read(_MAX_SOURCE_BYTES + 1)
        if len(source) > _MAX_SOURCE_BYTES:
            job.status = "failed"
            job.error_code = "preview_too_large"
            job.reason = "源文件超过预览上限"
            db.commit()
            db.refresh(job)
            return job
        name = (artifact.filename or artifact.relative_path or "").lower()
        if name.endswith(_HTML_EXTS) or (artifact.content_type or "").lower().split(";")[
            0
        ].strip() in _HTML_TYPES:
            document = source
        else:
            try:
                text = source.decode("utf-8", errors="replace")
            except Exception:
                text = source.decode("utf-8", errors="replace")
            escaped = html.escape(text)
            title = html.escape(artifact.filename or "preview")
            document = (
                "<!doctype html><meta charset=utf-8><title>" + title + "</title>"
                "<style>body{font:13px/1.5 ui-monospace,Consolas,monospace;margin:16px;"
                "color:#1b1b1b}pre{white-space:pre-wrap;word-break:break-word}</style>"
                "<pre>" + escaped + "</pre>"
            ).encode("utf-8")
        key = f"tenants/{tenant_id}/previews/{job.id}.html"
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
    except PreviewError:
        raise
    except Exception as exc:  # storage/IO failures are honest 5xx-in-job, not hangs
        job.status = "failed"
        job.error_code = "preview_failed"
        job.reason = f"{type(exc).__name__}"
        db.commit()
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
    """Return the content stream for a ready job. Images stream the original
    artifact bytes; frontend previews stream the converted HTML object."""
    if job.status != "ready" or not job.preview_url:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "preview is not ready")
    artifact = db.get(Artifact, job.artifact_id)
    if artifact is None:
        raise PreviewError(404, "PREVIEW_NOT_FOUND", "")
    if job.kind == "image":
        if not all([s3_endpoint, bucket, access_key, secret_key]):
            raise PreviewError(503, "PREVIEW_UNCONFIGURED", "")
        client = _client(s3_endpoint, access_key, secret_key)
        stream = client.get_object(Bucket=bucket, Key=artifact.object_key)["Body"]
        return {
            "stream": stream,
            "content_type": artifact.content_type or "application/octet-stream",
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
