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
    assert result["added"] == ["deepseek-chat", "deepseek-reasoner"]
    assert result["skipped"] == []
    assert result["active"] == "deepseek-reasoner"
    assert "deepseek-chat" in state["cfg"]["models"]
    assert state["cfg"]["models"]["deepseek-chat"]["provider_name"] == "DeepSeek"
    assert state["cfg"]["active_model"] == "deepseek-reasoner"


def test_onboard_models_batch_skips_existing_ids(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _state = _in_memory_config(
        monkeypatch,
        model_manager,
        {
            "models": {
                "deepseek-chat": {
                    "base_url": "https://api.deepseek.com/v1",
                    "model_name": "deepseek-chat",
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

    assert result["added"] == ["deepseek-reasoner"]
    assert result["skipped"] == ["deepseek-chat"]
    assert result["active"] == "deepseek-reasoner"


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
