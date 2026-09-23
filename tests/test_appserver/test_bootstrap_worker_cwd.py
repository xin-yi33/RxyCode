"""RL2: bootstrap_agent must not change the process working directory."""

from __future__ import annotations

import os
import types


def _install_bootstrap_fakes(monkeypatch) -> None:
    import sys

    class FakeSettings:
        @staticmethod
        def load_config():
            return {"language": "en"}

    class FakeI18n:
        @staticmethod
        def set_lang(_value):
            return None

    class FakeAgent:
        def __init__(self, model_name=None, session_id=None):
            self.model_name = model_name
            self.session_id = session_id

    monkeypatch.setitem(
        sys.modules, "config.settings", types.SimpleNamespace(load_config=FakeSettings.load_config)
    )
    monkeypatch.setitem(sys.modules, "utils.i18n", types.SimpleNamespace(i18n=FakeI18n()))
    monkeypatch.setitem(sys.modules, "core.agent_v2", types.SimpleNamespace(AgentV2=FakeAgent))


def test_bootstrap_stub_does_not_change_cwd(tmp_path):
    from appserver.bootstrap import bootstrap_agent

    before = os.getcwd()
    bootstrap_agent(stub=True, workspace_root=tmp_path)
    assert os.getcwd() == before


def test_bootstrap_real_path_does_not_change_cwd(monkeypatch, tmp_path):
    from appserver.bootstrap import bootstrap_agent

    _install_bootstrap_fakes(monkeypatch)
    before = os.getcwd()
    bootstrap_agent(stub=False, workspace_root=tmp_path)
    assert os.getcwd() == before
