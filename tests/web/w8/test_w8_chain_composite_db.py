"""WEB-W8 composite chains on real Postgres, real Harness and real journal.

Chain: submit -> the Harness edits a file -> the write needs approval and the
turn parks with its checkpoint in the durable store -> approval -> a FRESH
agent instance (a restarted worker) resumes the ORIGINAL loop -> the model
reads back the file and answers. Substituted at the process seam only: the
AF_UNIX hop is an in-process channel bound to the real parent handlers; the
OS sandbox is not part of Windows hosts (its boundary is tested in the module
and unit suites where userns is available).
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from langchain_core.messages import ToolMessage

from RxyCode.RxyCode1_1_0.core.harness_checkpoint import HarnessPaused

from tests.web.w8.test_w8_harness_park_db import _lease, _seed, _status


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
    cfg["safety"].update(enabled=True, auto_approve=[], permission_mode="confirm_all",
                          allowed_write_paths=[str(isolated_runtime.workspace)])
    isolated_runtime.config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(AgentV2, "_build_llm", lambda self: UsageTrackingLLM(ScriptedChatModel([])))
    agent = AgentV2()
    monkeypatch.setattr(agent, "_detect_file_operation", lambda _text: None)
    monkeypatch.setattr(agent, "_detect_download_intent", lambda _text: None)
    return agent


def _script(monkeypatch, agent, turns: list[list[Any]]) -> list[list[Any]]:
    queue = list(turns)
    seen: list[list[Any]] = []

    async def stream(messages, bound_tools=None):
        seen.append(list(messages))
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        for delta in step:
            yield delta

    monkeypatch.setattr(agent, "_raw_stream", stream)
    return seen


class _InProcChannel:
    """The TurnChannel surface over the REAL parent handlers. Checkpoints are
    packed exactly as the wire packs them."""

    def __init__(self, handlers: dict[str, Any]) -> None:
        self._h = handlers

    def pause_approval(self, **kwargs: Any) -> dict[str, Any]:
        from rxycode_worker.ctl import pack_checkpoint

        kwargs["checkpoint_z"] = pack_checkpoint(kwargs.pop("checkpoint"))
        return self._h["pause_approval"](kwargs)

    def pause_question(self, **kwargs: Any) -> dict[str, Any]:
        from rxycode_worker.ctl import pack_checkpoint

        kwargs["checkpoint_z"] = pack_checkpoint(kwargs.pop("checkpoint"))
        return self._h["pause_question"](kwargs)

    def resume_state(self, approval_id: str) -> dict[str, Any]:
        return self._h["resume_state"]({"approval_id": approval_id})

    def emit(self, event_type: str, payload: Any) -> int:
        return int((self._h["emit"]({"type": event_type, "payload": dict(payload)}) or {}).get("seq") or 0)

    def journal_state(self, **kwargs: Any) -> str:
        return str(self._h["journal_state"](kwargs)["state"])

    def journal_reserve(self, **kwargs: Any) -> dict[str, Any]:
        return self._h["journal_reserve"](kwargs)

    def journal_complete(self, **kwargs: Any) -> str:
        out = self._h["journal_complete"](kwargs)
        if out.get("refused"):
            raise RuntimeError("journal_complete refused: unbound call")
        return str(out["result"])


def _channel(postgres_url, tenant, run_id, epoch, tmp_path, paused_info, worker="wkr-chain"):
    import rxycode_worker.drain as drain

    cfg = SimpleNamespace(database_url=postgres_url, worker_id=worker)
    handlers = drain._ctl_handlers(
        cfg,
        tenant_id=tenant,
        run_id=run_id,
        epoch=epoch,
        workdir=tmp_path,
        journal_dir=tmp_path / "journal",
        paused=threading.Event(),
        paused_info=paused_info,
        sandbox_id="sb-chain",
    )
    return _InProcChannel(handlers)


def test_w8_chain_submit_edit_approve_restart_test_final_answer(
    isolated_runtime, monkeypatch, postgres_url: str, tmp_path: Path
) -> None:
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker
    from rxycode_server.approvals.service import decide_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-chain", 6)
    workspace = isolated_runtime.workspace
    target = workspace / "fast.txt"
    paused_info: dict[str, Any] = {}
    channel = _channel(postgres_url, tenant, run_id, 6, tmp_path, paused_info)

    # -- Turn 1 (worker A): the shared Build entry parks on the write.
    agent = _agent(isolated_runtime, monkeypatch)
    _script(monkeypatch, agent, [[_tool_delta([("c-edit", "edit", {
        "filePath": str(target), "operation": "write", "content": "x\n"})])]])
    set_approval_broker(drain._CtlApproval(channel, run_id=run_id, workdir=workspace).broker())
    try:
        with pytest.raises(HarnessPaused) as paused:
            asyncio.run(agent._under_turn_budget(
                lambda: agent._fast_reply_with_tools("Create fast.txt", mode="build"),
                agent._new_turn_budget(),
            ))
    finally:
        set_approval_broker(None)
    assert not target.exists(), "nothing executes before the human decides"
    assert asyncio.run(drain._park_for_human(channel, paused.value, workspace)) == ""
    assert _status(postgres_url, run_id) == ("waiting_approval", None)
    approval_id = paused_info["approval_id"]

    # -- The human approves; the run is claimable again.
    decide_approval(postgres_url, tenant_id=tenant, approval_id=approval_id,
                    decision="approved", expected_revision=0)
    assert _status(postgres_url, run_id)[0] == "pending"

    # -- Worker B claims the run. The turn has exited (marker), the approved
    #    call executes ONCE through the parent journal, then a FRESH agent
    #    instance resumes the ORIGINAL loop from the durable checkpoint.
    from rxycode_server.events.store import append_event

    append_event(postgres_url, tenant_id=tenant, run_id=run_id,
                 event_type="turn.paused", payload={"approval_id": approval_id})
    _lease(postgres_url, run_id, "wkr-chain-b", 7)
    channel_b = _channel(postgres_url, tenant, run_id, 7, tmp_path, {}, worker="wkr-chain-b")
    record = drain._pending_resume(postgres_url, tenant, run_id)
    assert record is not None and record.get("unresolvable") is None
    monkeypatch.setenv("RXYCODE_TURN_APPROVAL", approval_id)
    resume = asyncio.run(drain._prepare_resume(channel=channel_b, run_id=run_id,
                                              tenant_id=tenant, workdir=workspace))
    assert target.read_text(encoding="utf-8") == "x\n", "the approved write ran"
    assert resume["checkpoint"]["paused"]["call_id"] == "c-edit"

    agent_b = _agent(isolated_runtime, monkeypatch)
    seen = _script(monkeypatch, agent_b, [
        [_tool_delta([("c-read", "read", {"filePath": str(target)})])],
        [_text_delta("Final Answer: fast.txt holds the approved write")],
    ])
    answer = asyncio.run(agent_b.resume_harness_turn(resume))
    assert "approved write" in answer
    tool_results = [m for m in seen[0] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_results] == ["c-edit"], "the approved result is the loop's input"
    assert any("x" in str(m.content) for m in seen[1] if isinstance(m, ToolMessage))

    # -- A duplicate resume never repeats the side effect: the journal reuses
    #    the stored outcome even when the workspace was wiped.
    target.unlink()
    again = asyncio.run(drain._prepare_resume(channel=channel_b, run_id=run_id,
                                             tenant_id=tenant, workdir=workspace))
    assert again["result"] == resume["result"]
    assert not target.exists(), "a second execution would have recreated the file"


def test_w8_chain_unknown_write_stops_with_recovery_and_never_reruns(
    isolated_runtime, monkeypatch, postgres_url: str, tmp_path: Path
) -> None:
    import rxycode_worker.drain as drain
    from RxyCode.RxyCode1_1_0.core.safety.approval import set_approval_broker
    from rxycode_server.approvals.service import decide_approval

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-u", 3)
    workspace = isolated_runtime.workspace
    target = workspace / "crash.txt"
    paused_info: dict[str, Any] = {}
    channel = _channel(postgres_url, tenant, run_id, 3, tmp_path, paused_info, worker="wkr-u")

    agent = _agent(isolated_runtime, monkeypatch)
    _script(monkeypatch, agent, [[_tool_delta([("c-w", "edit", {
        "filePath": str(target), "operation": "write", "content": "y\n"})])]])
    set_approval_broker(drain._CtlApproval(channel, run_id=run_id, workdir=workspace).broker())
    try:
        with pytest.raises(HarnessPaused) as paused:
            asyncio.run(agent._fast_reply_with_tools("Create crash.txt", mode="build"))
    finally:
        set_approval_broker(None)
    assert asyncio.run(drain._park_for_human(channel, paused.value, workspace)) == ""
    approval_id = paused_info["approval_id"]
    decide_approval(postgres_url, tenant_id=tenant, approval_id=approval_id,
                    decision="approved", expected_revision=0)

    # The previous claim reserved the write and died before completing it:
    # the journal can no longer prove whether the effect happened.
    record = drain._resume_state(postgres_url, tenant, run_id, approval_id)
    _lease(postgres_url, run_id, "wkr-u", 3)
    journal = drain._ChannelJournal(channel)
    journal.reserve(attempt_id=str(record["attempt_id"]), call_id=str(record["call_id"]),
                    tool="edit", args=drain._approval_args(record))

    _lease(postgres_url, run_id, "wkr-u2", 4)
    channel2 = _channel(postgres_url, tenant, run_id, 4, tmp_path, {}, worker="wkr-u2")
    monkeypatch.setenv("RXYCODE_TURN_APPROVAL", approval_id)
    with pytest.raises(drain._ResumeSettled) as settled:
        asyncio.run(drain._prepare_resume(channel=channel2, run_id=run_id,
                                         tenant_id=tenant, workdir=workspace))
    assert settled.value.status == "recovery_required"
    assert not target.exists(), "an unknown write is never retried blindly"
