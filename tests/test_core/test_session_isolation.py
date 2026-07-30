"""Logical-session isolation and durable reset tests."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "session_id",
    ["../escape", "..", "C:\\outside", "has space", "", "a" * 65],
)
def test_session_ids_reject_path_traversal_and_unsafe_names(session_id):
    from RxyCode.RxyCode1_1_0.memory.long_term import validate_session_id

    with pytest.raises(ValueError, match="session_id"):
        validate_session_id(session_id)


def test_memory_and_experience_retrieval_are_isolated_by_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    first = MemoryManager(session_id="session-a")
    first.add_interaction("private question", "private answer")
    first.save_session()
    asyncio.run(first.store_execution(
        "session-a",
        "task-a",
        "private PostgreSQL migration result",
    ))

    second = MemoryManager(session_id="session-b")
    second.load_session()

    assert second.short_term.message_count == 0
    assert "private answer" not in second.get_context_for_prompt("PostgreSQL")
    assert "private PostgreSQL" not in second.get_retrieval_context("migration")
    assert "private PostgreSQL" in first.get_retrieval_context("migration")


def test_agent_reset_removes_session_memory_experience_and_checkpoints(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    memory = MemoryManager(session_id="session-a")
    memory.add_interaction("secret", "answer")
    memory.save_session()
    asyncio.run(memory.store_execution("session-a", "task", "verified secret"))
    store = CheckpointStore(tmp_path / "checkpoints")
    store.save(
        "session-a",
        "request",
        "build",
        {"session_id": "session-a", "user_input": "request", "phase": "planning"},
    )
    agent = object.__new__(AgentV2)
    agent._session_id = "session-a"
    agent._memory = memory
    agent._checkpoint_store = store
    agent._session_loaded = True

    result = agent.reset_session()

    assert result["checkpoints"] == 1
    assert memory.long_term.load_history() == []
    assert memory.experience.search("secret", session="session-a") == []
    assert store.list(session_id="session-a") == []
    assert agent._session_loaded is False


def test_api_request_models_validate_and_carry_session_id():
    from RxyCode.RxyCode1_1_0.api_server import ChatRequest, CommandRequest

    assert ChatRequest(message="hello", session_id="team-1").session_id == "team-1"
    assert CommandRequest(command="/clear", session_id="team-1").session_id == "team-1"
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", session_id="../escape")


def test_api_history_namespaces_do_not_share_messages():
    from RxyCode.RxyCode1_1_0 import api_server

    class Agent:
        def __init__(self):
            self.sessions = []

        def set_session(self, session_id):
            self.sessions.append(session_id)

    previous = dict(api_server._state)
    agent = Agent()
    try:
        api_server._state["chat_history"] = []
        api_server._state["chat_histories"] = {}
        first = api_server._activate_session(agent, "session-a")
        first.append({"role": "user", "content": "private-a"})
        second = api_server._activate_session(agent, "session-b")

        assert second == []
        assert api_server._activate_session(agent, "session-a") == first
        assert agent.sessions == ["session-a", "session-b", "session-a"]
    finally:
        api_server._state.clear()
        api_server._state.update(previous)
