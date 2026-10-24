"""Independent approval-resume checks for process-liveness wiring."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
from RxyCode.RxyCode1_1_0.core import persistent_shell
from RxyCode.RxyCode1_1_0.core import session_runtime
from RxyCode.RxyCode1_1_0.core.harness_checkpoint import HarnessPaused
from RxyCode.RxyCode1_1_0.core.safety.approval import (
    ApprovalRequest,
    get_approval_broker,
    set_approval_broker,
)
from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
from RxyCode.RxyCode1_1_0.execution.tool_journal import (
    RemoteJournalAdapter,
    ToolExecutionJournal,
)
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from rxycode_worker import drain
from rxycode_worker.ctl import pack_checkpoint


class _ResumeChannel:
    def __init__(self, record: dict[str, Any], journal_dir: Path) -> None:
        self.record = record
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.journal = RemoteJournalAdapter(ToolExecutionJournal(journal_dir))

    def resume_state(self, _approval_id: str) -> dict[str, Any]:
        return {"record": dict(self.record)}

    def emit(self, event_type: str, payload: dict[str, Any]) -> int:
        self.events.append((event_type, dict(payload)))
        return len(self.events)

    def journal_state(self, *, attempt_id: str, call_id: str) -> str:
        return self.journal.state(attempt_id=attempt_id, call_id=call_id)

    def journal_reserve(
        self,
        *,
        attempt_id: str,
        call_id: str,
        tool: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.journal.reserve(
            attempt_id=attempt_id,
            call_id=call_id,
            tool=tool,
            args=args,
        )
        return {"action": result.action, "result": result.result}

    def journal_complete(
        self,
        *,
        attempt_id: str,
        call_id: str,
        tool: str,
        args: dict[str, Any],
        result: str,
    ) -> str:
        return self.journal.complete(
            attempt_id=attempt_id,
            call_id=call_id,
            tool=tool,
            args=args,
            result=result,
        )


def _record(
    *,
    call_id: str,
    attempt_id: str,
    command: str = "python -c \"print('RESUME_PROBE_OK')\"",
) -> dict[str, Any]:
    return {
        "kind": "approval",
        "approval_id": "approval-resume",
        "run_id": "run-resume-liveness",
        "call_id": call_id,
        "attempt_id": attempt_id,
        "tool": "bash",
        "arguments": {"command": command, "timeout": 20},
        "command": command,
        "checkpoint_z": pack_checkpoint({"user_input": "resume liveness probe"}),
    }


async def _wait_for_started_shell(session_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while session_id not in persistent_shell.started_identities():
        if time.monotonic() >= deadline:
            raise AssertionError(f"managed shell for {session_id!r} did not start")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_real_resume_probe_uses_owner_judge_and_tui_without_journal_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_id = "call_" + "6" * 32
    attempt_id = "att_" + "6" * 32
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    probe_script = tmp_path / "resume_probe.py"
    probe_script.write_text(
        "import time\n"
        "print('RESUME_PROBE_OK', flush=True)\n"
        "time.sleep(7)\n",
        encoding="utf-8",
    )
    record = _record(
        call_id=call_id,
        attempt_id=attempt_id,
        command=f'python "{probe_script.as_posix()}"',
    )
    channel = _ResumeChannel(record, tmp_path / "journal")

    emitted: list[tuple[str, dict[str, Any]]] = channel.events
    run_emit = drain._RunEmit(
        "",
        "tenant-resume",
        record["run_id"],
        emitter=channel.emit,
    )
    tui = ProtocolTui("session-resume", run_emit, run_id=record["run_id"])
    judge_payloads: list[tuple[float, dict[str, Any]]] = []

    async def owner_judge(payload: dict[str, Any]) -> dict[str, str]:
        judge_payloads.append((time.monotonic(), payload))
        return {"action": "continue", "note": "resume owner judge observed activity"}

    previous_broker = drain._CtlApproval(
        channel,
        run_id=record["run_id"],
        workdir=workspace,
    ).broker()
    old_tui = object()
    tui_token = ToolOrchestrator.bind_event_tui(old_tui)
    session_token = session_runtime.bind_session("session-resume")
    monkeypatch.setenv("RXYCODE_TURN_APPROVAL", str(record["approval_id"]))
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_checkpoints",
        (0.25,),
        raising=False,
    )
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_observe_seconds",
        shell_module.WATCHDOG_OBSERVE_SECONDS,
        raising=False,
    )
    set_approval_broker(previous_broker)
    started = time.monotonic()
    try:
        session_runtime.set_working_directory(workspace, persist=False)
        first = await drain._prepare_resume(
            channel=channel,
            run_id=record["run_id"],
            tenant_id="tenant-resume",
            workdir=workspace,
            liveness_judge=owner_judge,
            event_tui=tui,
        )
        second = await drain._prepare_resume(
            channel=channel,
            run_id=record["run_id"],
            tenant_id="tenant-resume",
            workdir=workspace,
            liveness_judge=owner_judge,
            event_tui=tui,
        )
        restored_broker = get_approval_broker()
        restored_tui = ToolOrchestrator.get_event_tui()
    finally:
        set_approval_broker(None)
        ToolOrchestrator.reset_event_tui(tui_token)
        session_runtime.reset_session_binding(session_token)
        await persistent_shell.release_all()

    assert "RESUME_PROBE_OK" in first["result"]
    assert second["result"] == first["result"]
    assert len(judge_payloads) == 1
    judge_at, payload = judge_payloads[0]
    assert judge_at - started >= 4.8
    assert payload["call_id"] == call_id
    assert payload["pid"] > 0
    assert payload["seq"] == 1
    assert payload["observation_seconds"] == 5.0

    liveness = [
        body for event_type, body in emitted if event_type == "process.liveness"
    ]
    assert len(liveness) == 1
    assert liveness[0]["call_id"] == call_id
    assert liveness[0]["pid"] == payload["pid"]
    assert liveness[0]["seq"] == 1
    assert liveness[0]["action"] == "continue"
    assert liveness[0]["note"] == "resume owner judge observed activity"
    assert restored_tui is old_tui
    assert restored_broker is previous_broker


@pytest.mark.asyncio
async def test_resume_cancellation_restores_ctl_approval_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session-resume-cancelled"
    record = _record(
        call_id="call_" + "7" * 32,
        attempt_id="att_" + "7" * 32,
        command="python -c \"import time; time.sleep(30)\"",
    )
    channel = _ResumeChannel(record, tmp_path / "journal")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    previous_broker = drain._CtlApproval(
        channel,
        run_id=record["run_id"],
        workdir=workspace,
    ).broker()
    old_tui = object()
    tui_token = ToolOrchestrator.bind_event_tui(old_tui)
    session_token = session_runtime.bind_session(session_id)
    cancel_tui = ProtocolTui(session_id, channel.emit, run_id=record["run_id"])
    judge_payloads: list[dict[str, Any]] = []

    async def owner_judge(payload: dict[str, Any]) -> dict[str, str]:
        judge_payloads.append(payload)
        return {"action": "continue", "note": "should be cancelled first"}

    monkeypatch.setenv("RXYCODE_TURN_APPROVAL", str(record["approval_id"]))
    set_approval_broker(previous_broker)
    try:
        session_runtime.set_working_directory(workspace, persist=False)
        resume_task = asyncio.create_task(
            drain._prepare_resume(
                channel=channel,
                run_id=record["run_id"],
                tenant_id="tenant-resume",
                workdir=workspace,
                liveness_judge=owner_judge,
                event_tui=cancel_tui,
            )
        )
        await _wait_for_started_shell(session_id)
        assert not resume_task.done()
        resume_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await resume_task
        assert judge_payloads == []
        assert session_id not in persistent_shell.started_identities()
        assert get_approval_broker() is previous_broker
        assert ToolOrchestrator.get_event_tui() is old_tui
        with pytest.raises(HarnessPaused):
            await previous_broker.request_approval(
                ApprovalRequest(
                    tool_name="write",
                    args_summary={"path": "next.txt"},
                    risk=RiskLevel.WRITE,
                )
            )
    finally:
        set_approval_broker(None)
        ToolOrchestrator.reset_event_tui(tui_token)
        session_runtime.reset_session_binding(session_token)
        await persistent_shell.release_all()
