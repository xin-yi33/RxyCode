"""BYOK submission binding: runs pin their model at submit time (§7.3, §13.6).

Enforcement on: no personal model -> 403 BYOK_REQUIRED with no run AND no
orphan session. A run stores the immutable model snapshot; run.created and
the run DTOs echo it — never the key.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.models import (  # noqa: E402
    ModelConnection,
    Run,
    RunEvent,
    SessionRow,
)
from tests.web.w9.test_runs_api import (  # noqa: E402
    _client,
    _csrf,
    _headers,
)

CANARY = "sk-canary-cc0099dd11223344"


@pytest.fixture
def byok_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rxycode_server.byok.keyring import generate

    path = tmp_path / "byok-keyring.json"
    generate(path)
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(path))
    monkeypatch.delenv("RXYCODE_BYOK_ALLOW_PRIVATE", raising=False)
    monkeypatch.delenv("RXYCODE_PLATFORM_MODEL_USERS", raising=False)
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "1")
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")


def _user(postgres_url: str, email: str):
    return _client(postgres_url, email)


def _make_model(client) -> str:
    """Create a connection + one catalogued model; return its model_ref."""
    conn = client.post(
        "/api/v1/model-connections",
        json={"preset_id": "deepseek", "api_key": CANARY},
        headers=_headers(_csrf(client)),
    )
    assert conn.status_code == 201, conn.text
    conn_id = conn.json()["connection"]["id"]
    added = client.post(
        f"/api/v1/model-connections/{conn_id}/models",
        json={"model_ids": ["deepseek-chat"]},
        headers=_headers(_csrf(client)),
    )
    return added.json()["results"][0]["model_ref"]


def _task(client, request_id=None, **extra):
    body = {
        "message": "do a thing",
        "request_id": request_id or ("req-" + uuid.uuid4().hex[:16]),
        "permission_profile": "confirm",
        **extra,
    }
    return client.post("/api/v1/tasks", json=body, headers=_headers(_csrf(client)))


def test_enforced_without_model_denies_and_orphans_nothing(
    postgres_url, byok_env
):
    client, me = _user(postgres_url, "nobyok@example.com")
    resp = _task(client)
    assert resp.status_code == 403
    assert resp.json()["code"] == "BYOK_REQUIRED"
    with Session(create_engine(postgres_url)) as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 0
        # A refused submission must not leave an orphan session behind.
        assert db.scalar(select(func.count()).select_from(SessionRow)) == 0


def test_owned_model_run_snapshot(postgres_url, byok_env):
    client, me = _user(postgres_url, "hasbyok@example.com")
    model_ref = _make_model(client)
    resp = _task(client, model_ref=model_ref)
    assert resp.status_code == 202, resp.text
    with Session(create_engine(postgres_url)) as db:
        run = db.get(Run, resp.json()["run_id"])
        assert run.model_ref == model_ref
        assert run.model_id == "deepseek-chat"
        assert run.provider_id == "deepseek"
        assert run.credential_source == "byok"
        assert run.connection_id.startswith("mc_")
        assert run.credential_version == 1
        created = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run.id, RunEvent.type == "run.created"
            )
        ).one()
        model = created.payload["model"]
        assert model["model_ref"] == model_ref
        assert model["credential_source"] == "byok"
        # The event log is durable and replayable — a key in it is forever.
        assert CANARY not in json.dumps(created.payload)


def test_foreign_model_ref_is_404(postgres_url, byok_env):
    client_a, _ = _user(postgres_url, "owner@example.com")
    client_b, _ = _user(postgres_url, "intruder@example.com")
    model_ref = _make_model(client_a)
    resp = _task(client_b, model_ref=model_ref)
    assert resp.status_code == 404
    assert resp.json()["code"] == "MODEL_NOT_FOUND"


def test_cleared_key_is_model_unavailable(postgres_url, byok_env):
    client, me = _user(postgres_url, "cleared@example.com")
    model_ref = _make_model(client)
    conn_id = client.get("/api/v1/models").json()["models"][0]["connection_id"]
    cleared = client.post(
        f"/api/v1/model-connections/{conn_id}/clear-key",
        headers=_headers(_csrf(client)),
    )
    assert cleared.status_code == 200
    resp = _task(client, model_ref=model_ref)
    assert resp.status_code == 409
    assert resp.json()["code"] == "MODEL_UNAVAILABLE"


def test_platform_ref_requires_allowlist(postgres_url, byok_env, monkeypatch):
    client, me = _user(postgres_url, "pleb@example.com")
    denied = _task(client, model_ref="platform")
    assert denied.status_code == 404
    assert denied.json()["code"] == "MODEL_NOT_FOUND"

    internal, internal_me = _user(postgres_url, "ops@example.com")
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", internal_me["user"]["id"])
    ok = _task(internal, model_ref="platform")
    assert ok.status_code == 202, ok.text
    with Session(create_engine(postgres_url)) as db:
        run = db.get(Run, ok.json()["run_id"])
        assert run.credential_source == "platform"
        assert run.model_ref == "platform"


def test_session_continuation_enforced(postgres_url, byok_env):
    client, me = _user(postgres_url, "cont@example.com")
    # A session row exists (created via the project API, no run attached).
    project_id = me["default_project_id"]
    session = client.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "existing"},
        headers=_headers(_csrf(client)),
    )
    assert session.status_code in (200, 201), session.text
    session_id = session.json()["id"]
    denied = client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "message": "hello",
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
        },
        headers=_headers(_csrf(client)),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "BYOK_REQUIRED"
    # With a valid model the same session accepts a run.
    model_ref = _make_model(client)
    ok = client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "message": "hello",
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
            "model_ref": model_ref,
        },
        headers=_headers(_csrf(client)),
    )
    assert ok.status_code == 202, ok.text


def test_request_id_conflict_by_model(postgres_url, byok_env):
    client, me = _user(postgres_url, "idem@example.com")
    conn = client.post(
        "/api/v1/model-connections",
        json={"preset_id": "deepseek", "api_key": CANARY},
        headers=_headers(_csrf(client)),
    ).json()["connection"]["id"]
    refs = [
        r["model_ref"]
        for r in client.post(
            f"/api/v1/model-connections/{conn}/models",
            json={"model_ids": ["m-a", "m-b"]},
            headers=_headers(_csrf(client)),
        ).json()["results"]
    ]
    request_id = "req-" + uuid.uuid4().hex[:16]
    first = _task(client, request_id=request_id, model_ref=refs[0])
    assert first.status_code == 202
    # Same request_id + same model_ref replays idempotently.
    replay = _task(client, request_id=request_id, model_ref=refs[0])
    assert replay.status_code == 202
    assert replay.json()["run_id"] == first.json()["run_id"]
    # Same request_id + a DIFFERENT model_ref is a conflict, not a new run.
    conflict = _task(client, request_id=request_id, model_ref=refs[1])
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REQUEST_CONFLICT"


def test_run_dtos_echo_model_and_legacy_null(postgres_url, byok_env):
    client, me = _user(postgres_url, "dto@example.com")
    model_ref = _make_model(client)
    bound = _task(client, model_ref=model_ref)
    assert bound.status_code == 202
    detail = client.get(f"/api/v1/runs/{bound.json()['run_id']}")
    assert detail.status_code == 200
    model = detail.json()["model"]
    assert model["model_ref"] == model_ref
    assert model["credential_source"] == "byok"
    assert model["model_id"] == "deepseek-chat"
    listing = client.get(
        f"/api/v1/sessions/{bound.json()['session_id']}/runs"
    ).json()["runs"]
    assert listing[0]["model"]["model_ref"] == model_ref
    assert CANARY not in detail.text
    assert CANARY not in client.get(
        f"/api/v1/sessions/{bound.json()['session_id']}/runs"
    ).text

    # A pre-BYOK row (no snapshot columns) reports model: null.
    with Session(create_engine(postgres_url)) as db:
        db.execute(
            update(Run)
            .where(Run.id == bound.json()["run_id"])
            .values(model_ref=None, model_id=None, credential_source=None)
        )
        db.commit()
    assert client.get(f"/api/v1/runs/{bound.json()['run_id']}").json()["model"] is None


def test_enforcement_off_legacy_no_snapshot(postgres_url, byok_env, monkeypatch):
    """With RXYCODE_BYOK_ENFORCE=0 a no-model submission stays legacy."""
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")
    client, me = _user(postgres_url, "legacy@example.com")
    resp = _task(client)
    assert resp.status_code == 202, resp.text
    with Session(create_engine(postgres_url)) as db:
        run = db.get(Run, resp.json()["run_id"])
        assert run.model_ref is None
        created = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run.id, RunEvent.type == "run.created"
            )
        ).one()
        assert created.payload.get("model") is None
    assert client.get(f"/api/v1/runs/{run.id}").json()["model"] is None
