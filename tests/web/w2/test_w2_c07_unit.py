"""WEB-W2-C07. An artifact downloads with a matching digest, and another tenant cannot read it."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from rxycode_server.artifacts.service import (  # noqa: E402
    ArtifactForbidden,
    open_download,
    read_download,
    store_artifact,
)
from rxycode_server.main import create_app  # noqa: E402
from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Membership,
    Organization,
    Project,
    Run,
    SessionRow,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402

ORIGIN = "http://127.0.0.1"
SECRET = "local-web-secret-value-32bytes!!"
_MINIO = "rxy-w2c07-minio"
_ACCESS = "rxycode"
_SECRET_KEY = "rxy-minio-secret-value"
_BUCKET = "rxycode-artifacts"
_BODY = b"artifact-secret-c07\n"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=False)


def _minio() -> dict[str, str]:
    _docker("rm", "-f", _MINIO)
    # Ephemeral host port — fixed ports raced parallel containers on the
    # shared CI runner ("address already in use" flakes).
    started = _docker(
        "run",
        "-d",
        "--name",
        _MINIO,
        "-p",
        "127.0.0.1:0:9000",
        "-e",
        f"MINIO_ROOT_USER={_ACCESS}",
        "-e",
        f"MINIO_ROOT_PASSWORD={_SECRET_KEY}",
        "bitnamilegacy/minio:2025.7.23",
    )
    assert started.returncode == 0, started.stderr
    bound = _docker("port", _MINIO, "9000/tcp")
    port = bound.stdout.strip().rsplit(":", 1)[-1]
    assert bound.returncode == 0 and port.isdigit(), bound.stderr or bound.stdout
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{endpoint}/minio/health/live", timeout=2) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        logs = _docker("logs", _MINIO)
        raise RuntimeError(logs.stderr or logs.stdout or "minio did not become ready")
    return {
        "endpoint": endpoint,
        "bucket": _BUCKET,
        "access_key": _ACCESS,
        "secret_key": _SECRET_KEY,
    }


def _seed_run(url: str) -> str:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c07", github_id="gh-c07", kind="github"))
        db.add(Organization(id="org-c07", tenant_id="tenant-c07"))
        db.add(Project(id="project-c07", tenant_id="tenant-c07", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c07",
                project_id="project-c07",
                title="files",
            )
        )
        db.commit()
    engine.dispose()
    created = create_run(
        url,
        tenant_id="tenant-c07",
        session_id=session_id,
        message="produce a file",
        target_id="local:c07",
        permission_profile="workspace-write",
        request_id="req-c07-file",
    )
    return created.run_id


def _s3_of(store: dict[str, str]) -> dict[str, str]:
    return {
        "s3_endpoint": store["endpoint"],
        "bucket": store["bucket"],
        "access_key": store["access_key"],
        "secret_key": store["secret_key"],
    }


def test_w2_c07_contract(postgres_url: str):
    """A finished tool file can be downloaded and its digest matches the bytes."""
    store = _minio()
    run_id = _seed_run(postgres_url)
    saved = store_artifact(
        postgres_url,
        tenant_id="tenant-c07",
        run_id=run_id,
        filename="note.txt",
        body=_BODY,
        content_type="text/plain",
        **_s3_of(store),
    )
    assert saved["sha256"] == hashlib.sha256(_BODY).hexdigest()
    assert saved["size"] == len(_BODY)
    assert saved["content_type"] == "text/plain"
    opened = open_download(
        postgres_url,
        tenant_id="tenant-c07",
        artifact_id=saved["artifact_id"],
        signing_key=SECRET,
        ttl_seconds=60,
    )
    body = read_download(
        postgres_url,
        tenant_id="tenant-c07",
        artifact_id=saved["artifact_id"],
        expires=opened["expires"],
        signature=opened["signature"],
        signing_key=SECRET,
        **_s3_of(store),
    )
    assert hashlib.sha256(body).hexdigest() == saved["sha256"]
    assert body == _BODY
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(User(id="user-c07-local", github_id=None, kind="local"))
        db.add(
            Membership(
                id="mem-c07",
                tenant_id="tenant-c07",
                user_id="user-c07-local",
                role="owner",
            )
        )
        db.commit()
    engine.dispose()
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        s3_endpoint=store["endpoint"],
        s3_bucket=store["bucket"],
        s3_access_key=store["access_key"],
        s3_secret_key=store["secret_key"],
    )
    client = TestClient(app)
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": ORIGIN, "X-Local-Secret": SECRET}
    assert client.post("/api/v1/auth/local/login", headers=headers).status_code == 200
    downloaded = client.get(
        f"/api/v1/runs/{run_id}/artifacts/{saved['artifact_id']}",
        params={"expires": opened["expires"], "signature": opened["signature"]},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == _BODY
    assert downloaded.headers["content-type"].startswith("text/plain")


def test_w2_c07_negative(postgres_url: str):
    """Tenant B cannot read tenant A's artifact, even with A's id."""
    store = _minio()
    run_id = _seed_run(postgres_url)
    saved = store_artifact(
        postgres_url,
        tenant_id="tenant-c07",
        run_id=run_id,
        filename="secret.txt",
        body=_BODY,
        content_type="text/plain",
        **_s3_of(store),
    )
    opened = open_download(
        postgres_url,
        tenant_id="tenant-c07",
        artifact_id=saved["artifact_id"],
        signing_key=SECRET,
        ttl_seconds=30,
    )
    with pytest.raises(ArtifactForbidden) as denied:
        read_download(
            postgres_url,
            tenant_id="tenant-other",
            artifact_id=saved["artifact_id"],
            expires=opened["expires"],
            signature=opened["signature"],
            signing_key=SECRET,
            **_s3_of(store),
        )
    assert denied.value.http_status == 403
    assert denied.value.code == "ARTIFACT_FORBIDDEN"
    assert b"artifact-secret-c07" not in str(denied.value).encode()
    with pytest.raises(ArtifactForbidden) as expired:
        read_download(
            postgres_url,
            tenant_id="tenant-c07",
            artifact_id=saved["artifact_id"],
            expires=opened["expires"],
            signature=opened["signature"],
            signing_key=SECRET,
            now=datetime.now(timezone.utc) + timedelta(hours=2),
            **_s3_of(store),
        )
    assert expired.value.http_status == 403
    assert b"artifact-secret-c07" not in str(expired.value).encode()
    app = create_app(
        postgres_url,
        mode="local",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        s3_endpoint=store["endpoint"],
        s3_bucket=store["bucket"],
        s3_access_key=store["access_key"],
        s3_secret_key=store["secret_key"],
    )
    client = TestClient(app)
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": ORIGIN, "X-Local-Secret": SECRET}
    assert client.post("/api/v1/auth/local/login", headers=headers).status_code == 200
    stolen = client.get(
        f"/api/v1/runs/{run_id}/artifacts/{saved['artifact_id']}",
        params={"expires": opened["expires"], "signature": opened["signature"]},
    )
    assert stolen.status_code == 403
    assert stolen.json()["code"] == "ARTIFACT_FORBIDDEN"
    assert b"artifact-secret-c07" not in stolen.content
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run is not None
        assert run.tenant_id == "tenant-c07"
    engine.dispose()
