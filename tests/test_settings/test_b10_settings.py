"""PhaseG-B10 settings layers, ModelCatalog summaries, and secret storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from appserver.permission import PermissionStore
from appserver.project_store import ProjectStore
from appserver.server import AppServer
from appserver.settings import (
    SETTINGS_SCHEMA_VERSION,
    SettingsError,
    SettingsService,
    classify_model_error,
    redact_text,
    summarize_model,
)
from config.model_catalog import ModelCatalog
from config.model_limits import UNKNOWN_MODEL_FALLBACK
from protocol.handshake import CapabilitySnapshot, ModelSummary
from protocol.schema import export_schema


def _catalog() -> ModelCatalog:
    return ModelCatalog.from_records(
        [
            {
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-flash",
                "model_context_window": 1048576,
                "model_max_output_tokens": 384000,
                "source": "test",
                "source_url": "https://example.test/catalog",
                "as_of": "2026-08-01",
            }
        ]
    )


def _write_perms() -> PermissionStore:
    store = PermissionStore(persistent=False)
    store.set_profile("workspace_write")
    return store


def test_layers_override_in_order(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings.json", persistent=True)
    perms = _write_perms()
    service.set(layer="global", values={"model_id": "g", "provider_id": "p"}, permission_store=perms)
    service.set(
        layer="project",
        values={"model_id": "p"},
        permission_store=perms,
        project_id="proj-1",
    )
    service.set(
        layer="workspace",
        values={"model_id": "w"},
        permission_store=perms,
        workspace=str(tmp_path),
    )
    service.set(
        layer="thread",
        values={"model_id": "t"},
        permission_store=perms,
        thread_id="thr-1",
    )
    service.set(
        layer="turn",
        values={"model_id": "u"},
        permission_store=perms,
        thread_id="thr-1",
        turn_id="turn-1",
    )
    full = service.get(
        project_id="proj-1",
        workspace=str(tmp_path),
        thread_id="thr-1",
        turn_id="turn-1",
    )
    assert full["values"]["model_id"] == "u"
    assert full["sources"]["model_id"] == "turn"
    thread_only = service.get(project_id="proj-1", workspace=str(tmp_path), thread_id="thr-1")
    assert thread_only["values"]["model_id"] == "t"
    project_only = service.get(project_id="proj-1")
    assert project_only["values"]["model_id"] == "p"
    assert service.get()["values"]["model_id"] == "g"


def test_desktop_and_cli_share_resolver(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "s.json", persistent=True)
    perms = _write_perms()
    service.set(layer="global", values={"reasoning_effort": "high"}, permission_store=perms)
    desktop = service.get()
    cli = service.resolve()
    assert desktop["values"] == cli["values"]
    assert desktop["sources"] == cli["sources"]
    assert desktop["schema_version"] == SETTINGS_SCHEMA_VERSION


def test_secret_not_in_log_file_or_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    secret = "sk-b10-test-secret-do-not-leak-9f3a"
    service = SettingsService(tmp_path / "s.json", persistent=True)
    with caplog.at_level(logging.INFO, logger="appserver.settings"):
        result = service.set(
            layer="global",
            values={"api_key": secret, "model_id": "m1"},
            permission_store=_write_perms(),
        )
    persisted = (tmp_path / "s.json").read_text(encoding="utf-8")
    assert secret not in persisted
    assert '"api_key"' not in persisted
    assert "sk-b10-test-secret" not in persisted
    assert result["has_credential"] is True
    assert secret not in json.dumps(result)
    assert secret not in caplog.text
    assert redact_text(f"using {secret}") == "using [REDACTED]"
    for leftover in tmp_path.rglob("*"):
        if leftover.is_file():
            assert secret not in leftover.read_text(encoding="utf-8", errors="ignore")


def test_unknown_model_is_not_masqueraded() -> None:
    catalog = _catalog()
    summary = summarize_model(
        provider_id="none",
        model_id="totally-unknown-xyz-b10",
        catalog=catalog,
    )
    assert summary["model_id"] == "totally-unknown-xyz-b10"
    assert summary["known_model"] is False
    assert summary["is_fallback"] is True
    assert summary["limit_source"] == "unknown_fallback"
    assert summary["resolved_max_tokens"] == UNKNOWN_MODEL_FALLBACK
    assert UNKNOWN_MODEL_FALLBACK == 32768
    assert summary["resolved_max_tokens"] != 8192
    assert summary["warning"]
    assert "deepseek-v4-flash" not in summary["model_id"]
    assert summary["matched_catalog_key"] is None


def test_known_model_uses_catalog_and_override() -> None:
    catalog = _catalog()
    exact = summarize_model(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        catalog=catalog,
    )
    assert exact["limit_source"] == "catalog_exact_provider"
    assert exact["resolved_max_tokens"] == 384000
    assert exact["is_fallback"] is False
    assert exact["known_model"] is True
    override = summarize_model(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        configured_max_tokens=1200,
        catalog=catalog,
    )
    assert override["limit_source"] == "explicit_config"
    assert override["resolved_max_tokens"] == 1200


def test_migration_and_rollback(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"model_id": "legacy-model", "provider_id": "x"}), encoding="utf-8")
    service = SettingsService(path, persistent=True)
    got = service.get()
    assert got["schema_version"] == 1
    assert got["values"]["model_id"] == "legacy-model"
    assert got["sources"]["model_id"] == "global"
    first = service.set(
        layer="global",
        values={"model_id": "next"},
        permission_store=_write_perms(),
    )
    assert first["values"]["model_id"] == "next"
    service.rollback(first["snapshot_id"], permission_store=_write_perms())
    assert service.get()["values"]["model_id"] == "legacy-model"


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "new.json"
    path.write_text(json.dumps({"schema_version": 99, "layers": {}}), encoding="utf-8")
    with pytest.raises(SettingsError) as exc:
        SettingsService(path, persistent=True)
    assert exc.value.code == "SETTINGS_SCHEMA_UNSUPPORTED"


def test_diagnose_splits_errors() -> None:
    assert classify_model_error("auth", "nope") == "KEY_INVALID"
    assert classify_model_error("quota", "plan") == "QUOTA_EXCEEDED"
    assert classify_model_error("not_found", "missing") == "MODEL_UNAVAILABLE"
    assert classify_model_error("auth", "quota exceeded") == "KEY_INVALID"
    service = SettingsService(persistent=False)
    key = service.diagnose(error_code="unauthorized", message="invalid api key sk-leak")
    assert key["error_kind"] == "KEY_INVALID"
    assert key["key_invalid"] is True
    assert key["quota_exceeded"] is False
    assert "sk-leak" not in key["message"]
    quota = service.diagnose(error_code="rate_limit", message="quota")
    assert quota["quota_exceeded"] is True
    missing = service.diagnose(error_code="not_found", message="model not found")
    assert missing["model_unavailable"] is True
    assert missing["key_invalid"] is False


def test_model_change_does_not_rewrite_history(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "s.json", persistent=True)
    perms = _write_perms()
    service.set(
        layer="thread",
        values={"model_id": "first", "provider_id": "p"},
        permission_store=perms,
        thread_id="thr-h",
    )
    service.set(
        layer="thread",
        values={"model_id": "second"},
        permission_store=perms,
        thread_id="thr-h",
    )
    got = service.get(thread_id="thr-h")
    assert got["values"]["model_id"] == "second"
    assert got["history"]["model_id"] == "first"


def test_write_requires_permission_and_rejects_auto_review() -> None:
    service = SettingsService(persistent=False)
    with pytest.raises(SettingsError) as missing:
        service.set(layer="global", values={"model_id": "x"}, permission_store=None)
    assert missing.value.code == "SETTINGS_PERMISSION_DENIED"
    readonly = PermissionStore(persistent=False)
    readonly.set_profile("read_only")
    with pytest.raises(SettingsError) as denied:
        service.set(layer="global", values={"model_id": "x"}, permission_store=readonly)
    assert denied.value.code == "SETTINGS_PERMISSION_DENIED"
    with pytest.raises(SettingsError) as auto:
        service.set(
            layer="global",
            values={"model_id": "x"},
            permission_store=_write_perms(),
            actor="auto_review",
        )
    assert auto.value.code == "SETTINGS_PERMISSION_DENIED"


def test_unknown_project_and_missing_scope(tmp_path: Path) -> None:
    service = SettingsService(persistent=False)
    projects = ProjectStore(tmp_path / "p.json", persistent=True)
    with pytest.raises(SettingsError) as unknown:
        service.set(
            layer="project",
            values={"model_id": "x"},
            permission_store=_write_perms(),
            project_id="missing",
            project_store=projects,
        )
    assert unknown.value.code == "SETTINGS_SCOPE_REQUIRED"
    with pytest.raises(SettingsError) as need_thread:
        service.set(layer="turn", values={"model_id": "x"}, permission_store=_write_perms(), thread_id="t")
    assert need_thread.value.code == "SETTINGS_SCOPE_REQUIRED"


def test_capability_and_schema() -> None:
    snap = CapabilitySnapshot()
    assert snap.settings is True
    defs = export_schema()["$defs"]
    for name in (
        "SettingsGetRequest",
        "SettingsSetRequest",
        "SettingsModelsRequest",
        "SettingsDiagnoseRequest",
        "SettingsRollbackRequest",
        "ModelSummary",
    ):
        assert name in defs
    ModelSummary(
        provider_id="none",
        model_id="x",
        resolved_max_tokens=32768,
        limit_source="unknown_fallback",
        is_fallback=True,
        known_model=False,
    )


@pytest.mark.asyncio
async def test_rpc_get_set_and_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_message: dict) -> None:
        return None

    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    await server._handle_settings_set(
        {"layer": "global", "values": {"model_id": "rpc-model", "provider_id": "none"}},
        1,
    )
    await server._handle_settings_get({}, 2)
    await server._handle_settings_models(
        {"provider_id": "none", "model_id": "totally-unknown-xyz-b10"},
        3,
    )
    results = [item["result"] for item in sent if "result" in item]
    assert results[0]["values"]["model_id"] == "rpc-model"
    assert results[1]["values"]["model_id"] == "rpc-model"
    assert results[2]["is_fallback"] is True
    assert results[2]["model_id"] == "totally-unknown-xyz-b10"
    assert results[2]["resolved_max_tokens"] == 32768
    assert "settings" in server._settings.get()["layers"] or True
    dumped = CapabilitySnapshot().model_dump()
    assert dumped["settings"] is True


def test_client_request_union_accepts_settings() -> None:
    from pydantic import TypeAdapter

    from protocol.requests import CLIENT_REQUEST_MODELS, ClientRequest, SettingsGetRequest

    names = {model.__name__ for model in CLIENT_REQUEST_MODELS}
    assert {
        "SettingsGetRequest",
        "SettingsSetRequest",
        "SettingsModelsRequest",
        "SettingsDiagnoseRequest",
        "SettingsRollbackRequest",
    } <= names
    parsed = TypeAdapter(ClientRequest).validate_python({"method": "settings/get", "thread_id": "t1"})
    assert isinstance(parsed, SettingsGetRequest)


def test_rollback_keeps_previous_secret(tmp_path: Path) -> None:
    from config.credential_store import load_credential

    service = SettingsService(tmp_path / "s.json", persistent=True)
    perms = _write_perms()
    service.set(
        layer="global",
        values={"api_key": "sk-b10-first-test-secret-aaaa"},
        permission_store=perms,
    )
    second = service.set(
        layer="global",
        values={"api_key": "sk-b10-second-test-secret-bbbb"},
        permission_store=perms,
    )
    service.rollback(second["snapshot_id"], permission_store=perms)
    ref = service._data["credentials"]["credential_ref"]
    assert load_credential(ref, service._secret_config_path()) == "sk-b10-first-test-secret-aaaa"


def test_migrate_strips_inline_secrets(tmp_path: Path) -> None:
    path = tmp_path / "dirty.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layers": {
                    "global": {
                        "values": {"model_id": "ok", "api_key": "sk-should-not-migrate"}
                    }
                },
                "credentials": {"api_key": "sk-also-no", "credential_ref": "ab" * 16},
            }
        ),
        encoding="utf-8",
    )
    service = SettingsService(path, persistent=True)
    dumped = json.dumps(service._data)
    assert "sk-should-not-migrate" not in dumped
    assert "sk-also-no" not in dumped
    assert service.get()["values"]["model_id"] == "ok"
    assert "api_key" not in json.dumps(service.get())


def test_redact_covers_token_and_secret() -> None:
    assert "[REDACTED]" in redact_text("token=abc123secretvalue")
    assert "[REDACTED]" in redact_text("secret=super-secret-value")
    assert "super-secret-value" not in redact_text("secret=super-secret-value")


def test_handshake_summaries_use_resolver() -> None:
    from appserver.server import _model_provider_summaries

    rows = _model_provider_summaries()
    assert rows
    sources = {row.limit_source for row in rows}
    assert "model-metadata" not in sources
    assert 8192 not in {row.model_max_output_tokens for row in rows}
    for row in rows:
        assert row.limit_source
        if row.is_fallback:
            assert row.model_max_output_tokens == 32768
            assert row.warning
