from __future__ import annotations

from types import SimpleNamespace

from appserver.agent_worker import configure_agent_workspace
from RxyCode.RxyCode1_1_0.core.session_runtime import (
    bind_session,
    current_working_directory,
    reset_session_binding,
)


def test_configure_agent_workspace_binds_session_scoped_working_directory(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))

    agent = SimpleNamespace(_session_id="latest")
    configured = configure_agent_workspace(
        agent,
        session_id="desktop-session-123",
        workspace_root=workspace,
    )

    assert configured is agent
    assert agent._session_id == "desktop-session-123"
    assert agent._workspace_root == workspace.resolve()

    token = bind_session("desktop-session-123")
    try:
        assert current_working_directory() == workspace.resolve()
    finally:
        reset_session_binding(token)


def test_agent_worker_bind_core_session_reuses_runtimes(tmp_path):
    """Live session/prompt must keep Session.agent_runtimes across warmup→H3."""
    from appserver.agent_worker import AgentWorker

    worker = AgentWorker()
    first = worker.bind_core_session("ses-live", tmp_path, lambda _n: None)
    first.agent_runtimes["architect"] = "kept"
    second = worker.bind_core_session("ses-live", tmp_path, lambda _n: None)
    assert second is first
    assert second.agent_runtimes["architect"] == "kept"
