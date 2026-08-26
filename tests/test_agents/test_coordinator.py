"""F6 · Coordinator 调度，不干活。"""

from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.core.agents.coordinator import (
    Coordinator,
    DispatchPacket,
    MemberForbiddenError,
    PrecheckError,
    VerifyVerdict,
)
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec, SopStage, TeamEvent, TeamSpec
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent


def _session() -> Session:
    return Session(session_id="ses-f6", workspace_root=".", emit=lambda _n: None)


def _member(role: str, *, tools: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        role=role,
        display_name=role,
        goal=role,
        prompt_stage="default",
        tools=tools,
    )


def _stage(
    name: str,
    role: str,
    *,
    expected_output: str = "note",
    output_key: str | None = None,
    next_on_success: str | None = None,
    next_on_failure: str | None = None,
    verify_before_next: list[str] | None = None,
    max_retries: int = 0,
) -> SopStage:
    return SopStage(
        name=name,
        role=role,
        expected_output=expected_output,
        output_key=output_key or name,
        next_on_success=next_on_success,
        next_on_failure=next_on_failure,
        verify_before_next=list(verify_before_next or ()),
        max_retries=max_retries,
    )


def _team() -> TeamSpec:
    return TeamSpec(
        name="dev",
        display_name="Dev",
        members=[_member("architect"), _member("coder", tools=["read", "write"])],
        stages=[
            _stage("plan", "architect", expected_output="design", next_on_success="code"),
            _stage("code", "coder", expected_output="write the file"),
        ],
        entry_stage="plan",
    )


def test_coordinator_tools_are_empty() -> None:
    coord = Coordinator(_session())
    assert coord.tools == []
    asyncio.run(coord.run_team(_team(), "build it"))
    assert coord.tools == []


def test_precheck_blocks_role_without_write_tool() -> None:
    team = TeamSpec(
        name="bad",
        display_name="Bad",
        members=[_member("coder", tools=["read", "grep"])],
        stages=[_stage("code", "coder", expected_output="write the file")],
        entry_stage="code",
    )
    coord = Coordinator(_session())
    with pytest.raises(PrecheckError, match="write tool"):
        coord._precheck(team.stages[0], team)


def test_members_cannot_form_a_team() -> None:
    coord = Coordinator(_session())
    with pytest.raises(MemberForbiddenError, match="may not create teams"):
        coord.member_form_team(_member("coder"), _team())


def test_llm_decision_emits_explicit_event() -> None:
    coord = Coordinator(_session())
    chosen = coord.choose_failure_target(["architect", "coder"])
    assert chosen == "architect"
    details = [getattr(ev, "detail", "") for ev in coord.events]
    assert "llm_route_decision" in details
    assert any(isinstance(ev, TeamEvent) and ev.detail == "llm_route_decision" for ev in coord.events)


def test_dispatch_packet_has_no_coordinator_history() -> None:
    coord = Coordinator(_session())
    coord._coordinator_history.append("secret coordinator thought")
    packet = coord._packet(_team().stages[0], _team(), "user task")
    assert isinstance(packet, DispatchPacket)
    assert packet.coordinator_history is None
    blob = f"{packet.goal}{packet.expected_output}{packet.context}"
    assert "secret coordinator thought" not in blob


class _CancelledChild:
    status = "cancelled"
    summary = "files: auth/routes.py; backend only; SKIP frontend"


class _CancelledRuntime:
    async def run(self, _req):  # noqa: ANN001
        return _CancelledChild()


def test_text_stage_nonempty_summary_ok_even_if_child_cancelled() -> None:
    coord = Coordinator(_session())
    team = _team()
    coord._runtimes["architect"] = _CancelledRuntime()
    out = asyncio.run(coord._dispatch_one(team.stages[0], team, "task", "architect"))
    assert out.ok is True
    assert "auth/routes.py" in out.answer


def test_write_stage_cancelled_child_stays_not_ok() -> None:
    coord = Coordinator(_session())
    team = _team()
    coord._runtimes["coder"] = _CancelledRuntime()
    out = asyncio.run(coord._dispatch_one(team.stages[1], team, "task", "coder"))
    assert out.ok is False


def test_stall_twice_triggers_replan_event() -> None:
    coord = Coordinator(_session())
    coord.record_progress(made_progress=False)
    assert coord.last_replan is None
    coord.record_progress(made_progress=False)
    assert coord.last_replan is not None
    assert any(
        isinstance(ev, TeamEvent) and ev.detail == "stall_replan" for ev in coord.events
    )


def test_run_team_emits_team_created_and_walks_sop() -> None:
    coord = Coordinator(_session())
    text = asyncio.run(coord.run_team(_team(), "ship it"))
    assert "plan" in text and "code" in text
    assert any(
        isinstance(ev, AgentEvent) and ev.method == "event/agent_team_created"
        for ev in coord.events
    )


def test_verifier_failure_is_recorded() -> None:
    class _V:
        def run(self, stage, result):
            return VerifyVerdict(passed=False, findings=["lint dirty"])

    team = TeamSpec(
        name="v",
        display_name="V",
        members=[_member("coder", tools=["write"])],
        stages=[
            _stage(
                "code",
                "coder",
                expected_output="note",
                verify_before_next=["lint"],
                next_on_failure=None,
                max_retries=0,
            )
        ],
        entry_stage="code",
    )
    coord = Coordinator(_session(), verifier=_V())
    asyncio.run(coord.run_team(team, "x"))
    assert coord.progress_ledger.delegations
