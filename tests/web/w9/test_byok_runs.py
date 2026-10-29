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
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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
    User,
)
from rxycode_server.byok.resolver import resolve_run_model  # noqa: E402
from tests.web.w9.test_runs_api import (  # noqa: E402
    _client,
    _csrf,
    _headers,
    _strip_grant,
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


def test_resolver_requires_byok_despite_allowlist_switches(monkeypatch):
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", "superuser")
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")

    class _DB:
        def get(self, model, _ref):
            if model is User:
                return SimpleNamespace(default_model_ref="platform")
            return None

        def scalars(self, _statement):
            # grant_for_user lookup — this actor holds no grant row.
            return SimpleNamespace(one_or_none=lambda: None)

    record = SimpleNamespace(user_id="superuser", tenant_id="tenant")
    with pytest.raises(HTTPException) as error:
        resolve_run_model(_DB(), record, None, mode="local")
    assert error.value.status_code == 403
    assert error.value.detail == "BYOK_REQUIRED"

    with pytest.raises(HTTPException) as explicit:
        resolve_run_model(_DB(), record, "platform", mode="local")
    assert explicit.value.status_code == 404
    assert explicit.value.detail == "MODEL_NOT_FOUND"


def test_enforced_without_model_denies_and_orphans_nothing(
    postgres_url, byok_env
):
    client, me = _user(postgres_url, "nobyok@example.com")
    # W13: registration auto-claimed a grant slot; this test asserts the
    # BYOK-only denial, so release it first (11th+ registrant semantics).
    _strip_grant(postgres_url, me["user"]["id"])
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
    # Grant released: the catalogue must hold only the BYOK row.
    _strip_grant(postgres_url, me["user"]["id"])
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


def test_platform_ref_is_rejected_even_for_allowlisted_user(
    postgres_url, byok_env, monkeypatch
):
    client, me = _user(postgres_url, "pleb@example.com")
    # W13: a grant holder CAN submit platform — the denial case needs a
    # grant-less user, so release the auto-claimed slot first.
    _strip_grant(postgres_url, me["user"]["id"])
    denied = _task(client, model_ref="platform")
    assert denied.status_code == 404
    assert denied.json()["code"] == "MODEL_NOT_FOUND"
    internal, internal_me = _user(postgres_url, "ops@example.com")
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", internal_me["user"]["id"])
    # The retired allowlist env grants nothing — the released user is
    # refused identically.
    _strip_grant(postgres_url, internal_me["user"]["id"])
    denied = _task(internal, model_ref="platform")
    assert denied.status_code == 404
    assert denied.json()["code"] == "MODEL_NOT_FOUND"


def test_legacy_platform_default_does_not_resolve(postgres_url, byok_env):
    client, me = _user(postgres_url, "old-platform-default@example.com")
    # The stale-default path is only reachable once the grant is gone.
    _strip_grant(postgres_url, me["user"]["id"])
    with Session(create_engine(postgres_url)) as db:
        user = db.get(User, me["user"]["id"])
        user.default_model_ref = "platform"
        db.commit()
    denied = _task(client)
    assert denied.status_code == 403
    assert denied.json()["code"] == "BYOK_REQUIRED"


def test_session_continuation_enforced(postgres_url, byok_env):
    client, me = _user(postgres_url, "cont@example.com")
    # BYOK-only denial: release the auto-claimed grant first.
    _strip_grant(postgres_url, me["user"]["id"])
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


def test_enforcement_off_still_requires_byok(postgres_url, byok_env, monkeypatch):
    """The legacy switch cannot restore Web's platform environment gateway."""
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")
    client, me = _user(postgres_url, "legacy@example.com")
    # With no grant and no BYOK model the submit must still refuse.
    _strip_grant(postgres_url, me["user"]["id"])
    resp = _task(client)
    assert resp.status_code == 403
    assert resp.json()["code"] == "BYOK_REQUIRED"


def test_platform_default_ref_is_rejected(postgres_url, byok_env):
    client, me = _user(postgres_url, "set-platform-default@example.com")
    # Grant holders may set the platform default (W13); the rejection case
    # needs a grant-less user.
    _strip_grant(postgres_url, me["user"]["id"])
    denied = client.post(
        "/api/v1/models/default",
        json={"model_ref": "platform"},
        headers=_headers(_csrf(client)),
    )
    assert denied.status_code == 404
    assert denied.json()["code"] == "MODEL_NOT_FOUND"
