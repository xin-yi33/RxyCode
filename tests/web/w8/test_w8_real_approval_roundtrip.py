"""W8 production approval round-trip through the shared Harness loop."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from langchain_core.messages import AIMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.harness_checkpoint import HarnessPaused, decode_messages
from tests.web.w8.test_w8_harness_park_db import _lease, _seed, _status


def _tool_delta(call_id: str, name: str, args: dict[str, Any]) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content="",
                    reasoning_content="",
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=call_id,
                            function=SimpleNamespace(
                                name=name,
                                arguments=json.dumps(args),
                            ),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )


def _text_delta(text: str) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=text,
                    reasoning_content="",
                    tool_calls=None,
                )
            )
        ],
        usage=None,
    )


def _agent(isolated_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from RxyCode.RxyCode1_1_0.config.settings import _default_config
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM
    from tests.support.scripted_llm import ScriptedChatModel

    cfg = _default_config()
    cfg["models"] = {
        "scripted": {
            "model_name": "scripted",
            "api_key": "test-only",
            "base_url": "https://example.invalid/v1",
        }
    }
    cfg["active_model"] = "scripted"
    cfg["agents"]["enabled"] = False
    cfg["execution"]["build_workflow"]["enabled"] = False
    cfg["safety"].update(
        enabled=True,
        auto_approve=[],
        permission_mode="confirm_all",
        allowed_write_paths=[str(isolated_runtime.workspace)],
    )
    isolated_runtime.config_path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(
        AgentV2,
        "_build_llm",
        lambda self: UsageTrackingLLM(ScriptedChatModel([])),
    )
    agent = AgentV2()
    monkeypatch.setattr(agent, "_detect_file_operation", lambda _text: None)
    monkeypatch.setattr(agent, "_detect_download_intent", lambda _text: None)
    return agent


class _PostgresChannel:
    """In-process transport over the production parent control handlers."""

    def __init__(self, handlers: dict[str, Any]) -> None:
        self._handlers = handlers

    def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
        from rxycode_worker.ctl import pack_checkpoint

        kwargs["checkpoint_z"] = pack_checkpoint(kwargs.pop("checkpoint"))
        return self._handlers["pause_approval"](kwargs)

    def resume_state(self, approval_id: str) -> dict[str, Any]:
        return self._handlers["resume_state"]({"approval_id": approval_id})


class _Emit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def _append(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append({"kind": kind, **payload})


def _pause_write(
    agent: Any,
    *,
    channel: Any,
    run_id: str,
    workspace: Path,
    target: Path,
    call_id: str = "call-w8-roundtrip",
) -> HarnessPaused:
    from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker
    import rxycode_worker.drain as drain

    calls = 0

    async def scripted_stream(messages: list[Any], _tools: Any = None):
        nonlocal calls
        calls += 1
        assert calls == 1
        yield _tool_delta(
            call_id,
            "edit",
            {
                "filePath": str(target),
                "operation": "write",
                "content": "x\n",
            },
        )

    agent._raw_stream = scripted_stream
    set_approval_broker(drain._CtlApproval(channel, run_id=run_id, workdir=workspace).broker())
    try:
        with pytest.raises(HarnessPaused) as paused:
            asyncio.run(
                agent._under_turn_budget(
                    lambda: agent._fast_reply_with_tools(
                        "Create fast.txt",
                        mode="build",
                    ),
                    agent._new_turn_budget(),
                )
            )
    finally:
        set_approval_broker(None)
    return paused.value


def test_w8_real_postgres_approval_execute_replay_and_same_agent_final(
    isolated_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
    tmp_path: Path,
) -> None:
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )
    from rxycode_server.approvals.service import decide_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    epoch = 11
    workspace = isolated_runtime.workspace
    target = workspace / "fast.txt"
    journal_dir = tmp_path / "parent-journal"
    paused_info: dict[str, Any] = {}
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-roundtrip", epoch)
    handlers = drain._ctl_handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-roundtrip"),
        tenant_id=tenant,
        run_id=run_id,
        epoch=epoch,
        workdir=workspace,
        journal_dir=journal_dir,
        paused=threading.Event(),
        paused_info=paused_info,
    )
    channel = _PostgresChannel(handlers)
    agent = _agent(isolated_runtime, monkeypatch)

    paused = _pause_write(
        agent,
        channel=channel,
        run_id=run_id,
        workspace=workspace,
        target=target,
    )
    assert paused.checkpoint is not None
    assert paused.call_id == "call-w8-roundtrip"
    assert paused.checkpoint["paused"] == {
        "call_id": "call-w8-roundtrip",
        "tool": "edit",
    }
    restored = decode_messages(paused.checkpoint["messages"])
    assert isinstance(restored[-1], AIMessage)
    assert [call["id"] for call in restored[-1].tool_calls] == ["call-w8-roundtrip"]
    assert not any(isinstance(message, ToolMessage) for message in restored)
    assert not target.exists(), "write ran before the human decision"

    assert asyncio.run(drain._park_for_human(channel, paused, workspace)) == ""
    assert _status(postgres_url, run_id) == ("waiting_approval", None)
    approval_id = paused_info["approval_id"]
    approved = decide_approval(
        postgres_url,
        tenant_id=tenant,
        approval_id=approval_id,
        decision="approved",
        expected_revision=0,
    )
    assert approved["status"] == "approved"
    assert _status(postgres_url, run_id)[0] == "pending"

    # The resumed claim fetches the verbatim stored call. Its parent-owned
    # journal is the production RemoteJournalAdapter, not a test shim.
    _lease(postgres_url, run_id, "wkr-roundtrip", epoch)
    state = channel.resume_state(approval_id)
    record = dict(state.get("record") or {})
    assert record["run_id"] == run_id
    assert record["source_call_id"] == "call-w8-roundtrip"
    assert record["arguments"]["content"] == "x\n"
    resumed_checkpoint = drain.unpack_checkpoint(record["checkpoint_z"])
    assert resumed_checkpoint == paused.checkpoint

    journal = RemoteJournalAdapter(ToolExecutionJournal(str(journal_dir)))
    ok, result, outcome = asyncio.run(
        drain._execute_approved_call(record, workspace, _Emit(), journal)
    )
    assert ok, result[:600]
    assert outcome is not None and outcome["status"] == "succeeded"
    assert target.read_text(encoding="utf-8") == "x\n"

    # Resume the SAME AgentV2 instance. Its next scripted model response is
    # derived from the injected real tool result, so the final answer cannot
    # pass by replaying a fabricated "wrote file" string.
    seen: list[list[Any]] = []
    resumed_calls = 0

    async def resumed_stream(messages: list[Any], _tools: Any = None):
        nonlocal resumed_calls
        resumed_calls += 1
        seen.append(list(messages))
        results = [
            str(message.content)
            for message in messages
            if isinstance(message, ToolMessage) and message.tool_call_id == "call-w8-roundtrip"
        ]
        assert len(results) == 1 and results[0].startswith(result)
        if resumed_calls == 1:
            yield _tool_delta(
                "call-w8-read",
                "read",
                {"filePath": str(target)},
            )
            return
        reads = [
            str(message.content)
            for message in messages
            if isinstance(message, ToolMessage) and message.tool_call_id == "call-w8-read"
        ]
        assert len(reads) == 1
        assert "x" in reads[0]
        yield _text_delta("Final Answer: round-trip verified")

    agent._raw_stream = resumed_stream
    answer = asyncio.run(
        agent.resume_harness_turn(
            {
                "checkpoint": resumed_checkpoint,
                "result": result,
                "outcome": outcome,
            }
        )
    )
    assert answer == "Final Answer: round-trip verified"
    assert len(seen) == 2
    first_ai = [message for message in seen[0] if isinstance(message, AIMessage)]
    second_ai = [message for message in seen[1] if isinstance(message, AIMessage)]
    resumed_tools = [message for message in seen[1] if isinstance(message, ToolMessage)]
    assert [call["id"] for call in first_ai[-1].tool_calls] == [
        "call-w8-roundtrip",
    ]
    assert [call["id"] for call in second_ai[-1].tool_calls] == ["call-w8-read"]
    assert [message.tool_call_id for message in resumed_tools] == [
        "call-w8-roundtrip",
        "call-w8-read",
    ]

    # A duplicate resume observes the completed journal entry. Removing the
    # file makes a second real write observable by its reappearance.
    target.unlink()
    replay = asyncio.run(drain._execute_approved_call(record, workspace, _Emit(), journal))
    assert replay == (True, result, None)
    assert not target.exists(), "completed journal entry was executed again"
    assert (
        journal.state(
            attempt_id=str(record["attempt_id"]),
            call_id=str(record["call_id"]),
        )
        == "completed"
    )


def test_w8_real_postgres_rejected_approval_has_no_side_effect(
    isolated_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
    tmp_path: Path,
) -> None:
    import rxycode_worker.drain as drain
    from rxycode_server.approvals.service import decide_approval
    from tests.web.w8.test_w8_harness_park_db import _lease, _seed, _status

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    epoch = 13
    workspace = isolated_runtime.workspace
    target = workspace / "fast.txt"
    journal_dir = tmp_path / "parent-journal"
    paused_info: dict[str, Any] = {}

    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-roundtrip", epoch)
    handlers = drain._ctl_handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-roundtrip"),
        tenant_id=tenant,
        run_id=run_id,
        epoch=epoch,
        workdir=workspace,
        journal_dir=journal_dir,
        paused=threading.Event(),
        paused_info=paused_info,
    )
    channel = _PostgresChannel(handlers)
    agent = _agent(isolated_runtime, monkeypatch)
    paused = _pause_write(
        agent,
        channel=channel,
        run_id=run_id,
        workspace=workspace,
        target=target,
        call_id="call-w8-db-rejected",
    )
    assert asyncio.run(drain._park_for_human(channel, paused, workspace)) == ""
    assert _status(postgres_url, run_id) == ("waiting_approval", None)
    approval_id = paused_info["approval_id"]
    assert approval_id

    rejected = decide_approval(
        postgres_url,
        tenant_id=tenant,
        approval_id=approval_id,
        decision="rejected",
        expected_revision=0,
    )
    assert rejected["status"] == "rejected"
    assert _status(postgres_url, run_id)[0] == "cancelled"
    assert drain._resume_state(postgres_url, tenant, run_id, approval_id) is None
    assert not target.exists()
    assert not list(journal_dir.glob("att_*.json"))
