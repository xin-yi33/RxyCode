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
    child = next(node for node in tree["nodes"] if node["parent_id"])
    parent = next(node for node in tree["nodes"] if node["id"] == child["parent_id"])
    cancelled = cancel_child(tree, child["id"])
    after_child = next(node for node in cancelled["nodes"] if node["id"] == child["id"])
    after_parent = next(node for node in cancelled["nodes"] if node["id"] == parent["id"])
    assert after_child["status"] == "cancelled"
    assert after_child["role"] == child["role"]
    assert after_parent["status"] == parent["status"]
    store = EventStore()
    before = store.latest_cursor()
    from rxycode_worker.agent_events import accept_steer

    steered = accept_steer(run_id=tree["run_id"], text="do not write the store", store=store)
    assert steered["store_written"] is False
    assert store.latest_cursor() == before
