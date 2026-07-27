"""LangGraph main graph: the full Hierarchical Plan-and-Execute pipeline.

Graph structure:
    START -> goal_planner -> decomposer -> [route_next]
                                              ↓
                            executor -> validator -> [route_after_validator]
                                              ↓
                              re_planner -> [route_next]
                              compressor -> [route_next]
                              error_recovery -> [route_next]
                              synthesizer -> END

Scheduling logic is embedded in route_next() / route_after_validator()
as pure conditional_edges - not as separate nodes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, START, END

from .state import AgentState, TaskNode, TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.execution.scheduler import TaskScheduler

if TYPE_CHECKING:
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node functions (each receives AgentState, returns partial state update)
# ---------------------------------------------------------------------------

_TRACEABLE_GRAPH_NODES = frozenset({
    "goal_planner",
    "decomposer",
    "executor",
    "validator",
    "reflection",
    "re_planner",
    "compressor",
    "error_recovery",
    "final_verifier",
    "synthesizer",
})


def _token_snapshot() -> tuple[int, int]:
    from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

    return int(token_stats.input_tokens), int(token_stats.output_tokens)


def _model_for(state: AgentState, role: str):
    router = state.get("_model_router")
    return router.get(role) if router is not None else state["_llm"]


async def _emit_state_hooks(
    state: AgentState,
    phase: str,
    subject: str,
    **payload,
) -> None:
    hooks = state.get("_hooks")
    if hooks is None:
        return
    results = await hooks.emit(phase, subject, payload)
    sink = state.get("_hook_audit")
    if isinstance(sink, list):
        sink.extend(result.to_dict() for result in results)


def _record_trajectory(state: AgentState, event_type: str, payload: dict) -> None:
    trajectory = state.get("_trajectory")
    if trajectory is not None:
        trajectory.record(event_type, payload)


def _trajectory_update(node_name: str, result: dict) -> dict:
    """Select decision-bearing node output without serializing runtime objects."""
    payload: dict = {
        "node": node_name,
        "next_phase": result.get("phase"),
    }
    tree = result.get("task_tree")
    if tree is not None and node_name in {
        "goal_planner",
        "decomposer",
        "re_planner",
        "error_recovery",
    }:
        payload["plan"] = tree.model_dump(mode="json")
    for key in (
        "execution_results",
        "reflections",
        "failure_attribution",
        "replan_count",
        "reflection_action",
        "final_verification",
        "compression_count",
        "final_response",
        "error",
    ):
        if key in result:
            payload[key] = result[key]
    return payload


def _plan_experience_summary(
    tree: TaskTree,
    *,
    focus_task_id: str = "",
) -> str:
    """Render bounded plan structure without execution output or evidence."""
    root = tree.nodes.get(tree.goal_id)
    lines = [f"Goal: {root.title if root is not None else tree.goal_id}"]
    if tree.constraints:
        lines.append("Constraints: " + "; ".join(tree.constraints[:8]))

    for task in list(tree.nodes.values())[:32]:
        dependency_titles = [
            tree.nodes[dependency_id].title
            for dependency_id in task.dependent_tasks[:8]
            if dependency_id in tree.nodes
        ]
        line = (
            f"- depth={task.depth} status={task.status.value} "
            f"title={task.title}"
        )
        if dependency_titles:
            line += " depends_on=" + ", ".join(dependency_titles)
        lines.append(line)

    focus = tree.nodes.get(focus_task_id)
    if focus is not None:
        lines.append(f"Focus task: {focus.title}")
        if focus.description:
            lines.append("Focus description: " + focus.description[:800])
        if focus.requirement:
            lines.append("Acceptance requirement: " + focus.requirement[:800])
    if len(tree.nodes) > 32:
        lines.append(f"[truncated {len(tree.nodes) - 32} additional plan nodes]")
    return "\n".join(lines)[:4000]


def observed_node(node_name: str, node):
    """Trace a real graph node with request-local token deltas."""

    async def wrapped(state: AgentState) -> dict:
        import asyncio

        tracer = state.get("_tracer")
        task_id = str(state.get("current_task_id") or "")
        span = tracer.start_span(node_name, task_id=task_id) if tracer else None
        before_input, before_output = _token_snapshot()
        _record_trajectory(
            state,
            "graph.node.started",
            {
                "node": node_name,
                "task_id": task_id,
                "session_id": str(state.get("session_id") or ""),
                "graph_phase": str(state.get("phase") or ""),
            },
        )
        await _emit_state_hooks(
            state,
            "before",
            "graph_node",
            node=node_name,
            task_id=task_id,
            session_id=str(state.get("session_id") or ""),
            graph_phase=str(state.get("phase") or ""),
        )
        _save_graph_checkpoint(state)
        try:
            result = await node(state)
        except BaseException as exc:
            after_input, after_output = _token_snapshot()
            _record_trajectory(
                state,
                "graph.node.failed",
                {
                    "node": node_name,
                    "task_id": task_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "token_usage": {
                        "input_tokens": max(0, after_input - before_input),
                        "output_tokens": max(0, after_output - before_output),
                    },
                },
            )
            await _emit_state_hooks(
                state,
                "error",
                "graph_node",
                node=node_name,
                task_id=task_id,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            _save_graph_checkpoint(
                state,
                {"error": f"{type(exc).__name__}: {str(exc)[:500]}"},
            )
            if span is not None:
                prompt_tokens = max(0, after_input - before_input)
                completion_tokens = max(0, after_output - before_output)
                tracer.end_span(
                    span,
                    status=(
                        "cancelled"
                        if isinstance(exc, asyncio.CancelledError)
                        else "error"
                    ),
                    token_usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                    error_msg=str(exc)[:500],
                )
            raise
        _save_graph_checkpoint(state, result)
        await _emit_state_hooks(
            state,
            "after",
            "graph_node",
            node=node_name,
            task_id=task_id,
            next_phase=str(result.get("phase") or state.get("phase") or ""),
        )
        after_input, after_output = _token_snapshot()
        trajectory_payload = _trajectory_update(node_name, result)
        trajectory_payload.update(
            {
                "task_id": task_id,
                "token_usage": {
                    "input_tokens": max(0, after_input - before_input),
                    "output_tokens": max(0, after_output - before_output),
                },
            }
        )
        _record_trajectory(state, "graph.node.completed", trajectory_payload)
        if span is not None:
            prompt_tokens = max(0, after_input - before_input)
            completion_tokens = max(0, after_output - before_output)
            tracer.end_span(
                span,
                token_usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )
        return result

    wrapped.__name__ = f"observed_{node_name}_node"
    return wrapped


def _merged_checkpoint_state(state: AgentState, update: dict | None = None) -> dict:
    """Recreate the post-node state before LangGraph applies its reducers."""
    merged = dict(state)
    if not update:
        return merged
    merged.update(update)
    if "execution_results" in update:
        merged["execution_results"] = [
            *list(state.get("execution_results", [])),
            *list(update.get("execution_results", [])),
        ]
    return merged


def _save_graph_checkpoint(state: AgentState, update: dict | None = None) -> None:
    store = state.get("_checkpoint_store")
    if store is None:
        return
    session_id = str(state.get("session_id") or "")
    user_input = str(
        state.get("_checkpoint_key_input") or state.get("user_input") or ""
    )
    mode = str(state.get("_checkpoint_mode") or "build")
    try:
        document = store.save(
            session_id,
            user_input,
            mode,
            _merged_checkpoint_state(state, update),
        )
        if update and update.get("phase") == "done":
            store.mark_complete(document["checkpoint_id"])
    except Exception as exc:
        _logger.warning("graph checkpoint failed at %s: %s", state.get("phase"), exc)

async def goal_planner_node(state: AgentState) -> dict:
    """Phase 1: Extract the top-level goal from user input."""
    from RxyCode.RxyCode1_1_0.planning.goal_planner import GoalPlanner
    llm = _model_for(state, "planner")
    memory: MemoryManager = state["_memory"]
    tui = state.get("_tui")

    if tui and hasattr(tui, "write_progress"):
        tui.write_progress("Analyzing request and extracting goal...")

    memory_ctx = await memory.get_context(
        state["session_id"],
        state["user_input"],
    )
    planner = GoalPlanner(llm)
    goal_result, tree = await planner.plan(state["user_input"], memory_ctx)

    if tui and hasattr(tui, "write_progress"):
        tui.write_progress(f"Goal: {goal_result.goal[:80]}")

    return {
        "task_tree": tree,
        "memory_context": memory_ctx,
        "phase": "planned",
    }


async def decomposer_node(state: AgentState) -> dict:
    """Phase 1b: Decompose the goal into a task tree."""
    from RxyCode.RxyCode1_1_0.planning.decomposer import HierarchicalDecomposer

    llm = _model_for(state, "planner")
    tree: TaskTree = state["task_tree"]
    memory_ctx = state.get("memory_context", "")
    tui = state.get("_tui")

    if tui and hasattr(tui, "write_progress"):
        tui.write_progress("Decomposing task into sub-tasks...")

    decomposer = HierarchicalDecomposer(llm, max_depth=4)
    tree = await decomposer.decompose(tree, memory_ctx)

    leaf_count = len(tree.get_pending_leaves())
    if tui and hasattr(tui, "write_progress"):
        tui.write_progress(f"Decomposed into {leaf_count} sub-tasks")

    return {"task_tree": tree, "phase": "executing"}


async def executor_node(state: AgentState) -> dict:
    """Phase 2: Execute the current task (serial) or parallel tasks.

    When ``state["parallel_tasks"]`` contains more than one task ID, all
    listed tasks are executed concurrently via ``asyncio.gather`` with a
    ``Semaphore(max_parallel)`` to limit concurrency.  Each task gets its
    own ``_ProgressTracker`` / watchdog.

    When ``parallel_tasks`` is empty or has a single entry, the original
    serial execution path is used unchanged.
    """
    from RxyCode.RxyCode1_1_0.execution.executor import Executor
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.config.settings import load_config
    from langchain_core.runnables import Runnable

    import asyncio
    import time as _time

    llm = _model_for(state, "executor")
    memory = state["_memory"]
    tree: TaskTree = state["task_tree"]
    tui = state.get("_tui")

    # Load execution config
    cfg = load_config() or {}
    exec_cfg = cfg.get("execution", {})
    max_parallel = exec_cfg.get("max_parallel", 3)

    class _ProgressTracker:
        """Tracks whether the executor is making real progress."""
        def __init__(self):
            self.last_activity = _time.time()
            self.error_count = 0
            self.last_error = ""
            self.chunks_received = 0
        def heartbeat(self):
            self.last_activity = _time.time()
            self.chunks_received += 1
        def record_error(self, err):
            self.error_count += 1
            self.last_error = str(err)
            self.last_activity = _time.time()  # errors count as activity
        def seconds_since_activity(self):
            return _time.time() - self.last_activity

    stall_timeout = max(
        0.0,
        float(exec_cfg.get("task_stall_timeout_seconds", 0) or 0),
    )
    max_timeout = max(
        0.0,
        float(exec_cfg.get("task_max_time_seconds", 7200) or 0),
    )
    check_interval = max(
        0.1,
        float(exec_cfg.get("heartbeat_interval_seconds", 15) or 15),
    )

    async def _run_single_task_body(task: TaskNode) -> dict:
        """Execute a single task with progress monitoring.

        Returns ``{"task_id": ..., "result": ...}``.
        """
        # Get task context from memory
        task_ctx = await memory.get_task_context(
            state["session_id"], task.id, task.parent_id, tree=tree,
        )

        tool_orch = state.get("_tool_orchestrator") or ToolOrchestrator()
        if tui and hasattr(tui, "write_progress"):
            tui.write_progress(f"Executing: {task.title[:60]}")

        executor = Executor(llm, tool_orch, config=cfg, event_tui=tui)
        tracker = _ProgressTracker()

        class _TrackingLLM(Runnable):
            """Wrapper that reports activity on every LLM call."""
            def __init__(self, inner, tracker):
                self._inner = inner
                self._tracker = tracker
            def invoke(self, msgs, config=None, **kw):
                self._tracker.heartbeat()
                try:
                    result = self._inner.invoke(msgs, config=config, **kw)
                    self._tracker.heartbeat()
                    return result
                except Exception as e:
                    self._tracker.record_error(e)
                    raise
            async def ainvoke(self, msgs, config=None, **kw):
                self._tracker.heartbeat()
                try:
                    result = await self._inner.ainvoke(msgs, config=config, **kw)
                    self._tracker.heartbeat()
                    return result
                except Exception as e:
                    self._tracker.record_error(e)
                    raise
            async def astream(self, msgs, config=None, **kw):
                self._tracker.heartbeat()
                async for chunk in self._inner.astream(
                    msgs, config=config, **kw
                ):
                    self._tracker.heartbeat()
                    yield chunk
            def bind_tools(self, tools, **kw):
                bound = self._inner.bind_tools(tools, **kw)
                return _TrackingLLM(bound, self._tracker)
            def __getattr__(self, name):
                return getattr(self._inner, name)

        async def _monitored_execute():
            """Execute with progress tracking injected into the LLM."""
            original_llm = executor._llm
            executor._llm = _TrackingLLM(original_llm, tracker)
            try:
                return await executor.execute_with_evidence(task, task_ctx)
            finally:
                executor._llm = original_llm

        async def _watchdog():
            """Monitor progress and cancel if truly stuck."""
            start = _time.time()
            while True:
                await asyncio.sleep(check_interval)
                elapsed = _time.time() - start
                stall = tracker.seconds_since_activity()

                # Report progress to user
                if tui and hasattr(tui, "write_progress"):
                    status = f"Working... {elapsed:.0f}s (chunks: {tracker.chunks_received})"
                    if stall > 10:
                        status += f" [idle: {stall:.0f}s]"
                    tui.write_progress(status)

                # Check for real problems
                if tracker.error_count >= 3:
                    if tui and hasattr(tui, "write_progress"):
                        tui.write_progress(f"Multiple errors detected: {tracker.last_error[:80]}")
                    return "error"

                if stall_timeout > 0 and stall >= stall_timeout:
                    if tui and hasattr(tui, "write_progress"):
                        tui.write_progress(f"No activity for {stall_timeout:.0f}s - task may be stuck")
                    return "stall"

                if max_timeout > 0 and elapsed >= max_timeout:
                    if tui and hasattr(tui, "write_progress"):
                        tui.write_progress(f"Task soft budget {max_timeout:.0f}s reached")
                    return "max_time"

        # Run executor and watchdog concurrently
        exec_task = asyncio.create_task(_monitored_execute())
        watch_task = asyncio.create_task(_watchdog())

        done, pending = await asyncio.wait(
            [exec_task, watch_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel whichever didn't finish
        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass

        evidence: list[dict] = []
        if exec_task in done:
            # Executor finished normally
            try:
                result, evidence = exec_task.result()
            except Exception as e:
                result = f"[Executor error] {type(e).__name__}: {str(e)[:200]}"
                if tui and hasattr(tui, "write_progress"):
                    tui.write_progress(f"Executor error: {type(e).__name__}")
        else:
            # Watchdog triggered
            reason = watch_task.result() if watch_task in done else "unknown"
            result = f"[{reason}] Task '{task.title[:50]}' did not complete normally."
            if tracker.last_error:
                result += f" Last error: {tracker.last_error[:100]}"
            if tracker.chunks_received > 0:
                result += f" (received {tracker.chunks_received} chunks before issue)"
            else:
                result += " (no progress was made - possible parse error or infinite loop)"
            if tui and hasattr(tui, "write_progress"):
                tui.write_progress(f"Task interrupted ({reason}): {result[:80]}")

        task.result = result
        task.evidence = evidence
        task.touch()

        if tui and hasattr(tui, "write_progress"):
            tui.write_progress(f"Completed: {task.title[:60]}")

        return {"task_id": task.id, "result": result}

    async def _run_single_task(task: TaskNode) -> dict:
        """Run one leaf task behind task-level hooks and trajectory events."""
        from RxyCode.RxyCode1_1_0.log.log_helpers import classify_agent_result

        payload = {
            "task_id": task.id,
            "task_title": task.title,
            "session_id": str(state.get("session_id") or ""),
            "parallel": len(dispatch_task_ids) > 1,
        }
        _record_trajectory(state, "task.started", payload)
        await _emit_state_hooks(state, "before", "task", **payload)
        try:
            update = await _run_single_task_body(task)
        except BaseException as exc:
            failure = {
                **payload,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
            _record_trajectory(state, "task.failed", failure)
            await _emit_state_hooks(state, "error", "task", **failure)
            raise

        result_status, detail = classify_agent_result(str(update.get("result") or ""))
        completion = {
            **payload,
            "status": result_status,
            "evidence_count": len(task.evidence),
        }
        if result_status == "succeeded":
            _record_trajectory(state, "task.completed", completion)
            await _emit_state_hooks(state, "after", "task", **completion)
        else:
            failure = {**completion, "error": detail[:500]}
            _record_trajectory(state, "task.failed", failure)
            await _emit_state_hooks(state, "error", "task", **failure)
        return update

    # Conditional-edge mutations of scalar state are not persisted by
    # LangGraph. route_next() does persist the TaskNode mutations, so RUNNING
    # leaves are the authoritative record of the batch selected for execution.
    # This also prevents stale IDs from a previous batch being replayed.
    dispatch_task_ids = [
        task.id
        for task in tree.get_leaf_nodes()
        if task.status == TaskStatus.RUNNING
    ]

    if not dispatch_task_ids:
        stale_id = state.get("current_task_id")
        return {
            "error": f"No RUNNING task found for dispatch ({stale_id!r})",
            "phase": "executing",
            "current_task_id": None,
            "parallel_tasks": [],
        }

    current_task_id = dispatch_task_ids[0]
    parallel_task_ids = dispatch_task_ids if len(dispatch_task_ids) > 1 else []

    if parallel_task_ids:
        # ── Parallel execution path ──────────────────────────────────
        sem = asyncio.Semaphore(max_parallel)

        async def _execute_one(tid: str) -> dict:
            async with sem:
                task = tree.nodes.get(tid)
                if not task:
                    return {"task_id": tid, "result": "Task not found"}
                return await _run_single_task(task)

        results = await asyncio.gather(
            *[_execute_one(tid) for tid in parallel_task_ids]
        )

        all_results = [
            {"task_id": r["task_id"], "result": r["result"]} for r in results
        ]

        # NOTE: Do NOT write to memory here - results are unverified.
        # Memory writes happen in validator_node only when PASSED.
        return {
            "task_tree": tree,
            "execution_results": all_results,
            "current_task_id": current_task_id,
            "parallel_tasks": parallel_task_ids,
            "phase": "validating",
        }

    else:
        # ── Serial execution path (existing behavior) ─────────────────
        task_id = current_task_id
        task = tree.nodes.get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found", "phase": "executing"}

        # NOTE: Do NOT write to memory here - the result is unverified.
        # Memory writes happen in validator_node only when PASSED.
        # Errors are logged in error_recovery_node via memory.log_error().
        result = await _run_single_task(task)

        return {
            "task_tree": tree,
            "execution_results": [result],
            "current_task_id": current_task_id,
            "parallel_tasks": [],
            "phase": "validating",
        }


async def validator_node(state: AgentState) -> dict:
    """Phase 3: Validate every task dispatched by the preceding executor."""
    import asyncio

    from RxyCode.RxyCode1_1_0.validation.validator import Validator

    llm = _model_for(state, "reflection")
    memory = state["_memory"]
    tree: TaskTree = state["task_tree"]
    task_ids = list(dict.fromkeys(
        state.get("parallel_tasks") or [state.get("current_task_id")]
    ))
    tasks = [tree.nodes[task_id] for task_id in task_ids if task_id in tree.nodes]

    if not tasks:
        return {"error": "No current task", "phase": "executing"}

    tui = state.get("_tui")
    validator = Validator(llm)
    failed_ids: list[str] = []

    for task in tasks:
        if tui and hasattr(tui, "write_progress"):
            tui.write_progress(f"Validating: {task.title[:60]}")

        try:
            vr = await validator.validate(
                title=task.title,
                description=task.description,
                requirement=task.requirement,
                result=task.result or "",
                evidence=task.evidence,
                tools_hint=task.tools_hint,
                effect=task.effect,
            )
            task.validation_result = vr.model_dump()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            task.validation_result = {
                "passed": False,
                "completeness_score": 0,
                "relevance_score": 0,
                "format_score": 0,
                "issues": [f"Validator error: {type(exc).__name__}: {exc}"],
                "suggestion": "Retry validation before accepting this result.",
            }
            task.status = TaskStatus.FAILED
            task.touch()
            failed_ids.append(task.id)
            await memory.log_error(
                state["session_id"], task.id,
                f"Validation error: {type(exc).__name__}: {exc}",
            )
            continue

        task.touch()
        if vr.passed:
            task.status = TaskStatus.PASSED
            # Only write each independently verified result to conversation memory.
            await memory.store_execution(
                state["session_id"], task.id, task.result or ""
            )
        else:
            task.status = TaskStatus.FAILED
            failed_ids.append(task.id)
            # Log validation failure to error log (not conversation memory).
            await memory.log_error(
                state["session_id"], task.id,
                f"Validation failed: {vr.issues}",
            )

    next_task_id = failed_ids[0] if failed_ids else tasks[0].id
    return {
        "task_tree": tree,
        "current_task_id": next_task_id,
        # The batch has been fully consumed. A later scheduler pass must build a
        # fresh dispatch list instead of replaying these tasks.
        "parallel_tasks": [],
        "phase": "validated",
    }


async def re_planner_node(state: AgentState) -> dict:
    """Phase 3b: Re-plan every failed task from the validated batch."""
    from RxyCode.RxyCode1_1_0.validation.re_planner import RePlanner

    llm = _model_for(state, "planner")
    tree: TaskTree = state["task_tree"]
    replanner = RePlanner(llm)
    current_id = state.get("current_task_id")
    failed_ids: list[str] = []
    if current_id and (
        current_id in tree.nodes
        and tree.nodes[current_id].status == TaskStatus.FAILED
    ):
        failed_ids.append(current_id)
    failed_ids.extend(
        task.id for task in tree.nodes.values()
        if task.status == TaskStatus.FAILED and task.id not in failed_ids
    )

    for task_id in failed_ids:
        await replanner.replan(tree, task_id)

    return {
        "task_tree": tree,
        "parallel_tasks": [],
        "replan_count": int(state.get("replan_count", 0) or 0) + len(failed_ids),
        "phase": "executing",
    }


async def reflection_node(state: AgentState) -> dict:
    """Classify failed tasks before selecting retry, re-plan, or termination."""
    from collections import Counter

    from RxyCode.RxyCode1_1_0.validation.reflection import Reflector

    tree: TaskTree = state["task_tree"]
    reflector = Reflector(_model_for(state, "reflection"))
    failures = [
        task for task in tree.nodes.values() if task.status == TaskStatus.FAILED
    ]
    records = list(state.get("reflections", []))
    attribution = Counter(state.get("failure_attribution", {}))
    actions: list[str] = []
    current_task_id = state.get("current_task_id")
    error: str | None = None
    memory: MemoryManager = state["_memory"]

    for task in failures:
        reflected = await reflector.reflect(task)
        record = {"task_id": task.id, **reflected.model_dump()}
        task.reflections = [*task.reflections[-4:], reflected.model_dump()]
        records.append(record)
        attribution[reflected.failure_type] += 1
        actions.append(reflected.action)
        lessons = reflected.lessons or [
            f"Failure pattern: {reflected.reason}"
        ]
        await memory.store_plan_experience(
            plan_summary=_plan_experience_summary(
                tree,
                focus_task_id=task.id,
            ),
            failure_type=reflected.failure_type,
            reason=reflected.reason,
            corrective_action=reflected.corrective_action,
            lessons=lessons,
            outcome="failed",
            session_id=state["session_id"],
        )
        if current_task_id is None:
            current_task_id = task.id
        if reflected.action == "terminate":
            task.status = TaskStatus.CANCELLED
            task.error_history.append(reflected.reason or "")
            task.touch()
        elif error is None:
            error = reflected.reason

    if "replan" in actions:
        action = "replan"
        current_task_id = next(
            (
                record["task_id"]
                for record in reversed(records)
                if record.get("action") == "replan"
                and tree.nodes.get(record["task_id"], None) is not None
                and tree.nodes[record["task_id"]].status == TaskStatus.FAILED
            ),
            current_task_id,
        )
    elif "retry" in actions:
        action = "retry"
    else:
        action = "terminate"

    return {
        "task_tree": tree,
        "reflections": records[-50:],
        "failure_attribution": dict(attribution),
        "reflection_action": action,
        "current_task_id": current_task_id,
        "error": error,
        "phase": "reflected",
    }


async def compressor_node(state: AgentState) -> dict:
    """Bound graph context while preserving full task results as artifacts."""
    import hashlib

    from RxyCode.RxyCode1_1_0.config.credential_store import atomic_write_text
    from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, load_config

    memory: MemoryManager = state["_memory"]
    session_id = state["session_id"]
    memory_ctx = await memory.compress_if_needed(session_id)
    cfg = load_config() or {}
    context_cfg = cfg.get("context", {})
    configured_result_chars = max(
        1000,
        int(context_cfg.get("max_task_result_chars", 12000) or 12000),
    )
    tree: TaskTree = state["task_tree"]
    result_count = max(
        1,
        sum(bool(task.result) for task in tree.nodes.values()),
    )
    token_limit = max(
        1000,
        int(context_cfg.get("graph_context_token_limit", 232000) or 232000),
    )
    per_result_budget = max(1000, int(token_limit * 3 * 0.7) // result_count)
    max_result_chars = min(configured_result_chars, per_result_budget)
    archive_dir = get_data_dir() / "context_artifacts"

    for task in tree.nodes.values():
        full_result = task.result or ""
        if len(full_result) <= max_result_chars:
            continue
        digest = hashlib.sha256(full_result.encode("utf-8")).hexdigest()
        path = archive_dir / f"{digest}.txt"
        if not path.is_file():
            archive_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, full_result)
        marker = (
            "\n\n[context compacted; full result: "
            + str(path)
            + f"; sha256={digest}]\n\n"
        )
        payload_chars = max(200, max_result_chars - len(marker))
        head_chars = payload_chars * 2 // 3
        tail_chars = payload_chars - head_chars
        task.result = full_result[:head_chars] + marker + full_result[-tail_chars:]
        task.result_artifact = str(path)
        task.touch()

    history = list(state.get("conversation_history", []))
    if len(history) > 20:
        history = history[-20:]
    for message in history:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content", ""))
        if len(content) > 2000:
            message["content"] = content[:1300] + "\n[history compacted]\n" + content[-700:]

    return {
        "task_tree": tree,
        "memory_context": memory_ctx,
        "conversation_history": history,
        "compression_count": int(state.get("compression_count", 0) or 0) + 1,
        "phase": "executing",
    }


async def error_recovery_node(state: AgentState) -> dict:
    """Handle execution errors.

    Pulls ``_memory`` / ``session_id`` from state (same as every other node -
    previously this referenced bare ``memory`` / ``session_id`` names and
    crashed with NameError whenever it was routed to).

    The ``handle_error`` decision is now honoured:
    - "retry"  -> task reset to PENDING; route_next() picks it up and sends
      it back to the executor.
    - "cancel" -> task marked CANCELLED; TaskScheduler.get_ready_tasks()
      cascade-cancels its dependents on the next route_next() pass.
    """
    from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorRecovery

    tree: TaskTree = state["task_tree"]
    task_id = state.get("current_task_id")
    error = state.get("error", "Unknown error")
    memory = state.get("_memory")
    session_id = state.get("session_id", "")

    recovery = ErrorRecovery()
    if task_id:
        action = recovery.handle_error(tree, task_id, error)
        # Log error to error log (NOT conversation memory)
        if memory is not None:
            await memory.log_error(session_id, task_id, error)
        if action == "cancel":
            # Trigger the CANCELLED cascade immediately so dependents are
            # marked before route_next() runs.
            scheduler = TaskScheduler(tree)
            scheduler.get_ready_tasks()

    return {"task_tree": tree, "error": None, "phase": "executing"}


async def synthesizer_node(state: AgentState) -> dict:
    """Phase 4: Synthesize all results into the final output."""
    from RxyCode.RxyCode1_1_0.planning.structured_output import (
        StructuredOutputError,
    )
    from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer

    llm = _model_for(state, "default")
    tree: TaskTree = state["task_tree"]
    tui = state.get("_tui")
    if tui and hasattr(tui, "write_progress"):
        tui.write_progress("Synthesizing final response...")

    synthesizer = OutputSynthesizer(llm)
    try:
        synthesis = await synthesizer.synthesize_grounded(
            tree,
            state["user_input"],
        )
        final = synthesis.answer
        synthesis_state = {
            "synthesis_manifest": synthesis.model_dump(mode="json"),
            "synthesis_error": None,
        }
    except StructuredOutputError as exc:
        from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error

        internal = "[Build incomplete: Synthesizer output was not valid grounded JSON.]"
        final = to_user_facing_error(internal)
        synthesis_state = {
            "synthesis_manifest": None,
            "synthesis_error": str(exc)[:1000],
        }

    return {
        "final_response": final,
        "final_verification": synthesis_state,
        "phase": "verifying",
    }


async def final_verifier_node(state: AgentState) -> dict:
    """Fail closed when the synthesized answer contradicts verified state."""
    from RxyCode.RxyCode1_1_0.execution.evidence import deterministic_issues
    from RxyCode.RxyCode1_1_0.validation.final_output import (
        verify_grounded_synthesis,
    )

    tree: TaskTree = state["task_tree"]
    final = str(state.get("final_response") or "").strip()
    issues = list(tree.validate_plan())
    leaves = tree.get_leaf_nodes()
    for task in leaves:
        if task.status == TaskStatus.CANCELLED:
            issues.append(f"Task cancelled: {task.title}")
        elif task.status != TaskStatus.PASSED:
            issues.append(f"Task not verified: {task.title} ({task.status.value})")
        else:
            try:
                issues.extend(deterministic_issues(task.evidence))
            except Exception as exc:
                issues.append(
                    f"Malformed evidence for task {task.title}: "
                    f"{type(exc).__name__}"
                )
    if not final:
        issues.append("Synthesizer produced no final response")

    synthesis_state = state.get("final_verification") or {}
    manifest = (
        synthesis_state.get("synthesis_manifest")
        if isinstance(synthesis_state, dict)
        else None
    )
    grounding_issues, grounding_metrics = verify_grounded_synthesis(
        tree,
        final,
        manifest,
    )
    issues.extend(grounding_issues)
    synthesis_error = (
        synthesis_state.get("synthesis_error")
        if isinstance(synthesis_state, dict)
        else None
    )
    if synthesis_error:
        issues.append(f"Synthesizer grounding failed: {synthesis_error}")

    verification = {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "verified_leaf_count": sum(
            task.status == TaskStatus.PASSED for task in leaves
        ),
        "total_leaf_count": len(leaves),
        **grounding_metrics,
    }
    if issues:
        from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error

        detail = "; ".join(verification["issues"][:8])
        final = to_user_facing_error(f"[Build incomplete: {detail}]")
    else:
        # A pure formatting mismatch (valid, verbatim, fully-cited claims
        # wrapped in extra prose) was repaired by verify_grounded_synthesis
        # to the canonical grounded answer.  Use that repaired answer so a
        # real deliverable is not discarded by a cosmetic mismatch.
        repaired = grounding_metrics.get("repaired_answer")
        if repaired:
            final = repaired
        memory: MemoryManager = state["_memory"]
        await memory.store_execution(state["session_id"], tree.goal_id, final)
        successful_lessons: list[str] = []
        for task in leaves:
            for reflection in task.reflections[-4:]:
                if not isinstance(reflection, dict):
                    continue
                for lesson in reflection.get("lessons", []):
                    if str(lesson).strip():
                        successful_lessons.append(str(lesson))
                    if len(successful_lessons) >= 7:
                        break
                if len(successful_lessons) >= 7:
                    break
            if len(successful_lessons) >= 7:
                break
        successful_lessons.append(
            "Reuse the plan only with equivalent acceptance criteria and "
            "fresh verification evidence"
        )
        await memory.store_plan_experience(
            plan_summary=_plan_experience_summary(tree),
            failure_type="none",
            reason="Final verification passed for every leaf and grounded claim",
            corrective_action=(
                "Preserve the validated dependencies and repeat deterministic "
                "verification before reporting success"
            ),
            lessons=successful_lessons,
            outcome="success",
            session_id=state["session_id"],
        )

    return {
        "final_response": final,
        "final_verification": verification,
        "phase": "done",
    }


# ---------------------------------------------------------------------------
# Routing functions (pure deterministic logic, no LLM calls)
# ---------------------------------------------------------------------------

def route_next(state: AgentState) -> str:
    """Main scheduling router: decide what to do next.

    Priority:
    1. All leaves PASSED/CANCELLED -> synthesize
    2. Context too large -> compress
    3. Ready tasks available -> execute
    4. No ready tasks but tree incomplete -> error
    """
    tree: TaskTree = state["task_tree"]

    # Check completion
    if tree.is_complete():
        return "synthesize"

    from RxyCode.RxyCode1_1_0.config.settings import load_config

    cfg = load_config() or {}
    context_cfg = cfg.get("context", {})
    token_limit = max(
        1000,
        int(context_cfg.get("graph_context_token_limit", 232000) or 232000),
    )
    max_compressions = max(
        1,
        int(context_cfg.get("max_context_compressions", 2) or 2),
    )

    # Check context size - use token estimate (~3 chars/token for mixed content).
    # The estimate covers ALL text that flows into the next LLM call:
    # memory_context + every task node's result text + conversation_history.
    memory_ctx = state.get("memory_context", "")
    results_text = "".join(
        (n.result or "") for n in tree.nodes.values()
    )
    history_text = "".join(
        str(m.get("content", "")) if isinstance(m, dict) else str(m)
        for m in state.get("conversation_history", [])
    )
    estimated_tokens = (len(memory_ctx) + len(results_text) + len(history_text)) // 3
    if estimated_tokens > token_limit:
        if int(state.get("compression_count", 0) or 0) >= max_compressions:
            state["error"] = (
                "Context remained above the configured token limit after "
                f"{max_compressions} compression attempts"
            )
            return "error"
        return "compress"

    # Find ready tasks
    scheduler = TaskScheduler(tree)
    ready = scheduler.get_ready_tasks()

    if ready:
        # Check if parallel execution is enabled
        exec_cfg = cfg.get("execution", {})
        parallel_enabled = bool(
            exec_cfg.get("parallel_enabled", False)
            or state.get("parallel_requested", False)
        )
        max_parallel = max(1, int(exec_cfg.get("max_parallel", 3) or 3))

        if parallel_enabled and len(ready) > 1:
            # Only tasks in the dispatched batch enter RUNNING. Remaining ready
            # tasks stay PENDING so the next scheduler pass can still select them.
            dispatched = ready[:max_parallel]
            for task in dispatched:
                task.status = TaskStatus.RUNNING
                task.touch()
            state["parallel_tasks"] = [task.id for task in dispatched]
            state["current_task_id"] = dispatched[0].id
            return "execute"
        else:
            # Serial: pick first ready task (existing behavior)
            next_task = ready[0]
            next_task.status = TaskStatus.RUNNING
            next_task.touch()
            state["current_task_id"] = next_task.id
            state["parallel_tasks"] = []
            return "execute"

    # No ready tasks - check if there are still running/planning tasks
    running = [n for n in tree.nodes.values() if n.status in (
        TaskStatus.RUNNING, TaskStatus.RE_PLANNING, TaskStatus.WAITING,
    )]
    if running:
        return "error"  # something is stuck

    # All tasks are either done or cancelled
    if tree.is_complete():
        return "synthesize"

    return "error"


def route_after_validator(state: AgentState) -> str:
    """Route after all results in the dispatched batch were validated."""
    tree: TaskTree = state["task_tree"]
    state["parallel_tasks"] = []

    failed_tasks = [
        task for task in tree.nodes.values()
        if task.status == TaskStatus.FAILED
    ]
    if failed_tasks:
        state["current_task_id"] = failed_tasks[0].id
        return "reflect"

    return route_next(state)


def route_after_reflection(state: AgentState) -> str:
    """Apply the evidence-grounded action chosen by the reflection node."""
    action = state.get("reflection_action")
    if action == "replan":
        return "re_plan"
    if action == "retry":
        if not state.get("error"):
            state["error"] = "Reflection requested a governed retry"
        return "error"
    return route_next(state)


def route_entry(state: AgentState) -> str:
    """Resume a durable snapshot at the next uncommitted graph boundary."""
    tree = state.get("task_tree")
    if tree is None:
        return "goal_plan"

    phase = str(state.get("phase") or "executing")
    if phase in {"planning", "planned"}:
        return "decompose"
    if phase == "validating":
        return "validate"
    if phase == "validated":
        return route_after_validator(state)
    if phase == "reflecting":
        return "reflect"
    if phase == "reflected":
        return route_after_reflection(state)
    if phase == "verifying":
        return "final_verify"
    if phase == "done":
        return "end"
    return route_next(state)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and return the compiled LangGraph."""

    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("goal_planner", observed_node("goal_planner", goal_planner_node))
    workflow.add_node("decomposer", observed_node("decomposer", decomposer_node))
    workflow.add_node("executor", observed_node("executor", executor_node))
    workflow.add_node("validator", observed_node("validator", validator_node))
    workflow.add_node("reflection", observed_node("reflection", reflection_node))
    workflow.add_node("re_planner", observed_node("re_planner", re_planner_node))
    workflow.add_node("compressor", observed_node("compressor", compressor_node))
    workflow.add_node("error_recovery", observed_node("error_recovery", error_recovery_node))
    workflow.add_node("synthesizer", observed_node("synthesizer", synthesizer_node))
    workflow.add_node("final_verifier", observed_node("final_verifier", final_verifier_node))

    # Edges
    workflow.add_conditional_edges(
        START,
        route_entry,
        {
            "goal_plan": "goal_planner",
            "decompose": "decomposer",
            "execute": "executor",
            "validate": "validator",
            "reflect": "reflection",
            "re_plan": "re_planner",
            "compress": "compressor",
            "synthesize": "synthesizer",
            "final_verify": "final_verifier",
            "error": "error_recovery",
            "end": END,
        },
    )
    workflow.add_edge("goal_planner", "decomposer")

    # Decomposer -> route_next
    workflow.add_conditional_edges(
        "decomposer",
        route_next,
        {"execute": "executor", "compress": "compressor", "synthesize": "synthesizer", "error": "error_recovery"},
    )

    # Executor -> Validator
    workflow.add_edge("executor", "validator")

    # Validator -> route_after_validator
    workflow.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "execute": "executor",
            "re_plan": "re_planner",
            "reflect": "reflection",
            "synthesize": "synthesizer",
            "compress": "compressor",
            "error": "error_recovery",
        },
    )

    workflow.add_conditional_edges(
        "reflection",
        route_after_reflection,
        {
            "execute": "executor",
            "re_plan": "re_planner",
            "synthesize": "synthesizer",
            "compress": "compressor",
            "error": "error_recovery",
        },
    )

    # Re-planner -> route_next
    workflow.add_conditional_edges(
        "re_planner",
        route_next,
        {"execute": "executor", "compress": "compressor", "synthesize": "synthesizer", "error": "error_recovery"},
    )

    # Compressor -> route_next
    workflow.add_conditional_edges(
        "compressor",
        route_next,
        {"execute": "executor", "compress": "compressor", "synthesize": "synthesizer", "error": "error_recovery"},
    )

    # Error recovery -> route_next
    workflow.add_conditional_edges(
        "error_recovery",
        route_next,
        {"execute": "executor", "compress": "compressor", "synthesize": "synthesizer", "error": END},
    )

    # The final response is persisted only after deterministic verification.
    workflow.add_edge("synthesizer", "final_verifier")
    workflow.add_edge("final_verifier", END)

    return workflow.compile()
