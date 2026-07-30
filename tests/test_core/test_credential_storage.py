from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml


def _opaque_value(label: str) -> str:
    return "opaque-" + label + "-credential-value"


def _assert_windows_acl_has_no_inheritance(path: Path) -> None:
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
        return
    result = subprocess.run(
        ["icacls", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "(I)" not in result.stdout


def test_model_credential_roundtrip_keeps_plaintext_out_of_both_files(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config.model_manager import add_model
    from RxyCode.RxyCode1_1_0.config.settings import get_model_config

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    credential = _opaque_value("roundtrip")

    stored = add_model(
        "local-name",
        credential,
        "https://provider.invalid/v1",
        model_name="provider-name",
    )

    config_path = tmp_path / "config.yaml"
    secret_path = tmp_path / "credentials.yaml"
    assert "api_key" not in stored
    assert "api_key_secret" in stored
    assert credential not in config_path.read_text(encoding="utf-8")
    assert credential not in secret_path.read_text(encoding="utf-8")
    assert get_model_config("local-name")["api_key"] == credential
    _assert_windows_acl_has_no_inheritance(config_path)
    _assert_windows_acl_has_no_inheritance(secret_path)


def test_load_migrates_legacy_inline_credential_atomically(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.config.settings import get_model_config, load_config

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    credential = _opaque_value("legacy")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "legacy": {
                        "api_key": credential,
                        "base_url": "https://provider.invalid/v1",
                        "model_name": "provider-name",
                    }
                },
                "active_model": "legacy",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config()

    entry = loaded["models"]["legacy"]
    assert "api_key" not in entry
    assert "api_key_secret" in entry
    assert credential not in config_path.read_text(encoding="utf-8")
    assert get_model_config("legacy", loaded)["api_key"] == credential
    assert not list(tmp_path.glob(".config.yaml.*.tmp"))
    _assert_windows_acl_has_no_inheritance(config_path)


def test_matching_environment_credential_never_creates_secret_file(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config.model_manager import add_model

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    credential = _opaque_value("environment")
    monkeypatch.setenv("RXYCODE_TEST_API_KEY", credential)

    stored = add_model(
        "environment-model",
        credential,
        "https://provider.invalid/v1",
    )

    assert stored["api_key_env"] == "RXYCODE_TEST_API_KEY"
    assert "api_key_secret" not in stored
    assert not (tmp_path / "credentials.yaml").exists()


def test_save_config_strips_inline_credential_without_mutating_caller(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    credential = _opaque_value("direct-save")
    supplied = {"models": {"m": {"api_key": credential}}, "active_model": "m"}

    save_config(supplied)
    loaded = load_config()

    assert supplied["models"]["m"]["api_key"] == credential
    assert "api_key" not in loaded["models"]["m"]
    assert credential not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_save_failure_removes_newly_created_credential(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.config import settings

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    credential = _opaque_value("rollback")
    supplied = {"models": {"m": {"api_key": credential}}, "active_model": "m"}

    def fail_write(path, cfg):
        raise OSError("injected config write failure")

    monkeypatch.setattr(settings, "_write_config", fail_write)
    with pytest.raises(OSError, match="injected config write failure"):
        settings.save_config(supplied)

    secret_document = yaml.safe_load(
        (tmp_path / "credentials.yaml").read_text(encoding="utf-8")
    )
    assert secret_document["credentials"] == {}


def test_atomic_write_replaces_from_same_directory_and_cleans_temporary_file(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config import credential_store

    destination = tmp_path / "config.yaml"
    replacements: list[tuple[Path, Path]] = []
    real_replace = credential_store.os.replace

    def observed_replace(source, target):
        replacements.append((Path(source), Path(target)))
        return real_replace(source, target)

    monkeypatch.setattr(credential_store.os, "replace", observed_replace)
    credential_store.atomic_write_text(destination, "models: {}\n")

    assert replacements
    source, target = replacements[-1]
    assert source.parent == destination.parent
    assert target == destination
    assert destination.read_text(encoding="utf-8") == "models: {}\n"
    assert not source.exists()
    _assert_windows_acl_has_no_inheritance(destination)


def test_atomic_write_failure_preserves_previous_file_and_cleans_temporary(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config import credential_store

    destination = tmp_path / "config.yaml"
    credential_store.atomic_write_text(destination, "before: true\n")

    def fail_replace(source, target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(credential_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        credential_store.atomic_write_text(destination, "after: true\n")

    assert destination.read_text(encoding="utf-8") == "before: true\n"
    assert not list(tmp_path.glob(".config.yaml.*.tmp"))


def test_replacing_model_removes_previous_credential(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.config.credential_store import load_credential
    from RxyCode.RxyCode1_1_0.config.model_manager import add_model
    from RxyCode.RxyCode1_1_0.config.settings import get_config_path

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    first = add_model(
        "replace-me", _opaque_value("first"), "https://provider.invalid/v1"
    )
    second = add_model(
        "replace-me", _opaque_value("second"), "https://provider.invalid/v1"
    )

    with pytest.raises(ValueError, match="unavailable"):
        load_credential(first["api_key_secret"], get_config_path())
    assert load_credential(second["api_key_secret"], get_config_path()) == _opaque_value(
        "second"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL contract")
def test_windows_permission_command_uses_only_trusted_principals(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.config import credential_store

    path = tmp_path / "config.yaml"
    path.write_text("{}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        credential_store, "_windows_current_sid", lambda: "S-1-5-21-1-2-3-1001"
    )

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(credential_store.subprocess, "run", fake_run)
    credential_store.restrict_file_permissions(path)

    command = calls[-1]
    assert "/inheritance:r" in command
    assert "/grant:r" in command
    assert "*S-1-5-21-1-2-3-1001:(F)" in command
    assert "*S-1-5-18:(F)" in command
    assert "*S-1-5-32-544:(F)" in command
