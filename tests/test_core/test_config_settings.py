"""
Tests for config/settings.py - Configuration management.

Covers: load/save, defaults, model config, MCP config, scheduler config.
"""
import os
import yaml
import pytest
from pathlib import Path


class TestGetConfigDir:
    def test_uses_env_var(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = get_data_dir()
        assert result == tmp_path

    def test_creates_dir_if_not_exists(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
        new_dir = tmp_path / "newconfig"
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(new_dir))
        result = get_data_dir()
        assert result.exists()

    def test_default_dir(self, monkeypatch, tmp_path):
        import RxyCode.RxyCode1_1_0.config.settings as settings

        monkeypatch.delenv("RXYCODE_DATA_DIR", raising=False)
        monkeypatch.setattr(settings.Path, "home", lambda: tmp_path)
        monkeypatch.setattr(settings, "DEFAULT_CONFIG_DIR", tmp_path / ".RxyCode")
        result = settings.get_data_dir()
        assert result == tmp_path / ".RxyCode"


class TestGetConfigPath:
    def test_returns_config_yaml(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import get_config_path
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = get_config_path()
        assert result.name == "config.yaml"
        assert result.parent == tmp_path


class TestGetOutputDir:
    def test_default_output_dir(self, tmp_path, monkeypatch):
        from datetime import datetime
        from RxyCode.RxyCode1_1_0.config.settings import get_output_dir

        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        result = get_output_dir()
        assert result.name == datetime.now().strftime("%Y-%m-%d")
        assert result.parent == tmp_path / "output"

    def test_uses_env_var(self, tmp_path, monkeypatch):
        from datetime import datetime
        from RxyCode.RxyCode1_1_0.config.settings import get_output_dir

        custom = tmp_path / "custom_output"
        monkeypatch.setenv("RXYCODE_OUTPUT_DIR", str(custom))
        result = get_output_dir()
        assert result == custom / datetime.now().strftime("%Y-%m-%d")
        assert result.exists()


class TestLoadConfig:
    def test_load_nonexistent_creates_default(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import load_config
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cfg = load_config()
        assert "models" in cfg
        assert "active_model" in cfg
        assert "language" in cfg
        assert "cache" in cfg

    def test_load_existing_config(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import load_config, get_config_path
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        # Write a custom config
        cfg_path = get_config_path()
        custom = {"models": {"m1": {"model_name": "test"}}, "active_model": "m1"}
        cfg_path.write_text(yaml.dump(custom), encoding="utf-8")
        loaded = load_config()
        assert loaded["active_model"] == "m1"
        assert "m1" in loaded["models"]

    def test_load_empty_yaml(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import (
            _default_config,
            get_config_path,
            load_config,
        )
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        cfg_path = get_config_path()
        cfg_path.write_text("", encoding="utf-8")
        loaded = load_config()
        # Empty YAML is treated as partial config and inherits defaults.
        assert loaded == _default_config()


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import save_config, load_config
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        custom = {"key": "value", "nested": {"a": 1}}
        save_config(custom)
        loaded = load_config()
        assert loaded["key"] == "value"
        assert loaded["nested"]["a"] == 1

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import save_config
        deep_dir = tmp_path / "a" / "b"
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(deep_dir))
        save_config({"test": True})
        assert (deep_dir / "config.yaml").exists()

    def test_save_unicode_values(self, tmp_path, monkeypatch):
        from RxyCode.RxyCode1_1_0.config.settings import save_config, load_config
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        save_config({"name": "你好世界"})
        loaded = load_config()
        assert loaded["name"] == "你好世界"


class TestDefaultConfig:
    def test_has_models(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert "models" in cfg
        assert cfg["models"] == {}

    def test_has_active_model(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert cfg["active_model"] is None

    def test_has_language(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert cfg["language"] == "zh"

    def test_has_memory_config(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert "memory" in cfg
        assert "short_term_window" in cfg["memory"]
        assert cfg["memory"]["long_term_threshold"] <= (
            cfg["memory"]["short_term_window"] * 2
        )

    def test_has_cache_config(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert cfg["cache"]["enabled"] is True
        assert cfg["cache"]["prompt_prefix_cache"] is True
        assert cfg["cache"]["ttl"] == 3600

    def test_has_mcp_servers(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert "mcpServers" in cfg

    def test_has_scheduler(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert cfg["scheduler"]["enabled"] is True
        assert cfg["scheduler"]["check_interval"] == 30

    def test_has_auto_compact(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config
        cfg = _default_config()
        assert cfg["autoCompact"] is True

    def test_execution_limits_are_enabled_by_default(self):
        from RxyCode.RxyCode1_1_0.config.settings import _default_config

        cfg = _default_config()

        execution = cfg["execution"]
        assert execution["sandbox_mode"] == "workspace"
        assert execution["tool_timeout_seconds"] > 600
        assert execution["task_max_time_seconds"] > 600
        assert execution["task_stall_timeout_seconds"] == 0
        assert execution["max_memory_mb"] > 0
        assert execution["max_processes"] > 0


class TestGetMcpConfig:
    def test_empty_config(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_mcp_config
        result = get_mcp_config({"mcpServers": {}})
        assert result == {}

    def test_with_servers(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_mcp_config
        cfg = {"mcpServers": {"server1": {"command": "node"}}}
        result = get_mcp_config(cfg)
        assert "server1" in result

    def test_missing_key(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_mcp_config
        result = get_mcp_config({})
        assert result == {}


class TestGetSchedulerConfig:
    def test_default(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_scheduler_config
        result = get_scheduler_config({})
        assert result["enabled"] is True
        assert result["check_interval"] == 30

    def test_custom(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_scheduler_config
        cfg = {"scheduler": {"enabled": False, "check_interval": 60}}
        result = get_scheduler_config(cfg)
        assert result["enabled"] is False
        assert result["check_interval"] == 60


class TestGetActiveModelConfig:
    def test_returns_active_model(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config
        cfg = {
            "active_model": "m1",
            "models": {"m1": {"model_name": "gpt-4"}, "m2": {"model_name": "claude"}},
        }
        result = get_active_model_config(cfg)
        assert result["model_name"] == "gpt-4"

    def test_no_active_returns_first(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config
        cfg = {"active_model": None, "models": {"m1": {"model_name": "gpt-4"}}}
        result = get_active_model_config(cfg)
        assert result["model_name"] == "gpt-4"

    def test_no_models_raises(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config
        with pytest.raises(ValueError):
            get_active_model_config({"active_model": None, "models": {}})

    def test_active_not_in_models_returns_first(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_active_model_config
        cfg = {"active_model": "nonexistent", "models": {"m1": {"model_name": "gpt-4"}}}
        result = get_active_model_config(cfg)
        assert result["model_name"] == "gpt-4"


class TestGetModelConfig:
    def test_returns_model(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_model_config
        cfg = {"models": {"m1": {"model_name": "gpt-4"}}}
        result = get_model_config("m1", cfg)
        assert result["model_name"] == "gpt-4"

    def test_not_found_raises(self):
        from RxyCode.RxyCode1_1_0.config.settings import get_model_config
        with pytest.raises(ValueError):
            get_model_config("nonexistent", {"models": {}})

    def test_environment_credential_reference_is_resolved_without_mutating_config(
        self, monkeypatch
    ):
        from RxyCode.RxyCode1_1_0.config.settings import get_model_config

        monkeypatch.setenv("RXYCODE_TEST_PROVIDER_KEY", "runtime-secret-value")
        stored = {
            "model_name": "test-model",
            "api_key_env": "RXYCODE_TEST_PROVIDER_KEY",
        }
        cfg = {"models": {"m1": stored}}

        result = get_model_config("m1", cfg)

        assert result["api_key"] == "runtime-secret-value"
        assert "api_key" not in stored
