"""Eval tasks must not share the default ``latest`` memory session."""

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

from evals.backends import bind_eval_session


def test_bind_eval_session_rebinds_memory_manager(isolated_runtime) -> None:
    agent = object.__new__(AgentV2)
    agent._session_id = "latest"
    agent._active_task = None
    agent._llm = None
    agent._rag_indexer_thread = None
    agent._session_loaded = True
    agent._agent_prefix_messages = ["stale"]
    agent._subset_tool_names = ["write"]
    agent._memory = MemoryManager(session_id="latest", llm=None)
    bind_eval_session(agent, "eval-safety-test-1")
    assert agent._session_id == "eval-safety-test-1"
    assert agent._memory.session_id == "eval-safety-test-1"
    assert agent._session_loaded is False
    assert agent._agent_prefix_messages is None
