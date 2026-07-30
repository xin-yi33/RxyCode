"""Crash-safe side-effect journal contracts and live wiring tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import StructuredTool


def _write_tool(counter: dict[str, int], *, result: str = "formatted"):
    async def format_text(value: str) -> str:
        counter["calls"] += 1
        return f"{result}: {value}"

    return StructuredTool.from_function(
        coroutine=format_text,
        name="format",
        description="mutating formatter",
    )


def test_checkpoint_attempt_survives_resume_but_rotates_after_completion(tmp_path):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore(tmp_path / "checkpoints")
    first = store.begin_attempt("session", "same request", "build")
    resumed = store.begin_attempt("session", "same request", "build")

    assert resumed["attempt_id"] == first["attempt_id"]

    store.mark_complete(first["checkpoint_id"])
    repeated = store.begin_attempt("session", "same request", "build")

    assert repeated["attempt_id"] != first["attempt_id"]
    assert repeated["completed"] is False


def test_journal_stores_only_hashes_and_clean_bounded_results(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    journal = ToolExecutionJournal(tmp_path, max_result_chars=1000)
    attempt_id = new_attempt_id()
    binding = journal.binding(attempt_id)
    secret = "fake-credential-that-must-not-be-persisted"
    call = binding.next_call("format", {"api_key": secret, "value": "x"})

    assert journal.reserve(attempt_id, call).action == "execute"
    completed = journal.complete(
        attempt_id,
        call,
        "token=another-secret sk-fake-abcdefghijklmnop " + ("x" * 2000),
    )
    reused = journal.reserve(attempt_id, call)

    raw = (tmp_path / f"{attempt_id}.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert "another-secret" not in raw
    assert "sk-fake-abcdefghijklmnop" not in raw
    assert reused.action == "reuse"
    assert reused.result == completed
    assert "token=***" in completed
    assert "journal result truncated" in completed


@pytest.mark.asyncio
async def test_completed_mutating_call_is_reused_on_simulated_resume(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}
    orchestrator = ToolOrchestrator()
    orchestrator.register("format", _write_tool(counter))
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()
    config = {"safety": {"enabled": False}}

    first_token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        first = await orchestrator.execute_tool(
            "format", {"value": "same"}, config=config
        )
    finally:
        orchestrator.reset_tool_journal(first_token)

    resumed_token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        resumed = await orchestrator.execute_tool(
            "format", {"value": "same"}, config=config
        )
    finally:
        orchestrator.reset_tool_journal(resumed_token)

    assert first == "formatted: same"
    assert resumed == first
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_pending_mutating_call_fails_closed_on_simulated_resume(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}
    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "format",
        _write_tool(counter, result="[error: formatter result was lost]"),
    )
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()
    config = {"safety": {"enabled": False}}

    first_token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        first = await orchestrator.execute_tool(
            "format", {"value": "same"}, config=config
        )
    finally:
        orchestrator.reset_tool_journal(first_token)

    resumed_token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        resumed = await orchestrator.execute_tool(
            "format", {"value": "same"}, config=config
        )
    finally:
        orchestrator.reset_tool_journal(resumed_token)

    assert first.startswith("[error:")
    assert "previous outcome unknown" in resumed
    assert counter["calls"] == 1
    assert journal.has_pending(attempt_id) is True


@pytest.mark.asyncio
async def test_same_binding_retry_cannot_bypass_pending_with_next_ordinal(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}
    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "format",
        _write_tool(counter, result="[error: response channel failed]"),
    )
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path)
    token = orchestrator.bind_tool_journal(journal, new_attempt_id())
    try:
        first = await orchestrator.execute_tool(
            "format", {"value": "same"}, config={"safety": {"enabled": False}}
        )
        retried = await orchestrator.execute_tool(
            "format", {"value": "same"}, config={"safety": {"enabled": False}}
        )
    finally:
        orchestrator.reset_tool_journal(token)

    assert first.startswith("[error:")
    assert "previous outcome unknown" in retried
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_known_nonzero_tool_result_is_not_committed_as_success(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}

    async def bash(command: str) -> str:
        counter["calls"] += 1
        return f"command={command}\n[exit code: 1]"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "bash",
        StructuredTool.from_function(
            coroutine=bash,
            name="bash",
            description="shell",
        ),
    )
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()
    token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        first = await orchestrator.execute_tool(
            "bash",
            {"command": "false"},
            config={"safety": {"enabled": False}},
        )
        retry = await orchestrator.execute_tool(
            "bash",
            {"command": "false"},
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_tool_journal(token)

    assert "exit code: 1" in first
    assert "previous outcome unknown" in retry
    assert counter["calls"] == 1
    assert journal.has_pending(attempt_id) is True


@pytest.mark.asyncio
async def test_read_tools_bypass_journal_and_are_not_deduplicated(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}

    async def read(value: str) -> str:
        counter["calls"] += 1
        return value

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "read",
        StructuredTool.from_function(
            coroutine=read,
            name="read",
            description="read",
        ),
    )
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()

    token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        assert await orchestrator.execute_tool(
            "read", {"value": "x"}, config={"safety": {"enabled": False}}
        ) == "x"
        assert await orchestrator.execute_tool(
            "read", {"value": "x"}, config={"safety": {"enabled": False}}
        ) == "x"
    finally:
        orchestrator.reset_tool_journal(token)

    assert counter["calls"] == 2
    assert not (tmp_path / f"{attempt_id}.json").exists()


@pytest.mark.asyncio
async def test_corrupt_journal_is_quarantined_and_mutation_is_blocked(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}
    journal = ToolExecutionJournal(tmp_path)
    attempt_id = new_attempt_id()
    (tmp_path / f"{attempt_id}.json").write_text('{"entries":', encoding="utf-8")
    orchestrator = ToolOrchestrator()
    orchestrator.register("format", _write_tool(counter))
    orchestrator.set_audit_logger(MagicMock())

    token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        result = await orchestrator.execute_tool(
            "format",
            {"value": "x"},
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_tool_journal(token)

    assert "journal unavailable" in result
    assert counter["calls"] == 0
    poison = json.loads(
        (tmp_path / f"{attempt_id}.json").read_text(encoding="utf-8")
    )
    assert poison["poisoned"] is True
    assert len(list((tmp_path / "corrupt").glob(f"{attempt_id}*.json"))) == 1

    retry_token = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        retry = await orchestrator.execute_tool(
            "format",
            {"value": "x"},
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_tool_journal(retry_token)
    assert "journal unavailable" in retry
    assert counter["calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_state", ["pending", "completed_unsealed"])
async def test_corrupt_checkpoint_cannot_orphan_and_bypass_old_attempt(
    tmp_path,
    entry_state,
):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    journal = ToolExecutionJournal(tmp_path / "journal")
    original = checkpoint_store.begin_attempt("session", "request", "build")
    binding = journal.binding(
        original["attempt_id"],
        original["checkpoint_id"],
    )
    call = binding.next_call("format", {"value": "same"})
    journal.reserve(
        original["attempt_id"],
        call,
        checkpoint_id=original["checkpoint_id"],
    )
    if entry_state == "completed_unsealed":
        journal.complete(original["attempt_id"], call, "formatted: same")

    checkpoint_path = (
        tmp_path / "checkpoints" / f"{original['checkpoint_id']}.json"
    )
    checkpoint_path.write_text('{"broken":', encoding="utf-8")
    replacement = checkpoint_store.begin_attempt("session", "request", "build")
    assert replacement["attempt_id"] != original["attempt_id"]

    counter = {"calls": 0}
    orchestrator = ToolOrchestrator()
    orchestrator.register("format", _write_tool(counter))
    orchestrator.set_audit_logger(MagicMock())
    token = orchestrator.bind_tool_journal(
        journal,
        replacement["attempt_id"],
        replacement["checkpoint_id"],
    )
    try:
        result = await orchestrator.execute_tool(
            "format",
            {"value": "same"},
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_tool_journal(token)

    assert "journal unavailable" in result
    assert counter["calls"] == 0


@pytest.mark.asyncio
async def test_agent_resume_reuses_completed_call_but_new_run_gets_new_attempt(
    tmp_path,
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    counter = {"calls": 0}
    orchestrator = ToolOrchestrator()
    orchestrator.register("format", _write_tool(counter))
    orchestrator.set_audit_logger(MagicMock())
    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "journal-session"
    agent._tool_tracer = None
    agent._hooks = None
    agent._checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    agent._tool_journal = ToolExecutionJournal(tmp_path / "journal")
    agent._tool_orchestrator = orchestrator

    async def crash_after_tool(_user_input: str, _mode: str) -> str:
        await orchestrator.execute_tool(
            "format",
            {"value": "same"},
            config={"safety": {"enabled": False}},
        )
        raise RuntimeError("simulated process boundary")

    agent._run_impl = crash_after_tool
    with pytest.raises(RuntimeError, match="simulated process boundary"):
        await agent._run_observed("same request", "build", "journal-crash")
    crashed_attempt = agent._checkpoint_store.begin_attempt(
        "journal-session", "same request", "build"
    )["attempt_id"]

    async def resume(_user_input: str, _mode: str) -> str:
        return await orchestrator.execute_tool(
            "format",
            {"value": "same"},
            config={"safety": {"enabled": False}},
        )

    agent._run_impl = resume
    assert await agent._run_observed(
        "same request", "build", "journal-resume"
    ) == "formatted: same"
    assert counter["calls"] == 1

    repeated = await agent._run_observed(
        "same request", "build", "journal-repeat"
    )
    new_attempt = agent._checkpoint_store.load(
        agent._checkpoint_store.checkpoint_id(
            "journal-session", "same request", "build"
        )
    )["attempt_id"]

    assert repeated == "formatted: same"
    assert counter["calls"] == 2
    assert new_attempt != crashed_attempt


def test_journal_retention_prunes_completed_but_never_pending_attempts(tmp_path):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    journal = ToolExecutionJournal(tmp_path, retention_limit=2)
    attempts = []
    for index in range(3):
        attempt = new_attempt_id()
        attempts.append(attempt)
        binding = journal.binding(attempt)
        call = binding.next_call("format", {"index": index})
        journal.reserve(attempt, call)
        journal.complete(attempt, call, "ok")
        journal.mark_attempt_complete(attempt)

    assert not (tmp_path / f"{attempts[0]}.json").exists()
    assert len(list(tmp_path.glob("att_*.json"))) == 2

    pending = new_attempt_id()
    binding = journal.binding(pending)
    journal.reserve(pending, binding.next_call("format", {"pending": True}))

    assert (tmp_path / f"{pending}.json").exists()
    assert json.loads((tmp_path / f"{pending}.json").read_text())["completed"] is False


@pytest.mark.parametrize("attempt_id", ["../outside", "att_bad", "C:\\outside"])
def test_journal_paths_reject_traversal(tmp_path, attempt_id):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import ToolExecutionJournal

    journal = ToolExecutionJournal(tmp_path)
    with pytest.raises(ValueError, match="attempt_id"):
        journal.load(attempt_id)
