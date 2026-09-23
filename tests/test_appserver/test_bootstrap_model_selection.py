"""A cold worker must bootstrap with the task's model, not the old global active model."""

from pathlib import Path


def test_bootstrap_agent_forwards_task_model(monkeypatch, tmp_path):
    from appserver import bootstrap

    captured = {}

    class FakeAgent:
        pass

    class FakeSettings:
        @staticmethod
        def load_config():
            return {"language": "en"}

    class FakeI18n:
        @staticmethod
        def set_lang(_value):
            return None

    import sys
    import types

    fake_settings_module = types.SimpleNamespace(load_config=FakeSettings.load_config)
    fake_i18n_module = types.SimpleNamespace(i18n=FakeI18n())
    fake_agent_module = types.SimpleNamespace(AgentV2=None)

    class FakeAgentClass:
        def __init__(self, model_name=None, session_id=None):
            captured["model_name"] = model_name
            captured["session_id"] = session_id

    fake_agent_module.AgentV2 = FakeAgentClass
    for name in (
        "config.settings",
        "RxyCode.RxyCode1_1_0.config.settings",
        "utils.i18n",
        "RxyCode.RxyCode1_1_0.utils.i18n",
    ):
        monkeypatch.setitem(sys.modules, name, fake_settings_module if name.endswith("settings") else fake_i18n_module)
    monkeypatch.setitem(sys.modules, "core.agent_v2", fake_agent_module)
    monkeypatch.setitem(sys.modules, "RxyCode.RxyCode1_1_0.core.agent_v2", fake_agent_module)
    result = bootstrap.bootstrap_agent(
        stub=False,
        workspace_root=tmp_path,
        model_name="deepseek/deepseek-v4-flash",
        session_id="ses-real-123",
    )

    assert isinstance(result, FakeAgentClass)
    assert captured["model_name"] == "deepseek/deepseek-v4-flash"
    assert captured["session_id"] == "ses-real-123"
