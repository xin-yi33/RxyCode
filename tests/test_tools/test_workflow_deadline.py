import asyncio
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _local_script_location(workflow, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        workflow,
        "_script_location",
        lambda: (tmp_path, str(tmp_path), ["test-python"]),
    )


@pytest.mark.asyncio
async def test_workflow_default_deadline_precedes_global_tool_deadline(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_config",
        lambda: {"execution": {"tool_timeout_seconds": 1800}},
    )
    observed = []

    async def execute(argv, *, workdir, timeout):
        observed.append((argv, workdir, timeout, Path(argv[1]).exists()))
        return {"stdout": "complete", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    result = await workflow._execute_script_async(
        "print('ok')",
        {},
        timeout_seconds=workflow.DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
    )

    assert result == "complete"
    assert observed == [
        (
            ["test-python", observed[0][0][1]],
            str(tmp_path),
            workflow.DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
            True,
        )
    ]
    assert not Path(observed[0][0][1]).exists()


@pytest.mark.asyncio
async def test_explicit_zero_uses_global_tool_deadline(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_config",
        lambda: {"execution": {"tool_timeout_seconds": 45}},
    )
    observed_timeout = []

    async def execute(_argv, *, workdir, timeout):
        assert workdir == str(tmp_path)
        observed_timeout.append(timeout)
        return {"stdout": "ok", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    assert await workflow._execute_script_async(
        "print('ok')", {}, timeout_seconds=0
    ) == "ok"
    assert observed_timeout == [45]


@pytest.mark.asyncio
async def test_workflow_deadline_is_clamped_to_global_tool_deadline(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_config",
        lambda: {"execution": {"tool_timeout_seconds": 30}},
    )

    async def execute(_argv, *, workdir, timeout):
        assert workdir == str(tmp_path)
        assert timeout == 30
        return {
            "stdout": "",
            "stderr": "[timeout after 30s]",
            "exit_code": -1,
            "success": False,
            "error_type": "timeout",
        }

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    result = await workflow._execute_script_async(
        "while True: pass", {}, timeout_seconds=120
    )

    assert result == "[workflow timeout: script deadline exceeded after 30s]"


@pytest.mark.asyncio
async def test_docker_script_uses_mounted_workdir_and_container_interpreter(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    monkeypatch.setattr(
        workflow.shell_executor,
        "_execution_policy",
        lambda _workdir: SimpleNamespace(
            mode="docker",
            cwd=tmp_path,
            workspace_root=tmp_path,
        ),
    )
    observed = []

    async def execute(argv, *, workdir, timeout):
        script_path = tmp_path / argv[1]
        observed.append((argv, workdir, timeout, script_path.exists()))
        return {"stdout": "docker", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    monkeypatch.setattr(
        workflow,
        "load_config",
        lambda: {"execution": {"tool_timeout_seconds": 1800}},
    )

    result = await workflow._execute_script_async(
        "print('ok')", {}, timeout_seconds=10
    )

    assert result == "docker"
    assert observed == [
        (["python", observed[0][0][1]], str(tmp_path), 10, True)
    ]
    assert "/" not in observed[0][0][1]
    assert "\\" not in observed[0][0][1]


@pytest.mark.asyncio
async def test_structured_tool_run_reaches_shell_executor(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    executed = threading.Event()

    async def execute(argv, *, workdir, timeout):
        assert argv[0] == "test-python"
        assert workdir == str(tmp_path)
        assert timeout == workflow.DEFAULT_WORKFLOW_TIMEOUT_SECONDS
        executed.set()
        return {"stdout": "wired", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    run_id = "wf-structured-terminal"
    result = await workflow.workflow_tool.ainvoke(
        {
            "operation": "run",
            "script": "print('wired')",
            "run_id": run_id,
        }
    )
    completed = json.loads(
        await workflow.manage_workflow_async(
            "status", run_id=run_id, timeout_seconds=2
        )
    )

    assert executed.is_set()
    assert result.startswith("wired\n")
    assert f"run_id: {run_id}; status: completed" in result
    assert completed["status"] == "completed"
    assert completed["result"] == "wired"


@pytest.mark.asyncio
async def test_cancel_propagates_to_controlled_executor(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    started = threading.Event()
    cancelled = threading.Event()

    async def execute(_argv, *, workdir, timeout):
        assert workdir == str(tmp_path)
        assert timeout > 0
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    run_id = "wf-explicit-cancel"
    running = asyncio.create_task(
        workflow.manage_workflow_async(
            "run",
            script="while True: pass",
            run_id=run_id,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    assert not running.done()

    result = await workflow.manage_workflow_async("cancel", run_id=run_id)
    run_result = await running
    terminal = json.loads(
        await workflow.manage_workflow_async(
            "wait", run_id=run_id, timeout_seconds=2
        )
    )

    assert "cancelled" in result.lower()
    assert run_result.startswith("[workflow cancelled]")
    assert cancelled.is_set()
    assert terminal["status"] == "cancelled"


@pytest.mark.asyncio
async def test_docker_sandbox_failure_never_retries_on_host(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    calls = []

    async def execute(argv, *, workdir, timeout):
        calls.append((argv, workdir, timeout))
        return {
            "stdout": "",
            "stderr": (
                "[docker_sandbox] Docker runtime is unavailable; "
                "host execution was not attempted"
            ),
            "exit_code": -1,
            "success": False,
            "error_type": "docker_sandbox",
        }

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)

    run_id = "wf-docker-fail-closed"
    result = await workflow.manage_workflow_async(
        "run",
        script="print('never-host')",
        run_id=run_id,
    )
    terminal = json.loads(
        await workflow.manage_workflow_async(
            "status", run_id=run_id, timeout_seconds=2
        )
    )

    assert len(calls) == 1
    assert result.startswith("[workflow error: docker_sandbox:")
    assert terminal["status"] == "failed"
    assert "docker_sandbox" in terminal["result"]
    assert "host execution was not attempted" in terminal["result"]


@pytest.mark.asyncio
async def test_workflow_wait_without_deadline_remains_cancellable():
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    run_id = "wf-cancellable-wait"
    workflow_key = workflow._workflow_key(run_id)
    with workflow._workflow_lock:
        workflow._workflows[workflow_key] = {
            "run_id": run_id,
            "status": "running",
        }
        workflow._workflow_events[workflow_key] = threading.Event()

    task = asyncio.create_task(
        workflow.manage_workflow_async("wait", run_id=run_id, timeout_seconds=0)
    )
    try:
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        with workflow._workflow_lock:
            workflow._workflows.pop(workflow_key, None)
            workflow._workflow_events.pop(workflow_key, None)


@pytest.mark.asyncio
async def test_run_does_not_acknowledge_success_before_script_finishes(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    async def execute(_argv, *, workdir, timeout):
        assert workdir == str(tmp_path)
        assert timeout > 0
        started.set()
        await asyncio.to_thread(release.wait)
        return {"stdout": "durable", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    run_id = "wf-no-early-ack"
    running = asyncio.create_task(
        workflow.manage_workflow_async(
            "run",
            script="print('durable')",
            run_id=run_id,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)

    status = json.loads(
        await workflow.manage_workflow_async("status", run_id=run_id)
    )
    assert status["status"] == "running"
    assert not running.done()

    release.set()
    result = await asyncio.wait_for(running, timeout=2)

    assert result.startswith("durable\n")
    assert "status: completed" in result


@pytest.mark.asyncio
async def test_side_effect_journal_completes_only_after_workflow_terminal_success(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    async def execute(_argv, *, workdir, timeout):
        started.set()
        await asyncio.to_thread(release.wait)
        return {"stdout": "committed", "stderr": "", "exit_code": 0, "success": True}

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    orchestrator = ToolOrchestrator()
    orchestrator.register("workflow", workflow.workflow_tool)
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path / "journal")
    attempt_id = new_attempt_id()
    binding = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        running = asyncio.create_task(
            orchestrator.execute_tool(
                "workflow",
                {
                    "operation": "run",
                    "script": "print('committed')",
                    "run_id": "wf-journal-terminal",
                },
                config={
                    "safety": {"enabled": False},
                    "execution": {"tool_timeout_seconds": 10},
                },
            )
        )
        assert await asyncio.to_thread(started.wait, 2)

        pending = journal.load(attempt_id)
        assert pending is not None
        assert {entry["status"] for entry in pending["entries"].values()} == {
            "pending"
        }
        assert not running.done()

        release.set()
        result = await asyncio.wait_for(running, timeout=2)
    finally:
        release.set()
        orchestrator.reset_tool_journal(binding)

    completed = journal.load(attempt_id)
    assert result.startswith("committed\n")
    assert completed is not None
    assert {entry["status"] for entry in completed["entries"].values()} == {
        "completed"
    }


@pytest.mark.asyncio
async def test_failed_workflow_is_not_committed_to_side_effect_journal(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)

    async def execute(_argv, *, workdir, timeout):
        return {
            "stdout": "",
            "stderr": "failure",
            "exit_code": 2,
            "success": False,
            "error_type": "execution_error",
        }

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    orchestrator = ToolOrchestrator()
    orchestrator.register("workflow", workflow.workflow_tool)
    orchestrator.set_audit_logger(MagicMock())
    journal = ToolExecutionJournal(tmp_path / "journal")
    attempt_id = new_attempt_id()
    binding = orchestrator.bind_tool_journal(journal, attempt_id)
    try:
        result = await orchestrator.execute_tool(
            "workflow",
            {
                "operation": "run",
                "script": "raise SystemExit(2)",
                "run_id": "wf-journal-failed",
            },
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_tool_journal(binding)

    assert result.startswith("[workflow error:")
    assert journal.has_pending(attempt_id) is True


@pytest.mark.asyncio
async def test_failed_run_returns_failure_prefix_and_terminal_state(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)

    async def execute(_argv, *, workdir, timeout):
        return {
            "stdout": "",
            "stderr": "script exploded",
            "exit_code": 7,
            "success": False,
            "error_type": "execution_error",
        }

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    run_id = "wf-real-failure"

    result = await workflow.manage_workflow_async(
        "run",
        script="raise RuntimeError('boom')",
        run_id=run_id,
    )
    status = json.loads(
        await workflow.manage_workflow_async("status", run_id=run_id)
    )

    assert result.startswith("[workflow error: execution_error: script exploded")
    assert "status: failed" in result
    assert status["status"] == "failed"


@pytest.mark.asyncio
async def test_timed_out_run_returns_only_after_controlled_executor_terminal(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    executor_returned = threading.Event()

    async def execute(_argv, *, workdir, timeout):
        executor_returned.set()
        return {
            "stdout": "",
            "stderr": f"[timeout after {timeout:g}s]",
            "exit_code": -1,
            "success": False,
            "error_type": "timeout",
        }

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    run_id = "wf-real-timeout"

    result = await workflow.manage_workflow_async(
        "run",
        script="while True: pass",
        run_id=run_id,
        timeout_seconds=9,
    )
    status = json.loads(
        await workflow.manage_workflow_async("status", run_id=run_id)
    )

    assert executor_returned.is_set()
    assert result.startswith("[workflow timeout: script deadline exceeded after 9s]")
    assert "status: failed" in result
    assert status["status"] == "failed"


@pytest.mark.asyncio
async def test_cancelling_run_task_cleans_controlled_executor(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import workflow_tool as workflow

    _local_script_location(workflow, tmp_path, monkeypatch)
    started = threading.Event()
    cleaned = threading.Event()

    async def execute(_argv, *, workdir, timeout):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaned.set()
            raise

    monkeypatch.setattr(workflow.shell_executor, "execute_argv_async", execute)
    run_id = "wf-caller-cancel"
    running = asyncio.create_task(
        workflow.manage_workflow_async(
            "run",
            script="while True: pass",
            run_id=run_id,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert cleaned.is_set()
    status = json.loads(
        await workflow.manage_workflow_async("status", run_id=run_id)
    )
    assert status["status"] == "cancelled"
