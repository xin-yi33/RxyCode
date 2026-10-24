"""WEB-W11-C09. Preview jobs: every kind renders, honest failure, sandboxed serve.

Contract (UI-2026-10-22 §07 API-PREVIEW-01/02, extended for
``所有类型的文件都可以预览``): POST /previews dedupes on the artifact's sha;
HTML is served as-is and text converts to an escaped static page; images and
media stream their original bytes; pdf/office/archive/binary convert to a
self-contained sandboxed HTML page (binary is the honest metadata fallback, so
no artifact is ever left without a preview); converted HTML is served under a
CSP sandbox; a converter failure is a ``failed`` job with a real reason
instead of a stuck queued spinner.
"""

from __future__ import annotations

import hashlib
import io
import sys
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

ORIGIN = "https://cloud.example"
SECRET = "local-web-secret-value-32bytes!!"


class _FakeBody(io.BytesIO):
    def iter_chunks(self, size: int = 8192):
        self.seek(0)
        while True:
            chunk = self.read(size)
            if not chunk:
                break
            yield chunk


class _FakeS3:
    """In-memory stand-in for the private artifact bucket."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(self, Bucket, Key, Body, ContentType="", **kw):
        data = Body if isinstance(Body, bytes) else Body.read()
        self.objects[Key] = (data, ContentType)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _FakeBody(self.objects[Key][0])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def head_bucket(self, Bucket):
        return {}

    def create_bucket(self, Bucket):
        return {}

    def put_bucket_acl(self, Bucket, ACL):
        return {}


def _github(app, client: TestClient, github_id: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(
                200, json={"access_token": f"ghs_{github_id}", "token_type": "bearer"}
            )
        return httpx.Response(200, json={"id": github_id, "login": f"user-{github_id}"})

    app.state.github_transport = httpx.MockTransport(handler)
    started = client.get("/api/v1/auth/github/start")
    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"state": started.json()["state"], "code": f"code-{github_id}"},
    )
    assert callback.status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": ORIGIN}


def _cloud_app(postgres_url: str):
    from rxycode_server.main import create_app
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(postgres_url)
    return create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="https://cloud.example/callback",
        s3_endpoint="https://s3.example",
        s3_bucket="artifacts",
    )


def _seed_artifact(
    postgres_url: str, run_id: str, tenant_id: str, *, filename: str,
    content_type: str, body: bytes,
) -> str:
    from rxycode_server.persistence.models import Artifact

    artifact_id = "art-" + uuid.uuid4().hex[:12]
    key = f"tenants/{tenant_id}/runs/{run_id}/{artifact_id}/{filename}"
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(
                Artifact(
                    id=artifact_id,
                    run_id=run_id,
                    object_key=key,
                    sha256=hashlib.sha256(body).hexdigest(),
                    size=len(body),
                    content_type=content_type,
                    filename=filename,
                    relative_path=filename,
                    availability="available",
                )
            )
            db.commit()
    finally:
        engine.dispose()
    return artifact_id


def _bucket_bytes(
    postgres_url: str, fake: "_FakeS3", artifact_id: str, body: bytes, content_type: str
) -> None:
    """Put the seeded artifact's bytes where the preview service will read them."""
    from rxycode_server.persistence.models import Artifact

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Artifact, artifact_id)
            fake.objects[row.object_key] = (body, content_type)
    finally:
        engine.dispose()


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("readme.txt", "hello from the archive")
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            "<w:p><w:r><w:t>Office preview works</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>escaped &lt;b&gt;tag&lt;/b&gt;</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    return buffer.getvalue()


def _stack(postgres_url: str, tmp_path: Path, monkeypatch, github_id: int):
    """App + logged-in owner + a run + a fake bucket with the artifact bytes."""
    from rxycode_server.previews import service as preview_service
    from rxycode_server.runs.service import create_run

    fake = _FakeS3()
    monkeypatch.setattr(preview_service, "_client", lambda *a, **k: fake)
    monkeypatch.setattr(preview_service, "_ensure_private_bucket", lambda *a, **k: None)

    app = _cloud_app(postgres_url)
    # The api reads creds off app.state — anything non-empty marks "configured".
    app.state.s3_endpoint = "https://s3.example"
    app.state.s3_bucket = "artifacts"
    app.state.s3_access_key = "k"
    app.state.s3_secret_key = "s"

    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, github_id)
    headers = _csrf(owner)
    project = owner.post(
        "/api/v1/projects", json={"name": "w11p", "repo_config": {}}, headers=headers
    )
    project_id = project.json()["id"]
    tenant_id = project.json()["tenant_id"]
    session = owner.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "s"},
        headers=headers,
    )
    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session.json()["id"],
        message="produce files",
        target_id="cloud:sandbox",
        permission_profile="default",
        request_id="req-" + uuid.uuid4().hex,
    )
    return app, owner, headers, tenant_id, accepted.run_id, fake


def test_w11_c09_contract(postgres_url: str, tmp_path: Path, monkeypatch) -> None:
    app, owner, headers, tenant_id, run_id, fake = _stack(
        postgres_url, tmp_path, monkeypatch, 1301
    )
    text_body = "line one\nline <two> & 'quotes'\n".encode()
    artifact_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="result.txt", content_type="text/plain", body=text_body,
    )
    # The artifact bytes live in the bucket under the artifact's object key.
    engine = create_engine(postgres_url, poolclass=NullPool)
    with Session(engine) as db:
        from rxycode_server.persistence.models import Artifact

        row = db.get(Artifact, artifact_id)
        fake.objects[row.object_key] = (text_body, "text/plain")
    engine.dispose()

    created = owner.post(
        "/api/v1/previews", json={"artifact_id": artifact_id}, headers=headers
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["kind"] == "frontend_static"
    assert job["status"] == "ready"
    assert job["preview_url"].endswith(f"/previews/{job['preview_id']}/content")

    # Dedupe on the same artifact sha — no second job.
    again = owner.post(
        "/api/v1/previews", json={"artifact_id": artifact_id}, headers=headers
    )
    assert again.json()["preview_id"] == job["preview_id"]

    status = owner.get(f"/api/v1/previews/{job['preview_id']}")
    assert status.json()["status"] == "ready"

    content = owner.get(f"/api/v1/previews/{job['preview_id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("text/html")
    # Sandbox CSP is the second wall after the iframe attribute.
    csp = content.headers.get("content-security-policy", "")
    assert "sandbox" in csp
    # Source text is escaped, never injected raw.
    assert "line <two>" not in content.text
    assert "&lt;two&gt;" in content.text

    # Image kind streams the original bytes, no conversion needed.
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    image_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="shot.png", content_type="image/png", body=png,
    )
    engine = create_engine(postgres_url, poolclass=NullPool)
    with Session(engine) as db:
        from rxycode_server.persistence.models import Artifact

        row = db.get(Artifact, image_id)
        fake.objects[row.object_key] = (png, "image/png")
    engine.dispose()
    job2 = owner.post(
        "/api/v1/previews", json={"artifact_id": image_id}, headers=headers
    ).json()
    assert job2["kind"] == "image"
    assert job2["status"] == "ready"
    body2 = owner.get(f"/api/v1/previews/{job2['preview_id']}/content")
    assert body2.status_code == 200
    assert body2.content == png

    # Media kind also streams the original bytes with the artifact content
    # type — the iframe's native player renders audio/video.
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 24
    media_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="clip.mp4", content_type="video/mp4", body=mp4,
    )
    _bucket_bytes(postgres_url, fake, media_id, mp4, "video/mp4")
    job_media = owner.post(
        "/api/v1/previews", json={"artifact_id": media_id}, headers=headers
    ).json()
    assert job_media["kind"] == "media"
    assert job_media["status"] == "ready"
    media = owner.get(f"/api/v1/previews/{job_media['preview_id']}/content")
    assert media.status_code == 200
    assert media.content == mp4
    assert media.headers["content-type"].startswith("video/mp4")
    # Streamed bytes are not an HTML document, so no sandbox CSP is applied.
    assert "content-security-policy" not in media.headers

    # Archive kind converts to a sandboxed member listing.
    archive_body = _zip_bytes()
    archive_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="bundle.zip", content_type="application/zip", body=archive_body,
    )
    _bucket_bytes(postgres_url, fake, archive_id, archive_body, "application/zip")
    job_zip = owner.post(
        "/api/v1/previews", json={"artifact_id": archive_id}, headers=headers
    ).json()
    assert job_zip["kind"] == "archive"
    assert job_zip["status"] == "ready"
    zip_page = owner.get(f"/api/v1/previews/{job_zip['preview_id']}/content")
    assert zip_page.status_code == 200
    assert "readme.txt" in zip_page.text
    assert "sandbox" in zip_page.headers.get("content-security-policy", "")

    # Office kind converts to escaped HTML text extraction.
    docx_body = _docx_bytes()
    docx_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="报告.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        body=docx_body,
    )
    _bucket_bytes(
        postgres_url,
        fake,
        docx_id,
        docx_body,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    job_docx = owner.post(
        "/api/v1/previews", json={"artifact_id": docx_id}, headers=headers
    ).json()
    assert job_docx["kind"] == "office"
    assert job_docx["status"] == "ready"
    docx_page = owner.get(f"/api/v1/previews/{job_docx['preview_id']}/content")
    assert docx_page.status_code == 200
    assert "Office preview works" in docx_page.text
    # Extracted text stays escaped, never injected raw.
    assert "escaped <b>tag</b>" not in docx_page.text
    assert "escaped &lt;b&gt;tag&lt;/b&gt;" in docx_page.text


def test_w11_c09_negative(postgres_url: str, tmp_path: Path, monkeypatch) -> None:
    app, owner, headers, tenant_id, run_id, fake = _stack(
        postgres_url, tmp_path, monkeypatch, 1302
    )
    blob = b"\x00\x01\x02binary" * 8
    artifact_id = _seed_artifact(
        postgres_url, run_id, tenant_id,
        filename="firmware.bin", content_type="application/octet-stream",
        body=blob,
    )
    _bucket_bytes(postgres_url, fake, artifact_id, blob, "application/octet-stream")

    # Binary is no longer "unsupported": the honest metadata + hexdump page is
    # ready, so every artifact kind has a preview.
    job = owner.post(
        "/api/v1/previews", json={"artifact_id": artifact_id}, headers=headers
    ).json()
    assert job["kind"] == "binary"
    assert job["status"] == "ready"
    assert job["error_code"] is None
    page = owner.get(f"/api/v1/previews/{job['preview_id']}/content")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "sandbox" in page.headers.get("content-security-policy", "")
    assert "SHA-256" in page.text
    assert "00000000" in page.text  # hexdump offset column
    assert "00 01 02" in page.text  # bytes rendered as hex, not raw
    assert job["preview_url"]

    # Missing artifact / foreign ids → 404.
    missing = owner.post(
        "/api/v1/previews",
        json={"artifact_id": "art-" + "0" * 12},
        headers=headers,
    )
    assert missing.status_code == 404

    # A second tenant cannot read the job or its content.
    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 1303)
    attacker.post(
        "/api/v1/projects",
        json={"name": "atk", "repo_config": {}},
        headers=_csrf(attacker),
    )
    assert attacker.get(f"/api/v1/previews/{job['preview_id']}").status_code == 404
    assert (
        attacker.get(f"/api/v1/previews/{job['preview_id']}/content").status_code
        == 404
    )

    # Anonymous is refused.
    anon = TestClient(app, base_url="https://cloud.example")
    assert anon.post("/api/v1/previews", json={"artifact_id": artifact_id}).status_code in (
        401,
        403,
    )
