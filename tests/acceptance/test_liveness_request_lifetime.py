"""Acceptance coverage for liveness requests following their own lifetime."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import time
from copy import deepcopy

import pytest
import yaml
from langchain_core.messages import AIMessage

from RxyCode.RxyCode1_1_0.config.settings import _default_config
from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core import session_runtime
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.timeout_decision import (
    TIMEOUT_DECISION_DEFAULTS,
    DecisionPolicy,
    ExtensionLedger,
    TimeoutDecisionEngine,
)
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence
from RxyCode.RxyCode1_1_0.tools import bash as bash_mod
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from RxyCode.RxyCode1_1_0.utils.shell import (
    SessionLivenessJudge,
    bind_process_probe,
    reset_process_probe,
    run_process_probe,
)


@pytest.fixture(autouse=True)
async def _clean_managed_shells():
    await ps.release_all()
    yield
    await ps.release_all()


def _agent_with_llm(isolated_runtime, monkeypatch, llm) -> AgentV2:
    cfg = _default_config()
    cfg["models"] = {
        "liveness-acceptance": {
            "model_name": "liveness-acceptance",
            "api_key": "test-only",
            "base_url": "https://example.invalid/v1",
        }
    }
    cfg["active_model"] = "liveness-acceptance"
    cfg["timeout_decision"] = deepcopy(TIMEOUT_DECISION_DEFAULTS)
    cfg["timeout_decision"]["enabled"] = False
    cfg["timeout_decision"]["decision_timeout_seconds"] = 15.0
    cfg["agents"]["enabled"] = False
    cfg["safety"].update(
        enabled=True,
        auto_approve=[],
        allowed_write_paths=[str(isolated_runtime.workspace)],
    )
    isolated_runtime.config_path.write_text(
        yaml.safe_dump(cfg),
        encoding="utf-8",
    )
    monkeypatch.setattr(AgentV2, "_build_llm", lambda self: llm)
    return AgentV2(session_id="liveness-request-lifetime")


class _SuspendedContinueLLM:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.started = asyncio.Event()

    async def ainvoke(self, _messages):
        self.started.set()
        await asyncio.sleep(self.delay)
        return AIMessage(content='{"action":"continue","note":"request completed"}')


@pytest.mark.asyncio
async def test_agentv2_liveness_outlives_p6_15s_and_uses_real_request_lifetime(
    isolated_runtime,
    monkeypatch,
) -> None:
    llm = _SuspendedContinueLLM(16.1)
    agent = _agent_with_llm(isolated_runtime, monkeypatch, llm)

    assert agent._cfg["timeout_decision"]["decision_timeout_seconds"] == 15.0
    assert agent._liveness_judge._timeout_seconds is None

    started = time.monotonic()
    verdict_task = asyncio.create_task(
        agent._liveness_judge(
            {
                "elapsed_seconds": 180.0,
                "cpu_start_percent": 0.0,
                "cpu_end_percent": 0.0,
                "io_start_bytes": 0,
                "io_end_bytes": 0,
                "busy": False,
            }
        )
    )
    await asyncio.wait_for(llm.started.wait(), timeout=1.0)
    await asyncio.sleep(15.2)

    assert not verdict_task.done(), "AgentV2 still borrowed the P6 15s clock"
    verdict = await asyncio.wait_for(verdict_task, timeout=2.0)
    assert verdict.action == "continue"
    assert verdict.note == "request completed"
    assert time.monotonic() - started >= 16.0


class _NativeTimeoutLLM:
    async def ainvoke(self, _messages):
        raise TimeoutError("configured provider request timeout")


@pytest.mark.asyncio
async def test_native_model_timeout_is_reported_as_unknown() -> None:
    judge = SessionLivenessJudge(lambda: _NativeTimeoutLLM())

    verdict = await judge({"elapsed_seconds": 180.0})

    assert verdict.action == "unknown"
    assert "TimeoutError" in verdict.note


class _CancelledLLM:
    async def ainvoke(self, _messages):
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_model_cancellation_is_not_converted_to_a_verdict() -> None:
    judge = SessionLivenessJudge(lambda: _CancelledLLM())

    with pytest.raises(asyncio.CancelledError):
        await judge({"elapsed_seconds": 180.0})


class _InvalidJsonLLM:
    async def ainvoke(self, _messages):
        return AIMessage(content="not a JSON decision")


@pytest.mark.asyncio
async def test_invalid_json_remains_an_unknown_verdict() -> None:
    judge = SessionLivenessJudge(lambda: _InvalidJsonLLM())

    verdict = await judge({"elapsed_seconds": 180.0})

    assert verdict.action == "unknown"
    assert "非 JSON" in verdict.note


class _AvailableSampler:
    available = True

    def __init__(self, _pid) -> None:
        pass

    def sample(self):
        return 0.0, 0, 1, 0


class _GatedHandler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancelled = False

    async def __call__(self, _payload):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished.set()
        return {"action": "continue", "note": "late feedback"}


@pytest.mark.asyncio
async def test_command_completion_cancels_and_awaits_inflight_judge(monkeypatch) -> None:
    monkeypatch.setattr(shell_module, "ProcessTreeSampler", _AvailableSampler)
    handler = _GatedHandler()
    completion = asyncio.Event()
    reports: list[tuple[str, dict | None]] = []

    async def reporter(text, details):
        reports.append((text, details))

    token = bind_process_probe(
        handler,
        call_id="completion-call",
        generation=1,
        reporter=reporter,
    )
    try:
        probe_task = asyncio.create_task(
            run_process_probe(
                4242,
                elapsed_seconds=180.0,
                completion=completion,
                observe_seconds=0.05,
            )
        )
        await asyncio.wait_for(handler.started.wait(), timeout=1.0)
        started = time.monotonic()
        completion.set()

        assert await asyncio.wait_for(probe_task, timeout=1.0) is None
        assert time.monotonic() - started < 0.5
        assert handler.cancelled is True
        assert handler.finished.is_set()
    finally:
        reset_process_probe(token)

    await asyncio.sleep(0.05)
    assert reports == []
    assert not [
        task
        for task in asyncio.all_tasks()
        if "_GatedHandler.__call__" in getattr(task.get_coro(), "__qualname__", "")
    ]


@pytest.mark.asyncio
async def test_user_cancel_cancels_and_awaits_inflight_judge(monkeypatch) -> None:
    monkeypatch.setattr(shell_module, "ProcessTreeSampler", _AvailableSampler)
    handler = _GatedHandler()
    reports: list[tuple[str, dict | None]] = []

    async def reporter(text, details):
        reports.append((text, details))

    token = bind_process_probe(
        handler,
        call_id="cancel-call",
        generation=1,
        reporter=reporter,
    )
    try:
        probe_task = asyncio.create_task(
            run_process_probe(
                4242,
                elapsed_seconds=180.0,
                observe_seconds=0.05,
            )
        )
        await asyncio.wait_for(handler.started.wait(), timeout=1.0)
        probe_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await probe_task
        assert handler.cancelled is True
        assert handler.finished.is_set()
    finally:
        reset_process_probe(token)

    await asyncio.sleep(0.05)
    assert reports == []
    assert not [
        task
        for task in asyncio.all_tasks()
        if "_GatedHandler.__call__" in getattr(task.get_coro(), "__qualname__", "")
    ]


def _shell_config(workspace) -> dict:
    return {
        "safety": {
            "enabled": True,
            "permission_mode": "full_auto",
            "auto_approve": ["write", "danger"],
        },
        "execution": {
            "sandbox_mode": "host",
            "workspace_root": str(workspace),
            "max_memory_mb": 0,
            "max_processes": 0,
            "os_sandbox": {"enabled": False},
            "tool_timeout_seconds": 5,
        },
    }


class _GatedLivenessJudge:
    def __init__(self) -> None:
        self.started: asyncio.Queue[dict] = asyncio.Queue()
        self.release = asyncio.Event()
        self.payloads: list[dict] = []

    async def __call__(self, payload):
        self.payloads.append(payload)
        await self.started.put(payload)
        await self.release.wait()
        return {"action": "continue", "note": "slow judge released"}


class _Tui:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def write_progress(self, _text, details=None):
        self.items.append(dict(details or {}))


def _streaming_command(marker, tag: str) -> str:
    code = (
        "import pathlib,sys,time;"
        "sys.stdout.write(chr(120) * 4096);"
        "sys.stdout.flush();"
        "pathlib.Path(sys.argv[1]).write_text(sys.argv[2]);"
        "time.sleep(0.8);"
        "print(sys.argv[2])"
    )
    if os.name == "nt":
        return (
            f"& {shlex.quote(sys.executable)} -c {shlex.quote(code)} "
            f"{shlex.quote(str(marker))} {shlex.quote(tag)}"
        )
    return (
        f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} "
        f"{shlex.quote(str(marker))} {shlex.quote(tag)}"
    )


async def _wait_for_path(path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_slow_judge_keeps_command_running_and_isolates_call_session_feedback(
    isolated_runtime,
    monkeypatch,
) -> None:
    config = _shell_config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_checkpoints",
        (0.05,),
    )
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_observe_seconds",
        0.05,
    )
    judge = _GatedLivenessJudge()
    orchestrator = ToolOrchestrator(
        tool_registry=default_registry,
        liveness_judge=judge,
    )
    orchestrator.register("bash", bash_mod.bash_tool)

    async def run_command(session_id: str, call_id: str, tag: str):
        marker = isolated_runtime.workspace / f"{tag}.marker"
        ui = _Tui()
        session_token = session_runtime.bind_session(session_id)
        try:
            result = await orchestrator.execute_tool(
                "bash",
                {
                    "command": _streaming_command(marker, tag),
                    "description": f"slow judge {tag}",
                    "workdir": "",
                    "timeout": 5,
                },
                call_id=call_id,
                config=config,
                event_tui=ui,
            )
            return result, marker, ui
        finally:
            session_runtime.reset_session_binding(session_token)

    first = asyncio.create_task(run_command("liveness-session-a", "liveness-call-a", "RXY_A"))
    second = asyncio.create_task(run_command("liveness-session-b", "liveness-call-b", "RXY_B"))
    first_marker = isolated_runtime.workspace / "RXY_A.marker"
    second_marker = isolated_runtime.workspace / "RXY_B.marker"
    markers_while_judge_held = False
    first_result = second_result = ""
    try:
        observed = {
            (await asyncio.wait_for(judge.started.get(), timeout=5.0))["call_id"],
            (await asyncio.wait_for(judge.started.get(), timeout=5.0))["call_id"],
        }
        assert observed == {"liveness-call-a", "liveness-call-b"}
        assert judge.release.is_set() is False
        assert {
            "liveness-session-a",
            "liveness-session-b",
        }.issubset(set(ps.active_identities()))

        markers_while_judge_held = await _wait_for_path(first_marker) and await _wait_for_path(
            second_marker
        )
        assert judge.release.is_set() is False

        judge.release.set()
        first_result, first_marker, first_ui = await asyncio.wait_for(first, timeout=6.0)
        second_result, second_marker, second_ui = await asyncio.wait_for(
            second,
            timeout=6.0,
        )
    finally:
        judge.release.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)

    assert markers_while_judge_held, (
        "command did not continue while the judge was blocked: "
        f"A={first_result!r}, B={second_result!r}"
    )
    assert "RXY_A" in str(first_result)
    assert "RXY_B" in str(second_result)
    first_feedback_calls = {
        item["call_id"] for item in first_ui.items if item.get("kind") == "process_liveness"
    }
    second_feedback_calls = {
        item["call_id"] for item in second_ui.items if item.get("kind") == "process_liveness"
    }
    assert first_feedback_calls == {"liveness-call-a"}
    assert second_feedback_calls == {"liveness-call-b"}
    assert len({payload["pid"] for payload in judge.payloads}) == 2


class _ImmediateDecisionLLM:
    async def ainvoke(self, _prompt):
        class _Response:
            content = '{"action":"continue","extend_seconds":300,"note":"keep","confidence":1.0}'

        return _Response()


@pytest.mark.asyncio
async def test_p6_decision_clock_and_ledger_remain_unchanged() -> None:
    section = deepcopy(TIMEOUT_DECISION_DEFAULTS)
    ledger = ExtensionLedger()
    engine = TimeoutDecisionEngine(
        _ImmediateDecisionLLM(),
        DecisionPolicy(section),
        ledger=ledger,
    )
    evidence = TimeoutEvidence(
        trigger_point="watchdog_stall",
        session_id="p6-session",
        run_id="p6-run",
        subject_id="p6-task",
        task_hint="task",
        elapsed_seconds=100.0,
        budget_seconds=100.0,
        extension_index=0,
        progress="",
        last_error="",
    )

    response = await engine.decide(evidence)

    assert section["decision_timeout_seconds"] == 15.0
    assert response.action == "continue"
    assert ledger.count(("p6-session", "p6-task")) == 1
    assert ledger.total_extended(("p6-session", "p6-task")) == 300.0
