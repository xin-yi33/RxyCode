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

    unknown = model_manager.infer_provider_group("https://custom.example.com/v1")
    assert unknown["id"] == "custom"
    assert unknown["name"] == "其他"


def test_provider_presets_include_opencode_go_under_other():
    from RxyCode.RxyCode1_1_0.config import model_manager

    presets = {p["id"]: p for p in model_manager.list_provider_presets()}
    go = presets["opencode-go"]
    assert go["name"] == "OpenCode Go"
    assert go["base_url"] == "https://opencode.ai/zen/go/v1"
    assert go["category"] == "其他"
