"""Recent-model history contracts: real switch history, not a template list.

``/model`` renders a 最近常用 group from this data, so it must track actual
``set_active_model`` calls and never outlive the models it points at.
"""

from copy import deepcopy


def _in_memory_config(monkeypatch, model_manager, cfg):
    """Route load_config/save_config through a dict (no config.yaml on disk)."""
    state = {"cfg": deepcopy(cfg)}

    monkeypatch.setattr(model_manager, "load_config", lambda: deepcopy(state["cfg"]))
    monkeypatch.setattr(
        model_manager,
        "save_config",
        lambda new_cfg: state.__setitem__("cfg", deepcopy(new_cfg)),
    )
    return state


def _cfg(*names, active=None, recent=None):
    return {
        "models": {name: {"base_url": "https://provider.example/v1"} for name in names},
        "active_model": active or (names[0] if names else None),
        **({"recent_models": list(recent)} if recent is not None else {}),
    }


def test_switching_records_history_most_recent_first(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, _cfg("alpha", "beta", "gamma"))

    assert model_manager.set_active_model("alpha") is True
    assert model_manager.set_active_model("beta") is True
    assert model_manager.set_active_model("gamma") is True

    assert state["cfg"]["recent_models"] == ["gamma", "beta", "alpha"]
    assert state["cfg"]["active_model"] == "gamma"


def test_reswitching_moves_an_entry_to_the_front_without_duplicating(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(
        monkeypatch, model_manager, _cfg("alpha", "beta", recent=["beta", "alpha"])
    )

    model_manager.set_active_model("alpha")

    assert state["cfg"]["recent_models"] == ["alpha", "beta"]


def test_history_is_capped(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    names = [f"model-{i}" for i in range(model_manager.RECENT_MODELS_LIMIT + 3)]
    state = _in_memory_config(monkeypatch, model_manager, _cfg(*names))

    for name in names:
        model_manager.set_active_model(name)

    history = state["cfg"]["recent_models"]
    assert len(history) == model_manager.RECENT_MODELS_LIMIT
    assert history[0] == names[-1]


def test_failed_switch_records_nothing(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(monkeypatch, model_manager, _cfg("alpha", recent=["alpha"]))

    assert model_manager.set_active_model("does-not-exist") is False
    assert state["cfg"]["recent_models"] == ["alpha"]


def test_removing_a_model_drops_it_from_history(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    state = _in_memory_config(
        monkeypatch, model_manager, _cfg("alpha", "beta", recent=["beta", "alpha"])
    )
    monkeypatch.setattr(model_manager, "delete_credential", lambda *_a, **_k: None)

    assert model_manager.remove_model("beta") is True
    assert state["cfg"]["recent_models"] == ["alpha"]


def test_history_reads_skip_stale_and_malformed_entries(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _in_memory_config(
        monkeypatch,
        model_manager,
        _cfg("alpha", recent=["alpha", "deleted-model", None, 42]),
    )

    assert model_manager.list_recent_models() == ["alpha"]


def test_history_reads_tolerate_a_missing_or_malformed_key(monkeypatch):
    from RxyCode.RxyCode1_1_0.config import model_manager

    _in_memory_config(monkeypatch, model_manager, _cfg("alpha"))
    assert model_manager.list_recent_models() == []

    _in_memory_config(
        monkeypatch, model_manager, {"models": {"alpha": {}}, "recent_models": "not-a-list"}
    )
    assert model_manager.list_recent_models() == []
