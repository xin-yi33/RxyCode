"""Pause a run on a LangGraph interrupt. The tool runs only after resume."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from rxycode_server.approvals.service import (
    get_approval,
    pause_under_lock,
    prepare_pause,
    settle_run,
)
from rxycode_worker.checkpoints import _call_on_selector, _open_saver, graph_thread_id
from rxycode_worker.supervisor import claim


class _GateState(TypedDict, total=False):
    approval_id: str
    attempt_id: str
    call_id: str
    run_id: str
    journal_dir: str
    workdir: str
    command: str
    decision: str
    output: str


def _gate(state: _GateState) -> dict[str, str]:
    """Interrupt before any later node. Resume re-enters here, then continues."""
    decision = interrupt({"approval_id": state.get("approval_id", "")})
    return {"decision": str(decision)}


def _effect(state: _GateState) -> dict[str, str]:
    if str(state.get("decision") or "") != "approved":
        return {"output": ""}
    box: dict[str, str] = {}

    def _run() -> None:
        box["text"] = asyncio.run(_execute_approved(state))

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join()
    return {"output": box.get("text", "")}


def _compile(saver: object):
    graph = StateGraph(_GateState)
    graph.add_node("gate", _gate)
    graph.add_node("effect", _effect)
    graph.add_edge(START, "gate")
    graph.add_edge("gate", "effect")
    graph.add_edge("effect", END)
    return graph.compile(checkpointer=saver)


async def _execute_approved(state: _GateState) -> str:
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        remote_checkpoint_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    journal = ToolExecutionJournal(state["journal_dir"])
    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    token = orchestrator.bind_tool_journal(
        journal,
        state["attempt_id"],
        remote_checkpoint_id(state["run_id"]),
        state["call_id"],
    )
    try:
        return await orchestrator.execute_tool(
            "bash",
            {
                "command": state.get("command", ""),
                "description": "approved shell",
                "workdir": state.get("workdir", ""),
            },
            {
                "safety": {
                    "enabled": True,
                    "permission_mode": "confirm_all",
                    "allowed_write_paths": [state.get("workdir", "")],
                },
                "execution": {
                    "workspace_root": state.get("workdir", ""),
                    "tool_retry_attempts": 1,
                },
            },
            approval_source="explicit_command",
            call_id=state.get("call_id"),
        )
    finally:
        orchestrator.reset_tool_journal(token)


async def _pause_graph(database_url: str, session_id: str, run_id: str, initial: dict) -> None:
    async with _open_saver(database_url) as saver:
        graph = _compile(saver)
        config = {"configurable": {"thread_id": graph_thread_id(session_id, run_id)}}
        await graph.ainvoke(initial, config)


async def _resume_graph(
    database_url: str,
    session_id: str,
    run_id: str,
    *,
    command: str,
    workdir: str,
) -> None:
    async with _open_saver(database_url) as saver:
        graph = _compile(saver)
        config = {"configurable": {"thread_id": graph_thread_id(session_id, run_id)}}
        await graph.ainvoke(
            Command(
                resume="approved",
                update={"command": command, "workdir": workdir},
            ),
            config,
        )


def _journal_state(journal_dir: str, attempt_id: str, call_id: str) -> str:
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        RemoteJournalAdapter,
        ToolExecutionJournal,
    )

    if not attempt_id or not call_id:
        return "not_started"
    return RemoteJournalAdapter(ToolExecutionJournal(journal_dir)).state(
        attempt_id=attempt_id,
        call_id=call_id,
    )


def pause_for_approval(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    tool: str,
    permission_scope: str,
    arguments: dict[str, Any],
    deadline: datetime,
    worker_id: str,
    epoch: int,
    journal_dir: str,
    workdir: str,
    command: str,
) -> dict[str, Any]:
    """Ask only when the run is not already fully authorized. Never run the tool here."""

    def write_checkpoint(session_id: str, approval_id: str, attempt_id: str) -> None:
        asyncio.run(
            _call_on_selector(
                lambda: _pause_graph(
                    database_url,
                    session_id,
                    run_id,
                    {
                        "approval_id": approval_id,
                        "attempt_id": attempt_id,
                        "call_id": call_id,
                        "run_id": run_id,
                        "journal_dir": journal_dir,
                        "workdir": workdir,
                        "command": command,
                    },
                )
            )
        )

    return pause_under_lock(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        call_id=call_id,
        tool=tool,
        permission_scope=permission_scope,
        arguments=arguments,
        deadline=deadline,
        worker_id=worker_id,
        epoch=epoch,
        command=command,
        workdir=workdir,
        write_checkpoint=write_checkpoint,
    )


def resume_approved(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    approval_id: str,
    worker_id: str,
    journal_dir: str,
    workdir: str,
    command: str,
) -> dict[str, Any]:
    """Continue the interrupted graph. A completed or unknown journal does not run again."""
    del workdir, command
    record = get_approval(database_url, tenant_id=tenant_id, approval_id=approval_id)
    if (
        record is None
        or record["run_id"] != run_id
        or record["status"] != "approved"
    ):
        return {"executed": False}
    before = _journal_state(journal_dir, record["attempt_id"], record["call_id"])
    if before in {"completed", "unknown"}:
        epoch = claim(database_url, run_id, worker_id)
        if epoch is not None:
            settle_run(
                database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                worker_id=worker_id,
                epoch=epoch,
                status="succeeded" if before == "completed" else "recovery_required",
            )
        return {"executed": False}
    epoch = claim(database_url, run_id, worker_id)
    if epoch is None:
        return {"executed": False}
    loaded = prepare_pause(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
    )
    if loaded is None:
        return {"executed": False}
    stored_command = record["command"]
    stored_workdir = record["workdir"]
    asyncio.run(
        _call_on_selector(
            lambda: _resume_graph(
                database_url,
                loaded["session_id"],
                run_id,
                command=stored_command,
                workdir=stored_workdir,
            )
        )
    )
    after = _journal_state(journal_dir, record["attempt_id"], record["call_id"])
    if after == "completed":
        terminal = "succeeded"
    elif after == "unknown":
        terminal = "recovery_required"
    else:
        terminal = "cancelled"
    settle_run(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
        status=terminal,
    )
    return {"executed": before == "not_started" and after == "completed"}
