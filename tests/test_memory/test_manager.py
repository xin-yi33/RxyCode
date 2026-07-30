"""
Tests for memory/manager.py - MemoryManager orchestration.

Covers: add_interaction, context retrieval, save/load session, compression.
"""
import asyncio
from unittest.mock import MagicMock


class TestMemoryManager:
    def _make(self, tmp_path, monkeypatch, session_id=None):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text("models: []", encoding="utf-8")
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager
        return MemoryManager(session_id=session_id)

    def test_init_creates_short_term(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        assert mm.short_term is not None

    def test_init_creates_long_term(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        assert mm.long_term is not None

    def test_init_creates_compressor(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        assert mm._compressor is not None

    def test_add_interaction(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        assert mm.short_term.message_count == 2

    def test_add_interaction_increments_turns(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("q1", "a1")
        mm.add_interaction("q2", "a2")
        assert mm.short_term.turn_count == 2

    def test_get_context_for_prompt_empty(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        ctx = mm.get_context_for_prompt()
        assert ctx == ""

    def test_get_context_for_prompt_with_messages(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        ctx = mm.get_context_for_prompt()
        assert "hello" in ctx
        assert "world" in ctx

    def test_get_context_for_prompt_with_query(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("python is great", "yes it is")
        ctx = mm.get_context_for_prompt(query="python")
        assert isinstance(ctx, str)

    def test_get_context_for_prompt_with_long_term(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.long_term.save_session_context("remembered context")
        ctx = mm.get_context_for_prompt()
        assert "remembered context" in ctx

    def test_get_context_for_prompt_truncates_long_term(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.long_term.save_session_context("x" * 3000)
        ctx = mm.get_context_for_prompt()
        assert "..." in ctx

    def test_save_session(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        mm.save_session()
        history = mm.long_term.load_history()
        assert len(history) == 2

    def test_save_session_empty(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.save_session()
        # No messages to save
        history = mm.long_term.load_history()
        assert history == []

    def test_load_session(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        mm.save_session()
        mm.clear()
        mm.load_session()
        assert mm.short_term.message_count > 0

    def test_clear(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        mm.clear()
        assert mm.short_term.message_count == 0

    def test_initialize_is_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        result = asyncio.run(mm.initialize())
        assert result is None

    def test_close_is_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        result = asyncio.run(mm.close())
        assert result is None

    def test_get_context_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch, "session1")
        mm.add_interaction("hello", "world")
        result = asyncio.run(mm.get_context("session1"))
        assert isinstance(result, str)

    def test_get_context_async_forwards_retrieval_query(
        self, tmp_path, monkeypatch,
    ):
        mm = self._make(tmp_path, monkeypatch, "session1")
        asyncio.run(mm.store_execution(
            "session1", "task1", "PostgreSQL migration completed",
        ))

        restarted = self._make(tmp_path, monkeypatch, "session1")
        result = asyncio.run(restarted.get_context(
            "session1", "PostgreSQL migration",
        ))

        assert "PostgreSQL migration completed" in result
        assert "Relevant verified experience" in result

    def test_get_task_context_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        result = asyncio.run(mm.get_task_context("session1", "task1"))
        assert isinstance(result, str)

    def test_verified_leaf_results_do_not_create_conversation_turns(
        self, tmp_path, monkeypatch,
    ):
        mm = self._make(tmp_path, monkeypatch, "session1")

        asyncio.run(mm.store_execution(
            "session1", "leaf-1", "PostgreSQL migration completed",
        ))
        asyncio.run(mm.store_execution(
            "session1", "leaf-2", "Rollback verification passed",
        ))

        assert mm.short_term.message_count == 0
        assert mm.short_term.turn_count == 0

        restarted = self._make(tmp_path, monkeypatch, "session1")
        migration = restarted.get_retrieval_context("PostgreSQL migration")
        rollback = restarted.get_retrieval_context("rollback verification")

        assert "PostgreSQL migration completed" in migration
        assert "Rollback verification passed" in rollback
        assert restarted.short_term.message_count == 0

    def test_log_error_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        asyncio.run(mm.log_error("session1", "task1", "error occurred"))
        # Error should be in the error log
        error_file = mm.long_term._session_dir / "errors.log"
        assert error_file.exists()

    def test_compress_if_needed_async(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        mm.add_interaction("hello", "world")
        result = asyncio.run(mm.compress_if_needed("session1"))
        assert isinstance(result, str)

    def test_count_tokens(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        tokens = mm.count_tokens("hello world")
        assert tokens > 0

    def test_count_tokens_empty(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        tokens = mm.count_tokens("")
        assert tokens == 0

    def test_threshold_default(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch, "session1")
        assert 2 <= mm.threshold <= mm.short_term.window_size * 2

    def test_current_query_default(self, tmp_path, monkeypatch):
        mm = self._make(tmp_path, monkeypatch)
        assert mm._current_query == ""

    def test_reads_memory_config_and_clamps_unreachable_threshold(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "memory:\n  short_term_window: 4\n  long_term_threshold: 50\n",
            encoding="utf-8",
        )
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        mm = MemoryManager()

        assert mm.short_term.window_size == 4
        assert mm.threshold == 8

    def test_message_threshold_compacts_and_persists_old_context(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "memory:\n  short_term_window: 6\n  long_term_threshold: 8\n",
            encoding="utf-8",
        )
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        mm = MemoryManager()
        for index in range(4):
            mm.add_interaction(f"question {index}", f"answer {index}")

        assert mm.short_term.message_count < mm.threshold
        assert "question 0" in mm.long_term.load_session_context()
        assert "question 3" in mm.get_context_for_prompt()

    def test_minimum_window_archives_without_deque_data_loss(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "memory:\n  short_term_window: 1\n  long_term_threshold: 2\n",
            encoding="utf-8",
        )
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        mm = MemoryManager()
        mm.add_interaction("minimum-window question", "minimum-window answer")

        assert mm.short_term.message_count == 0
        archived = mm.long_term.load_session_context()
        assert "minimum-window question" in archived
        assert "minimum-window answer" in archived

    def test_verified_and_failed_experiences_are_persisted_and_retrieved(
        self, tmp_path, monkeypatch,
    ):
        mm = self._make(tmp_path, monkeypatch, "session1")

        asyncio.run(mm.store_execution("session1", "task1", "FastAPI database fix succeeded"))
        asyncio.run(mm.log_error("session1", "task2", "Redis connection timeout failure"))

        restarted = self._make(tmp_path, monkeypatch, "session1")
        success_ctx = restarted.get_context_for_prompt("FastAPI database")
        failure_ctx = restarted.get_context_for_prompt("Redis timeout")

        assert "FastAPI database fix succeeded" in success_ctx
        assert "outcome=success" in success_ctx
        assert "Redis connection timeout failure" in failure_ctx
        assert "outcome=failed" in failure_ctx

    def test_structured_plan_experience_is_redacted_deduplicated_and_reused(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "memory:\n  experience_cross_session: false\n",
            encoding="utf-8",
        )
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        first = MemoryManager(session_id="session-plan")
        kwargs = {
            "plan_summary": "Database migration rollback plan password=swordfish",
            "failure_type": "tool_error",
            "reason": "Redis migration timed out with Bearer supersecrettoken",
            "corrective_action": "Retry the idempotent migration after health check",
            "lessons": ["Verify Redis health before database migration"],
            "outcome": "failed",
            "session_id": "session-plan",
        }
        assert asyncio.run(first.store_plan_experience(**kwargs)) is True
        assert asyncio.run(first.store_plan_experience(**kwargs)) is False

        restarted = MemoryManager(session_id="session-plan")
        planner_context = asyncio.run(restarted.get_context(
            "session-plan",
            "database migration Redis rollback",
        ))
        task = TaskNode(
            id="migration",
            title="Database migration rollback",
            description="Recover after Redis timeout",
        )
        executor_context = asyncio.run(restarted.get_task_context(
            "session-plan",
            task.id,
            tree=TaskTree(goal_id=task.id, nodes={task.id: task}),
        ))

        assert "[Relevant verified experience]" in planner_context
        assert '"failure_type":"tool_error"' in planner_context
        assert "[Relevant verified experience]" in executor_context
        assert "Verify Redis health" in executor_context
        assert "swordfish" not in planner_context
        assert "supersecrettoken" not in planner_context
        records = restarted.experience.search(
            "database migration Redis",
            kind="plan_reflection",
            outcome="failed",
            session="session-plan",
        )
        assert len(records) == 1
        assert '"session":"session-plan"' in records[0].text
        assert '"project":' in records[0].text
        isolated = MemoryManager(session_id="other-session")
        assert "tool_error" not in isolated.get_context_for_prompt(
            "database migration Redis rollback"
        )

    def test_enabled_code_rag_is_injected_with_configured_bounds(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "rag:\n"
            "  enabled: true\n"
            "  top_k: 3\n"
            "  max_context_chars: 321\n",
            encoding="utf-8",
        )
        import RxyCode.RxyCode1_1_0.rag.search as rag_search
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        retrieve = MagicMock(return_value="[1] app.py:10 parser implementation")
        monkeypatch.setattr(rag_search, "retrieve_context", retrieve)
        mm = MemoryManager()

        first = asyncio.run(mm.get_context("s1", "find parser implementation"))
        second = asyncio.run(mm.get_context("s1", "find parser implementation"))

        assert "[Relevant code context]" in first
        assert "app.py:10" in first
        assert second == first
        retrieve.assert_called_once_with(
            "find parser implementation",
            root=mm._project_root,
            top_k=3,
            max_chars=321,
            allow_network=False,
        )

    def test_code_rag_disabled_or_empty_query_has_no_side_effect(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "rag:\n  enabled: false\n",
            encoding="utf-8",
        )
        import RxyCode.RxyCode1_1_0.rag.search as rag_search
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        retrieve = MagicMock(side_effect=AssertionError("RAG must stay idle"))
        monkeypatch.setattr(rag_search, "retrieve_context", retrieve)
        disabled = MemoryManager()
        assert asyncio.run(disabled.get_context("s1", "query")) == ""

        (tmp_path / "config.yaml").write_text(
            "rag:\n  enabled: true\n",
            encoding="utf-8",
        )
        enabled = MemoryManager()
        assert asyncio.run(enabled.get_context("s1", "")) == ""
        retrieve.assert_not_called()

    def test_code_rag_cache_evicts_lru_without_disabling_future_queries(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "rag:\n"
            "  enabled: true\n"
            "  context_cache_entries: 2\n",
            encoding="utf-8",
        )
        import RxyCode.RxyCode1_1_0.rag.search as rag_search
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        retrieve = MagicMock(side_effect=RuntimeError("broken local index"))
        monkeypatch.setattr(rag_search, "retrieve_context", retrieve)
        mm = MemoryManager()

        assert mm.get_context_for_prompt("query one") == ""
        assert mm.get_context_for_prompt("query one") == ""
        assert mm.get_context_for_prompt("query two") == ""
        assert mm.get_context_for_prompt("query three") == ""

        assert retrieve.call_count == 3
        assert len(mm._rag_context_cache) == 2
        assert list(mm._rag_context_cache) == ["query two", "query three"]

    def test_task_context_injects_code_rag_from_current_task(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            "rag:\n  enabled: true\n  top_k: 2\n  max_chars: 222\n",
            encoding="utf-8",
        )
        import RxyCode.RxyCode1_1_0.rag.search as rag_search
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        retrieve = MagicMock(return_value="[1] db.py:7 migration helper")
        monkeypatch.setattr(rag_search, "retrieve_context", retrieve)
        task = TaskNode(
            id="migration", title="Implement migration",
            description="Add database migration helper",
            requirement="Keep rollback support",
        )
        tree = TaskTree(goal_id=task.id, nodes={task.id: task})

        result = asyncio.run(MemoryManager().get_task_context(
            "s1", task.id, tree=tree,
        ))

        assert "[Relevant code context]" in result
        assert "db.py:7 migration helper" in result
        query = retrieve.call_args.args[0]
        assert "Implement migration" in query
        assert "database migration helper" in query
        assert "Keep rollback support" in query
        assert retrieve.call_args.kwargs["top_k"] == 2
        assert retrieve.call_args.kwargs["max_chars"] == 222
