"""Worker bootstrap must bind AgentV2 memory to the REAL session id.

Regression tests for the 2026-09-23 fix: bootstrap_agent used to construct
AgentV2 without session_id, so MemoryManager stayed on the shared "latest"
compatibility bucket -> restart amnesia + cross-window context leaks.
"""

from __future__ import annotations

import sys
import types


def _fake_bootstrap_env(monkeypatch, captured):
    class FakeSettings:
        @staticmethod
        def load_config():
            return {"language": "en"}

    class FakeI18n:
        @staticmethod
        def set_lang(_value):
            return None

    class FakeAgentClass:
        def __init__(self, model_name=None, session_id=None):
            captured["model_name"] = model_name
            captured["session_id"] = session_id
            self._memory = None
            self._session_loaded = False

    fake_settings_module = types.SimpleNamespace(load_config=FakeSettings.load_config)
    fake_i18n_module = types.SimpleNamespace(i18n=FakeI18n())
    fake_agent_module = types.SimpleNamespace(AgentV2=FakeAgentClass)
    for name in (
        "config.settings",
        "RxyCode.RxyCode1_1_0.config.settings",
        "utils.i18n",
        "RxyCode.RxyCode1_1_0.utils.i18n",
    ):
        monkeypatch.setitem(
            sys.modules,
            name,
            fake_settings_module if name.endswith("settings") else fake_i18n_module,
        )
    monkeypatch.setitem(sys.modules, "core.agent_v2", fake_agent_module)
    monkeypatch.setitem(sys.modules, "RxyCode.RxyCode1_1_0.core.agent_v2", fake_agent_module)
    return FakeAgentClass


def test_bootstrap_agent_binds_real_session_id(monkeypatch, tmp_path):
    from appserver import bootstrap

    captured: dict = {}
    fake_cls = _fake_bootstrap_env(monkeypatch, captured)

    agent = bootstrap.bootstrap_agent(
        stub=False,
        workspace_root=tmp_path,
        model_name=None,
        session_id="ses-window-a",
    )

    assert isinstance(agent, fake_cls)
    assert captured["session_id"] == "ses-window-a"


def test_bootstrap_agent_without_session_id_keeps_latest_default(monkeypatch, tmp_path):
    """In-process/library callers that pass no session_id keep legacy behavior."""
    from appserver import bootstrap

    captured: dict = {}
    _fake_bootstrap_env(monkeypatch, captured)

    bootstrap.bootstrap_agent(stub=False, workspace_root=tmp_path, model_name=None)

    assert captured["session_id"] is None


def test_configure_agent_workspace_prefers_set_session(tmp_path, monkeypatch):
    """configure_agent_workspace must rebind memory, not just the attribute."""
    from appserver.agent_worker import configure_agent_workspace

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    calls: list[str] = []

    class FakeAgent:
        _session_id = "latest"

        def set_session(self, session_id: str) -> str:
            calls.append(session_id)
            self._session_id = session_id
            return session_id

    agent = FakeAgent()
    configure_agent_workspace(agent, session_id="ses-real-9", workspace_root=workspace)

    assert calls == ["ses-real-9"]
    assert agent._session_id == "ses-real-9"


def test_configure_agent_workspace_falls_back_for_stub(tmp_path, monkeypatch):
    """Stub-like agents without set_session still get the attribute binding."""
    from types import SimpleNamespace

    from appserver.agent_worker import configure_agent_workspace

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    agent = SimpleNamespace(_session_id="latest")
    configure_agent_workspace(agent, session_id="ses-stub-1", workspace_root=workspace)

    assert agent._session_id == "ses-stub-1"
