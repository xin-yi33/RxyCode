"""WEB-W11 preview job flow on a SQLite harness (no Docker/Postgres/S3).

The shared W11 ``postgres_url`` fixture needs a Docker Postgres, which is not
available in every environment. This module drives the real preview service
against an in-memory SQLite database and a fake bucket so the central promise
— *every* artifact kind becomes a ``ready`` job instead of
``preview_unsupported`` — stays regression-tested everywhere. Postgres-specific
row behaviour remains covered by ``test_w11_c09_unit``.
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from rxycode_server.persistence.models import (  # noqa: E402
    Artifact,
    Base,
    PreviewJob,
    Run,
)
from rxycode_server.previews import kinds, service  # noqa: E402

pytestmark = pytest.mark.unit

_TABLES = (Run.__table__, Artifact.__table__, PreviewJob.__table__)


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            out, self._payload = self._payload, b""
            return out
        out, self._payload = self._payload[:size], self._payload[size:]
        return out


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _FakeBody(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):  # noqa: N803
        self.objects[Key] = Body

    def head_bucket(self, Bucket):  # noqa: N803
        return {}

    def create_bucket(self, Bucket):  # noqa: N803
        return {}

    def put_bucket_acl(self, Bucket, ACL):  # noqa: N803
        return {}


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=list(_TABLES))
    fake = _FakeS3()
    monkeypatch.setattr(service, "_client", lambda *args, **kwargs: fake)
    monkeypatch.setattr(service, "_ensure_private_bucket", lambda *args, **kwargs: None)
    with Session(engine) as db:
        db.add(
            Run(
                id="run-1",
                tenant_id="tenant-1",
                session_id="session-1",
                status="completed",
                request_id="req-1",
                target_id="cloud:tenant-1:project-1",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    try:
        yield engine, fake
    finally:
        engine.dispose()


def _seed(
    engine,
    fake: _FakeS3,
    *,
    artifact_id: str,
    filename: str,
    content_type: str,
    body: bytes,
) -> None:
    with Session(engine) as db:
        db.add(
            Artifact(
                id=artifact_id,
                run_id="run-1",
                object_key=f"objects/{artifact_id}",
                sha256=hashlib.sha256(body).hexdigest(),
                size=len(body),
                content_type=content_type,
                filename=filename,
                relative_path=filename,
                availability="available",
            )
        )
        db.commit()
    fake.objects[f"objects/{artifact_id}"] = body


def _create(engine, artifact_id: str, tenant_id: str = "tenant-1") -> PreviewJob:
    with Session(engine) as db:
        return service.create_preview(
            db,
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            s3_endpoint="https://s3.example",
            bucket="artifacts",
            access_key="key",
            secret_key="secret",
        )


def _content(engine, job: PreviewJob) -> tuple[dict, bytes]:
    with Session(engine) as db:
        opened = service.open_content(
            db,
            job=job,
            s3_endpoint="https://s3.example",
            bucket="artifacts",
            access_key="key",
            secret_key="secret",
        )
        stream = opened["stream"]
        payload = stream.read() if hasattr(stream, "read") else stream
        return opened, payload


def test_binary_artifact_is_ready_with_metadata_page(harness) -> None:
    engine, fake = harness
    payload = b"\x00\x01\x02binary" * 8
    _seed(
        engine,
        fake,
        artifact_id="art-binary",
        filename="firmware.bin",
        content_type="application/octet-stream",
        body=payload,
    )
    job = _create(engine, "art-binary")
    assert job.kind == "binary"
    assert job.status == "ready"
    assert job.error_code is None
    assert job.preview_url

    opened, page = _content(engine, job)
    assert opened["sandboxed"] is True
    assert opened["content_type"].startswith("text/html")
    assert b"SHA-256" in page
    assert b"00000000" in page


def test_image_and_media_stream_original_bytes(harness) -> None:
    engine, fake = harness
    image = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    video = b"\x00\x00\x00\x18ftypmp42" + b"0" * 16
    _seed(
        engine,
        fake,
        artifact_id="art-image",
        filename="shot.png",
        content_type="image/png",
        body=image,
    )
    _seed(
        engine,
        fake,
        artifact_id="art-media",
        filename="clip.mp4",
        content_type="video/mp4",
        body=video,
    )
    for artifact_id, payload, content_type in (
        ("art-image", image, "image/png"),
        ("art-media", video, "video/mp4"),
    ):
        job = _create(engine, artifact_id)
        assert job.kind in (kinds.IMAGE, kinds.MEDIA)
        assert job.status == "ready"
        opened, served = _content(engine, job)
        assert served == payload
        assert opened["sandboxed"] is False
        assert opened["content_type"] == content_type


def test_streamed_kind_recovers_specific_content_type_from_filename(harness) -> None:
    """A generic registration must not make the browser download the image."""
    engine, fake = harness
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 8
    _seed(
        engine,
        fake,
        artifact_id="art-generic-image",
        filename="legacy-photo.png",
        content_type="application/octet-stream",
        body=png,
    )
    job = _create(engine, "art-generic-image")
    assert job.kind == kinds.IMAGE
    opened, served = _content(engine, job)
    assert served == png
    assert opened["content_type"] == "image/png"


def test_html_is_served_as_is_and_text_is_escaped(harness) -> None:
    engine, fake = harness
    html_body = b"<html><body><h1>as-is</h1></body></html>"
    text_body = b"line <two> & 'quotes'\n"
    _seed(
        engine,
        fake,
        artifact_id="art-html",
        filename="page.html",
        content_type="text/html",
        body=html_body,
    )
    _seed(
        engine,
        fake,
        artifact_id="art-text",
        filename="notes.md",
        content_type="text/markdown",
        body=text_body,
    )

    html_job = _create(engine, "art-html")
    assert html_job.kind == "frontend_static"
    assert html_job.status == "ready"
    opened, page = _content(engine, html_job)
    assert page == html_body
    assert opened["sandboxed"] is True

    text_job = _create(engine, "art-text")
    assert text_job.kind == "frontend_static"
    _, page = _content(engine, text_job)
    assert b"&lt;two&gt;" in page
    assert b"line <two>" not in page


def test_archive_artifact_is_ready_with_listing(harness) -> None:
    engine, fake = harness
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("readme.txt", "hello")
    _seed(
        engine,
        fake,
        artifact_id="art-zip",
        filename="bundle.zip",
        content_type="application/zip",
        body=buffer.getvalue(),
    )
    job = _create(engine, "art-zip")
    assert job.kind == "archive"
    assert job.status == "ready"
    opened, page = _content(engine, job)
    assert opened["sandboxed"] is True
    assert b"readme.txt" in page


def test_converter_failure_is_an_honest_failed_job(harness) -> None:
    engine, fake = harness
    _seed(
        engine,
        fake,
        artifact_id="art-pdf",
        filename="broken.pdf",
        content_type="application/pdf",
        body=b"this is not a pdf",
    )
    job = _create(engine, "art-pdf")
    assert job.kind == "pdf"
    assert job.status == "failed"
    assert job.error_code in {"preview_failed", "preview_unconfigured"}
    assert job.reason
    # A failed job has no content to offer and never hangs.
    with pytest.raises(service.PreviewError):
        _content(engine, job)


def test_oversize_source_fails_honestly(harness) -> None:
    engine, fake = harness
    oversized = b"x" * (service._MAX_SOURCE_BYTES + 1)
    _seed(
        engine,
        fake,
        artifact_id="art-huge",
        filename="huge.bin",
        content_type="application/octet-stream",
        body=oversized,
    )
    job = _create(engine, "art-huge")
    assert job.status == "failed"
    assert job.error_code == "preview_too_large"
    assert job.reason


def test_unconfigured_storage_fails_honestly(harness) -> None:
    engine, fake = harness
    _seed(
        engine,
        fake,
        artifact_id="art-nostore",
        filename="a.zip",
        content_type="application/zip",
        body=b"PK\x05\x06" + b"\x00" * 18,
    )
    with Session(engine) as db:
        job = service.create_preview(
            db,
            artifact_id="art-nostore",
            tenant_id="tenant-1",
            s3_endpoint=None,
            bucket=None,
            access_key=None,
            secret_key=None,
        )
    assert job.status == "failed"
    assert job.error_code == "preview_unconfigured"
    # Streaming kinds never need storage, so they stay ready.
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 8
    _seed(
        engine,
        fake,
        artifact_id="art-image-nostore",
        filename="x.png",
        content_type="image/png",
        body=png,
    )
    with Session(engine) as db:
        image_job = service.create_preview(
            db,
            artifact_id="art-image-nostore",
            tenant_id="tenant-1",
            s3_endpoint=None,
            bucket=None,
            access_key=None,
            secret_key=None,
        )
    assert image_job.status == "ready"


def test_dedupe_and_tenant_isolation(harness) -> None:
    engine, fake = harness
    body = b"\x00\x01"
    _seed(
        engine,
        fake,
        artifact_id="art-one",
        filename="one.bin",
        content_type="application/octet-stream",
        body=body,
    )
    first = _create(engine, "art-one")
    again = _create(engine, "art-one")
    assert first.id == again.id
    assert first.kind == again.kind == "binary"

    with pytest.raises(service.PreviewError) as foreign:
        _create(engine, "art-one", tenant_id="tenant-2")
    assert foreign.value.http_status == 403

    with pytest.raises(service.PreviewError) as missing:
        _create(engine, "art-missing")
    assert missing.value.http_status == 404
