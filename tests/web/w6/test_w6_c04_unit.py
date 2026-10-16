"""WEB-W6-C04. A real team run projects parent and child status."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agents.coordinator import Coordinator
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.core.subagents.events import EventStore
from RxyCode.RxyCode1_1_0.protocol.agents import TeamEvent

REPO = Path(__file__).resolve().parents[3]
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
if str(_WORKER) not in sys.path:
    sys.path.insert(0, str(_WORKER))


class _Pass:
    def run(self, stage, result):
        return type("V", (), {"passed": True, "findings": []})()


def _run(tmp_path: Path, session_id: str) -> tuple[list[object], list[object]]:
    emitted: list[object] = []
    coord = Coordinator(
        Session(session_id=session_id, workspace_root=tmp_path, emit=emitted.append),
        verifier=_Pass(),
    )
    coord.verdict_allows = lambda _digest: True  # type: ignore[method-assign]
    asyncio.run(coord.run_team(load_builtin_team(), "add a health endpoint"))
    return coord._tracer.get_spans(), emitted


_MANAGER = None
_CANCELLED: dict[str, bool] = {"hit": False}


def _live_child() -> tuple[str, str]:
    """A real child session whose runtime cancel is what the tree reflects."""
    global _MANAGER
    from protocol.subagents import (
        AgentDefinition,
        AgentMode,
        PermissionSpec,
        PermissionVerdict,
        TaskPermissionSpec,
        TaskRequest,
        ToolPermission,
        TriggerKind,
    )
    from RxyCode.RxyCode1_1_0.core.subagents.definitions import AgentDefinitionRegistry
    from RxyCode.RxyCode1_1_0.core.subagents.manager import ChildSessionManager
    from RxyCode.RxyCode1_1_0.core.subagents.modes import SubagentConfig, SubagentFeatureFlags
    from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session

    registry = AgentDefinitionRegistry()
    registry.register_builtin(
        AgentDefinition(
            id="explore",
            description="read",
            mode=AgentMode.SUBAGENT,
            steps=4,
            permission=PermissionSpec(
                read=ToolPermission.from_raw({"**": "allow"}),
                edit=ToolPermission.from_raw({"**": "deny"}),
                external_directory=PermissionVerdict.DENY,
            ),
            task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
        )
    )
    manager = ChildSessionManager(
        registry=registry,
        config=SubagentConfig(
            flags=SubagentFeatureFlags(
                subagents_enabled=True,
                subagents_task=True,
                subagents_mention=True,
                subagents_child_tasks=True,
            )
        ),
    )
    request = TaskRequest(
        parent_session_id="ses_primary_1",
        agent_id="explore",
        prompt="inspect",
        trigger=TriggerKind.AUTOMATIC,
    )
    definition = registry.get("explore")
    session = create_child_session(
        request,
        manager._compute_policy(request, definition),
        definition=definition,
    )
    session.root_session_id = "ses_primary_1"
    manager.get_tree("ses_primary_1").add(session)

    class _Runtime:
        def cancel(self) -> None:
            _CANCELLED["hit"] = True

    manager._live_runtimes[session.session_id] = _Runtime()
    _MANAGER = manager
    return session.session_id, "ses_primary_1"


async def _steer(run_id: str, text: str, store: EventStore) -> dict[str, object]:
    from appserver.agent_worker import AgentWorker
    from rxycode_worker.agent_events import accept_steer

    worker = AgentWorker()
    worker._session_id = run_id

    async def _hold() -> None:
        await asyncio.sleep(30)

    worker._run_task = asyncio.create_task(_hold())
    try:
        return await accept_steer(run_id=run_id, text=text, worker=worker, store=store)
    finally:
        task = worker._run_task
        if task is not None:
            task.cancel()


def test_w6_c04_contract(tmp_path: Path) -> None:
    """Child start and end keep the real parent id and a status."""
    from rxycode_worker.agent_events import explain_spend, project_run

    assert (REPO / "core" / "agents").is_dir()
    spans, emitted = _run(tmp_path, "ses-w6c04")
    events = [item for item in emitted if isinstance(item, TeamEvent)]
    assert spans
    assert events
    tree = project_run(spans=spans, events=events)
    span_ids = {span.span_id for span in spans}
    children = [node for node in tree["nodes"] if node["parent_id"]]
    assert children
    for node in children:
        assert node["parent_id"] in span_ids
        assert node["id"] in span_ids
        assert node["status"] in {"running", "completed", "failed", "cancelled"}
        assert node["role"]
    spent = explain_spend(spans)
    assert spent["total_tokens"] == sum(int(span.tokens or 0) for span in spans)
    assert spent["solo_tokens"] + spent["team_tokens"] == spent["total_tokens"]
    assert spent["lines"]


def test_w6_c04_negative(tmp_path: Path) -> None:
    """A child intermediate note stays out of the parent final answer."""
    from rxycode_worker.agent_events import cancel_child, final_answer, project_run

    spans, emitted = _run(tmp_path, "ses-w6c04-neg")
    events = [item for item in emitted if isinstance(item, TeamEvent)]
    tree = project_run(spans=spans, events=events)
    marker = "secret-child-draft-99"
    answer = final_answer(
        parent_text="ship the health endpoint",
        child_events=[{"kind": "intermediate", "text": marker, "name": "reasoning.summary"}],
    )
    assert answer["text"] == "ship the health endpoint"
    assert marker not in answer["text"]
    child_id, parent_id = _live_child()
    view = {
        "run_id": "ses_primary_1",
        "nodes": [
            {"id": parent_id, "parent_id": "", "role": "primary", "status": "running", "tokens": 1},
            {
                "id": child_id,
                "parent_id": parent_id,
                "role": "explore",
                "status": "running",
                "tokens": 2,
            },
        ],
    }
    cancelled = cancel_child(view, child_id, manager=_MANAGER)
    after_child = next(node for node in cancelled["nodes"] if node["id"] == child_id)
    after_parent = next(node for node in cancelled["nodes"] if node["id"] == parent_id)
    assert str(cancelled["outcome"]).startswith("cancelled")
    assert after_child["status"] == "cancelled"
    assert after_child["role"] == "explore"
    assert after_parent["status"] == "running"
    assert _CANCELLED["hit"] is True
    store = EventStore()
    before = store.latest_cursor()
    steered = asyncio.run(_steer(str(tree["run_id"]), "do not write the store", store))
    assert steered["store_written"] is False
    assert steered["accepted"] is True
    assert store.latest_cursor() == before
