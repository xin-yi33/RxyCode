"""WEB-W11-C07. Attachment lifecycle + run binding + artifact manifest.

Contract (UI-2026-10-22 §07 API-FILE-01..06, API-ART-01): an attachment is
created, receives streamed bytes, reports status, binds to a run inside the
run-creation transaction, rides the run.created payload to the worker, and
deletes cleanly. Guessing another tenant's attachment leaks nothing.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
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


def _github(app, client: TestClient, github_id: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(
                200, json={"access_token": f"ghs_{github_id}", "token_type": "bearer"}
            )
        return httpx.Response(200, json={"id": github_id, "login": f"user-{github_id}"})

    app.state.github_transport = httpx.MockTransport(handler)
    started = client.get("/api/v1/auth/github/start")
    assert started.status_code == 200
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
    )


def _fs_store(app, root: Path) -> None:
    from rxycode_server.attachments.store import BlobConfig

    app.state.attachment_blobs = BlobConfig("fs", root=str(root))


def _bootstrap(client: TestClient, headers: dict[str, str]) -> tuple[str, str, str]:
    project = client.post(
        "/api/v1/projects",
        json={"name": "w11", "repo_config": {}},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["id"]
    tenant_id = project.json()["tenant_id"]
    session = client.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "w11-session"},
        headers=headers,
    )
    assert session.status_code == 200
    return project_id, tenant_id, session.json()["id"]


def test_w11_c07_contract(postgres_url: str, tmp_path: Path) -> None:
    """create → PUT → ready → bind to run → load_run carries the manifest."""
    from rxycode_server.runs.service import create_run, load_run

    app = _cloud_app(postgres_url)
    _fs_store(app, tmp_path)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 1101)
    headers = _csrf(owner)
    _project_id, tenant_id, session_id = _bootstrap(owner, headers)
    user_id = owner.get("/api/v1/me").json()["user"]["id"]

    body = b"hello attachment " * 64
    created = owner.post(
        "/api/v1/attachments",
        json={
            "filename": "notes.txt",
            "content_type": "text/plain",
            "size_bytes": len(body),
            "session_id": session_id,
            "request_id": "req-" + uuid.uuid4().hex[:20],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    attachment = created.json()
    assert attachment["state"] == "created"
    attachment_id = attachment["attachment_id"]

    put = owner.put(
        f"/api/v1/attachments/{attachment_id}/content",
        content=body,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["state"] == "ready"
    assert put.json()["sha256"] == hashlib.sha256(body).hexdigest()

    status = owner.get(f"/api/v1/attachments/{attachment_id}")
    assert status.status_code == 200
    assert status.json()["state"] == "ready"
    assert status.json()["size_bytes"] == len(body)

    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="read my file",
        target_id="cloud:sandbox",
        permission_profile="default",
        request_id="req-" + uuid.uuid4().hex,
        user_id=user_id,
        attachment_ids=[attachment_id],
    )
    loaded = load_run(postgres_url, accepted.run_id)
    manifest = loaded["attachments"]
    assert len(manifest) == 1
    assert manifest[0]["attachment_id"] == attachment_id
    assert manifest[0]["filename"] == "notes.txt"
    assert manifest[0]["sha256"] == hashlib.sha256(body).hexdigest()
    assert manifest[0]["object_key"].startswith(f"tenants/{tenant_id}/attachments/")

    deleted = owner.delete(f"/api/v1/attachments/{attachment_id}", headers=headers)
    assert deleted.status_code == 204
    gone = owner.get(f"/api/v1/attachments/{attachment_id}")
    assert gone.status_code == 404


def test_w11_c07_negative(postgres_url: str, tmp_path: Path) -> None:
    """Foreign tenant sees nothing; oversize/mismatch/state errors map cleanly."""
    from rxycode_server.attachments.service import AttachmentError
    from rxycode_server.runs.service import create_run

    app = _cloud_app(postgres_url)
    _fs_store(app, tmp_path)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 1102)
    headers = _csrf(owner)
    _project_id, tenant_id, session_id = _bootstrap(owner, headers)
    user_id = owner.get("/api/v1/me").json()["user"]["id"]

    created = owner.post(
        "/api/v1/attachments",
        json={"filename": "secret.txt", "size_bytes": 5, "session_id": session_id},
        headers=headers,
    )
    attachment_id = created.json()["attachment_id"]
    owner.put(
        f"/api/v1/attachments/{attachment_id}/content",
        content=b"12345",
        headers={**headers, "Content-Type": "application/octet-stream"},
    )

    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 1103)
    aheaders = _csrf(attacker)
    _ap, _at, asession = _bootstrap(attacker, aheaders)

    assert attacker.get(f"/api/v1/attachments/{attachment_id}").status_code == 404
    assert (
        attacker.put(
            f"/api/v1/attachments/{attachment_id}/content",
            content=b"x",
            headers={**aheaders, "Content-Type": "application/octet-stream"},
        ).status_code
        == 404
    )
    assert (
        attacker.delete(
            f"/api/v1/attachments/{attachment_id}", headers=aheaders
        ).status_code
        == 404
    )

    # Attacker's run cannot bind the owner's attachment.
    with pytest.raises(AttachmentError):
        create_run(
            postgres_url,
            tenant_id=_at,
            session_id=asession,
            message="steal",
            target_id="cloud:sandbox",
            permission_profile="default",
            request_id="req-" + uuid.uuid4().hex,
            user_id=attacker.get("/api/v1/me").json()["user"]["id"],
            attachment_ids=[attachment_id],
        )

    # Declared size over the cap → 413 at create.
    over = owner.post(
        "/api/v1/attachments",
        json={"filename": "big.bin", "size_bytes": 128 * 1024 * 1024 + 1},
        headers=headers,
    )
    assert over.status_code == 413

    # Wire bytes ≠ declared size → 400 and the row fails honestly.
    declared = owner.post(
        "/api/v1/attachments",
        json={"filename": "mismatch.txt", "size_bytes": 10},
        headers=headers,
    ).json()
    mismatch = owner.put(
        f"/api/v1/attachments/{declared['attachment_id']}/content",
        content=b"short",
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "ATTACHMENT_SIZE_MISMATCH"
    failed = owner.get(f"/api/v1/attachments/{declared['attachment_id']}").json()
    assert failed["state"] == "failed"

    # A non-ready attachment cannot bind.
    pending = owner.post(
        "/api/v1/attachments",
        json={"filename": "pending.txt"},
        headers=headers,
    ).json()
    with pytest.raises(AttachmentError):
        create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_id,
            message="bind pending",
            target_id="cloud:sandbox",
            permission_profile="default",
            request_id="req-" + uuid.uuid4().hex,
            user_id=user_id,
            attachment_ids=[pending["attachment_id"]],
        )


def test_w11_c07_manifest(postgres_url: str) -> None:
    """API-ART-01: manifest envelope + per-item fields + signed download_url."""
    from rxycode_server.persistence.models import Artifact
    from rxycode_server.runs.service import create_run

    app = _cloud_app(postgres_url)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 1104)
    headers = _csrf(owner)
    _project_id, tenant_id, session_id = _bootstrap(owner, headers)

    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="make artifacts",
        target_id="cloud:sandbox",
        permission_profile="default",
        request_id="req-" + uuid.uuid4().hex,
    )
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(
                Artifact(
                    id="art-" + uuid.uuid4().hex[:12],
                    run_id=accepted.run_id,
                    object_key=f"tenants/{tenant_id}/runs/{accepted.run_id}/x/out.txt",
                    sha256="a" * 64,
                    size=42,
                    content_type="text/plain",
                    filename="out.txt",
                    relative_path="out.txt",
                    availability="available",
                    partial=False,
                    preview_kind="frontend",
                )
            )
            db.commit()
    finally:
        engine.dispose()

    listed = owner.get(f"/api/v1/runs/{accepted.run_id}/artifacts")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["manifest_status"] in {"partial", "complete"}
    assert "manifest_revision" in body
    assert len(body["artifacts"]) == 1
    item = body["artifacts"][0]
    assert item["filename"] == "out.txt"
    assert item["preview_kind"] == "frontend"
    assert item["availability"] == "available"
    assert item["partial"] is False
    assert item["size"] == 42
    assert item["download_url"].startswith(
        f"/api/v1/runs/{accepted.run_id}/artifacts/"
    )
    assert "signature=" in item["download_url"]

    # Bad signature cannot download.
    bad = owner.get(
        f"/api/v1/runs/{accepted.run_id}/artifacts/{item['artifact_id']}"
        "?expires=9999999999&signature=forged"
    )
    assert bad.status_code in (401, 403)
