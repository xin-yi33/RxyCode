"""Store a run file in MinIO and hand out a short-lived tenant signature."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Artifact, Outbox, Run, RunEvent

_RETENTION_DAYS = 7
_RETENTION_SECONDS = _RETENTION_DAYS * 24 * 60 * 60
_MAX_DOWNLOAD_TTL = 900


class ArtifactForbidden(Exception):
    """The caller does not get the object bytes."""

    def __init__(self) -> None:
        super().__init__("artifact forbidden")
        self.http_status = 403
        self.code = "ARTIFACT_FORBIDDEN"


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def _client(endpoint: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _safe_name(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if base in {"", ".", ".."}:
        return "artifact.bin"
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    return (cleaned or "artifact.bin")[:120]


def _signature(
    signing_key: str, artifact_id: str, tenant_id: str, expires: int, sha256: str
) -> str:
    message = f"{artifact_id}\n{tenant_id}\n{expires}\n{sha256}".encode()
    return hmac.new(signing_key.encode(), message, hashlib.sha256).hexdigest()


def _parse_expires(expires: int | str) -> int:
    try:
        value = int(expires)
    except (TypeError, ValueError) as exc:
        raise ArtifactForbidden() from exc
    if value <= 0:
        raise ArtifactForbidden()
    return value


def _moment(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _ensure_private_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "rxycode-artifact-retention",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "tenants/"},
                    "Expiration": {"Days": _RETENTION_DAYS},
                }
            ]
        },
    )
    client.put_bucket_acl(Bucket=bucket, ACL="private")


def _add_event(db: Session, run: Run, event_type: str, payload: dict) -> None:
    retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
    seq = max(int(run.event_seq or 0), int(retained or 0)) + 1
    run.event_seq = seq
    event_id = uuid.uuid4().hex
    db.add(
        RunEvent(
            event_id=event_id,
            run_id=run.id,
            tenant_id=run.tenant_id,
            seq=seq,
            type=event_type,
            payload=payload,
            at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    db.add(Outbox(id=uuid.uuid4().hex, event_id=event_id, dispatch_status="pending", attempts=0))


def _owned(
    db: Session, artifact_id: str, tenant_id: str, run_id: str | None
) -> tuple[Artifact, Run]:
    row = db.get(Artifact, artifact_id)
    if row is None:
        raise ArtifactForbidden()
    run = db.get(Run, row.run_id)
    if run is None or run.tenant_id != tenant_id:
        raise ArtifactForbidden()
    if run_id is not None and run.id != run_id:
        raise ArtifactForbidden()
    return row, run


def store_artifact(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    filename: str,
    body: bytes,
    content_type: str,
    s3_endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
) -> dict[str, object]:
    """Upload the bytes, then save metadata and artifact.created in one transaction."""
    if not isinstance(body, bytes) or len(content_type) > 128 or not content_type.strip():
        raise ArtifactForbidden()
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            run = db.get(Run, run_id)
            if run is None or run.tenant_id != tenant_id:
                raise ArtifactForbidden()
    finally:
        engine.dispose()

    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid.uuid4().hex
    object_key = f"tenants/{tenant_id}/runs/{run_id}/{artifact_id}/{_safe_name(filename)}"
    if len(object_key) > 400:
        raise ArtifactForbidden()
    client = _client(s3_endpoint, access_key, secret_key)
    _ensure_private_bucket(client, bucket)
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body,
        ContentType=content_type,
        ACL="private",
        Metadata={
            "sha256": digest,
            "content-type": content_type,
            "ttl-seconds": str(_RETENTION_SECONDS),
        },
    )
    payload = {
        "artifact_id": artifact_id,
        "sha256": digest,
        "size": len(body),
        "content_type": content_type,
        "ttl_seconds": _RETENTION_SECONDS,
    }
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                client.delete_object(Bucket=bucket, Key=object_key)
                raise ArtifactForbidden()
            db.add(
                Artifact(
                    id=artifact_id,
                    run_id=run.id,
                    object_key=object_key,
                    sha256=digest,
                    size=len(body),
                    content_type=content_type,
                )
            )
            _add_event(db, run, "artifact.created", payload)
            db.commit()
    except Exception:
        client.delete_object(Bucket=bucket, Key=object_key)
        raise
    finally:
        engine.dispose()
    return {"artifact_id": artifact_id, **payload}


def open_download(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
    signing_key: str,
    ttl_seconds: int,
) -> dict[str, object]:
    """Sign a download that expires within fifteen minutes for this tenant only."""
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0 or ttl_seconds > _MAX_DOWNLOAD_TTL:
        raise ArtifactForbidden()
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row, _run = _owned(db, artifact_id, tenant_id, None)
            expires = int(datetime.now(timezone.utc).timestamp()) + ttl_seconds
            signature = _signature(signing_key, row.id, tenant_id, expires, row.sha256)
            return {
                "artifact_id": row.id,
                "expires": expires,
                "signature": signature,
                "ttl_seconds": ttl_seconds,
            }
    finally:
        engine.dispose()


def read_download(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
    expires: int | str,
    signature: str,
    signing_key: str,
    s3_endpoint: str | None = None,
    bucket: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> bytes:
    """Return the object only after the tenant, expiry, and signature all match."""
    expires_at = _parse_expires(expires)
    if _moment(now).timestamp() >= expires_at:
        raise ArtifactForbidden()
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row, _run = _owned(db, artifact_id, tenant_id, run_id)
            expected = _signature(signing_key, row.id, tenant_id, expires_at, row.sha256)
            object_key = row.object_key
            digest = row.sha256
            size = int(row.size)
    finally:
        engine.dispose()
    try:
        matches = hmac.compare_digest(expected, signature)
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise ArtifactForbidden()
    if not s3_endpoint or not bucket or not access_key or not secret_key:
        raise RuntimeError("artifact storage is not configured")
    client = _client(s3_endpoint, access_key, secret_key)
    found = client.get_object(Bucket=bucket, Key=object_key)
    data = found["Body"].read()
    if hashlib.sha256(data).hexdigest() != digest or len(data) != size:
        raise ArtifactForbidden()
    return data
