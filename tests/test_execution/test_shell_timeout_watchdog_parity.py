"""Regression: the managed-shell route must keep the shell watchdog contract.

These are real-process tests. Checkpoints and observation windows are
accelerated, but the ShellExecutor, ToolOrchestrator, bash tool, and managed
shell are production objects.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import time

import pytest
from rxycode_core.runtime.execution_port import (
    ExecutionPort,
    bind_execution_port,
    reset_execution_port,
)

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools import bash as bash_mod
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from RxyCode.RxyCode1_1_0.utils.shell import (
    ShellExecutor,
    bind_process_probe,
    process_probe_deadlines,
    reset_process_probe,
    run_process_probe,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _clean_managed_shells():
    await ps.release_all()
    yield
    await ps.release_all()


def _config(workspace) -> dict:
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


def _patch_clock(
    monkeypatch,
    notices: list[str],
    *,
    executor: ShellExecutor | None = None,
) -> None:
    target = executor or shell_module.shell_executor
    monkeypatch.setattr(
        target,
        "watchdog_checkpoints",
        (0.05,),
    )
    monkeypatch.setattr(
        target,
        "watchdog_observe_seconds",
        0.05,
    )
    monkeypatch.setattr(
        target,
        "watchdog_idle_kill_after",
        30.0,
    )
    monkeypatch.setattr(
        shell_module,
        "_emit_bash_watchdog",
        notices.append,
    )


def _sleep_command(seconds: float) -> str:
    code = f"import time; time.sleep({seconds})"
    if os.name == "nt":
        return f"& {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _orchestrator(judge=None) -> ToolOrchestrator:
    orchestrator = ToolOrchestrator(
        tool_registry=default_registry,
        liveness_judge=judge,
    )
    orchestrator.register("bash", bash_mod.bash_tool)
    return orchestrator


class _LateStopJudge:
    def __init__(self, delay: float = 1.5) -> None:
        self.delay = delay
        self.started = asyncio.Event()
        self.cancelled = False
        self.calls = 0

    async def __call__(self, _payload):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"action": "stop", "note": "late stop must be discarded"}


async def test_real_shell_executor_observes_and_notifies(
    isolated_runtime, monkeypatch
):
    from RxyCode.RxyCode1_1_0.utils.tui import get_tui, set_tui

    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    notices: list[str] = []

    executor = ShellExecutor()
    _patch_clock(monkeypatch, notices, executor=executor)

    class _Tui:
        def write_progress(self, text, details=None):
            notices.append(text)

    previous = get_tui()
    set_tui(_Tui())
    try:
        result = await asyncio.wait_for(
            executor.execute_argv_async(
                [sys.executable, "-c", "import time; time.sleep(0.35)"],
                workdir=str(isolated_runtime.workspace),
                timeout=5,
            ),
            timeout=5,
        )
    finally:
        set_tui(previous)

    assert result["success"] is True
    assert notices, "the one-shot ShellExecutor watchdog did not report its probe"
    assert any("CPU" in note and "IO" in note for note in notices)


async def test_real_orchestrator_managed_bash_keeps_observation_and_feedback(
    isolated_runtime, monkeypatch
):
    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    notices: list[str] = []
    _patch_clock(monkeypatch, notices)

    orchestrator = ToolOrchestrator(tool_registry=default_registry)
    orchestrator.register("bash", bash_mod.bash_tool)
    class _Tui:
        def write_progress(self, text, details=None):
            notices.append(text)

    result = await asyncio.wait_for(
        orchestrator.execute_tool(
            "bash",
            {
                "command": _sleep_command(0.35),
                "description": "accelerated watchdog regression",
                "workdir": "",
                "timeout": 5,
            },
            config=config,
            event_tui=_Tui(),
        ),
        timeout=8,
    )

    assert "error" not in str(result).lower()
    assert ps.active_identities(), "the production dispatch did not take the managed path"
    assert notices, "managed bash bypassed the shared CPU/IO probe and user feedback"
    assert any("CPU" in note and "IO" in note for note in notices)


async def test_probe_deadlines_are_unique_and_continue_after_600():
    assert shell_module.WATCHDOG_OBSERVE_SECONDS == 5.0
    due = process_probe_deadlines(0.0, 1500.0, (180.0, 300.0, 600.0))

    assert due == [180.0, 300.0, 600.0, 900.0, 1200.0]
    assert len(due) == len(set(due))


async def test_probe_requires_two_valid_cpu_samples(monkeypatch):
    payloads: list[dict] = []
    sequences = iter([
        [(0.0, 0, 1, 0), (80.0, 0, 1, 0), (0.0, 0, 1, 0)],
        [(0.0, 0, 1, 0), (80.0, 0, 1, 0), (80.0, 0, 1, 0)],
    ])

    class _Sampler:
        def __init__(self, _pid):
            self.values = iter(next(sequences))

        def sample(self):
            return next(self.values)

    async def handler(payload):
        payloads.append(payload)
        return {"action": "unknown", "note": "test"}

    monkeypatch.setattr(shell_module, "ProcessTreeSampler", _Sampler)
    for generation in (1, 2):
        token = bind_process_probe(
            handler,
            call_id=f"call-{generation}",
            generation=generation,
        )
        try:
            await run_process_probe(
                4242,
                elapsed_seconds=10.0,
                observe_seconds=0.01,
            )
        finally:
            reset_process_probe(token)

    assert payloads[0]["busy"] is False
    assert payloads[1]["busy"] is True
    assert payloads[0]["call_id"] == "call-1"
    assert payloads[1]["generation"] == 2
    assert payloads[1]["pid"] == 4242
    assert payloads[1]["seq"] == 1


async def test_short_managed_command_does_not_wait_for_observer(
    isolated_runtime, monkeypatch
):
    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_checkpoints",
        (5.0,),
    )
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_observe_seconds",
        2.0,
    )
    judge = _LateStopJudge(delay=3.0)
    orchestrator = _orchestrator(judge)

    started = time.monotonic()
    result = await orchestrator.execute_tool(
        "bash",
        {
            "command": _sleep_command(0.02),
            "description": "short",
            "workdir": "",
            "timeout": 5,
        },
        config=config,
    )

    assert time.monotonic() - started < 1.0
    assert judge.calls == 0
    assert "error" not in str(result).lower()


async def test_managed_completed_command_discards_late_stop_and_next_call(
    isolated_runtime, monkeypatch
):
    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    notices: list[str] = []
    _patch_clock(monkeypatch, notices)
    judge = _LateStopJudge(delay=3.0)
    orchestrator = _orchestrator(judge)

    class _Tui:
        def write_progress(self, _text, details=None):
            notices.append(str((details or {}).get("probe_id") or ""))

    token = ToolOrchestrator.bind_event_tui(_Tui())
    try:
        first = asyncio.create_task(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": _sleep_command(0.5),
                    "description": "late stop",
                    "workdir": "",
                    "timeout": 5,
                },
                config=config,
            )
        )
        await asyncio.wait_for(judge.started.wait(), timeout=2.0)
        started = time.monotonic()
        result = await asyncio.wait_for(first, timeout=2.5)
        assert time.monotonic() - started < 1.2
        assert judge.cancelled is True
        assert "stopped by process liveness" not in str(result).lower()

        ToolOrchestrator.clear_live_dedup()
        second = await orchestrator.execute_tool(
            "bash",
            {
                "command": "Write-Output next-ok" if os.name == "nt" else "echo next-ok",
                "description": "next",
                "workdir": "",
                "timeout": 5,
            },
            config=config,
        )
        assert "next-ok" in str(second)
        assert judge.calls == 1
    finally:
        ToolOrchestrator.reset_event_tui(token)


async def test_native_completed_command_discards_late_stop_and_next_call(
    isolated_runtime, monkeypatch
):
    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    notices: list[str] = []
    _patch_clock(monkeypatch, notices)
    judge = _LateStopJudge(delay=3.0)
    orchestrator = _orchestrator(judge)
    port_token = bind_execution_port(ExecutionPort())

    class _Tui:
        def write_progress(self, _text, details=None):
            notices.append(str((details or {}).get("probe_id") or ""))

    tui_token = ToolOrchestrator.bind_event_tui(_Tui())
    try:
        first = asyncio.create_task(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": _sleep_command(0.5),
                    "description": "native late stop",
                    "workdir": "",
                    "timeout": 5,
                },
                config=config,
            )
        )
        await asyncio.wait_for(judge.started.wait(), timeout=2.0)
        started = time.monotonic()
        result = await asyncio.wait_for(first, timeout=3.0)
        assert time.monotonic() - started < 1.4
        assert judge.cancelled is True
        assert "stopped by process liveness" not in str(result).lower()

        monkeypatch.setattr(
            shell_module.shell_executor,
            "watchdog_checkpoints",
            (5.0,),
        )
        ToolOrchestrator.clear_live_dedup()
        second = await orchestrator.execute_tool(
            "bash",
            {
                "command": "Write-Output native-next-ok" if os.name == "nt" else "echo native-next-ok",
                "description": "native next",
                "workdir": "",
                "timeout": 5,
            },
            config=config,
        )
        assert "native-next-ok" in str(second)
        assert judge.calls == 1
    finally:
        ToolOrchestrator.reset_event_tui(tui_token)
        reset_execution_port(port_token)


async def test_probe_reporter_stays_with_request_context():
    class _Tui:
        def __init__(self):
            self.items = []

        def write_progress(self, text, details=None):
            self.items.append((text, details))

    orchestrator = ToolOrchestrator()
    first_tui = _Tui()
    second_tui = _Tui()

    async def report(tui, marker):
        token = ToolOrchestrator.bind_event_tui(tui)
        try:
            await orchestrator._report_process_liveness(
                marker,
                {"kind": "process_liveness", "probe_id": marker},
            )
        finally:
            ToolOrchestrator.reset_event_tui(token)

    await asyncio.gather(
        report(first_tui, "request-a"),
        report(second_tui, "request-b"),
    )

    assert [item[1]["probe_id"] for item in first_tui.items] == ["request-a"]
    assert [item[1]["probe_id"] for item in second_tui.items] == ["request-b"]


async def test_session_liveness_judge_does_not_depend_on_p6_enabled():
    from RxyCode.RxyCode1_1_0.core.timeout_decision import (
        TIMEOUT_DECISION_DEFAULTS,
        SessionLivenessJudge,
    )

    class _LLM:
        async def ainvoke(self, _messages):
            class _Response:
                content = '{"action":"continue","note":"active"}'

            return _Response()

    assert TIMEOUT_DECISION_DEFAULTS["enabled"] is False
    judge = SessionLivenessJudge(lambda: _LLM(), timeout_seconds=1.0)
    verdict = await judge({"cpu_start_percent": 10.0, "cpu_end_percent": 10.0})

    assert verdict.action == "continue"
    assert verdict.note == "active"
