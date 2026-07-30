"""
Tests for core/graph.py route_next() token estimation.

The estimate must account for memory_context + all task node result text
+ conversation_history text (total chars // 3), not just memory_context.
"""
import pytest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock


def _make_state(memory_ctx="", results=None, history=None):
    from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree, TaskStatus

    root = TaskNode(title="goal", description="g")
    root.status = TaskStatus.PASSED
    tree = TaskTree(goal_id=root.id)
    tree.nodes[root.id] = root

    for i, res in enumerate(results or []):
        leaf = TaskNode(
            title=f"leaf{i}",
            description="d",
            parent_id=root.id,
            depth=1,
        )
        leaf.status = TaskStatus.PASSED
        leaf.result = res
        root.children_ids.append(leaf.id)
        tree.nodes[leaf.id] = leaf

    # Always keep one PENDING leaf so the tree is never "complete" —
    # otherwise route_next short-circuits to "synthesize" before the
    # context-size check runs.
    pending = TaskNode(
        title="pending",
        description="d",
        parent_id=root.id,
        depth=1,
    )
    root.children_ids.append(pending.id)
    tree.nodes[pending.id] = pending

    return {
        "user_input": "x",
        "session_id": "s",
        "task_tree": tree,
        "memory_context": memory_ctx,
        "conversation_history": history or [],
        "current_task_id": None,
        "execution_results": [],
        "final_response": None,
        "phase": "executing",
        "error": None,
        "_llm": MagicMock(),
        "_memory": MagicMock(),
        "_tool_orchestrator": None,
        "_tui": None,
    }


class TestRouteNextTokenEstimate:
    def test_small_context_executes(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        state = _make_state(memory_ctx="small")
        assert route_next(state) == "execute"

    def test_large_memory_context_triggers_compress(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        big = "x" * (232_001 * 3)
        state = _make_state(memory_ctx=big)
        assert route_next(state) == "compress"

    def test_large_task_results_trigger_compress(self):
        """memory_context alone is small, but task results push it over."""
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        big_result = "r" * (232_001 * 3)
        state = _make_state(memory_ctx="tiny", results=[big_result])
        assert route_next(state) == "compress"

    def test_large_conversation_history_triggers_compress(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        big_msg = "h" * (232_001 * 3)
        state = _make_state(
            memory_ctx="tiny",
            history=[{"role": "user", "content": big_msg}],
        )
        assert route_next(state) == "compress"

    def test_combined_sources_trigger_compress(self):
        """Each source is below threshold alone; combined they exceed it."""
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        part = "y" * (100_000 * 3)  # ~100k tokens each
        state = _make_state(
            memory_ctx=part,
            results=[part],
            history=[{"role": "assistant", "content": part}],
        )
        assert route_next(state) == "compress"

    def test_repeated_no_progress_compression_fails_honestly(self):
        from RxyCode.RxyCode1_1_0.core.graph import route_next

        state = _make_state(memory_ctx="x" * (232_001 * 3))
        state["compression_count"] = 2

        assert route_next(state) == "error"
        assert "compression attempts" in state["error"]


@pytest.mark.asyncio
async def test_compressor_archives_full_result_and_bounds_graph_copy(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "context:\n"
        "  max_task_result_chars: 1000\n"
        "  graph_context_token_limit: 2000\n",
        encoding="utf-8",
    )
    from RxyCode.RxyCode1_1_0.core.graph import compressor_node

    state = _make_state(results=["r" * 6000])
    state["compression_count"] = 0
    state["_memory"] = MagicMock(
        compress_if_needed=AsyncMock(return_value="bounded memory")
    )

    update = await compressor_node(state)

    compacted = next(
        task for task in update["task_tree"].nodes.values()
        if task.result_artifact
    )
    assert len(compacted.result) < 1200
    assert "context compacted" in compacted.result
    assert compacted.result_artifact
    assert open(compacted.result_artifact, encoding="utf-8").read() == "r" * 6000
    assert update["compression_count"] == 1
