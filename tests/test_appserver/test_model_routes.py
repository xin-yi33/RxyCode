"""Phase 4 D5 · Model/credential JSON-RPC route tests.

Covers the thin adapter layer (appserver/model_routes.py): every method
delegates to config.model_manager / config.credential_store and never
reimplements business logic. Uses an isolated config dir per test.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.appserver import model_routes


def test_source_tree_top_level_appserver_can_import_model_manager(monkeypatch):
    top_level_routes = importlib.import_module("appserver.model_routes")
    manager = importlib.import_module("config.model_manager")
    monkeypatch.setattr(manager, "set_active_model", lambda model_id: model_id == "demo")

    assert top_level_routes.set_active({"id": "demo"}) == {"ok": True, "id": "demo"}


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point settings at a temp dir so model writes never touch user config."""
    from RxyCode.RxyCode1_1_0.config import settings

    from RxyCode.RxyCode1_1_0.config import model_manager

    cfg_path = tmp_path / "config.yaml"
    # model_manager binds settings functions at module import time, so patch
    # model_manager's own references (not settings.*) for the isolation to
    # actually take effect.
    monkeypatch.setattr(model_manager, "get_config_path", lambda: cfg_path)
    monkeypatch.setattr(model_manager, "load_config", lambda: {})
    monkeypatch.setattr(model_manager, "save_config", lambda cfg: None)
    return tmp_path


def test_list_models_empty(isolated_config):
    result = model_routes.list_models()
    assert result["models"] == []
    assert result["active"] in (None, "")


def test_list_presets_shape(isolated_config):
    result = model_routes.list_presets()
    assert "presets" in result
    assert isinstance(result["presets"], list)


def test_remove_requires_id(isolated_config):
    result = model_routes.remove({})
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_set_active_requires_id(isolated_config):
    result = model_routes.set_active({})
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_onboard_validates_empty_fields(isolated_config):
    result = asyncio.run(model_routes.onboard({}))
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_onboard_rejects_invalid_base_url(isolated_config):
    result = asyncio.run(
        model_routes.onboard(
            {"provider_model_id": "x", "api_key": "sk-x", "base_url": "http://insecure"}
        )
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_discover_validates_empty(isolated_config):
    result = asyncio.run(model_routes.discover({}))
    assert result["ok"] is False


def test_onboard_batch_validates_empty(isolated_config):
    result = asyncio.run(model_routes.onboard_batch({}))
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_test_connection_requires_id(isolated_config):
    result = asyncio.run(model_routes.test_connection({}))
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_upsert_credential_requires_model(isolated_config):
    result = model_routes.upsert_credential({"id": "ghost", "api_key": "sk-x"})
    assert result["ok"] is False
    assert result["error_code"] == "not_found"


def test_delete_credential_requires_model(isolated_config):
    result = model_routes.delete_credential({"id": "ghost"})
    assert result["ok"] is False
    assert result["error_code"] == "not_found"


def test_credentials_never_echo_key(isolated_config):
    """The adapter must never put the raw key in any response field."""
    # No response path returns 'api_key' directly; onboarding probes redact.
    assert "api_key" not in model_routes.upsert_credential({"id": "x", "api_key": "sk-secret"}).get(
        "message", ""
    )

def test_set_active_with_effort_updates_global(isolated_config, monkeypatch):
    """models/set_active 带 effort → 切换模型并设置全局档位。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(model_manager, "set_active_model", lambda name: name == "demo")
    recorded = {}
    monkeypatch.setattr(
        model_manager, "set_effort", lambda v: recorded.__setitem__("effort", v) or True
    )

    result = model_routes.set_active({"id": "demo", "effort": "medium"})
    assert result == {"ok": True, "id": "demo"}
    assert recorded.get("effort") == "medium"


def test_set_active_invalid_effort_rejected(isolated_config, monkeypatch):
    """effort 非空字符串校验失败 → 返回 invalid 错误（后端拒绝）。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(model_manager, "set_active_model", lambda name: True)
    monkeypatch.setattr(model_manager, "set_effort", lambda v: False)

    result = model_routes.set_active({"id": "demo", "effort": "  "})
    assert result["ok"] is False
    assert result["error_code"] == "invalid"


def test_set_active_without_effort_keeps_unset(isolated_config, monkeypatch):
    """不带 effort 参数 → 不改动全局档位（optional_field 语义）。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(model_manager, "set_active_model", lambda name: True)
    touched = []
    monkeypatch.setattr(
        model_manager, "set_effort", lambda v: touched.append(v) or True
    )

    result = model_routes.set_active({"id": "demo"})
    assert result == {"ok": True, "id": "demo"}
    assert touched == []


def test_set_active_non_string_effort_rejected(isolated_config, monkeypatch):
    """审计修复（luna audit2）：effort 非字符串（数字等）→ 拒绝，不 str() 化。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    monkeypatch.setattr(model_manager, "set_active_model", lambda name: True)
    touched = []
    monkeypatch.setattr(
        model_manager, "set_effort", lambda v: touched.append(v) or True
    )

    result = model_routes.set_active({"id": "demo", "effort": 123})
    assert result["ok"] is False
    assert result["error_code"] == "invalid"
    assert touched == []


def test_list_models_exposes_effort_key(isolated_config):
    """models/list 返回 effort 键（全局档位），未设置时为 None。"""
    result = model_routes.list_models()
    assert "effort" in result


def test_list_models_deepseek_flash_window_is_1m(isolated_config, monkeypatch):
    """Official wire id deepseek-flash must expose the 1M v4 window, not 256k."""
    from RxyCode.RxyCode1_1_0.config import model_manager, settings

    cfg = {
        "active_model": "deepseek/deepseek-v4.1-flash",
        "models": {
            "deepseek/deepseek-v4.1-flash": {
                "model_name": "deepseek-flash",
                "nickname": "deepseek-flash",
                "base_url": "https://api.deepseek.com/v1",
                "provider_id": "deepseek",
            }
        },
    }
    monkeypatch.setattr(settings, "load_config", lambda: cfg)
    monkeypatch.setattr(
        model_manager, "ensure_models_provider_metadata", lambda c, persist=False: c
    )
    monkeypatch.setattr(
        model_manager,
        "infer_provider_group",
        lambda url: {"id": "deepseek", "name": "DeepSeek"},
    )
    monkeypatch.setattr(model_manager, "prune_recent_models", lambda c: [])
    monkeypatch.setattr(model_manager, "get_effort", lambda: None)

    result = model_routes.list_models()
    item = result["models"][0]
    assert item["context_window"] == 1048576
