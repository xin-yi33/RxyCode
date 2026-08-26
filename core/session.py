"""Headless session facade over AgentV2 (Phase 2 strangler entry point)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from ..protocol.notifications import ErrorNotification, FinalAnswer, ProgressUpdate, TokenUsage

from RxyCode.RxyCode1_1_0.core.agents.coordinator import BudgetExceeded, Coordinator
from RxyCode.RxyCode1_1_0.core.agents.router import ExecutionMode, get_default_router
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team
from RxyCode.RxyCode1_1_0.log.log_helpers import classify_agent_result
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats


EmitCallback = Callable[[BaseModel], None]


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
        previous = primary_usage_counters()
        cursor = thinking_cursor(agent)
        workspace = Path(self.workspace_root).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if hasattr(agent, "_session_id"):
            agent._session_id = self.session_id
        if hasattr(agent, "_workspace_root"):
            agent._workspace_root = workspace

        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

        session_token = bind_session(self.session_id)
        try:
            set_working_directory(workspace)
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
                detail = str(exc)
                if tui is not None and hasattr(tui, "exhaust_active_recovery"):
                    tui.exhaust_active_recovery(detail)
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
            usage_kwargs = {
                "input_tokens": max(delta_input, 0) if usage_reported else None,
                "output_tokens": max(delta_output, 0) if usage_reported else None,
                "cache_hit_tokens": max(delta_cache_hit_tokens, 0) if usage_reported else None,
                "cache_hit_rate": cache_hit_rate if usage_reported else None,
                "reporting_status": "reported" if usage_reported else "not_reported",
            }
            self.emit(TokenUsage(session_id=self.session_id, **usage_kwargs))

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
                    **usage_kwargs,
                )

            if tui is not None and hasattr(tui, "exhaust_active_recovery"):
                tui.exhaust_active_recovery(detail)
            self.emit(
                ErrorNotification(
                    session_id=self.session_id,
                    run_id=run_id,
                    message=detail,
                    status=status,
                )
            )
            return PromptResult(
                answer=answer,
                status=status,
                detail=detail,
                thinking=thinking,
                **usage_kwargs,
            )
        finally:
            reset_session_binding(session_token)

    @staticmethod
    def _agents_enabled() -> bool:
        """Cheap read of agents.enabled. Missing config means the default (off).

        Avoid ``load_config()`` here: it creates a file on first use and would
        delay stub hangs / ``session/interrupt`` on a cold worker. Parse the
        YAML text without importing yaml (lazy-import budget).
        """
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
                    value = stripped.split(":", 1)[1].split("#", 1)[0].strip().lower()
                    return value in {"true", "yes", "1"}
            return False
        except Exception:
            return False

    async def _dispatch_user_turn(self, agent: Any, text: str, mode: str) -> str:
        """Route slash commands and expert-team vs solo before AgentV2."""
        stripped = (text or "").strip()
        cmd = ""
        rest = ""
        if stripped.startswith("/"):
            head, _, tail = stripped.partition(" ")
            cmd = head.lower()
            rest = tail.strip()

        # Default product: agents.enabled=false. Stay on AgentV2 without
        # ModeRouter events or Coordinator setup so stub hangs / concurrent
        # session/prompt overlap keep the previous latency.
        if cmd not in {"/solo", "/team", "/team-multi", "/why-mode", "/agents"}:
            if not self._agents_enabled():
                return await agent.run(stripped, mode=mode)

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

            decision = router.route(stripped)
            if cmd in {"/solo", "/team", "/team-multi"}:
                task = rest
            else:
                task = (decision.task or stripped).strip()

            if decision.mode in (ExecutionMode.TEAM, ExecutionMode.TEAM_MULTI_MODEL):
                if not task:
                    return router.handle_slash(stripped)
                if decision.mode is ExecutionMode.TEAM_MULTI_MODEL:
                    self.emit(
                        ProgressUpdate(
                            session_id=self.session_id,
                            text="多模型协作尚未启用（Phase H），按同模型专家团运行",
                        )
                    )
                team_name = "software_dev"
                try:
                    from RxyCode.RxyCode1_1_0.config.settings import load_config

                    team_name = str(
                        (load_config().get("agents") or {}).get("team") or "software_dev"
                    )
                except Exception:
                    team_name = "software_dev"
                try:
                    team = load_builtin_team(team_name)
                except Exception:
                    team = load_builtin_team("software_dev")
                self._active_agent = agent
                try:
                    coord = Coordinator(self, emit=self.emit)
                    return await coord.run_team(team, task)
                finally:
                    self._active_agent = None

            run_text = rest if cmd == "/solo" and rest else stripped
            return await agent.run(run_text, mode=mode)
        finally:
            router._emit = previous_emit

    def interrupt(self, agent: Any) -> bool:
        """Request cancellation on the underlying agent, if supported."""
        cancel = getattr(agent, "cancel", None)
        if callable(cancel):
            return bool(cancel())
        return False
