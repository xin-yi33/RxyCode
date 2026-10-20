"""WEB-W8 S3. Shared Harness pause point inside the ordinary tool loop.

A tool call that needs a human decision parks the loop with a checkpoint:
completed calls keep their results, the paused call and the calls after it
never run inside this turn. Resume injects the approved result as data (the
caller owns the journal and at-most-once execution), records the calls that
did not run, and continues the same loop to a final answer.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.messages import AIMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.harness_checkpoint import (
    NOT_EXECUTED_NOTE,
    HarnessPaused,
    decode_messages,
    encode_messages,
)
from RxyCode.RxyCode1_1_0.core.safety.approval import (
    ApprovalBroker,
    ApprovalDecision,
    set_approval_broker,
)


class _PauseFirstAsk(ApprovalBroker):
    def __init__(self) -> None:
        super().__init__()
        self.asks = 0

    async def _ask(self, request):  # noqa: ANN001
        self.asks += 1
        if self.asks == 1:
            raise HarnessPaused(request.call_id, {"tool": request.tool_name})
        return ApprovalDecision.APPROVED


def _tool_delta(calls):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(
            content="",
            reasoning_content="",
            tool_calls=[
                SimpleNamespace(index=i, id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                for i, (cid, name, args) in enumerate(calls)
            ],
        ))],
        usage=None,
    )


def _text_delta(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, reasoning_content="", tool_calls=None))],
        usage=None,
    )


def _agent(isolated_runtime, monkeypatch):
    from RxyCode.RxyCode1_1_0.config.settings import _default_config
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, UsageTrackingLLM
    from tests.support.scripted_llm import ScriptedChatModel

    cfg = _default_config()
    cfg["models"] = {"scripted": {"model_name": "scripted", "api_key": "test-only",
                                  "base_url": "https://example.invalid/v1"}}
    cfg["active_model"] = "scripted"
    cfg["agents"]["enabled"] = False
    cfg["safety"].update(enabled=True, auto_approve=[],
                          allowed_write_paths=[str(isolated_runtime.workspace)])
    isolated_runtime.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(AgentV2, "_build_llm", lambda self: UsageTrackingLLM(ScriptedChatModel([])))
    agent = AgentV2()
    monkeypatch.setattr(agent, "_detect_file_operation", lambda _text: None)
    monkeypatch.setattr(agent, "_detect_download_intent", lambda _text: None)
    return agent


@pytest.mark.asyncio
async def test_w8_s3_pause_checkpoints_then_resume_reaches_final_answer(isolated_runtime, monkeypatch):
    agent = _agent(isolated_runtime, monkeypatch)
    target = isolated_runtime.workspace / "fast.txt"
    broker = _PauseFirstAsk()
    set_approval_broker(broker)
    seen = []

    async def first_stream(messages, bound_tools=None):
        seen.append(list(messages))
        yield _tool_delta([("c-edit", "edit", {"filePath": str(target), "operation": "write", "content": "x\n"})])

    monkeypatch.setattr(agent, "_raw_stream", first_stream)
    try:
        with pytest.raises(HarnessPaused) as paused:
            await agent._fast_reply_with_tools("Create fast.txt", mode="build")
    finally:
        set_approval_broker(None)

    checkpoint = paused.value.checkpoint
    assert checkpoint is not None and paused.value.call_id == "c-edit"
    json.dumps(checkpoint)
    assert checkpoint["paused"] == {"call_id": "c-edit", "tool": "edit"}
    assert checkpoint["remaining"] == []
    restored = decode_messages(checkpoint["messages"])
    assert isinstance(restored[-1], AIMessage) and restored[-1].tool_calls[0]["id"] == "c-edit"
    assert not target.exists()

    resumed_messages = []

    async def resumed_stream(messages, bound_tools=None):
        resumed_messages.append(list(messages))
        yield _text_delta("Final Answer: fast.txt holds the approved write")

    monkeypatch.setattr(agent, "_raw_stream", resumed_stream)
    answer = await agent._fast_reply_with_tools(
        "Create fast.txt",
        mode="build",
        resume={"checkpoint": checkpoint, "result": "wrote fast.txt"},
    )
    assert "approved write" in answer
    assert not target.exists(), "resume must not execute the approved call a second time"
    tool_results = [m for m in resumed_messages[0] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_results] == ["c-edit"]
    assert "wrote fast.txt" in str(tool_results[0].content)
    assert broker.asks == 1


@pytest.mark.asyncio
async def test_w8_s3_completed_calls_stay_and_later_calls_are_marked_not_executed(isolated_runtime, monkeypatch):
    agent = _agent(isolated_runtime, monkeypatch)
    first = isolated_runtime.workspace / "one.txt"
    second = isolated_runtime.workspace / "two.txt"
    first.write_text("alpha\n", encoding="utf-8")
    broker = _PauseFirstAsk()
    set_approval_broker(broker)

    async def first_stream(messages, bound_tools=None):
        yield _tool_delta([
            ("c-read", "read", {"filePath": str(first)}),
            ("c-edit", "edit", {"filePath": str(second), "operation": "write", "content": "beta\n"}),
            ("c-later", "edit", {"filePath": str(isolated_runtime.workspace / "three.txt"),
                                 "operation": "write", "content": "gamma\n"}),
        ])

    monkeypatch.setattr(agent, "_raw_stream", first_stream)
    try:
        with pytest.raises(HarnessPaused) as paused:
            await agent._fast_reply_with_tools("Edit two files", mode="build")
    finally:
        set_approval_broker(None)

    checkpoint = paused.value.checkpoint
    assert checkpoint["paused"]["call_id"] == "c-edit"
    assert checkpoint["remaining"] == ["c-later"]
    before = decode_messages(checkpoint["messages"])
    done = [m for m in before if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in done] == ["c-read"], "completed read keeps its result"
    assert "alpha" in str(done[0].content)
    assert not (isolated_runtime.workspace / "three.txt").exists()
    assert not second.exists()

    resumed_messages = []

    async def resumed_stream(messages, bound_tools=None):
        resumed_messages.append(list(messages))
        yield _text_delta("Final Answer: done")

    monkeypatch.setattr(agent, "_raw_stream", resumed_stream)
    answer = await agent._fast_reply_with_tools(
        "Edit two files",
        mode="build",
        resume={"checkpoint": checkpoint, "result": "wrote two.txt"},
    )
    assert "done" in answer
    tool_results = {m.tool_call_id: str(m.content) for m in resumed_messages[0] if isinstance(m, ToolMessage)}
    assert set(tool_results) == {"c-read", "c-edit", "c-later"}
    assert "wrote two.txt" in tool_results["c-edit"]
    assert tool_results["c-later"] == NOT_EXECUTED_NOTE
    assert not (isolated_runtime.workspace / "three.txt").exists()


def test_w8_s3_codec_keeps_reasoning_replay_fields():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "read", "args": {"filePath": "a"}, "id": "c1", "type": "tool_call"}],
        additional_kwargs={"reasoning_content": "step one"},
    )
    rows = encode_messages([message])
    restored = decode_messages(json.loads(json.dumps(rows)))
    assert restored[0].additional_kwargs == {"reasoning_content": "step one"}
    assert restored[0].tool_calls[0]["id"] == "c1"
