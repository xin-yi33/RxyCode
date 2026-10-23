"""W12: session-workspace files API — list/download with tenant scoping."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.web.w9.test_auth import (  # noqa: E402
    _app,
    _csrf,
    _headers,
    _register,
)
from tests.web.w9.test_runs_api import _seed_byok  # noqa: E402


def _client(postgres_url: str, email: str):
    app = _app(postgres_url, mode="local")
    client = TestClient(app)
    response = _register(client, email, "str0ng-pass!")
    assert response.status_code == 201, response.text
    return client, response.json()


def _new_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/tasks",
        json={
            "message": "make files",
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
        },
        headers=_headers(_csrf(client)),
    )
    assert response.status_code == 202, response.text
    return response.json()["session_id"]


def _workspace(tmp_path: Path, tenant_id: str, session_id: str) -> Path:
    root = tmp_path / "runs" / tenant_id / session_id
    root.mkdir(parents=True)
    return root


def test_w12_files_list_download_scope(
    postgres_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.setenv("RXYCODE_WORKSPACES_ROOT", str(tmp_path / "runs"))
    client, me = _client(postgres_url, "files@example.com")
    _seed_byok(client)
    session_id = _new_session(client)
    ws = _workspace(tmp_path, me["organization"]["tenant_id"], session_id)
    (ws / "hello.txt").write_text("rxy-file-test", encoding="utf-8")
    (ws / "sub").mkdir()
    (ws / "sub" / "note.md").write_text("# hi", encoding="utf-8")
    (ws / ".turn-result.json").write_text("{}", encoding="utf-8")

    listing = client.get(f"/api/v1/sessions/{session_id}/files")
    assert listing.status_code == 200, listing.text
    paths = {f["path"] for f in listing.json()["files"]}
    assert paths == {"hello.txt", "sub/note.md"}  # dotfile hidden

    got = client.get(
        f"/api/v1/sessions/{session_id}/files/download",
        params={"path": "sub/note.md"},
    )
    assert got.status_code == 200, got.text
    assert got.text == "# hi"

    for bad in ("../outside.txt", "/etc/passwd", "sub/../../x"):
        denied = client.get(
            f"/api/v1/sessions/{session_id}/files/download",
            params={"path": bad},
        )
        assert denied.status_code == 403, (bad, denied.status_code)

    denied_dot = client.get(
        f"/api/v1/sessions/{session_id}/files/download",
        params={"path": ".turn-result.json"},
    )
    assert denied_dot.status_code == 404


def test_w12_files_tenant_isolation(
    postgres_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.setenv("RXYCODE_WORKSPACES_ROOT", str(tmp_path / "runs"))
    client_a, me_a = _client(postgres_url, "files-a@example.com")
    _seed_byok(client_a)
    session_id = _new_session(client_a)
    _workspace(tmp_path, me_a["organization"]["tenant_id"], session_id) / "x.txt"

    client_b, _me_b = _client(postgres_url, "files-b@example.com")
    response = client_b.get(f"/api/v1/sessions/{session_id}/files")
    assert response.status_code == 404


def test_w12_files_no_root(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    monkeypatch.delenv("RXYCODE_WORKSPACES_ROOT", raising=False)
    client, _me = _client(postgres_url, "files-c@example.com")
    _seed_byok(client)
    session_id = _new_session(client)
    response = client.get(f"/api/v1/sessions/{session_id}/files")
    assert response.status_code == 404
