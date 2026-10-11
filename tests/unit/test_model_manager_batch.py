"""Batch onboard and provider metadata on add_model."""

import threading
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


def test_onboard_batch_writes_config_and_credentials_once(monkeypatch):
    """20 and 100 models are validated once, then committed in one config save."""
    from RxyCode.RxyCode1_1_0.config import model_manager

    for count in (20, 100):
        state = {"cfg": {"models": {}}}
        loads = 0
        saves = 0
        credential_writes = 0

        def load(state=state):
            nonlocal loads
            loads += 1
            return deepcopy(state["cfg"])

        def save(new_cfg, state=state):
            nonlocal saves
            saves += 1
            state["cfg"] = deepcopy(new_cfg)

        def store_one(value, path):
            nonlocal credential_writes
            credential_writes += 1
            return f"secret:{credential_writes}:{value}"

        def store_many(values, path):
            nonlocal credential_writes
            credential_writes += 1
            return [f"secret:{index}:{value}" for index, value in enumerate(values)]

        monkeypatch.setattr(model_manager, "load_config", load)
        monkeypatch.setattr(model_manager, "save_config", save)
        monkeypatch.setattr(model_manager, "store_credential", store_one)
        if hasattr(model_manager, "store_credentials"):
            monkeypatch.setattr(model_manager, "store_credentials", store_many)
        monkeypatch.setattr(model_manager, "delete_credential", lambda *args, **kwargs: None)

        ids = [f"model-{index}" for index in range(count)]
        ids.append(ids[0])
        result = model_manager.onboard_models_batch(
            api_key="sk-batch",
            base_url="https://api.deepseek.com/v1",
            model_ids=ids,
            provider_id="deepseek",
            provider_name="DeepSeek",
            skip_probe=True,
        )

        assert len(result["added"]) == count
        assert result["skipped"] == ["deepseek/model-0"]
        assert loads <= 2
        assert saves == 1
        assert credential_writes == 1
        assert len(state["cfg"]["models"]) == count
        secrets = [entry["api_key_secret"] for entry in state["cfg"]["models"].values()]
        assert len(secrets) == len(set(secrets))


def test_onboard_batch_rolls_back_credentials_when_save_fails(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = {
        "cfg": {
            "models": {"other/kept": {"api_key_secret": "already-there", "model_name": "kept"}},
            "theme": "kept-setting",
        }
    }
    deleted: list[str] = []

    monkeypatch.setattr(model_manager, "load_config", lambda: deepcopy(state["cfg"]))

    def save(_new_cfg):
        raise RuntimeError("disk full")

    monkeypatch.setattr(model_manager, "save_config", save)
    monkeypatch.setattr(
        model_manager,
        "store_credential",
        lambda value, path: f"secret:{value}",
    )
    if hasattr(model_manager, "store_credentials"):
        monkeypatch.setattr(
            model_manager,
            "store_credentials",
            lambda values, path: [f"secret:{index}" for index in range(len(values))],
        )

    def delete(reference, path):
        deleted.append(reference)

    monkeypatch.setattr(model_manager, "delete_credential", delete)
    if hasattr(model_manager, "delete_credentials"):
        monkeypatch.setattr(
            model_manager,
            "delete_credentials",
            lambda references, path: deleted.extend(references),
        )

    try:
        model_manager.onboard_models_batch(
            api_key="sk-batch",
            base_url="https://api.deepseek.com/v1",
            model_ids=["model-a", "model-b"],
            provider_id="deepseek",
            provider_name="DeepSeek",
            skip_probe=True,
        )
    except RuntimeError as exc:
        assert "disk full" in str(exc)
    else:
        raise AssertionError("save failure must surface")

    assert state["cfg"]["theme"] == "kept-setting"
    assert state["cfg"]["models"]["other/kept"]["api_key_secret"] == "already-there"
    assert "already-there" not in deleted
    assert deleted


def test_batch_commit_keeps_changes_made_during_probe(monkeypatch):
    """A connection check must not freeze the config that is later saved."""
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = {"cfg": {"models": {}, "theme": "initial"}}

    monkeypatch.setattr(model_manager, "load_config", lambda: deepcopy(state["cfg"]))
    monkeypatch.setattr(
        model_manager,
        "save_config",
        lambda new_cfg: state.__setitem__("cfg", deepcopy(new_cfg)),
    )
    monkeypatch.setattr(model_manager, "delete_credential", lambda *args, **kwargs: None)
    monkeypatch.setattr(model_manager, "delete_credentials", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        model_manager,
        "store_credentials",
        lambda values, path: [f"new-{index}" for index in range(len(values))],
    )

    def probe(**_kwargs):
        state["cfg"]["theme"] = "changed-by-user"
        state["cfg"]["models"]["other/kept"] = {"model_name": "kept", "api_key_secret": "old-ref"}
        return {"success": True}

    monkeypatch.setattr(model_manager, "probe_model_connection", probe)
    result = model_manager.onboard_models_batch(
        api_key="env:AUDIT_FAKE_API_KEY",
        base_url="https://api.deepseek.com/v1",
        model_ids=["batch-model"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        skip_probe=False,
    )

    assert "deepseek/batch-model" in result["added"]
    assert "other/kept" in state["cfg"]["models"]
    assert state["cfg"]["models"]["other/kept"]["api_key_secret"] == "old-ref"
    assert state["cfg"]["theme"] == "changed-by-user"


def test_two_batches_keep_both_new_models(monkeypatch, tmp_path):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = {"cfg": {"models": {}, "theme": "shared"}}
    monkeypatch.setattr(model_manager, "get_config_path", lambda: tmp_path / "config.yaml")
    barrier = threading.Barrier(2)

    def load():
        snap = deepcopy(state["cfg"])
        try:
            barrier.wait(timeout=0.3)
        except threading.BrokenBarrierError:
            pass
        return snap

    def save(new_cfg):
        state["cfg"] = deepcopy(new_cfg)

    monkeypatch.setattr(model_manager, "load_config", load)
    monkeypatch.setattr(model_manager, "save_config", save)
    monkeypatch.setattr(model_manager, "delete_credential", lambda *args, **kwargs: None)
    monkeypatch.setattr(model_manager, "delete_credentials", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        model_manager,
        "store_credentials",
        lambda values, path: [f"ref-{values[0]}-{index}" for index in range(len(values))],
    )

    errors: list[BaseException] = []

    def run(model_id: str, provider: str):
        try:
            model_manager.onboard_models_batch(
                api_key=f"sk-{provider}",
                base_url="https://api.deepseek.com/v1" if provider == "deepseek" else "https://opencode.ai/zen/go/v1",
                model_ids=[model_id],
                provider_id=provider,
                provider_name=provider,
                skip_probe=True,
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=("left", "deepseek"))
    second = threading.Thread(target=run, args=("right", "opencode-go"))
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)
    assert not errors
    assert not first.is_alive() and not second.is_alive()
    assert "deepseek/left" in state["cfg"]["models"]
    assert "opencode-go/right" in state["cfg"]["models"]
    assert state["cfg"]["theme"] == "shared"


def test_commit_does_not_overwrite_model_added_before_save(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = {"cfg": {"models": {}, "theme": "kept-setting"}}
    deleted: list[str] = []
    monkeypatch.setattr(model_manager, "load_config", lambda: deepcopy(state["cfg"]))
    monkeypatch.setattr(
        model_manager,
        "save_config",
        lambda new_cfg: state.__setitem__("cfg", deepcopy(new_cfg)),
    )

    def store_many(values, path):
        state["cfg"]["models"]["deepseek/model-0"] = {
            "model_name": "model-0",
            "provider_id": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_secret": "already",
        }
        return ["new-ref" for _value in values]

    monkeypatch.setattr(model_manager, "store_credentials", store_many)
    monkeypatch.setattr(model_manager, "delete_credentials", lambda refs, path: deleted.extend(refs))
    result = model_manager.onboard_models_batch(
        api_key="sk-batch",
        base_url="https://api.deepseek.com/v1",
        model_ids=["model-0"],
        provider_id="deepseek",
        provider_name="DeepSeek",
        skip_probe=True,
    )
    assert result["added"] == []
    assert "deepseek/model-0" in result["skipped"]
    assert state["cfg"]["models"]["deepseek/model-0"]["api_key_secret"] == "already"
    assert state["cfg"]["theme"] == "kept-setting"
    assert "new-ref" in deleted
    assert "already" not in deleted


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
