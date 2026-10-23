"""Worker-side BYOK: per-run gateway resolution, child config, egress vet.

Pure python + PostgreSQL — runs on Windows, no bwrap. Canary keys only.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-server", "rxycode-worker", "rxycode-runner", "rxycode-protocol", "rxycode-core"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.byok.crypto import connection_aad, encrypt  # noqa: E402
from rxycode_server.byok.keyring import generate  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    ModelConnection,
    Organization,
    User,
)
from rxycode_worker import drain  # noqa: E402
from rxycode_worker.egress import EgressProxy, ModelGateway  # noqa: E402

CANARY = "sk-canary-ee55aa66bb77cc88"


@pytest.fixture
def byok_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "byok-keyring.json"
    generate(path)
    monkeypatch.setenv("RXYCODE_BYOK_KEYRING_FILE", str(path))
    monkeypatch.delenv("RXYCODE_BYOK_ALLOW_PRIVATE", raising=False)
    monkeypatch.delenv("RXYCODE_BYOK_ENFORCE", raising=False)
    monkeypatch.delenv("RXYCODE_PLATFORM_MODEL_USERS", raising=False)
    monkeypatch.delenv("RXYCODE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RXYCODE_API_KEY", raising=False)
    return path


def _seed_user(postgres_url: str, tag: str) -> tuple[str, str]:
    """Insert tenant + user rows; return (tenant_id, user_id)."""
    tenant_id = "t-" + uuid.uuid4().hex[:12]
    user_id = "u-" + uuid.uuid4().hex[:12]
    with Session(create_engine(postgres_url)) as db:
        db.add(Organization(id="org-" + tenant_id, tenant_id=tenant_id))
        db.add(User(id=user_id, kind="local"))
        db.commit()
    return tenant_id, user_id


def _insert_connection(
    postgres_url: str,
    tenant_id: str,
    user_id: str,
    *,
    api_key: str = CANARY,
    base_url: str = "https://api.deepseek.com/v1",
    version: int = 1,
    state: str = "active",
    with_key: bool = True,
) -> str:
    conn_id = "mc_" + uuid.uuid4().hex
    kwargs: dict = {}
    if with_key:
        ciphertext, nonce, key_id = encrypt(
            api_key,
            aad=connection_aad(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                connection_id=conn_id,
                credential_version=version,
            ),
        )
        kwargs = {"ciphertext": ciphertext, "nonce": nonce, "key_id": key_id}
    with Session(create_engine(postgres_url)) as db:
        db.add(
            ModelConnection(
                id=conn_id,
                tenant_id=tenant_id,
                owner_user_id=user_id,
                provider_id="deepseek",
                provider_name="DeepSeek",
                display_name="DeepSeek",
                base_url=base_url,
                credential_version=version,
                state=state,
                **kwargs,
            )
        )
        db.commit()
    return conn_id


def _identity(tenant_id: str, user_id: str, snapshot: dict | None) -> dict:
    return {
        "tenant_id": tenant_id,
        "project_id": "p1",
        "actor_id": user_id,
        "traceparent": "",
        "model": snapshot,
    }


def _snap(conn_id: str, version: int = 1, source: str = "byok") -> dict:
    return {
        "model_ref": "m_" + uuid.uuid4().hex,
        "model_id": "deepseek-chat",
        "provider_id": "deepseek",
        "provider_name": "DeepSeek",
        "credential_source": source,
        "connection_id": conn_id,
        "credential_version": version,
    }


def test_resolve_gateway_byok_success(postgres_url, byok_keyring):
    tenant_id, user_id = _seed_user(postgres_url, "a")
    conn_id = _insert_connection(postgres_url, tenant_id, user_id)
    snapshot = _snap(conn_id)
    gateway = drain._resolve_run_gateway(
        postgres_url, "run-1", _identity(tenant_id, user_id, snapshot), snapshot
    )
    assert gateway is not None
    assert gateway.scheme == "https"
    assert gateway.host == "api.deepseek.com"
    assert gateway.port == 443
    assert gateway.base_path == "/v1"
    assert gateway.vet is True
    assert gateway.headers["authorization"] == f"Bearer {CANARY}"
    # The canary only ever lives in parent-side gateway headers.


def test_resolve_gateway_version_mismatch(postgres_url, byok_keyring):
    tenant_id, user_id = _seed_user(postgres_url, "b")
    conn_id = _insert_connection(postgres_url, tenant_id, user_id, version=2)
    snapshot = _snap(conn_id, version=1)  # run pinned v1; stored is v2
    with pytest.raises(drain._CredentialRefused) as err:
        drain._resolve_run_gateway(
            postgres_url, "run-2", _identity(tenant_id, user_id, snapshot), snapshot
        )
    assert err.value.code == "CREDENTIAL_CHANGED"


def test_resolve_gateway_cleared_revoked_deleted(postgres_url, byok_keyring):
    tenant_id, user_id = _seed_user(postgres_url, "c")
    cleared = _insert_connection(postgres_url, tenant_id, user_id, with_key=False)
    revoked = _insert_connection(postgres_url, tenant_id, user_id, state="revoked")
    deleted = _insert_connection(postgres_url, tenant_id, user_id)
    with Session(create_engine(postgres_url)) as db:
        db.delete(db.get(ModelConnection, deleted))
        db.commit()
    for conn_id in (cleared, revoked, deleted):
        snapshot = _snap(conn_id)
        with pytest.raises(drain._CredentialRefused) as err:
            drain._resolve_run_gateway(
                postgres_url,
                "run-x",
                _identity(tenant_id, user_id, snapshot),
                snapshot,
            )
        assert err.value.code == "MODEL_UNAVAILABLE"


def test_platform_not_allowed():
    tenant_id, user_id = "tenant", "actor"
    snapshot = _snap("", source="platform")
    snapshot.update({"model_ref": "platform", "model_id": "deployed"})
    with pytest.raises(drain._CredentialRefused) as err:
        drain._resolve_run_gateway(
            "unused-database-url", "run-3", _identity(tenant_id, user_id, snapshot), snapshot
        )
    assert err.value.code == "PLATFORM_NOT_ALLOWED"


def test_platform_allowlist_cannot_enable_env_gateway(
    monkeypatch,
):
    tenant_id, user_id = "tenant", "actor"
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", user_id)
    monkeypatch.setenv("RXYCODE_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("RXYCODE_API_KEY", "sk-canary-platform")
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")
    monkeypatch.setattr(
        "rxycode_worker.egress.model_gateway_from_env",
        lambda: pytest.fail("platform gateway must not be read or called"),
    )
    snapshot = _snap("", source="platform")
    snapshot.update({"model_ref": "platform", "model_id": "deployed"})
    with pytest.raises(drain._CredentialRefused) as err:
        drain._resolve_run_gateway(
            "unused-database-url", "run-4", _identity(tenant_id, user_id, snapshot), snapshot
        )
    assert err.value.code == "PLATFORM_NOT_ALLOWED"


def test_missing_snapshot_requires_byok_even_when_enforcement_off(
    monkeypatch,
):
    monkeypatch.setenv("RXYCODE_BYOK_ENFORCE", "0")
    monkeypatch.setenv("RXYCODE_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("RXYCODE_API_KEY", "sk-canary-env")
    monkeypatch.setattr(
        "rxycode_worker.egress.model_gateway_from_env",
        lambda: pytest.fail("platform gateway must not be read or called"),
    )
    ident = _identity("tenant", "actor", None)
    with pytest.raises(drain._CredentialRefused) as err:
        drain._resolve_run_gateway("unused-database-url", "run-5", ident, None)
    assert err.value.code == "BYOK_REQUIRED"


def test_run_identity_reads_snapshot(postgres_url, byok_keyring):
    """_run_identity surfaces the persisted snapshot columns for a real run."""
    tenant_id, user_id = _seed_user(postgres_url, "g")
    conn_id = _insert_connection(postgres_url, tenant_id, user_id)
    snapshot = _snap(conn_id)
    from rxycode_server.runs.service import create_run

    with Session(create_engine(postgres_url)) as db:
        from rxycode_server.persistence.models import Project, SessionRow

        db.add(Project(id="p1", tenant_id=tenant_id, name="p1", repo_config={}))
        db.add(
            SessionRow(id="s1", tenant_id=tenant_id, project_id="p1", title="t")
        )
        db.commit()
    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id="s1",
        message="hi",
        target_id=f"cloud:{tenant_id}:p1",
        permission_profile="confirm",
        request_id="req-" + uuid.uuid4().hex[:16],
        user_id=user_id,
        model_snapshot=snapshot,
        request_model_ref=snapshot["model_ref"],
    )
    identity = drain._run_identity(postgres_url, accepted.run_id)
    assert identity["model"]["connection_id"] == conn_id
    assert identity["model"]["credential_source"] == "byok"
    assert identity["model"]["model_id"] == "deepseek-chat"


def test_child_config_override_no_secret(tmp_path):
    source = {
        "active_model": "deployed",
        "models": {
            "deployed": {
                "model_name": "deployed",
                "api_key": "sk-canary-hostkey-must-not-leak",
                "base_url": "https://upstream.example/v1",
            }
        },
        "safety": {"enabled": True},
    }
    override = {
        "model_id": "deepseek-chat",
        "provider_id": "deepseek",
        "provider_name": "DeepSeek",
        "api_transport": "",
        "max_tokens": 4096,
    }
    child = drain._build_child_config(
        source,
        workdir=tmp_path / "ws",
        egress_port=18881,
        env_model="deployed",
        model_override=override,
    )
    assert child["active_model"] == "deepseek/deepseek-chat"
    entry = child["models"]["deepseek/deepseek-chat"]
    assert entry["model_name"] == "deepseek-chat"
    assert entry["api_key"] == "confined"
    assert entry["base_url"] == "http://127.0.0.1:18881"
    assert entry["max_tokens"] == 4096
    dumped = yaml.safe_dump(child)
    assert "confined" in dumped
    assert "sk-canary" not in dumped
    assert "upstream.example" not in dumped


def test_prepare_child_dir_writes_config_without_source(
    tmp_path, monkeypatch
):
    """A BYOK run gets a config even with no host RXYCODE_DATA_DIR."""
    monkeypatch.delenv("RXYCODE_DATA_DIR", raising=False)
    conf = drain._prepare_child_data_dir(
        tmp_path / "conf",
        workdir=tmp_path / "ws",
        model_override={
            "model_id": "deepseek-chat",
            "provider_id": "deepseek",
            "provider_name": "DeepSeek",
        },
    )
    data = yaml.safe_load((conf / "config.yaml").read_text(encoding="utf-8"))
    assert data["active_model"] == "deepseek/deepseek-chat"
    entry = data["models"]["deepseek/deepseek-chat"]
    assert entry["api_key"] == "confined"
    assert entry["base_url"].startswith("http://127.0.0.1:")


class _Reader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _Writer:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def can_write_eof(self) -> bool:
        return True

    def write_eof(self) -> None:
        pass


def _drive_gateway(gateway: ModelGateway, monkeypatch, allow_private: bool):
    """Run one child request through _gateway_serve against a mock upstream."""
    captured: dict[str, bytes] = {}

    async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        head = await reader.readuntil(b"\r\n\r\n")
        captured["head"] = head
        captured["body"] = await reader.read(2)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    async def scenario() -> bytes:
        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        gateway.port = port
        proxy = EgressProxy(Path("unused.sock"), set(), gateway=gateway)
        child_reader = _Reader(
            [b"hi"]
        )
        child_writer = _Writer()
        await proxy._gateway_serve(
            child_reader,
            child_writer,
            "POST",
            "/chat/completions",
            ["Authorization: Bearer confined", "Content-Length: 2"],
        )
        server.close()
        await server.wait_closed()
        return b"".join(child_writer.written)

    if allow_private:
        monkeypatch.setenv("RXYCODE_BYOK_ALLOW_PRIVATE", "1")
    else:
        monkeypatch.delenv("RXYCODE_BYOK_ALLOW_PRIVATE", raising=False)
    response = asyncio.run(scenario())
    return response, captured


def test_gateway_vet_refuses_private_upstream(tmp_path, monkeypatch):
    gateway = ModelGateway(
        scheme="http",
        host="127.0.0.1",
        port=1,  # replaced by _drive_gateway with the real mock port
        base_path="/v1",
        headers={"authorization": f"Bearer {CANARY}"},
        vet=True,
    )
    response, captured = _drive_gateway(gateway, monkeypatch, allow_private=False)
    assert b"403" in response
    assert "head" not in captured  # upstream was never contacted


def test_gateway_injects_canary_never_child_placeholder(tmp_path, monkeypatch):
    gateway = ModelGateway(
        scheme="http",
        host="127.0.0.1",
        port=1,
        base_path="/v1",
        headers={"authorization": f"Bearer {CANARY}"},
        vet=True,
    )
    response, captured = _drive_gateway(gateway, monkeypatch, allow_private=True)
    assert b"200" in response
    head = captured["head"].decode("iso-8859-1")
    assert f"authorization: Bearer {CANARY}" in head
    assert "confined" not in head
    assert captured["body"] == b"hi"
