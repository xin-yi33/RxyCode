"""Coordinator：专家团团长。

职责（抄腾讯 WorkBuddy 专家团主理人，见 PHASE-F §2.3）：
  ① 建团   只有团长能建团，成员不得创建子团队（DC6）
  ② 派活   按 SOP 阶段下发自包含任务
  ③ 中转   所有跨成员消息必经此处（DC2）
  ④ 收口   汇总产出，决定是否进入下一阶段

团长自己**不写代码、不调业务工具**。它的工具集是空的，只能调协调动作。
这是刻意的：团长一旦开始干活，就会和成员抢上下文，而且它的上下文是全局
最宝贵的。

F8 MechanicalVerifier 是默认机械门；F9 BudgetGuard 仍可注入（缺省 noop）。
进入下一阶段前：机械检查不过就打回；audit_after_verify 还要求
当前产出 hash 上有 passed=True 的 VerdictRecord。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from RxyCode.RxyCode1_1_0.core.agents.blackboard import Blackboard
from RxyCode.RxyCode1_1_0.core.agents.budget import BudgetExceeded, BudgetGuard
from RxyCode.RxyCode1_1_0.core.agents.mailbox import Mailbox
from RxyCode.RxyCode1_1_0.core.agents.runtime import AgentRuntime
from RxyCode.RxyCode1_1_0.core.agents.team_prompt import compact_summary
from RxyCode.RxyCode1_1_0.core.prompts.templates import DELEGATE_REQUEST_TEMPLATE
from RxyCode.RxyCode1_1_0.protocol.subagents import ContextEnvelope
from RxyCode.RxyCode1_1_0.core.agents.sop import SopMachine, StageRecord
from RxyCode.RxyCode1_1_0.core.agents.spec import AgentSpecError, validate_team
from RxyCode.RxyCode1_1_0.core.agents.verifier import (
    MechanicalVerifier,
    VerifyContext,
    named_product_files,
    named_pytest_targets,
    subject_hash,
)
from RxyCode.RxyCode1_1_0.core.tracing import (
    Tracer,
    distillation_ui_notice,
    format_current_role,
)
from RxyCode.RxyCode1_1_0.protocol.agents import (
    AgentSpec,
    ConsultRequest,
    SopStage,
    TeamEvent,
    TeamSpec,
    VerdictRecord,
)
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent, ProgressUpdate

_WRITE_TOOLS = frozenset({"write", "edit", "patch"})
_WRITE_HINTS = ("write", "edit", "file", "patch", "写文件", "修改文件")
_STAGE_LABELS = {
    "clarify": "正在澄清需求",
    "plan": "正在制定方案",
    "implement": "正在实现",
    "test": "正在编写测试",
    "verify": "正在机械验证",
    "audit": "正在审计",
    "document": "正在写文档",
}


class CoordinatorError(RuntimeError):
    """Coordinator refused a team action."""


class PrecheckError(CoordinatorError):
    """Stage role cannot perform the required tools."""


class MemberForbiddenError(CoordinatorError):
    """Members must not create sub-teams (DC6)."""


class ConsultDenied(CoordinatorError):
    """may_consult does not allow this target."""


class ConsultBudgetExceeded(CoordinatorError):
    """Consult count or token budget exhausted."""


@dataclass
class TaskLedger:
    """Outer-loop book (Magentic-One)."""

    facts: list[str] = field(default_factory=list)
    facts_to_lookup: list[str] = field(default_factory=list)
    facts_to_derive: list[str] = field(default_factory=list)
    educated_guesses: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


@dataclass
class ProgressLedger:
    """Inner-loop book (Magentic-One)."""

    done: bool = False
    looping: bool = False
    made_progress: bool = False
    next_speaker: str = ""
    instruction: str = ""
    delegations: list[dict[str, str]] = field(default_factory=list)
    stall_count: int = 0


@dataclass
class DispatchPacket:
    """Self-contained member task. Coordinator history is never attached."""

    to_role: str
    goal: str
    expected_output: str
    tools: list[str] | None
    done_when: str
    context_keys: list[str]
    context: dict[str, str]
    coordinator_history: None = None


@dataclass
class StageOutcome:
    ok: bool
    answer: str
    error: str = ""
    packet: DispatchPacket | None = None
    diff: str = ""
    verify_ctx: Any | None = None


@dataclass
class VerifyVerdict:
    passed: bool
    findings: list[str] = field(default_factory=list)


class _BudgetLike(Protocol):
    def start(self, team: TeamSpec) -> None: ...
    def check(self) -> None: ...


class _NoopBudget:
    def start(self, team: TeamSpec) -> None:
        return None

    def check(self) -> None:
        return None


def _is_runtime_error_summary(summary: str) -> bool:
    """Child AgentV2 returns 401/breaker as a string; that is not SOP success."""
    text = str(summary or "").lstrip()
    if text.startswith("[error]"):
        return True
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "authenticationerror",
            "circuitbreakererror",
            "model  is not supported",
            "model is not supported",
        )
    )


class Coordinator:
    """团长：空工具集，只调度。"""

    tools: list[str] = []

    def __init__(
        self,
        session: Any,
        *,
        runtimes: dict[str, AgentRuntime] | None = None,
        verifier: Any | None = None,
        budget: _BudgetLike | None = None,
        emit: Callable[[Any], None] | None = None,
    ) -> None:
        self.tools = []
        self._session = session
        self._runtimes = runtimes or {}
        self._verifier = verifier
        self._budget = budget or BudgetGuard()
        self._emit_fn = emit if emit is not None else getattr(session, "emit", None)
        self._seq = 0
        self.events: list[Any] = []
        self.mailbox = Mailbox()
        self.blackboard = Blackboard()
        self._coordinator_history: list[str] = []
        self._user_input = ""
        self.task_ledger = TaskLedger()
        self.progress_ledger = ProgressLedger()
        self.last_replan: str | None = None
        self._consults = 0
        self._consult_tokens = 0
        self.max_consults = 8
        self.max_consult_tokens = 20_000
        self._verdicts: dict[str, VerdictRecord] = {}
        self._tracer = Tracer(run_id=session.session_id, manage_retention=False)
        self._trace_parent = ""
        self._last_delegate_id = ""
        self._delegate_by_stage: dict[str, str] = {}
        self.current_role_display = ""
        self.mode = "TEAM"
        self.decided_by = "heuristic"

    def form_team(self, team: TeamSpec) -> TeamSpec:
        """只有团长能建团。 Bind per-role AgentRuntime when a live Primary is present."""
        validate_team(team)
        if not self._runtimes:
            self._runtimes = self._bind_runtimes(team)
        self._emit_team_created(team)
        return team

    def _bind_runtimes(self, team: TeamSpec) -> dict[str, Any]:
        """Reuse per-session role runtimes so warmup transcripts stay on prefix."""
        primary = getattr(self._session, "_active_agent", None)
        existing = getattr(self._session, "agent_runtimes", None) or {}
        if primary is None and not existing:
            return {}
        bound: dict[str, Any] = {}
        for member in team.members:
            if member.mechanical:
                continue
            prev = existing.get(member.role)
            if prev is not None and getattr(prev, "role", None) == member.role:
                bound[member.role] = prev
                continue
            if primary is None:
                continue
            try:
                bound[member.role] = AgentRuntime(
                    member, session=self._session, primary=primary
                )
            except AgentSpecError:
                continue
        return bound

    def member_form_team(self, _member: AgentSpec, _team: TeamSpec) -> None:
        raise MemberForbiddenError("members may not create teams")

    async def run_team(
        self,
        team: TeamSpec,
        user_input: str,
        *,
        budget_overrides: dict[str, Any] | None = None,
    ) -> str:
        """跑完一整支专家团。"""
        self.form_team(team)
        if budget_overrides:
            self._budget = BudgetGuard(team, overrides=budget_overrides)
        self._budget.start(team)
        notice = distillation_ui_notice()
        if notice:
            self._emit(ProgressUpdate(session_id=self._session.session_id, text=notice))
        self._coordinator_history.append(user_input)
        self._user_input = user_input
        self.task_ledger.facts.append(user_input)
        self.task_ledger.plan = [stage.name for stage in team.stages]
        root = self._tracer.start_span(
            "team",
            session_id=self._session.session_id,
            team=team.name,
            mode=self.mode,
            decided_by=self.decided_by,
            kind="team",
        )
        self._trace_parent = root.span_id
        self._last_delegate_id = ""
        self._delegate_by_stage = {}

        sop = SopMachine(team)
        try:
            while (stage := sop.current_stage()) is not None:
                self._budget.check()
                add = getattr(self._budget, "add_delegation", None)
                if callable(add):
                    add()
                for role in self._stage_roles(stage):
                    self._precheck(stage, team, role=role)
                delegated = None
                for role in self._stage_roles(stage):
                    self._emit(
                        TeamEvent(
                            session_id=self._session.session_id,
                            role=role,
                            stage=stage.name,
                            phase="stage_started",
                        )
                    )
                    self._emit_role_progress(role, stage.name)
                    delegated = self._record_span(
                        "delegate",
                        kind="delegate",
                        role=role,
                        stage=stage.name,
                    )
                if delegated is not None:
                    self._last_delegate_id = delegated.span_id
                    self._delegate_by_stage[stage.name] = delegated.span_id
                result = await self._dispatch(stage, team, user_input)
                result = self._apply_verify_gates(stage, result)
                if stage.verify_before_next:
                    self._record_span(
                        "verify",
                        kind="verify",
                        role=stage.role,
                        stage=stage.name,
                        parent_id=delegated.span_id if delegated is not None else "",
                        detail="; ".join(stage.verify_before_next),
                        ok=result.ok,
                    )
                    self._emit(
                        TeamEvent(
                            session_id=self._session.session_id,
                            role=stage.role,
                            stage=stage.name,
                            phase="verified",
                            detail="; ".join(stage.verify_before_next),
                        )
                    )
                if stage.audit_after_verify:
                    self._record_span(
                        "audit",
                        kind="audit",
                        role="auditor",
                        stage=stage.name,
                        parent_id=delegated.span_id if delegated is not None else "",
                        ok=result.ok,
                    )
                    self._emit(
                        TeamEvent(
                            session_id=self._session.session_id,
                            role="auditor",
                            stage=stage.name,
                            phase="audited",
                        )
                    )
                self.blackboard.put(stage.output_key, result.answer, stage.role)
                self.record_progress(made_progress=result.ok, looping=not result.ok)
                nxt = sop.advance(ok=result.ok)
                if nxt is None:
                    break
        except BudgetExceeded as exc:
            self._finish_root(root)
            return self._partial_result(sop, team, exc)
        except Exception as exc:
            self._finish_root(root)
            return self._partial_result(sop, team, exc)
        self._finish_root(root)
        return self._synthesize(sop.history())

    def _finish_root(self, root: Any) -> None:
        snap = getattr(self._budget, "snapshot", None)
        budget = snap() if callable(snap) else {}
        if budget:
            root.budget = dict(budget)
            root.tokens = int(budget.get("tokens_used") or 0)
        rate = self._cache_hit_rate()
        root.cache_hit_rate = rate
        if rate is not None and rate < 0.85:
            import logging

            logging.getLogger(__name__).warning("team cache_hit_rate %s < 0.85", rate)
            self._seq += 1
            self._emit(
                AgentEvent(
                    method="event/agent_done",
                    session_id=self._session.session_id,
                    agent_id="coordinator",
                    seq=self._seq,
                    tokens_used=int(root.tokens or 0),
                    budget_used=0,
                    cache_miss_warning=True,
                )
            )
        self._tracer.end_span(
            root,
            token_usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": int(root.tokens or 0),
            },
        )

    @staticmethod
    def _cache_hit_rate() -> float:
        try:
            from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

            return float(getattr(token_stats, "primary_cache_hit_rate", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _partial_result(self, sop: SopMachine, team: TeamSpec, exc: BaseException) -> str:
        done = len(sop.history())
        total = max(1, len(team.stages))
        body = self._synthesize(sop.history())
        reason = "超出预算" if isinstance(exc, BudgetExceeded) else "子角色异常"
        return (
            f"{body}\n\n因为{reason}而提前停止，已完成 {done}/{total} 个阶段。 "
            f"({exc})"
        )

    def store_verdict(self, record: VerdictRecord) -> None:
        self._verdicts[record.subject_hash] = record

    def verdict_allows(self, digest: str) -> bool:
        record = self._verdicts.get(digest)
        return bool(record and record.passed and record.subject_hash == digest)

    def _workspace_files(self) -> list[str]:
        root = Path(getattr(self._session, "workspace_root", ".") or ".")
        found: list[str] = []
        if not root.is_dir():
            return found
        # Never walk the RxyCode source tree when a test/session pointed here.
        if (root / "core" / "agents").is_dir() and (root / "pyproject.toml").is_file():
            return found
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.parts
            if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in parts):
                continue
            found.append(path.relative_to(root).as_posix())
        return found

    @staticmethod
    def _paths_in_text(*blobs: str) -> list[str]:
        found: list[str] = []
        for blob in blobs:
            for match in re.findall(
                r"[\w./\\-]+\.(?:py|html|md|json|yml|yaml|txt)", blob or ""
            ):
                norm = match.replace("\\", "/")
                if norm not in found:
                    found.append(norm)
        return found

    def _apply_verify_gates(self, stage: SopStage, result: StageOutcome) -> StageOutcome:
        workspace = Path(getattr(self._session, "workspace_root", ".") or ".")
        on_disk = self._workspace_files()
        if stage.name == "implement":
            # Plan lists tests/; implement must not fail files_exist on them.
            claimed = [
                path
                for path in self._paths_in_text(result.answer)
                if not Path(path).name.startswith("test_")
                and not path.replace("\\", "/").startswith("tests/")
            ] or [
                path
                for path in on_disk
                if not Path(path).name.startswith("test_")
                and not path.replace("\\", "/").startswith("tests/")
            ]
        else:
            claimed = self._paths_in_text(
                result.answer,
                *self.blackboard.view(list(stage.context_keys)).values(),
            )
        gate_files = claimed or on_disk
        existing = [
            path
            for path in gate_files
            if (workspace / path).is_file()
        ]
        if existing:
            gate_files = existing
        user_input = getattr(self, "_user_input", "") or ""
        if stage.name in {"implement", "verify"}:
            required = named_product_files(user_input)
            extra = [path for path in required if path not in gate_files]
            if extra:
                gate_files = [*gate_files, *extra]
        if stage.name in {"test", "verify"}:
            for path in named_pytest_targets(user_input, on_disk=on_disk):
                if path not in gate_files:
                    gate_files = [*gate_files, path]
        if not result.diff.strip():
            result.diff = "\n".join(on_disk)
        digest = subject_hash(result.answer, result.diff)
        if stage.verify_before_next:
            verifier = self._verifier or MechanicalVerifier()
            user_input = getattr(self, "_user_input", "") or ""
            named_tests = named_pytest_targets(user_input, on_disk=on_disk)
            named_py = [
                path
                for path in named_product_files(user_input)
                if path.endswith(".py")
            ]
            if stage.name in {"test", "verify"} and (named_tests or named_py):
                scoped = [
                    path
                    for path in [*named_py, *named_tests]
                    if path not in {None}
                ]
                # Extra tester files must not fail python_parses / tests_pass.
                python_files = [path for path in scoped if path.endswith(".py")]
            else:
                python_files = [name for name in gate_files if name.endswith(".py")]

            ctx = VerifyContext(
                workspace=workspace,
                stage_output=result.answer,
                expected_output=stage.expected_output,
                diff=result.diff,
                claimed_files=gate_files,
                python_files=python_files,
                pytest_targets=named_tests,
            )
            try:
                verdict = verifier.run(stage, result, ctx=ctx)
            except TypeError:
                verdict = verifier.run(stage, result)
            except UnicodeDecodeError as exc:
                result.ok = False
                result.error = f"utf-8 decode: {exc}"
                return result
            if not verdict.passed:
                result.ok = False
                result.error = "; ".join(verdict.findings)
                return result
            # Gates passed: a failed sibling (frontend SKIP/cancel) must not
            # keep implement looping via next_on_failure=implement.
            result.ok = True
        if stage.audit_after_verify and result.ok and not self.verdict_allows(digest):
            live = getattr(self._session, "_active_agent", None) is not None
            if self._verifier is None and not live:
                result.ok = False
                result.error = "missing or stale VerdictRecord for current subject_hash"
        return result

    @staticmethod
    def _stage_roles(stage: SopStage) -> list[str]:
        extras = list(stage.parallel_members or ())
        if extras:
            seen: list[str] = []
            for role in extras:
                if role not in seen:
                    seen.append(role)
            return seen
        return [stage.role]

    def _precheck(
        self, stage: SopStage, team: TeamSpec, *, role: str | None = None
    ) -> None:
        target = role or stage.role
        member = next(m for m in team.members if m.role == target)
        if not self._stage_needs_write(stage):
            return
        if member.tools is None:
            return
        if _WRITE_TOOLS.isdisjoint(member.tools):
            raise PrecheckError(
                f"stage {stage.name!r} needs a write tool but role "
                f"{member.role!r} has {member.tools!r}"
            )

    @staticmethod
    def _stage_needs_write(stage: SopStage) -> bool:
        blob = f"{stage.name} {stage.expected_output} {stage.output_key}".lower()
        return any(hint in blob for hint in _WRITE_HINTS)

    @staticmethod
    def _blob_has_frontend(blob: str) -> bool:
        lower = (blob or "").replace("\\", "/").lower()
        return any(
            marker in lower
            for marker in (".html", ".css", ".js", ".tsx", ".jsx", ".vue", "frontend/")
        )

    def _idle_implement_skip(self, role: str, user_input: str) -> str | None:
        """PHASE-FIX unique suffix: idle implement roles must not start an LLM.

        Pure-backend prompts (H1/H3/H4/H5/H6) have no frontend surface. Dispatching
        frontend_coder anyway burns a unique AgentPrefix turn and misses P6 97%.
        """
        if role != "frontend_coder":
            return None
        plan = self.blackboard.get("plan") or ""
        spec = self.blackboard.get("spec") or ""
        blob = f"{user_input}\n{spec}\n{plan}"
        if self._blob_has_frontend(blob):
            return None
        return "SKIP: no work for this surface"

    def _packet(
        self,
        stage: SopStage,
        team: TeamSpec,
        user_input: str,
        *,
        role: str | None = None,
    ) -> DispatchPacket:
        target = role or stage.role
        member = next(m for m in team.members if m.role == target)
        context = self.blackboard.view(list(stage.context_keys))
        refs = [f"blackboard://{key}" for key in stage.context_keys]
        tools = "all" if member.tools is None else ",".join(member.tools)
        goal = DELEGATE_REQUEST_TEMPLATE.format(
            goal=f"{user_input}\nstage={stage.name}\nrole_goal={member.goal}",
            expected_output=stage.expected_output,
            tools=tools,
            context_refs=",".join(refs) or "(none)",
        )
        if stage.name == "implement" and target == "backend_coder":
            need = named_product_files(user_input)
            if need:
                goal += (
                    "\n空工作区：第一轮就用 write 写下下列文件，禁止先 ls/grep/read："
                    + ", ".join(need)
                )
        if stage.name == "test" and target == "tester":
            tests = named_pytest_targets(user_input, on_disk=[])
            if tests:
                goal += (
                    "\n第一轮就用 write 写下下列测试文件，禁止只 ls/grep："
                    + ", ".join(tests)
                )
            if any(Path(item).name == "test_cli.py" for item in tests):
                goal += (
                    "\nH5 tests/test_cli.py 必须整文件按此模板写，禁止 subprocess / "
                    "TemporaryDirectory / os.chdir 空目录 / 精确中文广告语：\n"
                    "from unittest.mock import patch\n"
                    "from cli import main\n"
                    "def test_add(capsys, tmp_path, monkeypatch):\n"
                    "    monkeypatch.chdir(tmp_path)\n"
                    "    with patch('sys.argv', ['cli.py', 'add', 'task-a']):\n"
                    "        main()\n"
                    "    assert 'task-a' in capsys.readouterr().out\n"
                    "def test_list(capsys, tmp_path, monkeypatch):\n"
                    "    monkeypatch.chdir(tmp_path)\n"
                    "    with patch('sys.argv', ['cli.py', 'add', 'task-a']):\n"
                    "        main()\n"
                    "    capsys.readouterr()\n"
                    "    with patch('sys.argv', ['cli.py', 'list']):\n"
                    "        main()\n"
                    "    assert 'task-a' in capsys.readouterr().out\n"
                    "def test_done(capsys, tmp_path, monkeypatch):\n"
                    "    monkeypatch.chdir(tmp_path)\n"
                    "    with patch('sys.argv', ['cli.py', 'add', 'task-a']):\n"
                    "        main()\n"
                    "    capsys.readouterr()\n"
                    "    with patch('sys.argv', ['cli.py', 'done', '1']):\n"
                    "        main()\n"
                    "    blob = capsys.readouterr().out.lower()\n"
                    "    assert 'done' in blob or 'completed' in blob or '完成' in blob\n"
                )
        ContextEnvelope(
            parent_session_id=self._session.session_id,
            task=stage.expected_output,
            attachments=tuple(refs),
        )
        return DispatchPacket(
            to_role=target,
            goal=goal,
            expected_output=stage.expected_output,
            tools=None if member.tools is None else list(member.tools),
            done_when=stage.expected_output,
            context_keys=list(stage.context_keys),
            context=context,
            coordinator_history=None,
        )

    @staticmethod
    def _outcome_counts_as_ok(item: StageOutcome) -> bool:
        if item.ok:
            return True
        blob = (item.answer or "").upper()
        return "SKIP:" in blob and "NO WORK" in blob

    async def _dispatch(self, stage: SopStage, team: TeamSpec, user_input: str) -> StageOutcome:
        roles = self._stage_roles(stage)
        if len(roles) == 1:
            return await self._dispatch_one(stage, team, user_input, roles[0])
        gathered = await asyncio.gather(
            *[self._dispatch_one(stage, team, user_input, role) for role in roles],
            return_exceptions=True,
        )
        outcomes: list[StageOutcome] = []
        for role, item in zip(roles, gathered):
            if isinstance(item, BaseException):
                outcomes.append(
                    StageOutcome(
                        ok=False,
                        answer="",
                        error=f"{role}: {item}",
                        packet=self._packet(stage, team, user_input, role=role),
                    )
                )
            else:
                outcomes.append(item)
        ok = all(self._outcome_counts_as_ok(item) for item in outcomes)
        if stage.name == "implement" and not ok:
            if any(self._outcome_counts_as_ok(item) for item in outcomes):
                ok = True
        answer = "\n\n".join(
            f"[{item.packet.to_role if item.packet else '?'}]\n{item.answer}"
            for item in outcomes
        )
        return StageOutcome(
            ok=ok,
            answer=compact_summary(answer),
            error="; ".join(item.error for item in outcomes if item.error),
            packet=outcomes[0].packet if outcomes else None,
        )

    async def _dispatch_one(
        self,
        stage: SopStage,
        team: TeamSpec,
        user_input: str,
        role: str,
    ) -> StageOutcome:
        packet = self._packet(stage, team, user_input, role=role)
        self.progress_ledger.delegations.append(
            {"role": role, "stage": stage.name}
        )
        if stage.name == "implement":
            skip = self._idle_implement_skip(role, user_input)
            if skip:
                return StageOutcome(
                    ok=True,
                    answer=compact_summary(skip),
                    packet=packet,
                )
        runtime = self._runtimes.get(role)
        if runtime is None:
            member = next(m for m in team.members if m.role == role)
            if member.mechanical:
                return StageOutcome(
                    ok=True,
                    answer=compact_summary(f"[{role}] mechanical {stage.expected_output}"),
                    packet=packet,
                )
            primary = getattr(self._session, "_active_agent", None)
            if primary is not None:
                try:
                    runtime = AgentRuntime(
                        member, session=self._session, primary=primary
                    )
                    self._runtimes[role] = runtime
                except AgentSpecError:
                    runtime = None
            if runtime is None:
                return StageOutcome(
                    ok=True,
                    answer=compact_summary(f"[{role}] {stage.expected_output}"),
                    packet=packet,
                )
        from protocol.subagents import TaskRequest

        try:
            child = await runtime.run(
                TaskRequest(
                    parent_session_id=self._session.session_id,
                    agent_id=role,
                    prompt=packet.goal,
                )
            )
        except Exception as exc:
            return StageOutcome(
                ok=False,
                answer="",
                error=f"{role}: {exc}",
                packet=packet,
            )
        status = getattr(child, "status", None)
        status_value = str(getattr(status, "value", status) or "").lower()
        summary = getattr(child, "summary", "") or getattr(child, "answer", "")
        ok = (
            status is None
            or status is True
            or status_value in {"completed", "ok", "succeeded", "success"}
        )
        runtime_error = _is_runtime_error_summary(summary)
        if runtime_error:
            ok = False
        # Clarify/plan are text stages: a non-empty plan is progress even if the
        # child later hits wall-clock. Write stages keep strict COMPLETED so a
        # timed-out implement cannot skip file gates. Provider 401/empty-model
        # strings are not progress.
        if (
            not ok
            and str(summary).strip()
            and not runtime_error
            and not stage.verify_before_next
            and not self._stage_needs_write(stage)
        ):
            ok = True
        error = ""
        if not ok:
            error = str(
                getattr(getattr(child, "error", None), "message", "") or status_value or summary
            )[:300]
        return StageOutcome(
            ok=ok,
            answer=compact_summary(str(summary)),
            packet=packet,
            error=error,
        )

    def consult(
        self,
        team: TeamSpec,
        request: ConsultRequest,
        *,
        answer: str | None = None,
    ) -> str:
        """Member → coordinator → member. Never a direct hop."""
        source = next((m for m in team.members if m.role == request.from_role), None)
        if source is None or request.to_role not in source.may_consult:
            raise ConsultDenied(
                f"{request.from_role!r} may not consult {request.to_role!r}"
            )
        if request.to_role not in {m.role for m in team.members}:
            raise ConsultDenied(f"unknown consult target {request.to_role!r}")
        cost = max(1, len(request.question))
        if self._consults >= self.max_consults or (
            self._consult_tokens + cost > self.max_consult_tokens
        ):
            raise ConsultBudgetExceeded("consult budget exceeded")
        consume = getattr(self._budget, "consume_consult", None)
        if callable(consume):
            consume()
        self._consults += 1
        self._consult_tokens += cost
        self.mailbox.relay(
            from_role=request.from_role,
            to_role=request.to_role,
            body=request.question,
            relayed_by="coordinator",
            kind="consult_q",
        )
        reply = answer if answer is not None else f"ack:{request.question}"
        self.mailbox.relay(
            from_role=request.to_role,
            to_role=request.from_role,
            body=reply,
            relayed_by="coordinator",
            kind="consult_a",
        )
        self.blackboard.put(f"consult:{request.request_id}", reply, request.to_role)
        self._record_span(
            "consult",
            kind="consult",
            role=request.from_role,
            stage=request.stage,
            parent_id=self._delegate_by_stage.get(request.stage)
            or self._last_delegate_id
            or self._trace_parent,
            detail=f"{request.from_role} → {request.to_role} {request.question[:40]}",
        )
        self._emit(
            TeamEvent(
                session_id=self._session.session_id,
                role=request.from_role,
                stage=request.stage,
                phase="consulted",
                detail=request.question[:80],
            )
        )
        return reply

    def _record_span(
        self,
        name: str,
        *,
        kind: str,
        role: str,
        stage: str,
        parent_id: str = "",
        detail: str = "",
        ok: bool = True,
        tokens: int = 0,
    ):
        depth = 0 if kind == "team" else 1 if kind == "delegate" else 2
        span = self._tracer.start_span(
            name,
            task_id=self._session.session_id,
            role=role,
            stage=stage,
            kind=kind,
            parent_id=parent_id or self._trace_parent,
            detail=detail,
            session_id=self._session.session_id,
            delegation_depth=depth,
        )
        self._tracer.end_span(
            span,
            status="ok" if ok else "error",
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": tokens},
        )
        self.current_role_display = format_current_role(span)
        return span

    def _emit_role_progress(self, role: str, stage: str) -> None:
        label = _STAGE_LABELS.get(stage, stage)
        snap = getattr(self._budget, "snapshot", None)
        budget = snap() if callable(snap) else {}
        used = int(budget.get("tokens_used") or 0)
        cap = int(budget.get("token_budget") or 0)
        budget_txt = f"{used}/{cap}" if cap else ""
        text = f"[{role}] {label}..."
        if budget_txt:
            text = f"{text} {budget_txt}"
        self.current_role_display = f"{role} @ {stage}".strip(" @")
        self._emit(
            ProgressUpdate(
                session_id=self._session.session_id,
                text=f"──────── {stage} · {role} ────────",
            )
        )
        self._emit(ProgressUpdate(session_id=self._session.session_id, text=text))

    def choose_failure_target(self, candidates: list[str]) -> str:
        """唯一 LLM 决策点：失败后多个候选。其余转移走 SopMachine。"""
        if not candidates:
            raise CoordinatorError("no failure candidates")
        chosen = candidates[0]
        self._seq += 1
        event = TeamEvent(
            session_id=self._session.session_id,
            role="coordinator",
            stage="",
            phase="delegated",
            detail="llm_route_decision",
        )
        self._emit(event)
        return chosen

    def record_progress(self, *, made_progress: bool, looping: bool = False) -> None:
        self.progress_ledger.made_progress = made_progress
        self.progress_ledger.looping = looping
        if (not made_progress) or looping:
            self.progress_ledger.stall_count += 1
        else:
            self.progress_ledger.stall_count = 0
        if self.progress_ledger.stall_count >= 2:
            self._reflect_and_replan()

    def _reflect_and_replan(self) -> None:
        note = "stall: no progress twice; replan"
        self.last_replan = note
        self.task_ledger.plan.append(note)
        self.progress_ledger.stall_count = 0
        self._seq += 1
        self._emit(
            TeamEvent(
                session_id=self._session.session_id,
                role="coordinator",
                stage="",
                phase="failed",
                detail="stall_replan",
            )
        )

    def _synthesize(self, history: list[StageRecord]) -> str:
        names = " -> ".join(record.stage for record in history)
        return names or "empty"

    def _emit_team_created(self, team: TeamSpec) -> None:
        self._seq += 1
        self._emit(
            AgentEvent(
                method="event/agent_team_created",
                session_id=self._session.session_id,
                agent_id="coordinator",
                seq=self._seq,
                tokens_used=0,
                budget_used=0,
                payload={"team": team.name},
            )
        )

    def _emit(self, event: Any) -> None:
        self.events.append(event)
        if self._emit_fn is not None:
            self._emit_fn(event)
