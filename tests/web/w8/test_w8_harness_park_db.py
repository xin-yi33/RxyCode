"""W8 Harness park/resume on real Postgres (no OS sandbox needed).

The confined turn parks through the parent control handlers with a Harness
checkpoint attached. These tests drive the REAL parent handlers, the durable
approval/question services and the answer/consume transitions. Nothing in
the child executes; the pause/resume contract is what is under test.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
for _entry in (
    REPO,
    REPO / "packages" / "rxycode-server" / "src",
    REPO / "packages" / "rxycode-worker" / "src",
    REPO / "packages" / "rxycode-runner" / "src",
):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


def _seed(postgres_url: str, tenant: str, run_id: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import (
        Organization,
        Project,
        Run,
        SessionRow,
        User,
    )

    upgrade_head(postgres_url)
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if db.get(User, f"u-{tenant}") is None:
                db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            if db.get(Organization, f"o-{tenant}") is None:
                db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            if db.get(Project, f"p-{tenant}") is None:
                db.add(Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={}))
            db.add(
                SessionRow(
                    id=f"s-{run_id}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"
                )
            )
            db.add(
                Run(
                    id=run_id,
                    tenant_id=tenant,
                    session_id=f"s-{run_id}",
                    status="leased",
                    request_id=f"req-{run_id}",
                )
            )
            db.commit()
    finally:
        engine.dispose()


def _lease(postgres_url: str, run_id: str, worker: str, epoch: int) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET status = 'leased', lease_owner = :w, lease_epoch = :e,"
                    " lease_until = :u WHERE id = :r"
                ),
                {"w": worker, "e": epoch, "u": datetime.now(timezone.utc) + timedelta(minutes=5), "r": run_id},
            )
    finally:
        engine.dispose()


def _status(postgres_url: str, run_id: str) -> tuple[str, Any]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return tuple(
                conn.execute(
                    text("SELECT status, lease_owner FROM runs WHERE id = :r"), {"r": run_id}
                ).one()
            )
    finally:
        engine.dispose()


def _approval_rows(postgres_url: str, run_id: str) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT COUNT(*) FROM approvals WHERE run_id = :r"), {"r": run_id}
                ).scalar()
                or 0
            )
    finally:
        engine.dispose()


def _checkpoint(user_input: str, call_id: str, tool: str) -> dict[str, Any]:
    return {
        "version": 1,
        "user_input": user_input,
        "mode": "build",
        "allowed_tool_names": None,
        "role_instruction": "",
        "messages": [
            {"kind": "human", "content": user_input},
            {
                "kind": "ai",
                "content": "",
                "tool_calls": [{"id": call_id, "name": tool, "args": {}, "type": "tool_call"}],
            },
        ],
        "paused": {"call_id": call_id, "tool": tool},
        "remaining": [],
        "state": {},
        "budget": None,
    }


def _handlers(cfg, *, tenant: str, run_id: str, epoch: int, tmp_path: Path, paused_info: dict):
    import rxycode_worker.drain as drain

    return drain._ctl_handlers(
        cfg,
        tenant_id=tenant,
        run_id=run_id,
        epoch=epoch,
        workdir=tmp_path,
        journal_dir=tmp_path / "journal",
        paused=threading.Event(),
        paused_info=paused_info,
        sandbox_id="sb-park",
    )


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_w8_harness_question_parks_answers_and_resumes_once(
    postgres_url: str, tmp_path: Path
) -> None:
    from rxycode_worker.ctl import pack_checkpoint
    from rxycode_server.approvals.service import (
        ApprovalStale,
        answer_question,
        decide_approval,
        list_pending,
        list_pending_questions_durable,
    )
    from rxycode_server.events.store import append_event
    import rxycode_worker.drain as drain

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-q", 4)
    cfg = SimpleNamespace(database_url=postgres_url, worker_id="wkr-q")
    paused_info: dict[str, Any] = {}
    handlers = _handlers(cfg, tenant=tenant, run_id=run_id, epoch=4, tmp_path=tmp_path, paused_info=paused_info)

    parked = handlers["pause_question"](
        {
            "question_id": "q-abc",
            "question": "Which database?",
            "header": "DB",
            "options": [{"label": "PostgreSQL", "value": "pg"}, {"label": "SQLite", "value": "sqlite"}],
            "deadline": _future(),
            "checkpoint_z": pack_checkpoint(_checkpoint("choose a database", "tc-1", "question")),
        }
    )
    assert parked["asked"] is True
    assert paused_info["approval_id"] == parked["approval_id"]
    assert _status(postgres_url, run_id) == ("waiting_approval", None)
    assert [q["question_id"] for q in list_pending_questions_durable(postgres_url, tenant_id=tenant, run_id=run_id)] == ["q-abc"]
    assert list_pending(postgres_url, tenant_id=tenant, run_id=run_id) == []

    # A value outside the offered options is refused; the run stays parked.
    with pytest.raises(ValueError):
        answer_question(postgres_url, tenant_id=tenant, run_id=run_id, question_id="q-abc", answer="mysql")
    assert _status(postgres_url, run_id)[0] == "waiting_approval"

    # A question row is never an approval: the decision endpoint refuses it.
    with pytest.raises(ApprovalStale):
        decide_approval(
            postgres_url,
            tenant_id=tenant,
            approval_id=parked["approval_id"],
            decision="approved",
            expected_revision=0,
        )

    assert answer_question(postgres_url, tenant_id=tenant, run_id=run_id, question_id="q-abc", answer="pg")["status"] == "answered"
    assert _status(postgres_url, run_id)[0] == "pending"
    with pytest.raises(ApprovalStale):
        answer_question(postgres_url, tenant_id=tenant, run_id=run_id, question_id="q-abc", answer="sqlite")

    # The resume claim: lease again, the parent confirms the turn has exited,
    # and the answer is handed to exactly one claimant.
    _lease(postgres_url, run_id, "wkr-q", 5)
    append_event(
        postgres_url,
        tenant_id=tenant,
        run_id=run_id,
        event_type="turn.paused",
        payload={"approval_id": parked["approval_id"]},
    )
    pending = drain._pending_resume(postgres_url, tenant, run_id)
    assert pending is not None and pending.get("kind") == "question"
    resumed = _handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-q"),
        tenant=tenant, run_id=run_id, epoch=5, tmp_path=tmp_path, paused_info={},
    )["resume_state"]({"approval_id": parked["approval_id"]})["record"]
    assert resumed["kind"] == "question"
    assert resumed["answer"] == "pg"
    restored = drain.unpack_checkpoint(resumed["checkpoint_z"])
    assert restored["user_input"] == "choose a database"
    assert restored["paused"]["call_id"] == "tc-1"

    again = _handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-q"),
        tenant=tenant, run_id=run_id, epoch=5, tmp_path=tmp_path, paused_info={},
    )["resume_state"]({"approval_id": parked["approval_id"]})["record"]
    assert again is None
    # Once consumed, a later claim must not restart the prompt.
    late = drain._pending_resume(postgres_url, tenant, run_id)
    assert late is not None and late.get("unresolvable") is True


def test_w8_harness_park_refused_without_checkpoint_persists_nothing(
    postgres_url: str, tmp_path: Path
) -> None:
    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-n", 2)
    handlers = _handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-n"),
        tenant=tenant, run_id=run_id, epoch=2, tmp_path=tmp_path, paused_info={},
    )
    refused = handlers["pause_approval"](
        {"source_call_id": "call_0123456789abcdef0123456789abcdef", "tool": "bash",
         "scope": "danger", "arguments": {"command": "rm x"}, "deadline": _future()}
    )
    assert refused == {"asked": False, "reason": "no_checkpoint"}
    assert _status(postgres_url, run_id) == ("leased", "wkr-n")
    assert _approval_rows(postgres_url, run_id) == 0


def test_w8_harness_approval_row_carries_checkpoint_and_stays_out_of_questions(
    postgres_url: str, tmp_path: Path
) -> None:
    from rxycode_worker.ctl import pack_checkpoint
    from rxycode_server.approvals.service import list_pending_questions_durable

    tenant = f"ten-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    _seed(postgres_url, tenant, run_id)
    _lease(postgres_url, run_id, "wkr-a", 3)
    paused_info: dict[str, Any] = {}
    handlers = _handlers(
        SimpleNamespace(database_url=postgres_url, worker_id="wkr-a"),
        tenant=tenant, run_id=run_id, epoch=3, tmp_path=tmp_path, paused_info=paused_info,
    )
    asked = handlers["pause_approval"](
        {"source_call_id": "call-9", "tool": "bash", "scope": "danger",
         "arguments": {"command": "touch /w/x"}, "deadline": _future(),
         "command": "touch /w/x",
         "checkpoint_z": pack_checkpoint(_checkpoint("touch it", "call-9", "bash"))}
    )
    assert asked["asked"] is True
    assert list_pending_questions_durable(postgres_url, tenant_id=tenant, run_id=run_id) == []
    from rxycode_server.approvals.service import get_approval

    row = get_approval(postgres_url, tenant_id=tenant, approval_id=asked["approval_id"])
    assert row["kind"] == "approval"
    assert row["checkpoint"]["paused"]["call_id"] == "call-9"


def test_w8_harness_turn_budget_counts_execution_and_restores_without_waiting() -> None:
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import TurnBudget

    now = [0.0]
    budget = TurnBudget(limit_seconds=100.0, clock=lambda: now[0])
    budget.start()
    now[0] = 30.0
    budget.pause()
    snapshot = budget.snapshot()
    assert snapshot["consumed_seconds"] == pytest.approx(30.0)
    # Parked for a day while waiting for a human: no execution time accrues.
    now[0] = 86_400.0
    restored = TurnBudget.restore(snapshot, clock=lambda: now[0])
    restored.start()
    now[0] = 86_420.0
    assert restored.elapsed() == pytest.approx(50.0)
    assert not restored.exhausted()


class _BudgetAgent:
    _session_id = "budget-session"

    def __init__(self, grants: list[float]) -> None:
        self._grants = list(grants)
        self.asked = 0

    async def _decide_turn_budget(self, budget, session_id: str, run_id: str) -> bool:
        self.asked += 1
        return budget.extend(self._grants.pop(0)) if self._grants else False


def _under(agent, factory, budget):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    return AgentV2._under_turn_budget(agent, factory, budget)


def test_w8_harness_turn_budget_completes_without_asking() -> None:
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import TurnBudget

    async def work() -> str:
        return "final"

    agent = _BudgetAgent([])
    assert asyncio.run(_under(agent, work, TurnBudget(limit_seconds=5.0))) == "final"
    assert agent.asked == 0


def test_w8_harness_turn_budget_stops_work_when_no_extension_is_granted() -> None:
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import TurnBudget, TurnBudgetExhausted

    finished = []

    async def work() -> str:
        try:
            await asyncio.sleep(10)
            return "late"
        finally:
            finished.append("cancelled-or-done")

    agent = _BudgetAgent([])
    with pytest.raises(TurnBudgetExhausted):
        asyncio.run(_under(agent, work, TurnBudget(limit_seconds=0.3)))
    assert agent.asked == 1
    assert finished == ["cancelled-or-done"]


def test_w8_harness_turn_budget_extensions_are_count_and_cap_bounded() -> None:
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import TurnBudget, TurnBudgetExhausted

    async def work() -> str:
        await asyncio.sleep(10)
        return "late"

    budget = TurnBudget(limit_seconds=0.3, max_extensions=1, hard_cap_seconds=5.0)
    agent = _BudgetAgent([0.3, 0.3])
    with pytest.raises(TurnBudgetExhausted):
        asyncio.run(_under(agent, work, budget))
    assert budget.extensions_used == 1
    assert agent.asked == 2


def test_w8_harness_pause_checkpoint_carries_consumed_budget() -> None:
    from langchain_core.messages import HumanMessage

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.harness_checkpoint import (
        TurnBudget,
        bind_turn_budget,
        reset_turn_budget,
    )

    now = [0.0]
    budget = TurnBudget(limit_seconds=100.0, clock=lambda: now[0])
    budget.start()
    now[0] = 12.0
    token = bind_turn_budget(budget)
    try:
        checkpoint = AgentV2._harness_pause_checkpoint(
            SimpleNamespace(),
            [HumanMessage(content="go")],
            paused_call_id="tc-9",
            valid_tool_calls=[{"id": "tc-9", "name": "question", "args": {}}],
            pending_ids={"tc-9"},
            user_input="go",
            mode="build",
            allowed_tool_names=None,
            role_instruction="",
            state={},
        )
    finally:
        reset_turn_budget(token)
    assert checkpoint["budget"]["consumed_seconds"] == pytest.approx(12.0)
    assert budget.elapsed() == pytest.approx(12.0)
    now[0] = 500.0
    assert budget.elapsed() == pytest.approx(12.0)


def test_w8_harness_turn_budget_is_configured_through_the_registry() -> None:
    from RxyCode.RxyCode1_1_0.config.timeouts import resolve_timeout

    assert resolve_timeout("turn.budget_seconds", {}) == 3600.0
    assert resolve_timeout("turn.budget_seconds", {"execution": {"turn_budget_seconds": 90}}) == 90.0
    assert resolve_timeout("turn.max_extensions", {}) == 4.0
