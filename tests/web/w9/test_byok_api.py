"""BYOK API + run-model submission binding (WEB BYOK §6.3, §7.2–7.3, §13.6–13.7).

All credentials are canaries (``sk-canary-*``); provider discovery/probe is
monkeypatched — no real network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.models import (  # noqa: E402
    ModelConnection,
    User,
    UserModel,
)
from tests.web.w9.test_runs_api import (  # noqa: E402
    _client,
    _csrf,
    _headers,
)

CANARY = "sk-canary-a1b2c3d4e5f60718"


@pytest.fixture
def byok_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from rxycode_server.byok.keyring import generate

    path = tmp_path / "byok-keyring.json"
    generate(path)
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(path))
    monkeypatch.delenv("RXYCODE_BYOK_ALLOW_PRIVATE", raising=False)
    monkeypatch.delenv("RXYCODE_BYOK_ENFORCE", raising=False)
    monkeypatch.delenv("RXYCODE_PLATFORM_MODEL_USERS", raising=False)
    return path


def _reg(postgres_url: str, email: str, monkeypatch) -> tuple[TestClient, dict]:
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    return _client(postgres_url, email)


def _create_connection(client: TestClient, api_key: str = CANARY, **extra):
    return client.post(
        "/api/v1/model-connections",
        json={"preset_id": "deepseek", "api_key": api_key, **extra},
        headers=_headers(_csrf(client)),
    )


def _add_models(client: TestClient, conn_id: str, ids: list[str]):
    return client.post(
        f"/api/v1/model-connections/{conn_id}/models",
        json={"model_ids": ids},
        headers=_headers(_csrf(client)),
    )


def _mm():
    from rxycode_server.api.models import _model_manager

    return _model_manager()


def test_platform_catalogue_policy_unit(monkeypatch):
    from rxycode_server.api import models as models_api

    actor = SimpleNamespace(user_id="superuser", tenant_id="tenant")
    user = SimpleNamespace(default_model_ref="platform")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(mode="local")))

    class _DB:
        def get(self, _model, _key):
            return user

        def execute(self, _statement):
            return SimpleNamespace(all=lambda: [])

    db = _DB()
    monkeypatch.setattr(models_api, "current_record", lambda _request: actor)
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", "superuser")
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")

    access = models_api.model_access(request, db)
    assert access["require_byok"] is True
    assert access["platform_allowed"] is False
    assert access["default_model_ref"] is None
    listing = models_api.list_models(request, db)
    assert listing == {"models": [], "default_model_ref": None}

    monkeypatch.setattr(models_api, "require_write", lambda _request: None)
    with pytest.raises(HTTPException) as error:
        models_api.set_default_model(
            models_api._DefaultIn(model_ref="platform"), request, db
        )
    assert error.value.status_code == 404
    assert error.value.detail == "MODEL_NOT_FOUND"


def test_create_preset_and_custom(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "byok-a@example.com", monkeypatch)
    resp = _create_connection(client)
    assert resp.status_code == 201, resp.text
    conn = resp.json()["connection"]
    assert conn["provider_id"] == "deepseek"
    assert conn["base_url"] == "https://api.deepseek.com/v1"
    assert conn["has_key"] is True
    assert conn["credential_version"] == 1
    assert conn["state"] == "active"
    # The key never appears — not even masked — in the raw response text.
    assert CANARY not in resp.text

    monkeypatch.setenv("RXYCODE_BYOK_ALLOW_PRIVATE", "1")
    custom = client.post(
        "/api/v1/model-connections",
        json={
            "base_url": "http://127.0.0.1:9/v1",
            "provider_name": "local mock",
            "api_key": "sk-canary-custom",
        },
        headers=_headers(_csrf(client)),
    )
    assert custom.status_code == 201, custom.text
    assert custom.json()["connection"]["base_url"] == "http://127.0.0.1:9/v1"


def test_canary_never_in_responses_or_db(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "leak@example.com", monkeypatch)
    resp = _create_connection(client)
    conn_id = resp.json()["connection"]["id"]
    for path in (
        "/api/v1/model-connections",
        "/api/v1/models",
        "/api/v1/models/access",
    ):
        listed = client.get(path)
        assert listed.status_code == 200
        assert CANARY not in listed.text, path
    patched = client.patch(
        f"/api/v1/model-connections/{conn_id}",
        json={"display_name": "renamed"},
        headers=_headers(_csrf(client)),
    )
    assert CANARY not in patched.text
    with Session(create_engine(postgres_url)) as db:
        row = db.get(ModelConnection, conn_id)
        assert row.ciphertext is not None
        assert CANARY.encode() not in row.ciphertext
        assert row.ciphertext != CANARY.encode()


def test_patch_key_version_semantics(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "patch@example.com", monkeypatch)
    conn = _create_connection(client).json()["connection"]
    # Empty key patch = keep version.
    kept = client.patch(
        f"/api/v1/model-connections/{conn['id']}",
        json={"api_key": "", "display_name": "still same key"},
        headers=_headers(_csrf(client)),
    )
    assert kept.status_code == 200
    assert kept.json()["connection"]["credential_version"] == 1
    # New key bumps the version and re-seals under the new AAD.
    bumped = client.patch(
        f"/api/v1/model-connections/{conn['id']}",
        json={"api_key": "sk-canary-rotated-002"},
        headers=_headers(_csrf(client)),
    )
    assert bumped.json()["connection"]["credential_version"] == 2
    from rxycode_server.byok.crypto import (
        BYOKDecryptError,
        connection_aad,
        decrypt,
    )

    with Session(create_engine(postgres_url)) as db:
        row = db.get(ModelConnection, conn["id"])
        plain = decrypt(
            row.ciphertext,
            row.nonce,
            row.key_id,
            aad=connection_aad(
                tenant_id=me["organization"]["tenant_id"],
                owner_user_id=me["user"]["id"],
                connection_id=conn["id"],
                credential_version=2,
            ),
        )
        assert plain == "sk-canary-rotated-002"
        # The OLD version's AAD must no longer verify the re-sealed key.
        with pytest.raises(BYOKDecryptError):
            decrypt(
                row.ciphertext,
                row.nonce,
                row.key_id,
                aad=connection_aad(
                    tenant_id=me["organization"]["tenant_id"],
                    owner_user_id=me["user"]["id"],
                    connection_id=conn["id"],
                    credential_version=1,
                ),
            )


def test_foreign_connection_is_404_everywhere(
    postgres_url, byok_keyring, monkeypatch
):
    client_a, _ = _reg(postgres_url, "owner-a@example.com", monkeypatch)
    client_b, _ = _reg(postgres_url, "owner-b@example.com", monkeypatch)
    conn = _create_connection(client_a).json()["connection"]
    conn_id = conn["id"]
    model_ref = _add_models(client_a, conn_id, ["deepseek-chat"]).json()[
        "results"
    ][0]["model_ref"]

    # B sees no connections at all.
    assert client_b.get("/api/v1/model-connections").json()["connections"] == []
    verbs = [
        ("patch", f"/api/v1/model-connections/{conn_id}", {"display_name": "x"}),
        ("delete", f"/api/v1/model-connections/{conn_id}", None),
        ("post", f"/api/v1/model-connections/{conn_id}/clear-key", {}),
        ("post", f"/api/v1/model-connections/{conn_id}/discover", {}),
        ("post", f"/api/v1/model-connections/{conn_id}/models", {"model_ids": ["m1"]}),
        ("post", f"/api/v1/model-connections/{conn_id}/test", {}),
        ("delete", f"/api/v1/models/{model_ref}", None),
        ("post", "/api/v1/models/default", {"model_ref": model_ref}),
    ]
    for method, path, body in verbs:
        resp = client_b.request(
            method.upper(),
            path,
            json=body,
            headers=_headers(_csrf(client_b)),
        )
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
    # The row is untouched.
    assert (
        client_a.get("/api/v1/model-connections").json()["connections"][0]["id"]
        == conn_id
    )


def test_discover_and_add_models(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "disc@example.com", monkeypatch)
    conn_id = _create_connection(client).json()["connection"]["id"]

    captured = {}

    def fake_discover(*, api_key: str, base_url: str) -> dict:
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return {
            "success": True,
            "elapsed": 0.01,
            "models": [
                {"id": "deepseek-chat", "name": "DeepSeek Chat"},
                {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner"},
            ],
        }

    monkeypatch.setattr(_mm(), "discover_provider_models", fake_discover)
    found = client.post(
        f"/api/v1/model-connections/{conn_id}/discover",
        headers=_headers(_csrf(client)),
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["success"] is True
    # The DECRYPTED canary reached the provider call; it is never echoed back.
    assert captured["api_key"] == CANARY
    assert CANARY not in found.text
    assert {m["id"] for m in body["models"]} == {"deepseek-chat", "deepseek-reasoner"}
    assert all(m["added"] is False for m in body["models"])

    added = _add_models(client, conn_id, ["deepseek-chat", "deepseek-chat", "bad id!!", "x" * 300])
    results = added.json()["results"]
    # first occurrence adds; second occurrence of the same id -> exists
    assert results[0]["status"] == "added"
    assert results[1]["status"] == "exists"
    assert results[2]["status"] == "invalid"
    assert results[3]["status"] == "invalid"

    again = _add_models(client, conn_id, ["deepseek-chat", "deepseek-reasoner"])
    again_map = {r["model_id"]: r["status"] for r in again.json()["results"]}
    assert again_map == {"deepseek-chat": "exists", "deepseek-reasoner": "added"}

    # Discovery flags already-catalogued ids.
    found2 = client.post(
        f"/api/v1/model-connections/{conn_id}/discover",
        headers=_headers(_csrf(client)),
    )
    added_flags = {m["id"]: m["added"] for m in found2.json()["models"]}
    assert added_flags == {"deepseek-chat": True, "deepseek-reasoner": True}


def test_models_list_and_default(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "default@example.com", monkeypatch)
    conn_id = _create_connection(client).json()["connection"]["id"]
    model_ref = _add_models(client, conn_id, ["deepseek-chat"]).json()[
        "results"
    ][0]["model_ref"]

    listing = client.get("/api/v1/models")
    assert listing.status_code == 200
    models = listing.json()["models"]
    assert len(models) == 1
    assert models[0]["model_ref"] == model_ref
    assert models[0]["model_id"] == "deepseek-chat"
    assert models[0]["source"] == "byok"
    assert models[0]["status"] == "available"
    assert listing.json()["default_model_ref"] is None

    set_default = client.post(
        "/api/v1/models/default",
        json={"model_ref": model_ref},
        headers=_headers(_csrf(client)),
    )
    assert set_default.json()["default_model_ref"] == model_ref
    cleared = client.post(
        "/api/v1/models/default",
        json={"model_ref": None},
        headers=_headers(_csrf(client)),
    )
    assert cleared.json()["default_model_ref"] is None


def test_delete_model_and_connection_clears_default(
    postgres_url, byok_keyring, monkeypatch
):
    client, me = _reg(postgres_url, "delete@example.com", monkeypatch)
    conn_id = _create_connection(client).json()["connection"]["id"]
    refs = [
        r["model_ref"]
        for r in _add_models(client, conn_id, ["m-one", "m-two"]).json()["results"]
    ]
    # Deleting a model that is the default clears the default.
    client.post(
        "/api/v1/models/default",
        json={"model_ref": refs[0]},
        headers=_headers(_csrf(client)),
    )
    client.delete(f"/api/v1/models/{refs[0]}", headers=_headers(_csrf(client)))
    assert client.get("/api/v1/models").json()["default_model_ref"] is None
    assert len(client.get("/api/v1/models").json()["models"]) == 1
    # Deleting the connection cascades the remaining model and clears it too.
    client.post(
        "/api/v1/models/default",
        json={"model_ref": refs[1]},
        headers=_headers(_csrf(client)),
    )
    deleted = client.delete(
        f"/api/v1/model-connections/{conn_id}", headers=_headers(_csrf(client))
    )
    assert deleted.status_code == 200
    listing = client.get("/api/v1/models").json()
    assert listing["models"] == []
    assert listing["default_model_ref"] is None


def test_private_base_url_refused_unless_override(
    postgres_url, byok_keyring, monkeypatch
):
    client, me = _reg(postgres_url, "ssrf@example.com", monkeypatch)
    for base_url in (
        "http://127.0.0.1:9000/v1",
        "http://192.168.1.5/v1",
        "https://user:pass@example.com/v1",
        "ftp://example.com",
    ):
        resp = client.post(
            "/api/v1/model-connections",
            json={"base_url": base_url, "api_key": "sk-canary-x"},
            headers=_headers(_csrf(client)),
        )
        assert resp.status_code == 400, (base_url, resp.text)
        assert resp.json()["code"] == "INVALID_BASE_URL"
    monkeypatch.setenv("RXYCODE_BYOK_ALLOW_PRIVATE", "1")
    ok = client.post(
        "/api/v1/model-connections",
        json={"base_url": "http://127.0.0.1:9/v1", "api_key": "sk-canary-x"},
        headers=_headers(_csrf(client)),
    )
    assert ok.status_code == 201, ok.text


def test_missing_keyring_503_no_row(postgres_url, monkeypatch):
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", "/nonexistent/keyring.json")
    client, me = _reg(postgres_url, "nokeyring@example.com", monkeypatch)
    resp = _create_connection(client)
    assert resp.status_code == 503
    assert resp.json()["code"] == "BYOK_UNAVAILABLE"
    with Session(create_engine(postgres_url)) as db:
        assert db.scalars(select(ModelConnection)).all() == []
    access = client.get("/api/v1/models/access")
    assert access.json()["byok_available"] is False


def test_billable_probe_requires_opt_in(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "bill@example.com", monkeypatch)
    conn_id = _create_connection(client).json()["connection"]["id"]
    refused = client.post(
        f"/api/v1/model-connections/{conn_id}/test",
        json={"model_id": "deepseek-chat"},
        headers=_headers(_csrf(client)),
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "BILLABLE_TEST_NOT_CONFIRMED"

    captured = {}

    def fake_probe(*, api_key, base_url, provider_model_id, **kw):
        captured["api_key"] = api_key
        return {"success": True, "elapsed": 0.2, "transport": "openai_chat"}

    monkeypatch.setattr(_mm(), "probe_model_connection", fake_probe)
    ok = client.post(
        f"/api/v1/model-connections/{conn_id}/test",
        json={"model_id": "deepseek-chat", "allow_billable": True},
        headers=_headers(_csrf(client)),
    )
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    assert ok.json()["test_status"] == "ok"
    assert captured["api_key"] == CANARY
    assert CANARY not in ok.text

    # Free check via /models catalogue — no allow_billable needed.
    def fake_discover(*, api_key, base_url):
        return {"success": True, "elapsed": 0.1, "models": [{"id": "deepseek-chat"}]}

    monkeypatch.setattr(_mm(), "discover_provider_models", fake_discover)
    free = client.post(
        f"/api/v1/model-connections/{conn_id}/test",
        json={},
        headers=_headers(_csrf(client)),
    )
    assert free.status_code == 200
    assert free.json()["success"] is True


def test_access_endpoint_shape(postgres_url, byok_keyring, monkeypatch):
    client, me = _reg(postgres_url, "access@example.com", monkeypatch)
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "1")
    access = client.get("/api/v1/models/access")
    assert access.status_code == 200
    assert access.json() == {
        "require_byok": True,
        "platform_allowed": False,
        "byok_available": True,
        "default_model_ref": None,
    }
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", me["user"]["id"])
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")
    access = client.get("/api/v1/models/access").json()
    assert access["require_byok"] is True
    assert access["platform_allowed"] is False
    models = client.get("/api/v1/models").json()["models"]
    assert all(m["source"] == "byok" for m in models)


def test_legacy_platform_default_is_hidden_on_catalogue_reads(
    postgres_url, byok_keyring, monkeypatch
):
    client, me = _reg(postgres_url, "stale-default@example.com", monkeypatch)
    with Session(create_engine(postgres_url)) as db:
        user = db.get(User, me["user"]["id"])
        user.default_model_ref = "platform"
        db.commit()
    assert client.get("/api/v1/models/access").json()["default_model_ref"] is None
    result = client.get("/api/v1/models").json()
    assert result["models"] == []
    assert result["default_model_ref"] is None
