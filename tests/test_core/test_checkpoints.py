"""Persistent execution checkpoint contract tests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskStatus, TaskTree


def _state(*, session_id: str = "session-1", status=TaskStatus.PENDING) -> dict:
    root = TaskNode(id="root", title="Build feature", status=status)
    tree = TaskTree(goal_id=root.id, nodes={root.id: root})
    return {
        "user_input": "Build feature",
        "session_id": session_id,
        "task_tree": tree,
        "memory_context": "bounded context",
        "conversation_history": [{"role": "user", "content": "hello"}],
        "current_task_id": root.id,
        "execution_results": [
            {
                "status": TaskStatus.PASSED,
                "at": datetime(2026, 7, 25, 8, 30, tzinfo=timezone.utc),
                "node": TaskNode(id="result", title="Result"),
            }
        ],
        "parallel_tasks": [],
        "parallel_requested": False,
        "reflections": [],
        "failure_attribution": {},
        "replan_count": 0,
        "reflection_action": None,
        "final_verification": None,
        "compression_count": 0,
        "final_response": None,
        "phase": "executing",
        "error": None,
    }


@pytest.fixture
def checkpoint_dir(tmp_path, monkeypatch):
    import RxyCode.RxyCode1_1_0.core.checkpoints as checkpoints

    monkeypatch.setattr(checkpoints, "get_data_dir", lambda: tmp_path)
    return tmp_path / "checkpoints"


def test_checkpoint_id_is_stable_and_scoped_by_session_input_and_mode():
    from RxyCode.RxyCode1_1_0.core.checkpoints import stable_checkpoint_id

    checkpoint_id = stable_checkpoint_id("s1", "Build it", "plan_execute")

    assert checkpoint_id == stable_checkpoint_id("s1", "Build it", "plan_execute")
    assert checkpoint_id != stable_checkpoint_id("s2", "Build it", "plan_execute")
    assert checkpoint_id != stable_checkpoint_id("s1", "Build that", "plan_execute")
    assert checkpoint_id != stable_checkpoint_id("s1", "Build it", "fast")
    assert re.fullmatch(r"cp_[0-9a-f]{32}", checkpoint_id)


def test_save_is_atomic_json_and_serializes_only_durable_fields(
    checkpoint_dir, monkeypatch
):
    import RxyCode.RxyCode1_1_0.core.checkpoints as checkpoints

    replace = MagicMock(wraps=checkpoints.os.replace)
    monkeypatch.setattr(checkpoints.os, "replace", replace)
    sentinel = object()
    state = _state()
    state["execution_results"][0]["_memory"] = "nested-runtime-secret"
    state.update(
        {
            "_llm": sentinel,
            "_memory": sentinel,
            "_tui": sentinel,
            "_tool_orchestrator": sentinel,
            "_tracer": sentinel,
            "custom_public_but_not_durable": sentinel,
        }
    )
    store = checkpoints.CheckpointStore(retention_limit=10)

    saved = store.save(
        session_id="session-1",
        user_input="Build feature",
        mode="plan_execute",
        state=state,
    )

    path = checkpoint_dir / f"{saved['checkpoint_id']}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert replace.call_count == 1
    assert list(checkpoint_dir.glob("*.tmp")) == []
    assert set(document["state"]) == checkpoints.DURABLE_STATE_FIELDS
    assert not any(key.startswith("_") for key in document["state"])
    assert "custom_public_but_not_durable" not in document["state"]
    assert "nested-runtime-secret" not in path.read_text(encoding="utf-8")
    assert document["state"]["task_tree"]["nodes"]["root"]["status"] == "pending"
    assert document["state"]["execution_results"][0]["status"] == "passed"
    assert document["state"]["execution_results"][0]["at"].endswith("+00:00")


def test_atomic_replace_failure_preserves_previous_snapshot_and_cleans_temp(
    checkpoint_dir, monkeypatch
):
    import RxyCode.RxyCode1_1_0.core.checkpoints as checkpoints

    store = checkpoints.CheckpointStore()
    saved = store.save("s1", "Build", "plan_execute", _state(session_id="s1"))
    path = checkpoint_dir / f"{saved['checkpoint_id']}.json"
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(checkpoints.os, "replace", fail_replace)
    changed = _state(session_id="s1")
    changed["phase"] = "validating"

    with pytest.raises(OSError, match="replace failed"):
        store.save("s1", "Build", "plan_execute", changed)

    assert path.read_bytes() == before
    assert list(checkpoint_dir.glob("*.tmp")) == []


def test_load_recovers_interrupted_statuses_and_persists_audit_notes(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    root = TaskNode(id="root", title="Root")
    running = TaskNode(
        id="running",
        title="Running",
        parent_id=root.id,
        status=TaskStatus.RUNNING,
    )
    replanning = TaskNode(
        id="replanning",
        title="Replanning",
        parent_id=root.id,
        status=TaskStatus.RE_PLANNING,
    )
    root.children_ids = [running.id, replanning.id]
    state = _state()
    state["task_tree"] = TaskTree(
        goal_id=root.id,
        nodes={node.id: node for node in (root, running, replanning)},
    )
    store = CheckpointStore()
    saved = store.save("s1", "Build", "plan_execute", state)

    loaded = store.load(saved["checkpoint_id"])

    nodes = loaded["state"]["task_tree"]["nodes"]
    assert nodes["running"]["status"] == "pending"
    assert nodes["replanning"]["status"] == "pending"
    assert len(loaded["recovery_notes"]) == 2
    assert {note["from_status"] for note in loaded["recovery_notes"]} == {
        "running",
        "re_planning",
    }
    assert all(note["event"] == "interrupted_task_recovered" for note in loaded["recovery_notes"])
    assert "checkpoint recovery" in nodes["running"]["error_history"][-1].lower()
    assert loaded["state"]["phase"] == "executing"
    assert loaded["state"]["current_task_id"] is None

    loaded_again = store.load(saved["checkpoint_id"])
    assert len(loaded_again["recovery_notes"]) == 2


def test_load_preserves_completed_executor_result_for_validation(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    state = _state(status=TaskStatus.RUNNING)
    state["phase"] = "validating"
    state["task_tree"].nodes["root"].result = "tool already completed"
    store = CheckpointStore()
    saved = store.save("s1", "Build", "plan_execute", state)

    loaded = store.load(saved["checkpoint_id"])

    assert loaded["state"]["phase"] == "validating"
    assert loaded["state"]["task_tree"]["nodes"]["root"]["status"] == "running"
    assert loaded["recovery_notes"] == []


def test_load_list_mark_complete_and_reset(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore()
    first = store.save("s1", "First", "plan_execute", _state(session_id="s1"))
    second = store.save("s1", "Second", "fast", _state(session_id="s1"))
    store.save("s2", "Third", "plan_execute", _state(session_id="s2"))

    assert store.load(first["checkpoint_id"])["state"]["task_tree"]["goal_id"] == "root"
    assert store.mark_complete(first["checkpoint_id"]) is True
    assert store.mark_complete("cp_" + "0" * 32) is False
    assert store.load(first["checkpoint_id"])["completed"] is True
    assert len(store.list()) == 3
    assert [item["checkpoint_id"] for item in store.list(session_id="s1", include_completed=False)] == [
        second["checkpoint_id"]
    ]

    assert store.reset(checkpoint_id=second["checkpoint_id"]) == 1
    assert store.load(second["checkpoint_id"]) is None
    assert store.reset(session_id="s1") == 1
    assert store.reset(session_id="s2") == 1
    assert store.list() == []


def test_corrupt_checkpoint_is_quarantined_without_breaking_list(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import (
        CheckpointStore,
        stable_checkpoint_id,
    )

    store = CheckpointStore()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = stable_checkpoint_id("s1", "broken", "plan_execute")
    broken = checkpoint_dir / f"{checkpoint_id}.json"
    broken.write_text('{"state": ', encoding="utf-8")

    assert store.load(checkpoint_id) is None
    assert not broken.exists()
    quarantined = list((checkpoint_dir / "corrupt").glob(f"{checkpoint_id}*.json"))
    assert len(quarantined) == 1
    assert store.list() == []


def test_retention_is_hard_bounded(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore(retention_limit=2)
    first = store.save("s1", "First", "plan_execute", _state(session_id="s1"))
    second = store.save("s2", "Second", "plan_execute", _state(session_id="s2"))
    store.mark_complete(first["checkpoint_id"])
    store.mark_complete(second["checkpoint_id"])
    third = store.save("s3", "Third", "plan_execute", _state(session_id="s3"))

    ids = {item["checkpoint_id"] for item in store.list()}
    assert len(ids) == 2
    assert first["checkpoint_id"] not in ids
    assert ids == {second["checkpoint_id"], third["checkpoint_id"]}


def test_retention_never_evicts_active_replay_roots(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore(retention_limit=2)
    first = store.save("s1", "First", "build", _state(session_id="s1"))
    second = store.save("s2", "Second", "build", _state(session_id="s2"))
    third = store.save("s3", "Third", "build", _state(session_id="s3"))

    assert {item["checkpoint_id"] for item in store.list()} == {
        first["checkpoint_id"],
        second["checkpoint_id"],
        third["checkpoint_id"],
    }


def test_checkpoint_paths_reject_traversal(checkpoint_dir):
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    store = CheckpointStore()
    with pytest.raises(ValueError, match="checkpoint_id"):
        store.load("../outside")
    with pytest.raises(ValueError, match="checkpoint_id"):
        store.reset(checkpoint_id="C:\\outside")


def test_constructor_rejects_unbounded_or_invalid_retention():
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore

    with pytest.raises(ValueError, match="retention_limit"):
        CheckpointStore(retention_limit=0)
