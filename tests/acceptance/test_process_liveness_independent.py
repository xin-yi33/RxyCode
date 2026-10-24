"""Independent acceptance checks for the process-liveness release slice."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core import session_runtime
from RxyCode.RxyCode1_1_0.core.timeout_decision import SessionLivenessJudge
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.protocol.notifications import ProgressUpdate
from RxyCode.RxyCode1_1_0.tools import bash as bash_mod
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from RxyCode.RxyCode1_1_0.utils import shell as shell_module

REPO = Path(__file__).resolve().parents[2]
REDUCER = REPO / "apps" / "web" / "src" / "features" / "runs" / "eventReducer.ts"


def _config(workspace: Path) -> dict:
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
            "tool_timeout_seconds": 30,
            "os_sandbox": {"enabled": False},
        },
    }


def _reduce(events: list[dict]) -> dict:
    from tests.support.pgurl import bun_path

    bun = bun_path()
    assert bun, "bun is required for the shipped reducer contract"
    with tempfile.TemporaryDirectory(prefix="rxy-liveness-e2e-") as temp:
        driver = Path(temp) / "driver.ts"
        driver.write_text(
            "import { reduceEvents } from "
            + json.dumps(REDUCER.as_posix())
            + "\nconst events = "
            + json.dumps(events)
            + "\nconsole.log(JSON.stringify("
            + "reduceEvents(events, 'running', 0, 'run-independent')))"
            + "\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [bun, str(driver)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


@pytest.mark.asyncio
async def test_short_tool_call_does_not_wait_for_observation(
    isolated_runtime, monkeypatch
) -> None:
    config = _config(isolated_runtime.workspace)
    monkeypatch.setattr(shell_module, "load_config", lambda: config)
    monkeypatch.setattr(bash_mod, "load_config", lambda: config)
    session_token = session_runtime.bind_session("accept-short-command")
    orchestrator = ToolOrchestrator(tool_registry=default_registry)
    orchestrator.register("bash", bash_mod.bash_tool)
    try:
        started = time.monotonic()
        result = await asyncio.wait_for(
            orchestrator.execute_tool(
                "bash",
                {
                    "command": "python -c \"print('RXY_SHORT_OK')\"",
                    "description": "short command acceptance",
                    "workdir": "",
                    "timeout": 30,
                },
                call_id="accept-short-command",
                config=config,
            ),
            timeout=4.0,
        )
        elapsed = time.monotonic() - started
        assert "RXY_SHORT_OK" in str(result), result
        assert elapsed < 4.0
    finally:
        orchestrator.shutdown_sync_executor(wait=True)
        await ps.release_all()
        session_runtime.reset_session_binding(session_token)


class _StaticLivenessLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        return AIMessage(
            content='{"action":"continue","note":"进程仍有观察窗口活动"}'
        )


@pytest.mark.asyncio
async def test_real_five_second_probe_projects_to_web_reducer(monkeypatch) -> None:
    import rxycode_worker.drain as drain

    emitted: list[ProgressUpdate] = []
    llm = _StaticLivenessLLM()
    judge = SessionLivenessJudge(lambda: llm, timeout_seconds=2.0)
    orchestrator = ToolOrchestrator(
        tool_registry=default_registry,
        liveness_judge=judge,
    )
    tui_token = ToolOrchestrator.bind_event_tui(
        ProtocolTui("accept-liveness", emitted.append)
    )
    probe_token = shell_module.bind_process_probe(
        orchestrator._judge_process_liveness,
        call_id="accept-probe-call",
        generation=7,
        reporter=orchestrator._report_process_liveness,
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(10)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        started = time.monotonic()
        probe = await shell_module.run_process_probe(
            process.pid,
            elapsed_seconds=180.0,
        )
        elapsed = time.monotonic() - started
        assert probe is not None
        assert probe.action == "continue"
        assert elapsed >= 4.8
        assert llm.calls == 1
        assert len(emitted) == 1

        update = emitted[0]
        assert update.details is not None
        assert update.details.observation_seconds == 5.0
        assert update.details.call_id == "accept-probe-call"
        assert update.details.generation == 7
        assert update.details.seq == 1
        assert update.details.pid == process.pid

        rows = drain._projection_rows(
            "event/progress",
            update.model_dump(mode="json"),
            {},
            run_id="run-independent",
        )
        assert len(rows) == 1
        row_kind, payload = rows[0]
        assert row_kind == "process.liveness"
        reduced = _reduce(
            [
                {
                    "seq": 1,
                    "type": "process.liveness",
                    "payload": payload,
                }
            ]
        )
        timeline = reduced["view"]["timeline"]
        assert len(timeline) == 1
        assert timeline[0]["kind"] == "liveness"
        assert timeline[0]["probeId"] == probe.details["probe_id"]
        assert timeline[0]["action"] == "continue"
        assert timeline[0]["observationSeconds"] == 5.0
    finally:
        shell_module.reset_process_probe(probe_token)
        ToolOrchestrator.reset_event_tui(tui_token)
        orchestrator.shutdown_sync_executor(wait=False)
        if process.returncode is None:
            process.kill()
        await process.wait()


class _AlternatingCPUSampler:
    def __init__(self, _pid: int | None) -> None:
        self._samples = iter(
            [
                (0.0, 0, 1, 1000),
                (80.0, 0, 1, 1000),
                (0.0, 0, 1, 1000),
            ]
        )

    def sample(self) -> tuple[float, int, int, int]:
        return next(self._samples)


@pytest.mark.asyncio
async def test_cpu_busy_requires_both_interval_samples_hot(monkeypatch) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(shell_module, "ProcessTreeSampler", _AlternatingCPUSampler)
    monkeypatch.setattr(
        shell_module.shell_executor,
        "watchdog_idle_cpu_percent",
        5.0,
    )

    async def handler(payload: dict) -> dict[str, str]:
        payloads.append(payload)
        return {"action": "continue", "note": "keep current budget"}

    async def reporter(_text: str, _details: dict) -> None:
        return None

    token = shell_module.bind_process_probe(
        handler,
        call_id="accept-cpu",
        generation=1,
        reporter=reporter,
    )
    try:
        probe = await shell_module.run_process_probe(
            123456,
            elapsed_seconds=20.0,
            observe_seconds=0.1,
        )
    finally:
        shell_module.reset_process_probe(token)

    assert probe is not None
    assert len(payloads) == 1
    assert payloads[0]["cpu_start_percent"] == 80.0
    assert payloads[0]["cpu_end_percent"] == 0.0
    assert payloads[0]["busy"] is False


def test_default_observation_window_is_five_seconds() -> None:
    assert shell_module.WATCHDOG_OBSERVE_SECONDS == 5.0
    assert shell_module.shell_executor.watchdog_observe_seconds == 5.0
