"""执行模式路由。

三级决策，从便宜到贵，命中即返回：

  第 1 级 用户显式指令      /solo /team /team-multi /explore，自然语言
                            开专家团 / 用子代理 / 用explore，或 settings 强制
  第 2 级 确定性信号        只读探索 vs 可拆实现 vs 短问答 / 单文件修 bug
  第 3 级 LLM 判难度        可选，模型由用户在 settings 里指定；候选含 explore

抄 Grok Build：explore 是只读代码库调查子代理；专家团是另一条 SOP 路径。
Grok 把 spawn_subagent 常驻工具表，由模型选 explore vs general-purpose。
这里用便宜启发式先选定 {solo, team, explore}，含糊时才走已有 L3。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from RxyCode.RxyCode1_1_0.protocol.notifications import AgentEvent, ExperimentTag

_CMD_RE = re.compile(
    r"^\s*/(?P<cmd>solo|team-multi|team|explore|why-mode)\b(?P<rest>.*)$",
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
    r"前后端|多模块|独立改造|多人审计|可拆成|可拆|"
    r"structured split|front-?end and back-?end|frontend and backend",
    re.IGNORECASE,
)
_SCOPE_RE = re.compile(r"重构|迁移|设计|refactor|migrat|redesign", re.IGNORECASE)
# Solo-only. Must not OR into explore.
_READONLY_RE = re.compile(r"只读|read-?only|不要改|不要写", re.IGNORECASE)
# 废弃代码（2026-09-21）：explore = bool(_EXPLORE_RE.search(blob) or _READONLY_RE.search(blob))
# 「不要改文件内容」被当成只读探索，打开 notes.md 被整轮派给 explore。禁止再引用。
_HOST_OPEN_RE = re.compile(
    r"系统默认程序|给我预览|open_file|不要等我关|"
    r"Typora|记事本|\bnotepad\b|"
    r"(?:用(?:系统)?默认(?:程序|应用)打开)|"
    r"请打开当前目录|不存在的文件|如果打不开|不要静默重试",
    re.IGNORECASE,
)
_FEATURE_RE = re.compile(
    r"完整功能|端到端|整套|跨层|full-?stack|spanning layers",
    re.IGNORECASE,
)
_WRITE_RE = re.compile(
    r"实现(?:一个|完整)?|写入|创建(?:一个)?(?:文件|功能|页面|模块)|"
    r"修改代码|添加功能|写一个|落盘|改代码|"
    r"修(?:一下)?(?:这个)?bug|"
    r"\bimplement\b|\badd (?:a |the )?feature\b|"
    r"\bwrite (?:a |the )?files?\b|\bfix (?:the |this )?(?:bug|issue)\b",
    re.IGNORECASE,
)
_CREATE_WITH_OPEN_RE = re.compile(r"新建|创建|写入|先写|写一个", re.IGNORECASE)
_MISSING_OPEN_RE = re.compile(
    r"如果打不开|不存在的文件|不要静默重试",
    re.IGNORECASE,
)


def is_open_only_preview_task(text: str) -> bool:
    """True when the user asked to preview/open a file, not to write source.

    E3 「打开不存在的文件并报告错误」must not inherit the local-build write
    nudge or the ``tests/test_lru_cache.py`` fast-build contract.
    """
    blob = text or ""
    if not _HOST_OPEN_RE.search(blob):
        return False
    if _MISSING_OPEN_RE.search(blob):
        return True
    if _CREATE_WITH_OPEN_RE.search(blob) or _WRITE_RE.search(blob):
        return False
    return True
_EXPLORE_RE = re.compile(
    r"查代码|找(?:一下)?(?:某个|哪个)?模块|代码在哪|在哪个文件|"
    r"只读探索|这个(?:功能|模块|代码)?怎么工作|"
    r"为什么这样(?:工作|实现)|代码库|搜一下代码|"
    r"\bwhere (?:is|does)\b|\bhow does\b.+\bwork\b|"
    r"\bfind (?:the )?(?:module|file|symbol)\b|"
    r"\bsearch (?:the )?(?:code|codebase)\b|\bcodebase\b",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|yo|你好|您好|嗨|在吗|早上好|晚上好|哈喽)"
    r"[\s!！。.?？~～]*$",
    re.IGNORECASE,
)
_NL_TEAM_RE = re.compile(
    r"(?:请)?(?:帮我)?(?:开|用|启用|强制|走|拉)(?:一下)?专家团(?:模式)?",
    re.IGNORECASE,
)
_NL_EXPLORE_RE = re.compile(
    r"(?:请)?(?:帮我)?(?:开|用|启用|走|拉)(?:一下)?\s*explore(?:\s*子代理)?|"
    r"(?:use|spawn|start)\s+explore(?:\s+subagent)?",
    re.IGNORECASE,
)
_NL_SUBAGENT_RE = re.compile(
    r"(?:请)?(?:帮我)?(?:开|用|启用|走)(?:一下)?子代理|"
    r"(?:use|enable|start)\s+(?:a\s+)?subagents?",
    re.IGNORECASE,
)


class ExecutionMode(str, Enum):
    SOLO = "solo"
    TEAM = "team"
    TEAM_MULTI_MODEL = "team_multi"
    EXPLORE = "explore"


@dataclass(frozen=True)
class RouteIntent:
    """Natural-language routing overlay parsed before slash/heuristics."""

    mode: ExecutionMode | None
    persist_route: bool
    persist_subagents: bool
    remainder: str
    reason: str


@dataclass
class L2Thresholds:
    short_question_max_chars: int = 80
    min_files_for_team: int = 2
    min_leaves_for_team: int = 6


@dataclass
class RoutingDecision:
    mode: ExecutionMode
    decided_by: Literal["user", "heuristic", "llm", "default"]
    reason: str
    tokens_used: int = 0
    experiment_tag: ExperimentTag = "E0"
    task: str = ""


def parse_route_intent(text: str) -> RouteIntent:
    """Parse 开专家团 / 用子代理 / 用explore without requiring a slash."""
    blob = text or ""
    persist_route = bool(_NL_TEAM_RE.search(blob))
    persist_explore = bool(_NL_EXPLORE_RE.search(blob))
    persist_subagents = bool(_NL_SUBAGENT_RE.search(blob)) or persist_explore
    remainder = blob
    for pattern in (_NL_TEAM_RE, _NL_EXPLORE_RE, _NL_SUBAGENT_RE):
        remainder = pattern.sub(" ", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip()
    mode: ExecutionMode | None = None
    reason = ""
    if persist_route:
        mode = ExecutionMode.TEAM
        reason = "nl 开专家团"
    elif persist_explore:
        mode = ExecutionMode.EXPLORE
        reason = "nl 用explore"
    return RouteIntent(
        mode=mode,
        persist_route=persist_route,
        persist_subagents=persist_subagents,
        remainder=remainder,
        reason=reason,
    )


_AGENTS_CACHE: tuple[str, float, dict[str, Any]] | None = None


def _settings_agents() -> dict[str, Any]:
    """Read agents.* without parsing the whole config on every route().

    load_config() re-reads YAML and re-applies ACL on Windows; four calls per
    turn would dominate ModeRouter vs the regex heuristics.
    """
    global _AGENTS_CACHE
    try:
        from RxyCode.RxyCode1_1_0.config.settings import get_config_path, load_config

        path = get_config_path()
        key = str(path)
        mtime = path.stat().st_mtime if path.exists() else 0.0
        cached = _AGENTS_CACHE
        if cached is not None and cached[0] == key and cached[1] == mtime:
            return dict(cached[2])
        raw = load_config().get("agents") or {}
        data = dict(raw) if isinstance(raw, dict) else {}
        _AGENTS_CACHE = (key, mtime, data)
        return dict(data)
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
        """Execute /solo /team /team-multi /explore /why-mode. Returns user-facing text."""
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
        session_enabled: bool = False,
        allow_explore: bool = False,
    ) -> RoutingDecision:
        tag = self._tag()
        cmd, rest = self._split(text)
        if cmd in {"solo", "team", "team-multi", "explore"}:
            mode = {
                "solo": ExecutionMode.SOLO,
                "team": ExecutionMode.TEAM,
                "team-multi": ExecutionMode.TEAM_MULTI_MODEL,
                "explore": ExecutionMode.EXPLORE,
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

        intent = parse_route_intent(text)
        task = intent.remainder if (intent.mode or intent.persist_subagents) else (rest or text)
        if intent.mode is not None:
            return self._commit(
                RoutingDecision(
                    mode=intent.mode,
                    decided_by="user",
                    reason=intent.reason,
                    experiment_tag=tag,
                    task=task,
                ),
                session_id,
            )

        if not self._enabled() and not session_enabled:
            if allow_explore:
                explore_guess = self._heuristic(
                    task or text,
                    leaf_nodes=leaf_nodes,
                    readonly=readonly,
                )
                if explore_guess.mode is ExecutionMode.EXPLORE:
                    explore_guess.experiment_tag = tag
                    return self._commit(explore_guess, session_id)
                if explore_guess.reason == "host preview":
                    explore_guess.experiment_tag = tag
                    return self._commit(explore_guess, session_id)
            # 废弃代码（2026-09-21）：task=text
            # 用子代理 / 开专家团 剥掉触发语后的 remainder 被丢掉，
            # Session 会把整句「用子代理打开 notes.md」当任务正文。禁止再引用。
            return self._commit(
                RoutingDecision(
                    mode=ExecutionMode.SOLO,
                    decided_by="default",
                    reason="agents.enabled=false",
                    experiment_tag=tag,
                    task=task or text,
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
                    task=task or text,
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
                    task=task or text,
                ),
                session_id,
            )

        heuristic = self._heuristic(
            task or text,
            leaf_nodes=leaf_nodes,
            readonly=readonly,
        )
        heuristic.experiment_tag = tag
        if not self._router_model():
            return self._commit(heuristic, session_id)
        return self._llm_or_fallback(heuristic, task or text, session_id, tag)

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
        write = bool(_WRITE_RE.search(blob) or _SCOPE_RE.search(blob) or _SPLIT_RE.search(blob) or _FEATURE_RE.search(blob))
        # 废弃代码（2026-09-21）：explore = bool(_EXPLORE_RE.search(blob) or _READONLY_RE.search(blob))
        explore = bool(_EXPLORE_RE.search(blob))
        readonly_hint = bool(readonly or _READONLY_RE.search(blob))
        if _SERIAL_RE.search(blob) and not _SPLIT_RE.search(blob):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "serial dependency", task=blob)
        if _GREETING_RE.search(blob.strip()):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "greeting", task=blob)
        if _HOST_OPEN_RE.search(blob):
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "host preview", task=blob)
        if explore and not write:
            return RoutingDecision(ExecutionMode.EXPLORE, "heuristic", "readonly explore", task=blob)
        if readonly_hint and not write:
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "readonly task", task=blob)
        if len(blob) <= self.thresholds.short_question_max_chars and _QUESTION_RE.search(blob) and not write:
            return RoutingDecision(ExecutionMode.SOLO, "heuristic", "short question", task=blob)
        if _SPLIT_RE.search(blob) or _FEATURE_RE.search(blob):
            return RoutingDecision(ExecutionMode.TEAM, "heuristic", "structured split", task=blob)
        files = _FILE_RE.findall(blob)
        # 2026-09-23（P1a 复杂度闸门）：点名文件全在 tests/ 下的任务
        # （实现文件 + 它的测试）是单件小活，不进专家团七阶段 SOP。
        # 只有 tests/ 外点名 ≥2 个产品文件才算真正的「多文件」。
        # 依据：E26 现场——「写 eh26_lru.py + tests/test_eh26_lru.py」被判成
        # TEAM（multiple files），走了完整 SOP，用户反馈呈现奇怪。
        nontest_files = [
            f for f in files
            if not f.replace("\\", "/").lower().lstrip("./").startswith("tests/")
        ]
        if len(nontest_files) >= self.thresholds.min_files_for_team and write:
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
                "Reply with exactly one of: solo, team, explore, team_multi\n"
                "solo = greeting, short Q, single-file bugfix, or open/preview a local file.\n"
                "explore = read-only codebase question (where is X, how does Y work).\n"
                "Do not pick explore for 不要改文件 or Typora/notepad preview.\n"
                "team = multi-area implementation (frontend+backend, 多模块, full feature).\n"
                f"Task: {text[:500]}"
            )
            raw = str(self._llm_ask(prompt)).strip().lower().replace("-", "_")
            mode = {
                "solo": ExecutionMode.SOLO,
                "team": ExecutionMode.TEAM,
                "explore": ExecutionMode.EXPLORE,
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
