"""W9-H1: full_auto bash through LocalNativeBackend formats like run_bash.

The native path previously returned raw stdout — empty on success-without-
output and on never-started alike. It now feeds the normal path's
``tools.bash._format_result`` so both surfaces speak the same contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _rel in (
    Path("packages") / "rxycode-runner" / "src",
    Path("packages") / "rxycode-core" / "src",
):
    _src = REPO / _rel
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rxycode_runner.local.native_backend import LocalNativeBackend, NativeResult  # noqa: E402

_CFG = {"safety": {"enabled": True, "permission_mode": "full_auto", "auto_approve": []}}


@pytest.fixture
def queued_results(monkeypatch: pytest.MonkeyPatch):
    """Mock only the OS boundary: run_command returns queued NativeResults.

    A Web execution port is also bound for the duration.  A *bound* port is
    what distinguishes the Web runtime (native-backend contract, covered here)
    from the CLI runtime (managed persistent shell, covered by
    ``test_bash_e2e_chains``); without it the orchestrator would correctly
    prefer the CLI shell and never call ``run_command`` at all.
    """
    from rxycode_core.runtime import execution_port as port_module

    queue: list[NativeResult] = []

    async def fake_run(self, argv, cwd, *, timeout=1800):
        return queue.pop(0)

    monkeypatch.setattr(LocalNativeBackend, "run_command", fake_run)
    monkeypatch.setattr(
        port_module,
        "current_execution_port",
        lambda: port_module.default_execution_port(),
    )
    return queue


def _orchestrator():
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    return orchestrator


def _result(**overrides) -> NativeResult:
    raw = dict(
        started=True,
        wrapped=False,
        argv=[],
        approval="skipped",
        pid=1234,
        exit_code=0,
        stdout="",
        stderr="",
        timed_out=False,
    )
    raw.update(overrides)
    return NativeResult(**raw)


@pytest.mark.asyncio
async def test_h1_full_auto_success_without_output_returns_no_output(queued_results):
    queued_results.append(_result())
    out = await _orchestrator().execute_tool("bash", {"command": "true"}, config=_CFG)
    assert out == "[no output]"


@pytest.mark.asyncio
async def test_h1_full_auto_failure_keeps_error_prefix_and_exit_code(queued_results):
    queued_results.append(_result(exit_code=3, stdout="boom happened"))
    out = await _orchestrator().execute_tool(
        "bash", {"command": "exit 3"}, config=_CFG
    )
    assert out.startswith("[error executing bash:")
    assert "boom happened" in out
    assert "[exit code: 3]" in out


@pytest.mark.asyncio
async def test_h1_full_auto_large_output_is_truncated(queued_results):
    from RxyCode.RxyCode1_1_0.tools.bash import MAX_OUTPUT_CHARS, TRUNCATION_HINT

    queued_results.append(_result(stdout="x" * (MAX_OUTPUT_CHARS + 5000)))
    out = await _orchestrator().execute_tool(
        "bash", {"command": "cat huge.bin"}, config=_CFG
    )
    assert len(out) < MAX_OUTPUT_CHARS + 5000
    assert TRUNCATION_HINT in out


@pytest.mark.asyncio
async def test_h1_full_auto_never_started_is_an_error_not_empty(queued_results):
    queued_results.append(_result(started=False, pid=None))
    out = await _orchestrator().execute_tool("bash", {"command": "true"}, config=_CFG)
    assert out == "[error executing bash: command did not start]"

    from RxyCode.RxyCode1_1_0.execution.evidence import build_tool_evidence

    evidence = build_tool_evidence(
        "bash", {"command": "true"}, out, executed=True
    )
    assert evidence.status == "failed"


@pytest.mark.asyncio
async def test_h1_full_auto_timeout_formats_like_normal_path(queued_results):
    queued_results.append(_result(timed_out=True, exit_code=None, stdout="partial"))
    out = await _orchestrator().execute_tool(
        "bash", {"command": "sleep 60", "timeout": 5}, config=_CFG
    )
    assert out.startswith("[error executing bash:")
    assert "timeout after 5s" in out
