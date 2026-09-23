"""Headless session facade over AgentV2 (Phase 2 strangler entry point)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from ..protocol.notifications import ErrorNotification, FinalAnswer, ProgressUpdate, TokenUsage

from RxyCode.RxyCode1_1_0.core.agents.coordinator import BudgetExceeded, Coordinator
from RxyCode.RxyCode1_1_0.core.agents.router import (
    ExecutionMode,
    get_default_router,
    parse_route_intent,
)
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team
from RxyCode.RxyCode1_1_0.core.request_routing import is_fast_social_turn
from RxyCode.RxyCode1_1_0.log.log_helpers import classify_agent_result
from RxyCode.RxyCode1_1_0.recovery.error_recovery import should_emit_event_error
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats
from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error


EmitCallback = Callable[[BaseModel], None]

_APPROVED_PLAN_IMPLEMENT_PREFIXES = (
    "按已批准的计划开始实施",
    "已批准计划，开始实施",
)


def _is_approved_plan_implement(text: str) -> bool:
    head = (text or "").lstrip()
    return any(head.startswith(prefix) for prefix in _APPROVED_PLAN_IMPLEMENT_PREFIXES)


def primary_usage_counters() -> dict[str, int | float]:
    """FX-CB7 shipped snapshot: Primary cache_hit_tokens/input_tokens.

    Isolated Child scopes are excluded. Callers (Session.prompt / tests)
    must use this instead of mixing global token_stats totals.
    """
    return token_stats.primary_usage()


def reuse_or_create_session(
    existing: Session | None,
    *,
    session_id: str,
    workspace_root: Path | str,
    emit: EmitCallback,
    session_schema_version: int | None = None,
) -> Session:
    """F14 shared path: keep per-role AgentRuntime across prompts.

    A new Session() every session/prompt drops ``agent_runtimes``, so warmup
    AgentPrefix cannot ride into the next /team turn and Primary 97% misses.
    Same session_id + workspace reuses the object and only refreshes emit.
    """
    root = Path(workspace_root)
    if (
        existing is not None
        and existing.session_id == session_id
        and existing.workspace_root.resolve() == root.resolve()
    ):
        existing.emit = emit
        if session_schema_version is not None:
            existing.session_schema_version = session_schema_version
        return existing
    return Session(
        session_id=session_id,
        workspace_root=root,
        emit=emit,
        session_schema_version=session_schema_version,
    )


@dataclass(frozen=True)
class PromptResult:
    """Terminal outcome of one Session.prompt() turn."""

    answer: str
    status: str
    detail: str = ""
    thinking: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_hit_rate: float | None = None
    reporting_status: str = "not_reported"
    context_used: int | None = None


def thinking_cursor(agent: Any) -> tuple[tuple[str, ...], str]:
    """Snapshot agent thinking state before a prompt."""
    history = tuple(str(item) for item in getattr(agent, "_thinking_history", []))
    return history, str(getattr(agent, "_last_thinking", "") or "")


def thinking_since(agent: Any, cursor: tuple[tuple[str, ...], str]) -> str:
    """Return thinking text produced since ``thinking_cursor``."""
    previous_history, previous_last = cursor
    current_history = tuple(
        str(item) for item in getattr(agent, "_thinking_history", [])
    )
    if current_history[: len(previous_history)] == previous_history:
        new_history = current_history[len(previous_history) :]
    else:
        new_history = current_history
    if new_history:
        return "\n".join(new_history)
    current_last = str(getattr(agent, "_last_thinking", "") or "")
    return current_last if current_last != previous_last else ""


def notification_to_sse_event(notification: BaseModel) -> dict[str, Any] | None:
    """Map protocol notifications to legacy HTTP SSE event dicts.

    P3 strangler scope: only terminal ``final`` / ``error`` events are converted
    here. Mid-run events (token, tool_call, approval_request, ...) still flow
    through ``StreamTUI`` until P4/P5 migrate the full emit path.
    """
    if isinstance(notification, FinalAnswer):
        event: dict[str, Any] = {
            "type": "final",
            "run_id": notification.run_id,
            "text": notification.text,
            "thinking": notification.thinking or "",
            # Preserve provider reporting semantics for the legacy SSE bridge.
            # ``None`` means the provider did not report the metric; converting
            # it to zero makes the Desktop under-report usage and cache rate.
            "input_tokens": notification.input_tokens,
            "output_tokens": notification.output_tokens,
            "cache_hit_tokens": notification.cache_hit_tokens,
            "cache_hit_rate": notification.cache_hit_rate,
        }
        if notification.session_schema_version is not None:
            event["session_schema_version"] = notification.session_schema_version
        return event
    if isinstance(notification, ErrorNotification):
        event = {
            "type": "error",
            "message": notification.message,
        }
        if notification.run_id is not None:
            event["run_id"] = notification.run_id
        if notification.status is not None:
            event["status"] = notification.status
        return event
    if isinstance(notification, TokenUsage):
        return None
    method = getattr(notification, "method", None)
    if isinstance(method, str) and method.startswith("event/"):
        return None
    return None


class Session:
    """One conversation session. No direct I/O — output flows through ``emit``."""

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path | str,
        emit: EmitCallback,
        session_schema_version: int | None = None,
    ) -> None:
        self.session_id = session_id
        self.workspace_root = Path(workspace_root)
        self.emit = emit
        self.session_schema_version = session_schema_version
        # Phase F: Session may hold many expert-role runtimes. Single-agent
        # is zero or one role="default" entry; prompt() still runs AgentV2.
        self.agent_runtimes: dict[str, Any] = {}
        self._shared_agent_memory: dict[str, Any] = {}
        # Natural-language 开专家团 / 用子代理 persist for later turns.
        self._session_route_enabled = False
        self._session_subagents_opt_in = False
        self.drain_steers: Callable[[], list[str]] | None = None
        self._agents_enabled_cached = None
        try:
            self._agents_enabled_cached = self._read_agents_enabled()
        except Exception:
            self._agents_enabled_cached = False

    async def prompt(
        self,
        agent: Any,
        text: str,
        *,
        mode: str,
        run_id: str,
        tui: Any | None = None,
        permission_mode: str | None = None,
    ) -> PromptResult:
        """Run one user turn through AgentV2 and emit terminal protocol events."""
        try:
            from .ttft_clock import (
                bind_prompt_clock,
                mark_reasoning,
                reset_prompt_clock,
            )
        except ImportError:
            from RxyCode.RxyCode1_1_0.core.ttft_clock import (
                bind_prompt_clock,
                mark_reasoning,
                reset_prompt_clock,
            )
        from RxyCode.RxyCode1_1_0.protocol.notifications import ReasoningSnapshot

        clock_token = bind_prompt_clock()
        previous = primary_usage_counters()
        cursor = thinking_cursor(agent)
        outer_emit = self.emit

        def _emit_with_thinking_clock(notification: BaseModel) -> None:
            if isinstance(notification, ReasoningSnapshot):
                mark_reasoning(notification.text, kind="protocol")
            outer_emit(notification)

        self.emit = _emit_with_thinking_clock
        if tui is not None:
            tui._streamed_answer_chars = 0
        workspace = getattr(self, "_resolved_workspace", None)
        if workspace is None:
            workspace = Path(self.workspace_root).expanduser().resolve()
            self._resolved_workspace = workspace
            if not workspace.exists():
                workspace.mkdir(parents=True, exist_ok=True)
        # 2026-09-23: prefer set_session() over bare attribute assignment so a
        # session switch also rebuilds MemoryManager (bare assignment used to
        # leave memory bound to the previous/"latest" bucket).  Same-session
        # calls are a no-op inside set_session.
        _set_session = getattr(agent, "set_session", None)
        if callable(_set_session):
            _set_session(self.session_id)
        elif hasattr(agent, "_session_id"):
            agent._session_id = self.session_id
        if hasattr(agent, "_workspace_root"):
            agent._workspace_root = workspace
        agent._drain_steers = self.drain_steers

        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

        session_token = bind_session(self.session_id)
        try:
            set_working_directory(workspace, persist=False)
            try:
                if permission_mode is None:
                    answer = await self._dispatch_user_turn(agent, text, mode)
                else:
                    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import permission_mode_override

                    with permission_mode_override(permission_mode):
                        answer = await self._dispatch_user_turn(agent, text, mode)
            except BudgetExceeded as exc:
                answer = str(exc) or "team budget exceeded"
            except Exception as exc:
                raw = f"{type(exc).__name__}: {exc}"
                detail = to_user_facing_error(raw)
                # 2026-09-23：exhaust_active_recovery 只在有活跃恢复记录时才发，
                # 避免和 ErrorNotification 重复显示同一条消息。
                recovery_had_active = False
                if tui is not None and hasattr(tui, "exhaust_active_recovery"):
                    tracker = getattr(tui, "_recovery", None)
                    recovery_had_active = (
                        tracker is not None
                        and getattr(tracker, "active", None) is not None
                    )
                    tui.exhaust_active_recovery(detail)
                if should_emit_event_error(exc, retries_exhausted=True) and not recovery_had_active:
                    self.emit(
                        ErrorNotification(
                            session_id=self.session_id,
                            run_id=run_id,
                            message=detail,
                            status="failed",
                        )
                    )
                return PromptResult(answer="", status="failed", detail=detail)

            status, detail = classify_agent_result(answer)
            after = primary_usage_counters()
            delta_input = int(after["input_tokens"]) - int(previous["input_tokens"])
            delta_output = int(after["output_tokens"]) - int(previous["output_tokens"])
            delta_cache_hit_tokens = (
                int(after["cache_hit_tokens"]) - int(previous["cache_hit_tokens"])
            )
            cache_hit_rate = (
                max(delta_cache_hit_tokens, 0) / max(delta_input, 1) * 100
                if delta_input > 0
                else 0.0
            )
            thinking = thinking_since(agent, cursor)

            usage_reported = bool(delta_input or delta_output or delta_cache_hit_tokens)
            latest = token_stats.latest_request
            # Occupancy is the same tiktoken window compact uses. Billing
            # prompt_tokens / turn deltas include cached prefix and must not
            # drive the status bar.
            occupancy = 0
            occupancy_src = "token_stats"
            msgs = getattr(agent, "_agent_prefix_messages", None)
            est = getattr(agent, "_estimate_tokens", None)
            if callable(est) and msgs:
                try:
                    occupancy = int(est(list(msgs)) or 0)
                    occupancy_src = "estimate_tokens"
                except Exception:
                    occupancy = 0
            if occupancy <= 0:
                occupancy = int(getattr(token_stats, "context_used", 0) or 0)
                occupancy_src = "token_stats"
            latest_prompt = int(latest.get("prompt_tokens") or 0)
            window_used = occupancy
            streamed = int(getattr(tui, "_streamed_answer_chars", 0) or 0)
            usage_kwargs = {
                "input_tokens": max(delta_input, 0) if usage_reported else None,
                "output_tokens": max(delta_output, 0) if usage_reported else None,
                "cache_hit_tokens": max(delta_cache_hit_tokens, 0) if usage_reported else None,
                "cache_hit_rate": cache_hit_rate if usage_reported else None,
                "reporting_status": "reported" if usage_reported else "not_reported",
            }
            occupancy_kwargs = {"context_used": window_used or None}
            self.emit(
                TokenUsage(
                    session_id=self.session_id,
                    **occupancy_kwargs,
                    **usage_kwargs,
                )
            )

            if status == "failed" and streamed > 0:
                # Tokens already reached the TUI (HTML/files already shown).
                # A trailing [error]/empty classify must not paint MSG_DEFAULT.
                status = "succeeded"

            if status == "succeeded":
                if tui is not None and hasattr(tui, "resolve_active_recovery"):
                    tui.resolve_active_recovery()
                self.emit(
                    FinalAnswer(
                        session_id=self.session_id,
                        run_id=run_id,
                        text=answer,
                        thinking=thinking or None,
                        **usage_kwargs,
                        session_schema_version=self.session_schema_version,
                    )
                )
                return PromptResult(
                    answer=answer,
                    status=status,
                    detail=detail,
                    thinking=thinking,
                    **occupancy_kwargs,
                    **usage_kwargs,
                )

            # 2026-09-23：exhaust_active_recovery 只在有活跃恢复记录时才发事件，
            # 避免和下面的 ErrorNotification 重复显示同一条消息（用户现场：
            # 「模型调用已暂停」在界面上出现两次）。
            recovery_had_active = False
            if tui is not None and hasattr(tui, "exhaust_active_recovery"):
                tracker = getattr(tui, "_recovery", None)
                recovery_had_active = (
                    tracker is not None and getattr(tracker, "active", None) is not None
                )
                tui.exhaust_active_recovery(detail)
            visible = to_user_facing_error(detail)
            # 如果 recovery tracker 刚发了 RecoveryExhausted（带着同一条错误），
            # ErrorNotification 不再重复发。
            if not recovery_had_active:
                self.emit(
                    ErrorNotification(
                        session_id=self.session_id,
                        run_id=run_id,
                        message=visible,
                        status=status,
                    )
                )
            return PromptResult(
                answer=answer,
                status=status,
                detail=detail,
                thinking=thinking,
                **occupancy_kwargs,
                **usage_kwargs,
            )
        finally:
            self.emit = outer_emit
            reset_prompt_clock(clock_token)
            reset_session_binding(session_token)

    def _agents_enabled(self) -> bool:
        """Cheap read of agents.enabled. Missing config means the default (off).

        Avoid ``load_config()`` here: it creates a file on first use and would
        delay stub hangs / ``session/interrupt`` on a cold worker. Parse the
        YAML text without importing yaml (lazy-import budget). Cached per
        Session so the thinking-TTFT clock is not charged a config-file read
        on every prompt.
        """
        cached = getattr(self, "_agents_enabled_cached", None)
        if cached is not None:
            return cached
        value = self._read_agents_enabled()
        self._agents_enabled_cached = value
        return value

    @staticmethod
    def _read_agents_enabled() -> bool:
        try:
            from RxyCode.RxyCode1_1_0.config.settings import get_config_path

            path = get_config_path()
            if not path.exists():
                return False
            in_agents = False
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("agents:"):
                    in_agents = True
                    continue
                if in_agents and line[:1] not in " \t" and line.strip():
                    in_agents = False
                if not in_agents:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("enabled:"):
                    raw = stripped.split(":", 1)[1].split("#", 1)[0].strip().lower()
                    return raw in {"true", "yes", "1"}
            return False
        except Exception:
            return False

    @staticmethod
    def _appserver_stub() -> bool:
        """Harness-only: stdio E2E measures routing, not live child LLM."""
        return os.environ.get("RXYCODE_APPSERVER_STUB") == "1"

    async def _run_explore(self, prompt: str) -> str:
        """Dispatch the builtin explore subagent (Grok Build spawn_subagent analogue)."""
        self.emit(
            ProgressUpdate(
                session_id=self.session_id,
                text="正在用 explore 子代理探索代码库...",
            )
        )
        if self._appserver_stub():
            return f"explore:{prompt}"
        from RxyCode.RxyCode1_1_0.tools.subagent_task_tool import dispatch_subagent_task

        # 废弃代码（2026-09-21）：
        # return await dispatch_subagent_task(
        #     agent_id="explore", prompt=prompt, description="explore codebase",
        # )
        # description 曾写入 ContextEnvelope.task，子代理 Task: 变成这句展示文案。
        return await dispatch_subagent_task(agent_id="explore", prompt=prompt)

    def _apply_session_route_flags(self, agent: Any, text: str):
        intent = parse_route_intent(text)
        if intent.persist_route:
            self._session_route_enabled = True
        if intent.persist_subagents:
            self._session_subagents_opt_in = True
            try:
                agent._session_subagents_opt_in = True
            except Exception:
                pass
        return intent

    async def _dispatch_user_turn(self, agent: Any, text: str, mode: str) -> str:
        """Route slash commands and expert-team vs solo before AgentV2."""
        stripped = (text or "").strip()
        cmd = ""
        rest = ""
        if stripped.startswith("/"):
            head, _, tail = stripped.partition(" ")
            cmd = head.lower()
            rest = tail.strip()

        intent = self._apply_session_route_flags(agent, stripped)
        if self._session_subagents_opt_in:
            try:
                agent._session_subagents_opt_in = True
            except Exception:
                pass

        routing_cmds = {
            "/solo",
            "/team",
            "/team-multi",
            "/explore",
            "/why-mode",
            "/agents",
        }
        # 「用子代理」with no remainder only unhides `task` and records the
        # session flag. Return before the router so we do not run AgentV2
        # on the opt-in phrase itself.
        if (
            cmd not in routing_cmds
            and intent.mode is None
            and intent.persist_subagents
            and not intent.remainder
        ):
            return (
                "已为本会话打开子代理。下一条可以直接说需求；"
                "只读查代码会走 explore，也可 @explore。"
            )
        # Default product: agents.enabled=false. Stay on AgentV2 without
        # ModeRouter events or Coordinator setup so stub hangs / concurrent
        # session/prompt overlap keep the previous latency. Natural-language
        # 开专家团 / 用explore still enter the router. After 用子代理, skip
        # the cheap path so allow_explore can actually dispatch builtin explore.
        if cmd == "/compact":
            compact = getattr(agent, "compact_now", None)
            if compact is not None:
                return await compact()
            return "当前会话不支持 /compact。"
        cheap = (
            cmd not in routing_cmds
            and intent.mode is None
            and not intent.persist_route
            and not self._session_route_enabled
            and not self._session_subagents_opt_in
            and not self._agents_enabled()
        )
        if cheap:
            run_text = intent.remainder or stripped
            return await agent.run(run_text, mode=mode)

        router = get_default_router()
        previous_emit = router._emit
        router._emit = self.emit
        try:
            if cmd == "/why-mode":
                return router.handle_slash(stripped)
            if cmd == "/agents":
                from RxyCode.RxyCode1_1_0.config.settings import load_config, save_config
                from RxyCode.RxyCode1_1_0.core.agents.client_settings import apply_agents_args

                cfg = load_config()
                _agents, message = apply_agents_args(cfg, rest)
                save_config(cfg)
                return message
            if cmd == "/solo" and not rest:
                return router.handle_slash(stripped)

            decision = router.route(
                stripped,
                session_id=self.session_id,
                session_enabled=self._session_route_enabled,
                allow_explore=self._session_subagents_opt_in,
            )
            self.emit(ProgressUpdate(session_id=self.session_id, text="思考中..."))
            if cmd in {"/solo", "/team", "/team-multi", "/explore"}:
                task = rest
            elif intent.mode or intent.persist_route or intent.persist_subagents:
                # NL 开专家团/用explore consumed the trigger; do not fall back
                # to the raw phrase or Session would dispatch on the flag itself.
                task = (decision.task or intent.remainder or "").strip()
            else:
                task = (decision.task or stripped).strip()

            if decision.mode is ExecutionMode.EXPLORE:
                if not task:
                    if cmd == "/explore":
                        return router.handle_slash(stripped)
                    return (
                        "已为本会话记下 explore。下一条只读探索会派给 explore 子代理；"
                        "也可直接 @explore。"
                    )
                return await self._run_explore(task)

            if decision.mode in (ExecutionMode.TEAM, ExecutionMode.TEAM_MULTI_MODEL):
                # Approved plan already exists; do not restart SOP at clarify.
                if _is_approved_plan_implement(task):
                    return await agent.run(task, mode=mode)
                if not task:
                    if cmd in {"/team", "/team-multi"}:
                        return router.handle_slash(stripped)
                    return (
                        "已为本会话打开专家团自动路由。下一条可拆任务会走专家团；"
                        "/why-mode 查看原因。"
                    )
                if self._appserver_stub():
                    return f"team:{task}"
                if decision.mode is ExecutionMode.TEAM_MULTI_MODEL:
                    self.emit(
                        ProgressUpdate(
                            session_id=self.session_id,
                            text=(
                                "多模型协作已启用，按角色解析模型"
                                if mm_enabled
                                else "多模型协作未开启，按同模型专家团运行"
                            ),
                        )
                    )
                try:
                    team = load_builtin_team(team_name)
                except Exception:
                    team = load_builtin_team("software_dev")
                self._active_agent = agent
                try:
                    coord = Coordinator(self, emit=self.emit)
                    return await coord.run_team(
                        team,
                        task,
                        multi_model=True if decision.mode is ExecutionMode.TEAM_MULTI_MODEL and mm_enabled else None,
                    )
                finally:
                    self._active_agent = None

            run_text = rest if cmd == "/solo" and rest else (task or stripped)
            return await agent.run(run_text, mode=mode)
        finally:
            router._emit = previous_emit

    def interrupt(self, agent: Any) -> bool:
        """Request cancellation on the underlying agent, if supported."""
        cancel = getattr(agent, "cancel", None)
        if callable(cancel):
            return bool(cancel())
        return False
