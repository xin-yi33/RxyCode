"""执行模式路由。

三级决策，从便宜到贵，命中即返回：

  第 1 级 用户显式指令      /solo /team /team-multi 或 settings 强制
  第 2 级 确定性信号        任务可拆性、涉及文件数、是否跨模块、任务树规模、是否只读
  第 3 级 LLM 判难度        可选，模型由用户在 settings 里指定

为什么不是纯 LLM 判断：调研显示基于 LLM 的路由会增加延迟、成本和不确定性
（见 PHASE-F §2.2）。大部分请求用确定性信号就能判准，把 LLM 留给真正含糊
的那一小部分。

为什么保留 LLM 那一级：确定性信号看不出"这个需求有多难"，只能看出"它涉及
多少东西"。含糊场景需要语义判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from RxyCode.RxyCode1_1_0.core.request_routing import is_fast_social_turn
from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent, ExperimentTag

_CMD_RE = re.compile(
    r"^\s*/(?P<cmd>solo|team-multi|team|why-mode)\b(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_FILE_RE = re.compile(
    r"\b[\w./\\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"[?？]\s*$|^(?:why|how|what|是否|为什么|怎么|什么是)\b",
    re.IGNORECASE,
)
_SERIAL_RE = re.compile(
    r"单文件|必须同步|全量上下文|强耦合|改\s*A\s*必须|one file|serial depend",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(
    r"前后端|多模块|独立改造|多人审计|可拆成|structured split|front-?end and back-?end",
    re.IGNORECASE,
)
_SCOPE_RE = re.compile(r"重构|迁移|设计|refactor|migrat|redesign", re.IGNORECASE)
_READONLY_RE = re.compile(r"只读|read-?only|不要改|不要写", re.IGNORECASE)


class ExecutionMode(str, Enum):
    SOLO = "solo"
    TEAM = "team"
    TEAM_MULTI_MODEL = "team_multi"


@dataclass
class L2Thresholds:
    short_question_max_chars: int = 80
    min_files_for_team: int = 4
    min_leaves_for_team: int = 6


@dataclass
class RoutingDecision:
    mode: ExecutionMode
    decided_by: Literal["user", "heuristic", "llm", "default"]
    reason: str
    tokens_used: int = 0
    experiment_tag: ExperimentTag = "E0"
    task: str = ""


def _settings_agents() -> dict[str, Any]:
    try:
        from RxyCode.RxyCode1_1_0.config.settings import load_config

        raw = load_config().get("agents") or {}
        return dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


class ModeRouter:
    """Cheap-to-expensive execution-mode router."""

    def __init__(
        self,
        *,
        llm_ask: Callable[[str], str] | None = None,
        emit: Callable[[AgentEvent], None] | None = None,
        budget: Any | None = None,
        enabled: bool | None = None,
        router_model: str | None = None,
        experiment_tag: ExperimentTag = "E0",
    ) -> None:
        self.thresholds = L2Thresholds()
        self._llm_ask = llm_ask
        self._emit = emit
        self._budget = budget
        self._enabled_override = enabled
        self._router_model_override = router_model
        self._experiment_tag = experiment_tag
        self._llm_calls = 0
        self.last_decision: RoutingDecision | None = None
        self.trace: list[RoutingDecision] = []
        self._seq = 0

    def handle_slash(self, raw: str) -> str:
        """Execute /solo /team /team-multi /why-mode. Returns user-facing text."""
        match = _CMD_RE.match(raw or "")
        if not match:
            return "unknown mode command"
        cmd = match.group("cmd").lower()
        rest = (match.group("rest") or "").strip()
        if cmd == "why-mode":
            last = self.last_decision
            if last is None:
                return "no routing decision yet"
            return (
                f"mode={last.mode.value} decided_by={last.decided_by} "
                f"tag={last.experiment_tag} reason={last.reason}"
            )
        decision = self.route(raw)
        return (
            f"forced {decision.mode.value}"
            + (f" for: {rest}" if rest else "")
        )

    def route(
        self,
        text: str,
        *,
        session_id: str = "ses-route",
        leaf_nodes: int = 0,
        readonly: bool = False,
    ) -> RoutingDecision:
        tag = self._tag()
        cmd, rest = self._split(text)
        if cmd in {"solo", "team", "team-multi"}:
            mode = {
                "solo": ExecutionMode.SOLO,
                "team": ExecutionMode.TEAM,
                "team-multi": ExecutionMode.TEAM_MULTI_MODEL,
            }[cmd]
            return self._commit(
                RoutingDecision(
                    mode=mode,
                    decided_by="user",
                    reason=f"slash /{cmd}",
                    experiment_tag=tag,
                    task=rest,
                ),
                session_id,
            )

        task_text = rest or text
        if is_fast_social_turn(task_text):
            return self._commit(
                RoutingDecision(
                    mode=ExecutionMode.SOLO,
                    decided_by="heuristic",
                    reason="social greeting",
                    experiment_tag=tag,
                    task=task_text,
                ),
                session_id,
            )

        if not self._enabled():
            return self._commit(
                RoutingDecision(
                    mode=ExecutionMode.SOLO,
                    decided_by="default",
                    reason="agents.enabled=false",
                    experiment_tag=tag,
                    task=text,
                ),
                session_id,
            )

        route_mode = str(_settings_agents().get("route_mode") or "auto").lower()
        if route_mode == "solo":
            return self._commit(
                RoutingDecision(
                    mode=ExecutionMode.SOLO,
                    decided_by="user",
                    reason="settings.route_mode=solo",
                    experiment_tag=tag,
                    task=rest or text,
                ),
                session_id,
            )
        if route_mode == "team":
            return self._commit(
                RoutingDecision(
                    mode=ExecutionMode.TEAM,
                    decided_by="user",
                    reason="settings.route_mode=team",
                    experiment_tag=tag,
                    task=rest or text,
                ),
                session_id,
            )

        heuristic = self._heuristic(rest or text, leaf_nodes=leaf_nodes, readonly=readonly)
        heuristic.experiment_tag = tag
        if not self._router_model():
            return self._commit(heuristic, session_id)
        return self._llm_or_fallback(heuristic, rest or text, session_id, tag)

    def apply_efficiency_gate(
        self,
        *,
        team_beats_solo: bool,
        min_files_for_team: int | None = None,
        min_leaves_for_team: int | None = None,
    ) -> L2Thresholds:
        """F14 writes L2 thresholds back. E2 🔴 keeps enabled=false (caller)."""
        if min_files_for_team is not None:
            self.thresholds.min_files_for_team = min_files_for_team
        elif team_beats_solo:
            self.thresholds.min_files_for_team = max(1, self.thresholds.min_files_for_team - 1)
        else:
            self.thresholds.min_files_for_team += 1
        if min_leaves_for_team is not None:
            self.thresholds.min_leaves_for_team = min_leaves_for_team
        return self.thresholds

    def _heuristic(self, text: str, *, leaf_nodes: int, readonly: bool) -> RoutingDecision:
        blob = text or ""
        if readonly or _READONLY_RE.search(blob):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "readonly task", task=blob)
        if _SERIAL_RE.search(blob):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "serial dependency", task=blob)
        if len(blob) <= self.thresholds.short_question_max_chars and _QUESTION_RE.search(blob):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "short question", task=blob)
        if _SPLIT_RE.search(blob):
            return RoutingDecision(ExecutionMode.TEAM, "heuristic", "structured split", task=blob)
        files = _FILE_RE.findall(blob)
        if len(files) >= self.thresholds.min_files_for_team:
            return RoutingDecision(ExecutionMode.TEAM, "heuristic", "multiple files", task=blob)
        if leaf_nodes >= self.thresholds.min_leaves_for_team:
            return RoutingDecision(ExecutionMode.TEAM, "heuristic", "task-tree leaves", task=blob)
        if _SCOPE_RE.search(blob):
            return RoutingDecision(ExecutionMode.TEAM, "heuristic", "wide-scope verb", task=blob)
        return RoutingDecision(ExecutionMode.SOLO, "heuristic", "default heuristic", task=blob)

    def _llm_or_fallback(
        self,
        fallback: RoutingDecision,
        text: str,
        session_id: str,
        tag: ExperimentTag,
    ) -> RoutingDecision:
        self._llm_calls += 1
        try:
            if self._llm_ask is None:
                raise RuntimeError("router llm unavailable")
            prompt = (
                "Reply with exactly one of: solo, team, team_multi\n"
                f"Task: {text[:500]}"
            )
            raw = str(self._llm_ask(prompt)).strip().lower().replace("-", "_")
            mode = {
                "solo": ExecutionMode.SOLO,
                "team": ExecutionMode.TEAM,
                "team_multi": ExecutionMode.TEAM_MULTI_MODEL,
            }.get(raw.split()[0] if raw else "")
            if mode is None:
                raise ValueError("unparseable router output")
            tokens = max(1, len(prompt) // 4)
            add = getattr(self._budget, "add_tokens", None)
            if callable(add):
                add(tokens)
            return self._commit(
                RoutingDecision(
                    mode=mode,
                    decided_by="llm",
                    reason="llm difficulty",
                    tokens_used=tokens,
                    experiment_tag=tag,
                    task=text,
                ),
                session_id,
            )
        except Exception:
            fallback.reason = f"{fallback.reason}; llm failed, using heuristic"
            return self._commit(fallback, session_id)

    def _commit(self, decision: RoutingDecision, session_id: str) -> RoutingDecision:
        self.last_decision = decision
        self.trace.append(decision)
        if self._emit is not None:
            self._seq += 1
            reason = (decision.reason or "route")[:256]
            self._emit(
                AgentEvent(
                    method="event/agent_routed",
                    session_id=session_id,
                    agent_id="mode_router",
                    seq=self._seq,
                    experiment_tag=decision.experiment_tag,
                    routing_reason=reason,
                    tokens_used=decision.tokens_used,
                    budget_used=0,
                    payload={"mode": decision.mode.value, "decided_by": decision.decided_by},
                )
            )
        return decision

    def _enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return bool(_settings_agents().get("enabled", False))

    def _router_model(self) -> str | None:
        if self._router_model_override is not None:
            return self._router_model_override
        value = _settings_agents().get("router_model")
        return str(value) if value else None

    def _tag(self) -> ExperimentTag:
        raw = self._experiment_tag or _settings_agents().get("experiment_tag") or "E0"
        return raw if raw in {"E0", "E1", "E2"} else "E0"

    @staticmethod
    def _split(text: str) -> tuple[str | None, str]:
        match = _CMD_RE.match(text or "")
        if not match:
            return None, text
        return match.group("cmd").lower(), (match.group("rest") or "").strip()


_DEFAULT: ModeRouter | None = None


def get_default_router() -> ModeRouter:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ModeRouter()
    return _DEFAULT
