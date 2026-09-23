"""Headless `rxycode config add-model` must work without a TUI."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from RxyCode.RxyCode1_1_0 import main
from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config


def test_config_help_advertises_add_model_and_base_url():
    result = CliRunner().invoke(main.cli, ["config", "--help"])
    assert result.exit_code == 0, result.output
    assert "add-model" in result.output
    assert "--base-url" in result.output
    assert "RXYCODE_API_KEY" in result.output


def test_empty_config_error_points_at_real_add_model_command():
    with pytest.raises(ValueError, match="rxycode config add-model") as exc:
        get_active_model_config({"models": {}, "active_model": ""})
    assert "RXYCODE_API_KEY" in str(exc.value)
    assert "python -m RxyCode config add-model" not in str(exc.value)


def test_add_model_requires_base_url_and_env_key(monkeypatch, tmp_path):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("RXYCODE_API_KEY", raising=False)

    missing_url = CliRunner().invoke(
        main.cli, ["config", "add-model", "zen-mimo", "mimo-v2.5"]
    )
    assert missing_url.exit_code != 0
    assert "--base-url" in missing_url.output

    monkeypatch.setenv("RXYCODE_API_KEY", "")
    missing_key = CliRunner().invoke(
        main.cli,
        [
            "config",
            "add-model",
            "zen-mimo",
            "mimo-v2.5",
            "--base-url",
            "https://opencode.ai/zen/v1",
        ],
    )
    assert missing_key.exit_code != 0
    assert "RXYCODE_API_KEY" in missing_key.output


def test_add_model_writes_isolated_config_without_echoing_key(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data))
    monkeypatch.setenv("RXYCODE_API_KEY", "sk-test-not-a-real-key")

    result = CliRunner().invoke(
        main.cli,
        [
            "config",
            "add-model",
            "zen-mimo",
            "mimo-v2.5",
            "--base-url",
            "https://opencode.ai/zen/v1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Added zen-mimo" in result.output
    assert "sk-test-not-a-real-key" not in result.output

    cfg_text = (data / "config.yaml").read_text(encoding="utf-8")
    assert "mimo-v2.5" in cfg_text
    assert "https://opencode.ai/zen/v1" in cfg_text
    assert "sk-test-not-a-real-key" not in cfg_text
    assert "zen-mimo" in cfg_text
