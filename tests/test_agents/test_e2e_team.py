"""F11 · software_dev 专家团端到端（mock LLM）。"""

from __future__ import annotations

import asyncio
import time

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from RxyCode.RxyCode1_1_0.core.agents.coordinator import Coordinator, PrecheckError, StageOutcome
from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime
from RxyCode.RxyCode1_1_0.core.agents.spec import validate_team
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team
from RxyCode.RxyCode1_1_0.core.agents.verifier import SOFTWARE_DEV_STAGE_CHECKS, subject_hash
from RxyCode.RxyCode1_1_0.tools.registry import default_registry
from RxyCode.RxyCode1_1_0.core.prompts import list_stages
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.protocol.agents import (
    AgentSpec,
    ConsultRequest,
    SopStage,
    TeamEvent,
    TeamSpec,
    VerdictRecord,
)

_WRITE = {"write", "edit", "patch"}
_KNOWN_TOOLS = {
    "bash", "cd", "datetime", "diagnostics", "download_file", "download_mcp",
    "download_skill", "edit", "format", "git", "glob", "grep", "history", "ls",
    "memory", "open_file", "patch", "question", "read", "skill", "task", "view",
    "vision", "webfetch", "websearch", "workflow", "write", "code_search",
}


class _Stamp:
    def __init__(self) -> None:
        self.coord: Coordinator | None = None
        self.fail_first_implement = False
        self._implement_seen = 0
        self.fail_audit_left = 0
        self._audit_seen = 0

    def run(self, stage, result):
        if stage.name == "implement":
            self._implement_seen += 1
            if self.fail_first_implement and self._implement_seen == 1:
                return type("V", (), {"passed": False, "findings": ["lint_clean: dirty"]})()
        if stage.name == "audit":
            self._audit_seen += 1
            if self.fail_audit_left > 0:
                self.fail_audit_left -= 1
                return type("V", (), {"passed": False, "findings": ["audit reject"]})()
        digest = subject_hash(result.answer, getattr(result, "diff", "") or "")
        if self.coord is not None:
            self.coord.store_verdict(
                VerdictRecord(
                    subject_hash=digest,
                    auditor_role="auditor",
                    passed=True,
                    created_at=time.time(),
                )
            )
        return type("V", (), {"passed": True, "findings": []})()


def _coord(stamp: _Stamp | None = None) -> Coordinator:
    gate = stamp or _Stamp()
    coord = Coordinator(
        Session(session_id="ses-f11", workspace_root=".", emit=lambda _n: None),
        verifier=gate,
    )
    gate.coord = coord
    return coord


def test_team_loads_and_validates() -> None:
    team = load_builtin_team("software_dev")
    validate_team(team)
    assert team.name == "software_dev"
    roles = {m.role for m in team.members}
    assert roles >= {
        "pm",
        "architect",
        "frontend_coder",
        "backend_coder",
        "tester",
        "verifier",
        "security_auditor",
        "quality_auditor",
        "maintainability_auditor",
        "doc",
    }
    assert {s.name for s in team.stages} >= {
        "clarify",
        "plan",
        "implement",
        "test",
        "verify",
        "audit",
        "document",
    }
    implement = next(s for s in team.stages if s.name == "implement")
    assert set(implement.parallel_members or []) == {"frontend_coder", "backend_coder"}
    audit = next(s for s in team.stages if s.name == "audit")
    assert set(audit.parallel_members or []) == {
        "security_auditor",
        "quality_auditor",
        "maintainability_auditor",
    }
    assert team.extra.get("ecosystem.disable_model_invocation") is True
    assert next(s for s in team.stages if s.name == "implement").max_retries == 1
    assert next(s for s in team.stages if s.name == "test").max_retries == 1
    assert next(s for s in team.stages if s.name == "verify").max_retries == 0
    assert next(s for s in team.stages if s.name == "verify").next_on_failure == "audit"
    assert next(s for s in team.stages if s.name == "audit").max_retries == 1


def test_prompt_stages_exist() -> None:
    keys = set(list_stages())
    assert {
        "agent_architect",
        "agent_coder",
        "agent_auditor",
        "agent_pm",
        "agent_frontend_coder",
        "agent_backend_coder",
        "agent_tester",
    } <= keys


def test_yaml_tool_names_are_real() -> None:
    team = load_builtin_team()
    for member in team.members:
        if member.tools:
            unknown = set(member.tools) - _KNOWN_TOOLS
            assert not unknown, unknown


def test_auditor_cannot_edit_files() -> None:
    team = load_builtin_team()
    auditors = [
        m
        for m in team.members
        if m.role.endswith("auditor") or m.role in {"pm", "architect"}
    ]
    assert auditors
    for auditor in auditors:
        assert _WRITE.isdisjoint(auditor.tools or []), auditor.role
    stage = SopStage(
        name="hack",
        role="quality_auditor",
        expected_output="write the file",
        output_key="hack",
    )
    hacked = TeamSpec(
        name="x",
        display_name="x",
        members=list(team.members),
        stages=[stage],
        entry_stage="hack",
    )
    coord = _coord()
    try:
        coord._precheck(stage, hacked)
        raise AssertionError("auditor write stage must fail precheck")
    except PrecheckError:
        pass


class _StubArgs(BaseModel):
    value: str = Field(default="x")


def _ensure_named_tool(name: str, *, risk: str) -> None:
    if default_registry.get(name) is not None:
        return

    def _run(value: str = "x") -> str:
        return value

    default_registry.register(
        StructuredTool.from_function(
            func=_run,
            name=name,
            description=name,
            args_schema=_StubArgs,
        ),
        risk=risk,
    )


def test_architect_dispatch_cannot_write() -> None:
    """Live form_team must scope architect tools so write never executes."""
    for name in ("read", "grep", "ls"):
        _ensure_named_tool(name, risk="read")
    for name in ("write", "edit", "patch"):
        _ensure_named_tool(name, risk="write")
    writes: list[str] = []

    class _Spy:
        async def run(self, text: str, mode: str = "build") -> str:
            result = await self._execute_tool(
                "write", {"path": "hack.py", "content": "nope"}
            )
            writes.append(str(result))
            return f"plan:{result}"

        async def _execute_tool(self, name: str, args: dict, **kwargs: object) -> str:
            writes.append(name)
            return f"executed:{name}"

    session = Session(session_id="ses-scope", workspace_root=".", emit=lambda _n: None)
    spy = _Spy()
    session._active_agent = spy
    coord = Coordinator(session, emit=lambda _n: None)
    team = load_builtin_team()
    coord.form_team(team)
    architect = coord._runtimes["architect"]
    assert isinstance(architect, AgentRuntime)
    names = set(architect.registry.get_names())
    assert "write" not in names
    assert "edit" not in names
    assert "patch" not in names
    assert "read" in names
    assert architect.cache_namespace == "agent:architect"
    coder = coord._runtimes["backend_coder"]
    assert coder.spec.tools is None
    assert coder.cache_namespace == "agent:backend_coder"
    assert architect.cache_namespace != coder.cache_namespace
    assert "verifier" not in coord._runtimes
    assert architect is not coder
    plan = next(stage for stage in team.stages if stage.name == "plan")
    result = asyncio.run(coord._dispatch(plan, team, "add auth/*.py"))
    assert "write" not in writes
    assert any("blocked" in item for item in writes)
    assert "write" not in (result.packet.tools or [])
    assert result.ok is True


def test_completed_enum_status_advances_past_plan() -> None:
    """str(ChildStatus.COMPLETED) is 'ChildStatus.COMPLETED' on 3.11+; must still count as ok."""

    class _Done:
        async def run(self, text: str, mode: str = "build") -> str:
            return "structured plan with files and checks"

    coord = _coord()
    coord._session._active_agent = _Done()
    text = asyncio.run(coord.run_team(load_builtin_team(), "add a health endpoint"))
    stages = [part.strip() for part in text.replace("->", " ").split() if part.strip()]
    assert "plan" in stages
    assert "implement" in stages
    assert "audit" in stages
    assert coord.progress_ledger.stall_count == 0


def test_happy_path_plan_implement_audit() -> None:
    text = asyncio.run(_coord().run_team(load_builtin_team(), "add a health endpoint"))
    for name in ("clarify", "plan", "implement", "test", "verify", "audit", "document"):
        assert name in text, name


def test_passing_verify_gates_promote_failed_dispatch(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-promote", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    implement = next(stage for stage in load_builtin_team().stages if stage.name == "implement")
    result = StageOutcome(
        ok=False,
        answer="wrote app.py",
        error="frontend_coder cancelled",
        diff="app.py",
    )
    out = coord._apply_verify_gates(implement, result)
    assert out.ok is True, out.error


def test_parallel_implement_one_failed_sibling_still_ok() -> None:
    from protocol.subagents import ChildStatus, TaskResult

    class _Rec:
        def __init__(self, role: str) -> None:
            self.role = role

        async def run(self, task: object) -> TaskResult:
            if self.role == "frontend_coder":
                return TaskResult(
                    request_id="1",
                    child_session_id=self.role,
                    status=ChildStatus.FAILED,
                    summary="",
                )
            return TaskResult(
                request_id="1",
                child_session_id=self.role,
                status=ChildStatus.COMPLETED,
                summary="wrote backend/app.py",
            )

    team = load_builtin_team()
    coord = _coord()
    coord._runtimes.update(
        {
            "frontend_coder": _Rec("frontend_coder"),
            "backend_coder": _Rec("backend_coder"),
        }
    )
    implement = next(stage for stage in team.stages if stage.name == "implement")
    result = asyncio.run(
        coord._dispatch(implement, team, "frontend/index.html backend/app.py")
    )
    assert result.ok is True


def test_provider_error_summary_is_not_sop_success() -> None:
    from protocol.subagents import ChildStatus, TaskResult
    from RxyCode.RxyCode1_1_0.core.agents.coordinator import _is_runtime_error_summary

    assert _is_runtime_error_summary(
        "[error] AuthenticationError: Error code: 401 - Model  is not supported"
    )
    assert _is_runtime_error_summary(
        "[error] CircuitBreakerError: Timeout not elapsed yet, circuit breaker still open"
    )
    assert not _is_runtime_error_summary("SKIP: no work for this surface")

    class _Rec:
        async def run(self, task: object) -> TaskResult:
            return TaskResult(
                request_id="1",
                child_session_id="backend_coder",
                status=ChildStatus.COMPLETED,
                summary="[error] AuthenticationError: Model  is not supported",
            )

    team = load_builtin_team()
    coord = _coord()
    coord._runtimes["backend_coder"] = _Rec()
    implement = next(stage for stage in team.stages if stage.name == "implement")
    result = asyncio.run(
        coord._dispatch_one(
            implement,
            team,
            "/team lru_cache.py",
            "backend_coder",
        )
    )
    assert result.ok is False


def test_tester_packet_names_pytest_file() -> None:
    team = load_builtin_team()
    coord = _coord()
    stage = next(s for s in team.stages if s.name == "test")
    packet = coord._packet(
        stage, team, "/team tests/test_calc.py 至少 6 条。pytest 必须绿。"
    )
    assert "tests/test_calc.py" in packet.goal
    assert "第一轮就用 write" in packet.goal


def test_tester_packet_h5_cli_template_forbids_subprocess() -> None:
    team = load_builtin_team()
    coord = _coord()
    stage = next(s for s in team.stages if s.name == "test")
    packet = coord._packet(
        stage,
        team,
        "/team 实现 CLI：cli.py 用 argparse 提供 add/list/done；"
        "store.py 用 JSON 文件持久化；tests/test_cli.py 测三条命令。pytest 必须绿。",
    )
    assert "tests/test_cli.py" in packet.goal
    assert "from cli import main" in packet.goal
    assert "禁止 subprocess" in packet.goal
    assert "task-a" in packet.goal


def test_idle_frontend_skips_without_llm() -> None:
    """H3-style backend-only implement must not start frontend_coder (P6 suffix)."""

    from protocol.subagents import ChildStatus, TaskResult

    class _Rec:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def run(self, task: object) -> TaskResult:
            self.calls.append(str(getattr(task, "prompt", task)))
            return TaskResult(
                request_id="1",
                child_session_id="frontend_coder",
                status=ChildStatus.COMPLETED,
                summary="should not run",
            )

    rec = _Rec()
    team = load_builtin_team()
    coord = _coord()
    coord._runtimes["frontend_coder"] = rec
    implement = next(stage for stage in team.stages if stage.name == "implement")
    result = asyncio.run(
        coord._dispatch_one(
            implement,
            team,
            "/team 实现带 TTL 的 LRU：lru_cache.py 提供 get/set/delete。",
            "frontend_coder",
        )
    )
    assert rec.calls == []
    assert result.ok is True
    assert "SKIP:" in result.answer


def test_frontend_dispatches_when_html_named() -> None:
    from protocol.subagents import ChildStatus, TaskResult

    class _Rec:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, task: object) -> TaskResult:
            self.calls += 1
            return TaskResult(
                request_id="1",
                child_session_id="frontend_coder",
                status=ChildStatus.COMPLETED,
                summary="wrote frontend/index.html",
            )

    rec = _Rec()
    team = load_builtin_team()
    coord = _coord()
    coord._runtimes["frontend_coder"] = rec
    implement = next(stage for stage in team.stages if stage.name == "implement")
    result = asyncio.run(
        coord._dispatch_one(
            implement,
            team,
            "frontend/index.html 调 /echo",
            "frontend_coder",
        )
    )
    assert rec.calls == 1
    assert result.ok is True


def test_sop_reaches_document_after_verify() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.sop import SopMachine

    team = load_builtin_team()
    assert next(s for s in team.stages if s.name == "test").next_on_failure == "verify"
    assert next(s for s in team.stages if s.name == "verify").next_on_failure == "audit"
    sop = SopMachine(team)
    assert sop.advance(ok=True).name == "plan"
    assert sop.advance(ok=True).name == "implement"
    assert sop.advance(ok=True).name == "test"
    assert sop.advance(ok=True).name == "verify"
    assert sop.advance(ok=True).name == "audit"
    assert sop.advance(ok=True).name == "document"
    assert sop.advance(ok=True) is None


def test_implement_retries_then_goes_to_test() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.sop import SopMachine

    team = load_builtin_team()
    implement = next(stage for stage in team.stages if stage.name == "implement")
    assert implement.next_on_failure == "test"
    sop = SopMachine(team)
    assert sop.advance(ok=True).name == "plan"
    assert sop.advance(ok=True).name == "implement"
    assert sop.advance(ok=False).name == "implement"
    assert sop.advance(ok=False).name == "test"


def test_verify_failure_goes_to_audit() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.sop import SopMachine

    team = load_builtin_team()
    sop = SopMachine(team)
    assert sop.advance(ok=True).name == "plan"
    assert sop.advance(ok=True).name == "implement"
    assert sop.advance(ok=True).name == "test"
    assert sop.advance(ok=True).name == "verify"
    assert sop.advance(ok=False).name == "audit"


def test_test_stage_requires_named_pytest_file(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "lru_cache.py").write_text("class LRUCache:\n    pass\n", encoding="utf-8")
    (tests / "test_lru_warmup.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-named-missing", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    coord._user_input = (
        "/team 实现带 TTL 的 LRU：lru_cache.py；tests/test_lru_cache.py 覆盖淘汰。pytest 必须绿。"
    )
    team = load_builtin_team()
    test_stage = next(stage for stage in team.stages if stage.name == "test")
    out = coord._apply_verify_gates(
        test_stage,
        StageOutcome(ok=True, answer="wrote tests/test_lru_warmup.py", diff=""),
    )
    assert out.ok is False
    assert "test_lru_cache.py" in (out.error or "")


def test_empty_named_pytest_file_fails_python_parses(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "calc").mkdir()
    (tmp_path / "calc" / "eval.py").write_text("x = 1\n", encoding="utf-8")
    (tests / "test_calc.py").write_text("", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-empty-test", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    coord._user_input = (
        "/team tests/test_calc.py 至少 6 条。pytest 必须绿。"
    )
    team = load_builtin_team()
    test_stage = next(stage for stage in team.stages if stage.name == "test")
    out = coord._apply_verify_gates(
        test_stage,
        StageOutcome(ok=True, answer="wrote tests/test_calc.py", diff="tests/test_calc.py"),
    )
    assert out.ok is False
    assert "test_ functions" in (out.error or "")


def test_test_stage_files_exist_ignores_missing_plan_paths(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-test-gate", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    team = load_builtin_team()
    test_stage = next(stage for stage in team.stages if stage.name == "test")
    coord.blackboard.put("plan", "backend/app.py frontend/index.html tests/test_app.py", "architect")
    result = StageOutcome(
        ok=False,
        answer="wrote tests/test_app.py",
        diff="tests/test_app.py",
    )
    out = coord._apply_verify_gates(test_stage, result)
    assert out.ok is True, out.error


def test_test_stage_python_parses_ignores_extra_tester_files(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "lru_cache.py").write_text("class LRUCache:\n    pass\n", encoding="utf-8")
    (tests / "test_lru_cache.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (tests / "test_simple.py").write_text("def (\n", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-named-py", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    coord._user_input = (
        "/team 实现 LRU：lru_cache.py；tests/test_lru_cache.py 覆盖淘汰。pytest 必须绿。"
    )
    team = load_builtin_team()
    test_stage = next(stage for stage in team.stages if stage.name == "test")
    out = coord._apply_verify_gates(
        test_stage,
        StageOutcome(ok=True, answer="wrote tests/test_lru_cache.py", diff="tests/test_lru_cache.py"),
    )
    assert out.ok is True, out.error


def test_coders_forbid_java() -> None:
    team = load_builtin_team()
    for role in ("frontend_coder", "backend_coder"):
        member = next(m for m in team.members if m.role == role)
        blob = " ".join(member.constraints).lower()
        assert "java" in blob, role


def test_mechanical_fail_retries_implement() -> None:
    stamp = _Stamp()
    stamp.fail_first_implement = True
    text = asyncio.run(_coord(stamp).run_team(load_builtin_team(), "fix lint"))
    assert stamp._implement_seen >= 2
    assert "implement" in text


def test_audit_reject_still_reaches_document() -> None:
    stamp = _Stamp()
    stamp.fail_audit_left = 3
    text = asyncio.run(_coord(stamp).run_team(load_builtin_team(), "ship"))
    assert "audit" in text
    assert "document" in text


def test_retries_exhausted_then_fails() -> None:
    team = TeamSpec(
        name="tiny",
        display_name="tiny",
        members=[AgentSpec(role="coder", display_name="c", goal="c", prompt_stage="agent_coder")],
        stages=[
            SopStage(
                name="implement",
                role="coder",
                expected_output="note",
                output_key="implementation",
                next_on_success=None,
                next_on_failure=None,
                max_retries=0,
                verify_before_next=["lint_clean"],
            )
        ],
        entry_stage="implement",
    )

    class _AlwaysFail:
        def run(self, stage, result):
            return type("V", (), {"passed": False, "findings": ["no"]})()

    coord = Coordinator(
        Session(session_id="ses-fail", workspace_root=".", emit=lambda _n: None),
        verifier=_AlwaysFail(),
    )
    text = asyncio.run(coord.run_team(team, "x"))
    assert "implement" in text


def test_coder_consults_architect() -> None:
    team = load_builtin_team()
    coord = _coord()
    reply = coord.consult(
        team,
        ConsultRequest(
            session_id="ses-f11",
            request_id="q1",
            from_role="backend_coder",
            to_role="architect",
            question="方案里没提到迁移脚本",
            stage="implement",
        ),
        answer="补一节 migration",
    )
    assert reply == "补一节 migration"
    assert all(msg.relayed_by == "coordinator" for msg in coord.mailbox.all())


def test_budget_returns_partial() -> None:
    text = asyncio.run(
        _coord().run_team(
            load_builtin_team(),
            "big",
            budget_overrides={"max_delegations": 0},
        )
    )
    assert "超出预算" in text


def test_implement_declares_both_check_levels() -> None:
    team = load_builtin_team()
    implement = next(s for s in team.stages if s.name == "implement")
    assert list(implement.verify_before_next) == SOFTWARE_DEV_STAGE_CHECKS["implement"]


def test_backend_child_may_write_architect_may_not() -> None:
    for name in ("read", "write"):
        _ensure_named_tool(name, risk="read" if name == "read" else "write")
    session = Session(session_id="ses-ws", workspace_root=".", emit=lambda _n: None)
    architect = AgentRuntime(
        AgentSpec(
            role="architect",
            display_name="a",
            goal="plan",
            prompt_stage="agent_architect",
            tools=["read"],
        ),
        session=session,
    )
    backend = AgentRuntime(
        AgentSpec(
            role="backend_coder",
            display_name="b",
            goal="code",
            prompt_stage="agent_backend_coder",
            tools=None,
        ),
        session=session,
    )
    assert architect.child.check_tool("write", {"path": "x.py"}) is False
    assert backend.child.check_tool("write", {"path": "x.py"}) is True


def test_role_runtime_child_token_budget_is_team_sized() -> None:
    session = Session(session_id="ses-budget", workspace_root=".", emit=lambda _n: None)
    spec = AgentSpec(
        role="architect",
        display_name="a",
        goal="plan",
        prompt_stage="agent_architect",
        tools=[],
    )
    runtime = AgentRuntime(spec, session=session)
    assert runtime.child.budget.budget.max_tokens >= 120_000
    assert runtime.child.budget.budget.max_wall_time_seconds >= 300
    writer = AgentRuntime(
        AgentSpec(
            role="backend_coder",
            display_name="b",
            goal="code",
            prompt_stage="agent_backend_coder",
            tools=None,
        ),
        session=session,
    )
    assert writer.child.budget.budget.max_steps >= 80


def test_session_prompt_team_binds_agent_runtime() -> None:
    """Session.prompt /team must form per-role AgentRuntime, not reuse Primary."""
    from RxyCode.RxyCode1_1_0.protocol.agents import TeamEvent

    for name in ("read", "grep", "ls", "write", "edit", "patch", "bash"):
        _ensure_named_tool(name, risk="read" if name in {"read", "grep", "ls"} else "write")

    events: list[object] = []
    session = Session(
        session_id="ses-live-bind",
        workspace_root=".",
        emit=events.append,
    )

    class _Spy:
        async def run(self, text: str, mode: str = "build") -> str:
            return "ok-from-role"

    spy = _Spy()
    result = asyncio.run(
        session.prompt(spy, "/team 实现 GET /health", mode="build", run_id="run-bind")
    )
    assert result.status in {"succeeded", "failed"}
    team_events = [e for e in events if isinstance(e, TeamEvent)]
    roles = [e.role for e in team_events]
    assert "pm" in roles or "architect" in roles
    assert session._active_agent is None
    runtimes = session.agent_runtimes
    assert "architect" in runtimes
    assert isinstance(runtimes["architect"], AgentRuntime)
    assert runtimes["architect"].cache_namespace == "agent:architect"
    if "backend_coder" in runtimes:
        assert runtimes["backend_coder"].cache_namespace == "agent:backend_coder"
        assert runtimes["architect"] is not runtimes["backend_coder"]


def test_second_team_prompt_reuses_session_runtimes() -> None:
    """F14 shared path: warmup then H3 must keep the same per-role AgentRuntime."""
    from RxyCode.RxyCode1_1_0.protocol.agents import TeamEvent

    for name in ("read", "grep", "ls", "write", "edit", "patch", "bash"):
        _ensure_named_tool(name, risk="read" if name in {"read", "grep", "ls"} else "write")

    events: list[object] = []
    session = Session(
        session_id="ses-reuse-runtime",
        workspace_root=".",
        emit=events.append,
    )

    class _Spy:
        async def run(self, text: str, mode: str = "build") -> str:
            return "ok-from-role"

    spy = _Spy()
    first = asyncio.run(
        session.prompt(spy, "/team 实现 GET /health", mode="build", run_id="run-1")
    )
    assert first.status in {"succeeded", "failed"}
    first_runtimes = dict(session.agent_runtimes)
    assert "architect" in first_runtimes
    second = asyncio.run(
        session.prompt(spy, "/team 实现 GET /health", mode="build", run_id="run-2")
    )
    assert second.status in {"succeeded", "failed"}
    assert session.agent_runtimes["architect"] is first_runtimes["architect"]
    team_events = [e for e in events if isinstance(e, TeamEvent)]
    assert team_events


def test_parallel_audit_dispatches_three_roles() -> None:
    from protocol.subagents import ChildStatus, TaskResult

    class _Rec:
        def __init__(self, role: str) -> None:
            self.role = role
            self.prompts: list[str] = []

        async def run(self, task: object) -> TaskResult:
            self.prompts.append(str(getattr(task, "prompt", task)))
            return TaskResult(
                request_id="1",
                child_session_id=self.role,
                status=ChildStatus.COMPLETED,
                summary=f"{self.role}: finding at app.py:1",
            )

    team = load_builtin_team()
    recs = {
        role: _Rec(role)
        for role in (
            "security_auditor",
            "quality_auditor",
            "maintainability_auditor",
        )
    }
    coord = _coord()
    coord._runtimes.update(recs)
    audit = next(stage for stage in team.stages if stage.name == "audit")
    result = asyncio.run(coord._dispatch(audit, team, "review login"))
    assert result.ok is True
    for rec in recs.values():
        assert rec.prompts, rec.role
    assert "security_auditor" in result.answer
    assert "quality_auditor" in result.answer
    assert "maintainability_auditor" in result.answer


def test_parallel_implement_emits_stage_started_for_both_coders() -> None:
    events: list[object] = []
    gate = _Stamp()
    coord = Coordinator(
        Session(session_id="ses-par-impl", workspace_root=".", emit=events.append),
        verifier=gate,
        emit=events.append,
    )
    gate.coord = coord
    coord.verdict_allows = lambda _digest: True  # type: ignore[method-assign]
    asyncio.run(coord.run_team(load_builtin_team(), "health"))
    started = [
        (ev.role, ev.stage)
        for ev in events
        if isinstance(ev, TeamEvent) and ev.phase == "stage_started"
    ]
    assert ("frontend_coder", "implement") in started
    assert ("backend_coder", "implement") in started
    assert ("security_auditor", "audit") in started
    assert ("quality_auditor", "audit") in started
    assert ("maintainability_auditor", "audit") in started


def test_parallel_implement_skip_counts_as_ok() -> None:
    from protocol.subagents import ChildStatus, TaskResult

    class _Rec:
        def __init__(self, role: str) -> None:
            self.role = role

        async def run(self, task: object) -> TaskResult:
            if self.role == "frontend_coder":
                return TaskResult(
                    request_id="1",
                    child_session_id=self.role,
                    status=ChildStatus.CANCELLED,
                    summary="SKIP: no work for this surface",
                )
            return TaskResult(
                request_id="1",
                child_session_id=self.role,
                status=ChildStatus.COMPLETED,
                summary="wrote auth/routes.py",
            )

    team = load_builtin_team()
    coord = _coord()
    coord._runtimes.update(
        {
            "frontend_coder": _Rec("frontend_coder"),
            "backend_coder": _Rec("backend_coder"),
        }
    )
    implement = next(stage for stage in team.stages if stage.name == "implement")
    result = asyncio.run(coord._dispatch(implement, team, "login"))
    assert result.ok is True
    assert "SKIP" in result.answer


def test_dispatch_one_swallows_child_runtime_errors() -> None:
    class _Boom:
        async def run(self, _task: object) -> None:
            raise RuntimeError("recovery exhausted")

    team = load_builtin_team()
    coord = _coord()
    coord._runtimes["pm"] = _Boom()
    clarify = next(stage for stage in team.stages if stage.name == "clarify")
    out = asyncio.run(coord._dispatch_one(clarify, team, "login", "pm"))
    assert out.ok is False
    assert "recovery exhausted" in out.error


def test_run_team_child_exception_returns_partial() -> None:
    class _Boom:
        async def run(self, _task: object) -> None:
            raise RuntimeError("recovery exhausted")

    coord = _coord()
    coord._runtimes["pm"] = _Boom()
    text = asyncio.run(coord.run_team(load_builtin_team(), "login"))
    assert "clarify" in text


def test_implement_files_exist_ignores_tests_listed_in_plan(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    auth = tmp_path / "auth"
    auth.mkdir()
    (auth / "routes.py").write_text(
        "def login():\n    return {'token': 'x'}\n", encoding="utf-8"
    )
    coord = Coordinator(
        Session(session_id="ses-files", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    team = load_builtin_team()
    implement = next(stage for stage in team.stages if stage.name == "implement")
    coord.blackboard.put("spec", "auth/routes.py tests/test_login.py", "pm")
    coord.blackboard.put("plan", "files: auth/routes.py tests/test_login.py", "architect")
    result = StageOutcome(ok=True, answer="wrote auth/routes.py", diff="auth/routes.py")
    out = coord._apply_verify_gates(implement, result)
    assert out.ok is True, out.error


def test_implement_requires_named_product_file(tmp_path) -> None:
    from RxyCode.RxyCode1_1_0.core.agents.verifier import MechanicalVerifier

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "app.py").write_text("class LRUCache:\n    pass\n", encoding="utf-8")
    coord = Coordinator(
        Session(session_id="ses-named", workspace_root=str(tmp_path), emit=lambda _n: None),
        verifier=MechanicalVerifier(),
    )
    coord._user_input = (
        "/team 实现带 TTL 的 LRU：lru_cache.py 提供 get/set/delete；"
        "tests/test_lru_cache.py 覆盖淘汰。"
    )
    implement = next(stage for stage in load_builtin_team().stages if stage.name == "implement")
    result = StageOutcome(ok=True, answer="wrote backend/app.py", diff="backend/app.py")
    out = coord._apply_verify_gates(implement, result)
    assert out.ok is False
    assert "lru_cache.py" in (out.error or "")


def test_implement_packet_tells_backend_to_write_named_files() -> None:
    coord = Coordinator(
        Session(session_id="ses-pkt", workspace_root=".", emit=lambda _n: None)
    )
    team = load_builtin_team()
    implement = next(stage for stage in team.stages if stage.name == "implement")
    packet = coord._packet(
        implement,
        team,
        "/team 实现 lru_cache.py；tests/test_lru_cache.py 覆盖淘汰。",
        role="backend_coder",
    )
    assert "lru_cache.py" in packet.goal
    assert "write" in packet.goal.lower()
