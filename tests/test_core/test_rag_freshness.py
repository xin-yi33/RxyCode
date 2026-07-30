from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _write_rag_config(data_dir: Path, **overrides: object) -> None:
    values = {
        "enabled": True,
        "context_cache_entries": 4,
        "context_cache_ttl_seconds": 30,
        "refresh_debounce_seconds": 0.03,
    }
    values.update(overrides)
    lines = ["rag:"]
    for key, value in values.items():
        rendered = str(value).lower() if isinstance(value, bool) else value
        lines.append(f"  {key}: {rendered}")
    (data_dir / "config.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def test_context_cache_is_run_scoped_ttl_lru_and_never_permanently_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    _write_rag_config(
        tmp_path,
        context_cache_entries=2,
        context_cache_ttl_seconds=10,
    )
    import RxyCode.RxyCode1_1_0.memory.manager as manager_mod
    import RxyCode.RxyCode1_1_0.rag.search as search_mod

    clock = {"now": 100.0}
    monkeypatch.setattr(
        manager_mod, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )
    retrieve = MagicMock(side_effect=lambda query, **_kwargs: f"context:{query}")
    monkeypatch.setattr(search_mod, "retrieve_context", retrieve)
    memory = manager_mod.MemoryManager()

    assert memory.get_code_context("one") == "context:one"
    assert memory.get_code_context("one") == "context:one"
    memory.get_code_context("two")
    memory.get_code_context("three")
    assert list(memory._rag_context_cache) == ["two", "three"]

    # A new top-level run invalidates even unexpired entries.
    memory.begin_run("run-2")
    assert memory.get_code_context("one") == "context:one"
    assert retrieve.call_count == 4

    # TTL also refreshes within an unusually long single run.
    clock["now"] += 11
    assert memory.get_code_context("one") == "context:one"
    assert retrieve.call_count == 5


def test_context_cache_stays_bounded_under_concurrent_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    _write_rag_config(tmp_path, context_cache_entries=3)
    import RxyCode.RxyCode1_1_0.rag.search as search_mod
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    monkeypatch.setattr(
        search_mod,
        "retrieve_context",
        lambda query, **_kwargs: f"result:{query}",
    )
    memory = MemoryManager()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(memory.get_code_context, map(str, range(40))))

    assert len(results) == 40
    assert len(memory._rag_context_cache) == 3
    assert memory.get_code_context("future-query") == "result:future-query"
    assert len(memory._rag_context_cache) == 3


def test_new_file_is_retrievable_before_and_after_incremental_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "base.py").write_text("base_value = 1\n", encoding="utf-8")
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(data_dir))
    monkeypatch.chdir(project)
    _write_rag_config(data_dir, refresh_debounce_seconds=0.02)

    import RxyCode.RxyCode1_1_0.rag.index as index_mod
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    monkeypatch.setattr(index_mod, "is_embedding_available", lambda: False)
    index_mod.index_project(project)
    memory = MemoryManager()
    assert memory.get_code_context("neon_fresh_symbol") == ""

    indexer = index_mod.BackgroundIndexer(project, debounce_seconds=0.02)
    indexer.start(initial_delay=60)
    memory.bind_rag_indexer(indexer)
    try:
        (project / "fresh.py").write_text(
            "def neon_fresh_symbol():\n    return 'new code'\n",
            encoding="utf-8",
        )
        generation = indexer.request_refresh()
        memory.invalidate_code_context(
            code_changed=True,
            refresh_generation=generation,
        )

        # Dirty retrieval bypasses the stale durable index immediately.
        immediate = memory.get_code_context("neon_fresh_symbol")
        assert "fresh.py" in immediate
        assert "neon_fresh_symbol" in immediate

        assert indexer.wait_for_idle(timeout=5)
        memory.begin_run("after-refresh")
        persisted = memory.get_code_context("neon_fresh_symbol")
        assert "fresh.py" in persisted
        assert indexer.wait_for_idle(timeout=5)
        memory.get_code_context("neon_fresh_symbol")
        assert memory.rag_cache_status()["dirty"] is False
    finally:
        indexer.stop()


def test_background_indexer_debounces_and_recovers_from_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import RxyCode.RxyCode1_1_0.rag.index as index_mod

    calls: list[int] = []

    def index_once_then_succeed(_root: Path) -> int:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("temporary index failure")
        return 7

    monkeypatch.setattr(index_mod, "index_project", index_once_then_succeed)
    indexer = index_mod.BackgroundIndexer(tmp_path, debounce_seconds=0.04)
    indexer.start(initial_delay=0)
    try:
        assert indexer.wait_for_idle(timeout=2)
        failed = indexer.status()
        assert failed["runs_failed"] == 1
        assert failed["worker_alive"] is True
        assert failed["last_error_type"] == "RuntimeError"

        for _ in range(30):
            indexer.request_refresh()
        assert indexer.wait_for_idle(timeout=2)
        recovered = indexer.status()
        assert calls == [1, 2]
        assert recovered["runs_succeeded"] == 1
        assert recovered["last_error_type"] is None
        assert recovered["state"] == "idle"
    finally:
        assert indexer.stop()


def test_disabled_start_creates_no_worker_or_registry_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import RxyCode.RxyCode1_1_0.rag.index as index_mod

    monkeypatch.setattr(index_mod, "load_config", lambda: {"rag": {"enabled": False}})
    before = dict(index_mod._background_indexers)

    assert index_mod.start_background_indexer(tmp_path, delay=0) is None
    assert index_mod._background_indexers == before


def test_disabled_agent_does_not_expose_code_search_tool() -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = AgentV2.__new__(AgentV2)
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._tool_orchestrator = ToolOrchestrator()

    agent._register_tools()

    assert "code_search" not in agent._tool_orchestrator._registry
    assert all(tool.name != "code_search" for tool in agent._get_core_tools())


def test_start_background_indexer_reuses_one_worker_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import RxyCode.RxyCode1_1_0.rag.index as index_mod

    monkeypatch.setattr(
        index_mod,
        "load_config",
        lambda: {
            "rag": {
                "enabled": True,
                "refresh_debounce_seconds": 0.02,
            }
        },
    )
    index_mod.stop_background_indexer(tmp_path)
    first = index_mod.start_background_indexer(tmp_path, delay=60)
    second = index_mod.start_background_indexer(tmp_path, delay=60)
    try:
        assert first is not None
        assert second is first
        assert first.status()["worker_alive"] is True
    finally:
        assert index_mod.stop_background_indexer(tmp_path) == 1


@pytest.mark.asyncio
async def test_production_tool_hook_invalidates_and_schedules_only_successful_write(
    tmp_path: Path,
) -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.write import write_tool

    memory = MagicMock()
    memory._rag_enabled = True
    indexer = MagicMock()
    indexer.request_refresh.return_value = 23
    agent = AgentV2.__new__(AgentV2)
    agent._memory = memory
    agent._rag_indexer_thread = indexer
    hooks = HookRegistry()
    hooks.register("after", agent._handle_rag_tool_after)

    orchestrator = ToolOrchestrator()
    orchestrator.register("write", write_tool)
    audit: list[dict] = []
    token = orchestrator.bind_event_hooks(hooks, audit)
    try:
        result = await orchestrator.execute_tool(
            "write",
            {"filePath": str(tmp_path / "new.py"), "content": "value = 1\n"},
            config={"safety": {"enabled": False}},
        )
    finally:
        orchestrator.reset_event_hooks(token)

    assert result.startswith("[wrote ")
    indexer.request_refresh.assert_called_once_with()
    memory.invalidate_code_context.assert_called_once_with(
        code_changed=True,
        refresh_generation=23,
    )

    await hooks.emit(
        "after", "tool_call", {"tool": "write", "status": "error"}
    )
    await hooks.emit(
        "after", "tool_call", {"tool": "read", "status": "ok"}
    )
    indexer.request_refresh.assert_called_once_with()


@pytest.mark.asyncio
async def test_top_level_agent_run_resets_memory_rag_cache(isolated_runtime) -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "rag-run-session"
    agent._tool_tracer = None
    agent._hooks = None
    agent._memory = MagicMock()

    async def run_impl(_input: str, _mode: str) -> str:
        return "done"

    agent._run_impl = run_impl
    result = await agent._run_observed("query", "build", "rag-run-1")

    assert result == "done"
    agent._memory.begin_run.assert_called_once_with("rag-run-1")


def test_agent_runtime_status_reports_live_rag_worker_and_cache() -> None:
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._cfg = {
        "execution": {
            "tool_timeout_seconds": 1800,
            "pipeline_soft_budget_seconds": 3600,
            "task_stall_timeout_seconds": 0,
            "task_max_time_seconds": 7200,
        },
        "context": {},
        "observability": {
            "trajectory_retention_runs": 11,
            "trace_retention_runs": 12,
            "audit_max_bytes": 4096,
            "audit_backup_count": 3,
        },
    }
    agent._session_id = "status-session"
    agent._checkpoint_store = None
    agent._tool_journal = None
    agent._rate_limiter = None
    agent._last_hook_audit = []
    agent._last_failure_attribution = {"tool_error": 1}
    agent._model_router = SimpleNamespace(configured_roles=[])
    agent._memory = MagicMock()
    agent._memory._rag_enabled = True
    agent._memory.rag_cache_status.return_value = {
        "enabled": True,
        "entries": 2,
        "limit": 8,
        "ttl_seconds": 30,
        "dirty": True,
    }
    agent._rag_indexer_thread = MagicMock()
    agent._rag_indexer_thread.status.return_value = {
        "state": "scheduled",
        "worker_alive": True,
        "requested_generation": 5,
        "last_success_generation": 4,
        "runs_failed": 1,
    }

    status = agent.runtime_status()
    rag = status["rag"]

    assert rag["indexer_alive"] is True
    assert rag["indexer"]["state"] == "scheduled"
    assert rag["indexer"]["runs_failed"] == 1
    assert rag["context_cache"]["dirty"] is True
    assert status["session"]["id"] == "status-session"
    assert status["session"]["working_directory"]
    assert status["limits"]["task_stall_timeout_seconds"] == 0
    assert status["limits"]["task_max_time_seconds"] == 7200
    assert status["observability"] == {
        "trajectory_retention_runs": 11,
        "trace_retention_runs": 12,
        "audit_max_bytes": 4096,
        "audit_backup_count": 3,
        "last_failure_attribution": {"tool_error": 1},
    }
