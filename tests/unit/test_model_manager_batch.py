"""Batch onboard and provider metadata on add_model."""

from copy import deepcopy
from unittest.mock import MagicMock, patch


def _in_memory_config(monkeypatch, model_manager, cfg):
    state = {"cfg": deepcopy(cfg)}

    monkeypatch.setattr(model_manager, "load_config", lambda: deepcopy(state["cfg"]))
    monkeypatch.setattr(
        model_manager,
        "save_config",
        lambda new_cfg: state.__setitem__("cfg", deepcopy(new_cfg)),
    )
    monkeypatch.setattr(
        model_manager,
        "store_credential",
        lambda value, path: f"secret:{value}",
    )
    monkeypatch.setattr(model_manager, "delete_credential", lambda *args, **kwargs: None)
    return state


def test_add_model_persists_provider_metadata(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})

    model_manager.add_model(
        "deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        provider_id="deepseek",
        provider_name="DeepSeek",
    )

    entry = state["cfg"]["models"]["deepseek-chat"]
    assert entry["provider_id"] == "deepseek"
    assert entry["provider_name"] == "DeepSeek"


def test_onboard_models_batch_skips_probe_and_adds_multiple(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    probe = MagicMock(return_value={"success": True, "elapsed": 0.1})
    monkeypatch.setattr(model_manager, "probe_model_connection", probe)

    result = model_manager.onboard_models_batch(
        api_key="sk-batch",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-chat", "deepseek-reasoner"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        active_model_id="deepseek-reasoner",
        skip_probe=True,
    )

    probe.assert_not_called()
    assert result["added"] == ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"]
    assert result["skipped"] == []
    assert result["active"] == "deepseek/deepseek-reasoner"
    assert "deepseek/deepseek-chat" in state["cfg"]["models"]
    assert state["cfg"]["models"]["deepseek/deepseek-chat"]["provider_name"] == "DeepSeek"
    assert state["cfg"]["active_model"] == "deepseek/deepseek-reasoner"


def test_onboard_models_batch_skips_existing_ids(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _state = _in_memory_config(
        monkeypatch,
        model_manager,
        {
            "models": {
                "deepseek/deepseek-chat": {
                    "base_url": "https://api.deepseek.com/v1",
                    "model_name": "deepseek-chat",
                    "provider_id": "deepseek",
                    "provider_name": "DeepSeek",
                }
            }
        },
    )

    result = model_manager.onboard_models_batch(
        api_key="sk-batch",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-chat", "deepseek-reasoner"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        skip_probe=True,
    )

    assert result["added"] == ["deepseek/deepseek-reasoner"]
    assert result["skipped"] == ["deepseek/deepseek-chat"]
    assert result["active"] == "deepseek/deepseek-reasoner"


def test_onboard_models_batch_empty_ids_persists_nothing(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})

    result = model_manager.onboard_models_batch(
        api_key="sk-batch",
        base_url="https://api.deepseek.com/v1",
        model_ids=[],
        skip_probe=True,
    )

    assert result["added"] == []
    assert result["skipped"] == []
    assert result["active"] is None
    assert state["cfg"]["models"] == {}


def test_onboard_models_batch_namespaces_keys_by_provider(monkeypatch):
    """Same vendor model id under two providers must not collide."""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})

    first = model_manager.onboard_models_batch(
        api_key="sk-a",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-v4-flash"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        active_model_id="deepseek-v4-flash",
        skip_probe=True,
    )
    second = model_manager.onboard_models_batch(
        api_key="sk-b",
        base_url="https://opencode.ai/zen/go/v1",
        model_ids=["deepseek-v4-flash"],
        provider_id="opencode-go",
        provider_name="OpenCode Go",
        active_model_id="deepseek-v4-flash",
        skip_probe=True,
    )

    assert first["added"] == ["deepseek/deepseek-v4-flash"]
    assert second["added"] == ["opencode-go/deepseek-v4-flash"]
    assert "deepseek/deepseek-v4-flash" in state["cfg"]["models"]
    assert "opencode-go/deepseek-v4-flash" in state["cfg"]["models"]
    assert (
        state["cfg"]["models"]["deepseek/deepseek-v4-flash"]["model_name"]
        == "deepseek-v4-flash"
    )
    assert (
        state["cfg"]["models"]["opencode-go/deepseek-v4-flash"]["provider_name"]
        == "OpenCode Go"
    )


def test_infer_provider_group_from_url():
    from RxyCode.RxyCode1_1_0.config import model_manager

    deepseek = model_manager.infer_provider_group("https://api.deepseek.com/v1")
    assert deepseek["id"] == "deepseek"
    assert deepseek["name"] == "DeepSeek"

    opencode = model_manager.infer_provider_group("https://opencode.ai/zen/go/v1")
    assert opencode["id"] == "opencode-go"
    assert opencode["name"] == "OpenCode Go"

    zen = model_manager.infer_provider_group("https://opencode.ai/zen/v1")
    assert zen["id"] == "zen"
    assert zen["name"] == "OpenCode Zen"

    unknown = model_manager.infer_provider_group("https://custom.example.com/v1")
    assert unknown["id"] == "custom-custom-example-com"
    assert unknown["name"] == "custom.example.com"


def test_onboard_models_batch_allows_same_id_on_different_endpoint(monkeypatch):
    """Legacy bare key on OpenCode must not block DeepSeek official namespaced add."""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(
        monkeypatch,
        model_manager,
        {
            "models": {
                "deepseek-v4-flash": {
                    "base_url": "https://opencode.ai/zen/go/v1",
                    "model_name": "deepseek-v4-flash",
                }
            }
        },
    )

    result = model_manager.onboard_models_batch(
        api_key="sk-official",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-v4-flash", "deepseek-chat"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        active_model_id="deepseek-v4-flash",
        skip_probe=True,
    )

    assert "deepseek/deepseek-v4-flash" in result["added"]
    assert "deepseek/deepseek-chat" in result["added"]
    assert "deepseek-v4-flash" in state["cfg"]["models"]
    assert "deepseek/deepseek-v4-flash" in state["cfg"]["models"]


def test_ensure_models_provider_metadata_stamps_from_url(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(
        monkeypatch,
        model_manager,
        {
            "models": {
                "deepseek-v4-flash": {
                    "base_url": "https://opencode.ai/zen/go/v1",
                    "model_name": "deepseek-v4-flash",
                }
            }
        },
    )
    model_manager.ensure_models_provider_metadata()
    entry = state["cfg"]["models"]["deepseek-v4-flash"]
    assert entry["provider_id"] == "opencode-go"
    assert entry["provider_name"] == "OpenCode Go"


def test_add_model_defaults_max_tokens_auto_not_8192(monkeypatch):
    """M5：新增模型默认 max_tokens='auto'，不再写入固定 8192。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.add_model(
        "deepseek-v4-flash",
        "sk-test",
        "https://api.deepseek.com/v1",
        model_name="deepseek-v4-flash",
        provider_id="deepseek",
        provider_name="DeepSeek",
    )
    entry = state["cfg"]["models"]["deepseek-v4-flash"]
    assert entry["max_tokens"] == "auto"


def test_add_model_explicit_max_tokens_preserved(monkeypatch):
    """M5：用户显式 max_tokens 正整数 → 保持为显式覆盖。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.add_model(
        "custom/manual",
        "sk-test",
        "https://api.example.com/v1",
        model_name="manual",
        max_tokens=4096,
    )
    entry = state["cfg"]["models"]["custom/manual"]
    assert entry["max_tokens"] == 4096


def test_batch_onboard_writes_auto_not_fixed_default(monkeypatch):
    """M5：批量添加不把统一数字抄进每个模型。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.onboard_models_batch(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model_ids=["deepseek-v4-flash", "deepseek-v4-pro"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        active_model_id="deepseek-v4-flash",
        skip_probe=True,
    )
    flash = state["cfg"]["models"]["deepseek/deepseek-v4-flash"]
    pro = state["cfg"]["models"]["deepseek/deepseek-v4-pro"]
    assert flash["max_tokens"] == "auto"
    assert pro["max_tokens"] == "auto"
    assert flash["max_tokens"] == pro["max_tokens"]  # 都是 auto，不是同数字


def test_add_model_rejects_invalid_max_tokens(monkeypatch):
    """M5：0/负数/空串/浮点/布尔 → 拒绝。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    _in_memory_config(monkeypatch, model_manager, {"models": {}})
    for bad in (0, -5, 1.5, "", "yes", True):
        try:
            model_manager.add_model(
                f"m-{type(bad).__name__}",
                "sk-test",
                "https://api.example.com/v1",
                model_name="m",
                max_tokens=bad,
            )
            raise AssertionError(f"should have rejected max_tokens={bad!r}")
        except ValueError:
            pass


def test_add_model_duplicate_same_provider_fails_closed(monkeypatch):
    """M5.5：同一 Provider + 同一 model_name（不同 key）→ 拒绝，不静默覆盖。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.add_model(
        "deepseek/deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        provider_id="deepseek",
    )
    # 用裸 key 再添加同一 vendor id → 拒绝
    try:
        model_manager.add_model(
            "deepseek-chat",
            "sk-other",
            "https://api.deepseek.com/v1",
            model_name="deepseek-chat",
            provider_id="deepseek",
        )
        raise AssertionError("duplicate same-provider model should be rejected")
    except ValueError:
        pass
    # 原配置保持不变
    assert "deepseek/deepseek-chat" in state["cfg"]["models"]
    assert "deepseek-chat" not in state["cfg"]["models"]


def test_add_model_same_key_update_allowed(monkeypatch):
    """M5.5：同 key 重新添加（更新）是允许的，不误判为冲突。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.add_model(
        "deepseek/deepseek-chat",
        "sk-a",
        "https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        provider_id="deepseek",
    )
    model_manager.add_model(
        "deepseek/deepseek-chat",
        "sk-b",
        "https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        provider_id="deepseek",
        max_tokens=4096,
    )
    entry = state["cfg"]["models"]["deepseek/deepseek-chat"]
    assert entry["max_tokens"] == 4096


def test_add_model_cross_provider_same_model_ok(monkeypatch):
    """M5.5：不同 Provider 同名模型可共存。"""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, {"models": {}})
    model_manager.add_model(
        "deepseek/deepseek-chat",
        "sk-a",
        "https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        provider_id="deepseek",
    )
    model_manager.add_model(
        "other/deepseek-chat",
        "sk-b",
        "https://other.example/v1",
        model_name="deepseek-chat",
        provider_id="other",
    )
    assert "deepseek/deepseek-chat" in state["cfg"]["models"]
    assert "other/deepseek-chat" in state["cfg"]["models"]
