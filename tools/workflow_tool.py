"""Durable-at-the-tool-boundary workflows using the controlled shell runtime.

``run`` does not acknowledge success until the underlying script reaches a
terminal state.  The dedicated runtime remains useful for cross-thread
status/cancel calls, while the side-effect journal sees the real result rather
than a misleading ``started`` acknowledgement.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError as FutureCancelledError, Future
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any, Coroutine
import uuid
import re

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..config.settings import load_config
from ..core.session_runtime import current_session_id
from ..utils.shell import shell_executor


DEFAULT_WORKFLOW_TIMEOUT_SECONDS = 1200.0
_CANCEL_CLEANUP_TIMEOUT_SECONDS = 15.0
_PRACTICALLY_UNBOUNDED_TIMEOUT_SECONDS = 365 * 24 * 60 * 60

_WorkflowKey = tuple[str, str]
_workflows: dict[_WorkflowKey, dict[str, Any]] = {}
_workflow_tasks: dict[_WorkflowKey, Future[str]] = {}
_workflow_events: dict[_WorkflowKey, threading.Event] = {}
_workflow_lock = threading.RLock()
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WORKFLOW_RETENTION_PER_SESSION = 100


class _WorkflowRuntime:
    """Own a persistent loop so sync and async callers share real tasks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            ready = threading.Event()

            def run_loop() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                loop.run_forever()

            self._thread = threading.Thread(
                target=run_loop,
                name="rxycode-workflow-runtime",
                daemon=True,
            )
            self._thread.start()
            ready.wait()
            assert self._loop is not None
            return self._loop

    def submit(self, coroutine: Coroutine[Any, Any, str]) -> Future[str]:
        return asyncio.run_coroutine_threadsafe(coroutine, self._ensure_loop())


_workflow_runtime = _WorkflowRuntime()


def _workflow_key(run_id: str) -> _WorkflowKey:
    return current_session_id(), run_id


def _prune_workflows_locked(session_id: str) -> None:
    terminal = [
        (key, workflow)
        for key, workflow in _workflows.items()
        if key[0] == session_id and workflow.get("status") in _TERMINAL_STATUSES
    ]
    terminal.sort(
        key=lambda item: float(item[1].get("finished") or 0),
        reverse=True,
    )
    for key, _workflow in terminal[_WORKFLOW_RETENTION_PER_SESSION:]:
        _workflows.pop(key, None)
        _workflow_tasks.pop(key, None)
        _workflow_events.pop(key, None)


def clear_session_workflows(session_id: str) -> int:
    """Cancel and forget process-local workflow state for one session."""
    from ..memory.long_term import validate_session_id

    resolved = validate_session_id(session_id)
    with _workflow_lock:
        keys = [key for key in _workflows if key[0] == resolved]
        tasks = [_workflow_tasks.get(key) for key in keys]
        events = [_workflow_events.get(key) for key in keys]
        for key in keys:
            _workflows.pop(key, None)
            _workflow_tasks.pop(key, None)
            _workflow_events.pop(key, None)
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    for event in events:
        if event is not None:
            event.set()
    return len(keys)


class WorkflowInput(BaseModel):
    operation: str = Field(description="Operation: run, status, wait, cancel")
    name: str = Field(default="", description="Workflow name or run_id")
    script: str = Field(default="", description="Inline workflow script (Python code)")
    args: str = Field(default="{}", description="JSON args for the workflow")
    run_id: str = Field(
        default="",
        description="Stable unique run ID for run/status/wait/cancel",
    )
    timeout_seconds: float = Field(
        default=DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
        ge=0,
        description=(
            "Run/wait deadline in seconds. Use 0 to disable the workflow-specific "
            "deadline; the global tool deadline still applies."
        ),
    )


def _normalise_timeout(timeout_seconds: float) -> float:
    return max(0.0, float(timeout_seconds or 0))


def _global_tool_timeout_seconds() -> float:
    try:
        execution = load_config().get("execution", {})
        return max(0.0, float(execution.get("tool_timeout_seconds", 1800) or 0))
    except (AttributeError, TypeError, ValueError):
        return 1800.0


def _effective_execution_timeout(timeout_seconds: float) -> float:
    """Coordinate a workflow deadline with the outer tool execution budget."""
    requested = _normalise_timeout(timeout_seconds)
    global_timeout = _global_tool_timeout_seconds()
    if requested > 0 and global_timeout > 0:
        return min(requested, global_timeout)
    if requested > 0:
        return requested
    if global_timeout > 0:
        return global_timeout
    # ShellExecutor intentionally requires a numeric deadline. When both
    # workflow and global deadlines are disabled, retain cancellation cleanup
    # while using an operationally unbounded ceiling.
    return float(_PRACTICALLY_UNBOUNDED_TIMEOUT_SECONDS)


def _script_location() -> tuple[Path, str, list[str]]:
    """Return host script directory, executor workdir and interpreter argv."""
    policy = shell_executor._execution_policy("")
    directory = (policy.cwd or Path.cwd()).resolve()
    if policy.mode == "docker":
        # The file is created beneath the bind-mounted workspace and addressed
        # relative to Docker's mapped workdir. A host sys.executable path is not
        # meaningful inside the container.
        return directory, str(directory), ["python"]
    return directory, str(directory), [sys.executable]


async def _execute_script_async(
    script: str,
    args: dict[str, Any],
    *,
    timeout_seconds: float,
) -> str:
    script_path: Path | None = None
    effective_timeout = _effective_execution_timeout(timeout_seconds)
    try:
        directory, workdir, interpreter = _script_location()
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix=".rxycode-workflow-",
            dir=directory,
            delete=False,
            encoding="utf-8",
        ) as script_file:
            script_file.write(f"_WORKFLOW_ARGS = {args!r}\n\n{script}")
            script_path = Path(script_file.name)

        script_argument = (
            script_path.name if interpreter == ["python"] else str(script_path)
        )
        result = await shell_executor.execute_argv_async(
            [*interpreter, script_argument],
            workdir=workdir,
            timeout=effective_timeout,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return f"[workflow error: {exc}]"
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)

    if result.get("error_type") == "timeout":
        source = "global tool" if _normalise_timeout(timeout_seconds) == 0 else "script"
        return (
            f"[workflow timeout: {source} deadline exceeded "
            f"after {effective_timeout:g}s]"
        )

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    if result.get("success"):
        output = stdout
        if stderr:
            output += "\n[stderr] " + stderr
        return output.strip() or "[no output]"

    detail = stderr.strip() or stdout.strip() or "controlled execution failed"
    error_type = str(result.get("error_type") or "execution_error")
    exit_code = result.get("exit_code", -1)
    return f"[workflow error: {error_type}: {detail}; exit code: {exit_code}]"


async def _run_workflow_bg(
    workflow_key: _WorkflowKey,
    name: str,
    script: str,
    args: dict[str, Any],
    timeout_seconds: float,
) -> str:
    """Execute one workflow and publish its terminal state."""
    try:
        with _workflow_lock:
            workflow = _workflows[workflow_key]
            if workflow["status"] == "cancelled":
                return "[workflow cancelled]"
            workflow["status"] = "running"
            workflow["started"] = time.time()

        if script:
            result = await _execute_script_async(
                script,
                args,
                timeout_seconds=timeout_seconds,
            )
        elif name:
            result = f"[workflow error: '{name}' is not a predefined workflow]"
        else:
            result = "[workflow error: no name or script provided]"

        with _workflow_lock:
            workflow = _workflows[workflow_key]
            if workflow["status"] != "cancelled":
                workflow["status"] = (
                    "failed"
                    if result.startswith(("[workflow error:", "[workflow timeout:"))
                    else "completed"
                )
                workflow["result"] = result
                workflow["finished"] = time.time()
        return result
    except asyncio.CancelledError:
        with _workflow_lock:
            workflow = _workflows[workflow_key]
            if workflow["status"] != "failed":
                workflow["status"] = "cancelled"
                workflow["result"] = "[workflow cancelled]"
                workflow["finished"] = time.time()
        raise
    except Exception as exc:
        result = f"[workflow error: {type(exc).__name__}: {exc}]"
        with _workflow_lock:
            workflow = _workflows[workflow_key]
            if workflow["status"] != "cancelled":
                workflow["status"] = "failed"
                workflow["error"] = str(exc)
                workflow["result"] = result
                workflow["finished"] = time.time()
        return result
    finally:
        with _workflow_lock:
            event = _workflow_events.get(workflow_key)
        if event is not None:
            event.set()


def _start_workflow(
    name: str,
    script: str,
    args: str,
    run_id: str,
    timeout_seconds: float,
) -> tuple[str, Future[str]]:
    rid = run_id or f"wf-{uuid.uuid4().hex[:8]}"
    if not _RUN_ID_RE.fullmatch(rid):
        raise ValueError(
            "workflow run_id must be a filesystem-safe identifier up to 128 characters"
        )
    try:
        parsed_args = json.loads(args)
    except json.JSONDecodeError:
        parsed_args = {}
    if not isinstance(parsed_args, dict):
        parsed_args = {}

    timeout = _normalise_timeout(timeout_seconds)
    session_id = current_session_id()
    workflow_key = (session_id, rid)
    with _workflow_lock:
        _prune_workflows_locked(session_id)
        if workflow_key in _workflows:
            raise ValueError(f"workflow run_id already exists: {rid}")
        _workflows[workflow_key] = {
            "run_id": rid,
            "session_id": session_id,
            "name": name,
            "status": "pending",
            "created": time.time(),
            "timeout_seconds": timeout,
        }
        _workflow_events[workflow_key] = threading.Event()
        task = _workflow_runtime.submit(
            _run_workflow_bg(workflow_key, name, script, parsed_args, timeout)
        )
        _workflow_tasks[workflow_key] = task

        def discard_task(finished: Future[str]) -> None:
            with _workflow_lock:
                if _workflow_tasks.get(workflow_key) is finished:
                    _workflow_tasks.pop(workflow_key, None)

        task.add_done_callback(discard_task)
    return rid, task


def _terminal_run_result(run_id: str) -> str:
    """Render an outcome that the shared evidence classifier can trust."""
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = dict(_workflows.get(workflow_key, {}))
    if not workflow:
        return f"[workflow error: workflow {run_id} not found]"

    status = str(workflow.get("status") or "unknown")
    result = str(workflow.get("result") or "")
    if status not in _TERMINAL_STATUSES:
        result = (
            f"[workflow error: run {run_id} returned without a terminal state "
            f"(status={status})]"
        )
        status = "failed"
    elif status == "cancelled" and not result:
        result = "[workflow cancelled]"
    elif status == "failed" and not result:
        detail = str(workflow.get("error") or "unknown execution failure")
        result = f"[workflow error: {detail}]"

    return f"{result}\n[workflow run_id: {run_id}; status: {status}]"


def _mark_runtime_failure(run_id: str, exc: BaseException) -> None:
    """Record failures in the workflow runtime itself, not script failures."""
    result = f"[workflow error: runtime {type(exc).__name__}: {exc}]"
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = _workflows.get(workflow_key)
        if workflow is not None and workflow.get("status") not in _TERMINAL_STATUSES:
            workflow["status"] = "failed"
            workflow["error"] = str(exc)
            workflow["result"] = result
            workflow["finished"] = time.time()
        event = _workflow_events.get(workflow_key)
    if event is not None:
        event.set()


def _run_workflow(
    name: str,
    script: str,
    args: str,
    run_id: str,
    timeout_seconds: float,
) -> str:
    """Start a workflow and block until its real terminal outcome is known."""
    try:
        rid, task = _start_workflow(name, script, args, run_id, timeout_seconds)
    except (TypeError, ValueError) as exc:
        return f"[workflow error: {exc}]"

    try:
        task.result()
    except FutureCancelledError:
        # A concurrent cancel call owns process cleanup; wait for its terminal
        # event before acknowledging cancellation to this caller.
        with _workflow_lock:
            event = _workflow_events.get(_workflow_key(rid))
        if event is not None:
            event.wait(timeout=_CANCEL_CLEANUP_TIMEOUT_SECONDS)
    except BaseException as exc:
        _mark_runtime_failure(rid, exc)
    return _terminal_run_result(rid)


def _status_workflow(run_id: str) -> str:
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = dict(_workflows.get(workflow_key, {}))
    if not workflow:
        return f"[error: workflow {run_id} not found]"
    return json.dumps(workflow, indent=2)


def _wait_workflow(run_id: str, timeout_seconds: float) -> str:
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = _workflows.get(workflow_key)
        event = _workflow_events.get(workflow_key)
    if not workflow:
        return f"[error: workflow {run_id} not found]"
    timeout = _normalise_timeout(timeout_seconds)
    if event is not None and not event.wait(timeout=timeout or None):
        return json.dumps({"run_id": run_id, "status": "timeout"})
    return _status_workflow(run_id)


def _cancel_workflow(run_id: str) -> str:
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = _workflows.get(workflow_key)
        if not workflow:
            return f"[error: workflow {run_id} not found]"
        if workflow["status"] in ("completed", "failed", "cancelled"):
            return json.dumps(dict(workflow), indent=2)
        was_pending = workflow["status"] == "pending"
        workflow["status"] = "cancelled"
        workflow["result"] = "[workflow cancelled]"
        workflow["finished"] = time.time()
        task = _workflow_tasks.get(workflow_key)
        event = _workflow_events.get(workflow_key)

    if task is not None:
        task.cancel()
    cleaned = True
    if event is not None:
        if was_pending:
            event.set()
        else:
            cleaned = event.wait(timeout=_CANCEL_CLEANUP_TIMEOUT_SECONDS)
    if not cleaned:
        message = (
            "[workflow error: cancellation cleanup did not finish within "
            f"{_CANCEL_CLEANUP_TIMEOUT_SECONDS:g}s for {run_id}]"
        )
        with _workflow_lock:
            workflow = _workflows.get(workflow_key)
            if workflow is not None:
                workflow["status"] = "failed"
                workflow["result"] = message
                workflow["finished"] = time.time()
        return message
    return f"Workflow {run_id} cancelled"


def manage_workflow(
    operation: str,
    name: str = "",
    script: str = "",
    args: str = "{}",
    run_id: str = "",
    timeout_seconds: float = DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
) -> str:
    if operation == "run":
        return _run_workflow(name, script, args, run_id, timeout_seconds)
    if operation == "status":
        return _status_workflow(run_id)
    if operation == "wait":
        return _wait_workflow(run_id, timeout_seconds)
    if operation == "cancel":
        return _cancel_workflow(run_id)
    return f"[error: unknown operation '{operation}']"


async def _wait_workflow_async(run_id: str, timeout_seconds: float) -> str:
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = _workflows.get(workflow_key)
        event = _workflow_events.get(workflow_key)
    if not workflow:
        return f"[error: workflow {run_id} not found]"
    timeout = _normalise_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout if timeout else None
    while event is not None and not event.is_set():
        if deadline is not None and time.monotonic() >= deadline:
            return json.dumps({"run_id": run_id, "status": "timeout"})
        await asyncio.sleep(0.05)
    return _status_workflow(run_id)


async def _cancel_workflow_async(run_id: str) -> str:
    workflow_key = _workflow_key(run_id)
    with _workflow_lock:
        workflow = _workflows.get(workflow_key)
        if not workflow:
            return f"[error: workflow {run_id} not found]"
        if workflow["status"] in ("completed", "failed", "cancelled"):
            return json.dumps(dict(workflow), indent=2)
        was_pending = workflow["status"] == "pending"
        workflow["status"] = "cancelled"
        workflow["result"] = "[workflow cancelled]"
        workflow["finished"] = time.time()
        task = _workflow_tasks.get(workflow_key)
        event = _workflow_events.get(workflow_key)

    if task is not None:
        task.cancel()
    cleaned = True
    if event is not None:
        if was_pending:
            event.set()
        else:
            deadline = time.monotonic() + _CANCEL_CLEANUP_TIMEOUT_SECONDS
            while not event.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            cleaned = event.is_set()
    if not cleaned:
        message = (
            "[workflow error: cancellation cleanup did not finish within "
            f"{_CANCEL_CLEANUP_TIMEOUT_SECONDS:g}s for {run_id}]"
        )
        with _workflow_lock:
            workflow = _workflows.get(workflow_key)
            if workflow is not None:
                workflow["status"] = "failed"
                workflow["result"] = message
                workflow["finished"] = time.time()
        return message
    return f"Workflow {run_id} cancelled"


async def _run_workflow_async(
    name: str,
    script: str,
    args: str,
    run_id: str,
    timeout_seconds: float,
) -> str:
    """Async foreground run with cooperative outer-task cancellation."""
    try:
        rid, task = _start_workflow(name, script, args, run_id, timeout_seconds)
    except (TypeError, ValueError) as exc:
        return f"[workflow error: {exc}]"

    try:
        await asyncio.wrap_future(task)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        caller_cancelled = current is not None and current.cancelling() > 0
        if caller_cancelled:
            # An outer tool timeout or user cancellation must reach the
            # controlled subprocess and wait for its process-tree cleanup.
            await _cancel_workflow_async(rid)
            raise

        # The concurrent Future was cancelled by a separate `cancel` call.
        # Do not report a terminal result until that call's cleanup completes.
        with _workflow_lock:
            event = _workflow_events.get(_workflow_key(rid))
        if event is not None:
            await asyncio.to_thread(
                event.wait,
                _CANCEL_CLEANUP_TIMEOUT_SECONDS,
            )
    except BaseException as exc:
        _mark_runtime_failure(rid, exc)
    return _terminal_run_result(rid)


async def manage_workflow_async(
    operation: str,
    name: str = "",
    script: str = "",
    args: str = "{}",
    run_id: str = "",
    timeout_seconds: float = DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
) -> str:
    if operation == "run":
        return await _run_workflow_async(
            name,
            script,
            args,
            run_id,
            timeout_seconds,
        )
    if operation == "status":
        return _status_workflow(run_id)
    if operation == "wait":
        return await _wait_workflow_async(run_id, timeout_seconds)
    if operation == "cancel":
        return await _cancel_workflow_async(run_id)
    return f"[error: unknown operation '{operation}']"


workflow_tool = StructuredTool(
    name="workflow",
    description=(
        "Workflow orchestration. Operations: run, status, wait, cancel. "
        "Use 'run' with 'script' to execute Python in the configured sandbox; "
        "run returns only after execution reaches a real terminal state."
    ),
    func=manage_workflow,
    coroutine=manage_workflow_async,
    args_schema=WorkflowInput,
)
