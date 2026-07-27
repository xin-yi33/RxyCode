"""ToolOrchestrator: intelligent tool selection and registration.

Manages the registry of available tools and selects the right subset
for a given task based on tools_hint.

Also hosts the safety gate (阶段二): ``execute_tool`` is the single
choke point every tool call should pass through — policy classification,
write-path whitelist, dry-run, approval and audit.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from contextvars import ContextVar, Token
from typing import Any

_logger = logging.getLogger(__name__)

from .evidence import ToolEvidence, build_tool_evidence, deterministic_issues


_evidence_sinks: ContextVar[tuple[list[ToolEvidence], ...]] = ContextVar(
    "tool_evidence_sinks",
    default=(),
)
_event_tui: ContextVar[Any | None] = ContextVar(
    "tool_event_tui",
    default=None,
)
_event_tracer: ContextVar[Any | None] = ContextVar(
    "tool_event_tracer",
    default=None,
)
_event_hooks: ContextVar[tuple[Any, list[dict]] | None] = ContextVar(
    "tool_event_hooks",
    default=None,
)
_event_trajectory: ContextVar[Any | None] = ContextVar(
    "tool_event_trajectory",
    default=None,
)
_tool_journal_binding: ContextVar[Any | None] = ContextVar(
    "tool_journal_binding",
    default=None,
)
_live_tool_dedup: ContextVar[dict[str, str] | None] = ContextVar(
    "live_tool_dedup",
    default=None,
)


def _canonical_tool_args(args: Any) -> str:
    import json

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return args
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(args)


class ToolOrchestrator:
    """Registry and selector for agent tools."""

    #: Read-only core tools, safe fallback when tools_hint matching fails.
    #: Adapted from Claude Code's read-only whitelist concept (Read/Grep/
    #: Glob/LS): on ambiguity the agent gets inspection tools only, never
    #: write/execute capabilities.
    READONLY_TOOL_NAMES = frozenset({
        "read", "view", "grep", "glob", "ls", "datetime",
        "websearch", "webfetch",
    })
    TOOL_ALIASES = {
        "web_search": "websearch",
        "search_web": "websearch",
        "web_fetch": "webfetch",
        "fetch_url": "webfetch",
        "open": "open_file",
        "browser": "open_file",
    }

    def __init__(self):
        self._registry: dict[str, Any] = {}
        self._risk_overrides: dict[str, Any] = {}
        self._audit_logger: Any | None = None

    def set_audit_logger(self, logger: Any) -> None:
        """Inject an AuditLogger (defaults to the shared one on first use)."""
        self._audit_logger = logger

    @staticmethod
    def clear_live_dedup() -> None:
        """Reset per-run identical-call cache (call at request start)."""
        _live_tool_dedup.set({})

    @staticmethod
    def _dedup_key(name: str, args: Any) -> str:
        return f"{name.lower()}::{_canonical_tool_args(args)}"
    @staticmethod
    def bind_event_tui(tui: Any | None) -> Token:
        """Bind the request-local consumer for complete tool lifecycle events."""
        return _event_tui.set(tui)

    @staticmethod
    def reset_event_tui(token: Token) -> None:
        _event_tui.reset(token)

    @staticmethod
    def get_event_tui() -> Any | None:
        return _event_tui.get()

    @staticmethod
    def bind_event_tracer(tracer: Any | None) -> Token:
        """Bind the request-local tracer used by every tool entry path."""
        return _event_tracer.set(tracer)

    @staticmethod
    def reset_event_tracer(token: Token) -> None:
        _event_tracer.reset(token)

    @staticmethod
    def get_event_tracer() -> Any | None:
        return _event_tracer.get()

    @staticmethod
    def bind_event_hooks(hooks: Any | None, audit_sink: list[dict]) -> Token:
        binding = (hooks, audit_sink) if hooks is not None else None
        return _event_hooks.set(binding)

    @staticmethod
    def reset_event_hooks(token: Token) -> None:
        _event_hooks.reset(token)

    @staticmethod
    def bind_event_trajectory(trajectory: Any | None) -> Token:
        """Bind the request-local durable trajectory logger."""
        return _event_trajectory.set(trajectory)

    @staticmethod
    def reset_event_trajectory(token: Token) -> None:
        _event_trajectory.reset(token)

    @staticmethod
    def get_event_trajectory() -> Any | None:
        return _event_trajectory.get()

    @staticmethod
    def bind_tool_journal(
        journal: Any | None,
        attempt_id: str | None,
        checkpoint_id: str | None = None,
    ) -> Token:
        """Bind one durable side-effect journal to the current request."""
        binding = (
            journal.binding(attempt_id, checkpoint_id)
            if journal is not None and attempt_id is not None
            else None
        )
        return _tool_journal_binding.set(binding)

    @staticmethod
    def reset_tool_journal(token: Token) -> None:
        _tool_journal_binding.reset(token)

    @staticmethod
    def get_tool_journal_binding() -> Any | None:
        return _tool_journal_binding.get()

    @staticmethod
    async def _emit_event_hooks(phase: str, **payload: Any) -> None:
        binding = _event_hooks.get()
        if binding is None:
            return
        hooks, sink = binding
        results = await hooks.emit(phase, "tool_call", payload)
        sink.extend(result.to_dict() for result in results)

    @staticmethod
    def begin_evidence_capture() -> Token:
        return _evidence_sinks.set((*_evidence_sinks.get(), []))

    @staticmethod
    def end_evidence_capture(token: Token) -> list[ToolEvidence]:
        sinks = _evidence_sinks.get()
        captured = list(sinks[-1]) if sinks else []
        _evidence_sinks.reset(token)
        return captured

    @staticmethod
    def _record_evidence(evidence: ToolEvidence) -> None:
        for sink in _evidence_sinks.get():
            sink.append(evidence)
        from ..log.logger import get_current_run_id
        from ..log.monitor import run_monitor

        run_monitor.record_evidence(get_current_run_id(), evidence)

    def _get_audit_logger(self):
        if self._audit_logger is None:
            from ..core.safety.audit import get_audit_logger
            self._audit_logger = get_audit_logger()
        return self._audit_logger

    def _finish(
        self,
        name: str,
        args: Any,
        result: str,
        *,
        executed: bool,
        approval: str,
        risk: Any | None = None,
        audit: Any | None = None,
        config: dict | None = None,
    ) -> str:
        text = self._clean_tool_output(result, config)
        evidence = build_tool_evidence(
            name,
            args,
            text,
            executed=executed,
            approval=approval,
            risk=risk,
        )
        self._record_evidence(evidence)
        artifact_issues = [
            issue
            for issue in deterministic_issues([evidence])
            if issue.startswith((
                "Expected artifact does not exist:",
                "Artifact failed format validation:",
            ))
        ]
        if executed and artifact_issues:
            text = f"[evidence failed: {'; '.join(artifact_issues)}]"
        if audit is not None and risk is not None:
            audit.log(tool=name, risk=risk, args=args, approval=approval, result=text)
        return text

    @staticmethod
    def _clean_tool_output(result: Any, config: dict | None = None) -> str:
        """Apply one bounded, secret-aware output contract to every tool."""
        text = str(result)
        text = "".join(
            char for char in text
            if char in "\n\r\t" or ord(char) >= 32
        )
        text = re.sub(
            r"(?i)\b(api[_-]?key|authorization|password|passwd|secret|token)"
            r"\s*([:=])\s*([^\s,;]+)",
            lambda match: f"{match.group(1)}{match.group(2)}***",
            text,
        )
        text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer ***", text)
        context_cfg = (config or {}).get("context", {})
        try:
            max_chars = max(
                1000,
                int(context_cfg.get("max_tool_output_chars", 30000) or 30000),
            )
        except (TypeError, ValueError):
            max_chars = 30000
        if len(text) <= max_chars:
            return text
        head = max_chars * 2 // 3
        tail = max_chars - head
        omitted = len(text) - max_chars
        return (
            text[:head]
            + f"\n[tool output truncated: {omitted} chars omitted]\n"
            + text[-tail:]
        )

    @classmethod
    def _canonical_name(cls, name: str) -> str:
        lowered = name.strip().lower()
        return cls.TOOL_ALIASES.get(lowered, lowered)

    def register(self, name: str, tool: Any, *, risk: Any | None = None) -> None:
        """Register a tool and an optional Agent-local minimum risk."""
        canonical = self._canonical_name(name)
        self._registry[canonical] = tool
        if risk is None:
            self._risk_overrides.pop(canonical, None)
            return
        from ..core.safety.policy import RiskLevel

        if isinstance(risk, RiskLevel):
            resolved = risk
        else:
            try:
                resolved = RiskLevel[str(risk).strip().upper()]
            except KeyError as exc:
                raise ValueError(f"invalid tool risk override: {risk!r}") from exc
        self._risk_overrides[canonical] = resolved

    def register_many(self, tools: dict[str, Any]) -> None:
        """Register multiple tools at once."""
        for name, tool in tools.items():
            self.register(name, tool)

    def unregister(self, name: str) -> bool:
        """Remove a tool by canonical name, returning whether it existed."""
        canonical = self._canonical_name(name)
        self._risk_overrides.pop(canonical, None)
        return self._registry.pop(canonical, None) is not None

    def get(self, name: str) -> Any | None:
        """Get a tool by canonical name or supported alias."""
        return self._registry.get(self._canonical_name(name))

    def get_all(self) -> dict[str, Any]:
        """Return all registered tools."""
        return dict(self._registry)

    def select_tools(self, hints: list[str]) -> list[Any]:
        """Select tools matching the given hints.

        - No hints -> all registered tools (explicit "use everything").
        - Hints with matches -> the matched tools.
        - Hints with NO matches -> only the read-only core subset
          (READONLY_TOOL_NAMES), so a bad hint never silently grants
          write/execute tools.

        Matching is case-insensitive substring match on name or description.
        """
        if not hints:
            return list(self._registry.values())

        selected = []
        for hint in hints:
            hint_lower = self._canonical_name(hint)
            for name, tool in self._registry.items():
                if hint_lower in name.lower():
                    selected.append(tool)
                    continue
                desc = getattr(tool, "description", "") or ""
                if hint_lower in desc.lower():
                    selected.append(tool)

        if selected:
            unique: list[Any] = []
            seen_ids: set[int] = set()
            for tool in selected:
                identity = id(tool)
                if identity not in seen_ids:
                    seen_ids.add(identity)
                    unique.append(tool)
            return unique
        return self.get_readonly_tools()

    def get_readonly_tools(self) -> list[Any]:
        """Return the registered read-only core tools (whitelist subset)."""
        return [
            tool for name, tool in self._registry.items()
            if name.lower() in self.READONLY_TOOL_NAMES
        ]

    def select_safe_tools(
        self,
        hints: list[str],
        config: dict | None = None,
        *,
        max_risk: Any | None = None,
    ) -> list[Any]:
        """Return LLM-facing proxies that can only execute through this gate."""
        from ..core.safety.policy import RiskLevel, get_tool_risk
        from langchain_core.tools import StructuredTool

        def make_executor(tool_name: str):
            async def execute_proxy(**kwargs: Any) -> str:
                return await self.execute_tool(tool_name, kwargs, config=config)
            return execute_proxy

        proxies: list[Any] = []
        for raw_tool in self.select_tools(hints):
            name = str(getattr(raw_tool, "name", ""))
            if not name:
                continue
            if max_risk is not None:
                limit = RiskLevel(max_risk)
                canonical = self._canonical_name(name)
                risk = max(
                    get_tool_risk(canonical),
                    self._risk_overrides.get(canonical, RiskLevel.READ),
                )
                if risk > limit:
                    continue

            proxies.append(StructuredTool.from_function(
                coroutine=make_executor(name),
                name=name,
                description=getattr(raw_tool, "description", "") or name,
                args_schema=getattr(raw_tool, "args_schema", None),
            ))
        return proxies

    def list_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._registry.keys())

    # ------------------------------------------------------------------
    # Safety gate (阶段二)
    # Adapted from OpenHands (MIT) openhands/security/ confirmation flow:
    # classify -> whitelist -> dry-run -> approve -> execute -> audit.
    # ------------------------------------------------------------------

    #: Arg keys that hold a filesystem path for write-target checking.
    _PATH_ARG_KEYS = (
        "filePath",
        "path",
        "file_path",
        "save_path",
        "target",
        "filename",
    )

    @staticmethod
    def _tool_timeout_seconds(config: dict | None) -> float:
        """Return the configured tool deadline, or zero when disabled/invalid."""
        if not isinstance(config, dict):
            return 0.0
        execution = config.get("execution") or {}
        if not isinstance(execution, dict):
            return 0.0
        try:
            return max(
                0.0,
                float(execution.get("tool_timeout_seconds", 1800) or 0),
            )
        except (TypeError, ValueError):
            return 0.0

    async def _invoke_and_finish(
        self,
        name: str,
        args: Any,
        tool: Any,
        config: dict | None,
        *,
        approval: str,
        risk: Any,
        audit: Any,
    ) -> str:
        """Invoke once, applying the shared deadline and terminal recording."""
        timeout = self._tool_timeout_seconds(config)
        execution_cfg = (config or {}).get("execution", {})
        try:
            retry_attempts = max(
                1,
                int(execution_cfg.get("tool_retry_attempts", 3) or 3),
            )
            retry_wait = max(
                0.0,
                float(execution_cfg.get("tool_retry_wait_multiplier", 1.0) or 0),
            )
        except (TypeError, ValueError):
            retry_attempts, retry_wait = 1, 1.0

        journal_binding = self.get_tool_journal_binding()
        journal_call = None
        if journal_binding is not None and getattr(risk, "name", "") in {
            "WRITE",
            "DANGER",
        }:
            try:
                journal_call = journal_binding.next_call(name, args)
                reservation = journal_binding.journal.reserve(
                    journal_binding.attempt_id,
                    journal_call,
                    checkpoint_id=journal_binding.checkpoint_id,
                )
            except Exception as exc:
                # A missing/corrupt/unwritable journal weakens the replay
                # guarantee.  Mutating execution therefore stops before the
                # external action rather than silently bypassing the ledger.
                # Preserve the underlying cause in the log so a transient
                # lock-busy or an orphan-attempt guard can be told apart from a
                # genuine corruption failure.
                _logger.warning(
                    "side-effect journal unavailable for %s: %s: %s",
                    name,
                    type(exc).__name__,
                    exc,
                )
                return self._finish(
                    name,
                    args,
                    f"[blocked: side-effect journal unavailable for {name}]",
                    executed=False,
                    approval="journal_unavailable",
                    risk=risk,
                    audit=audit,
                    config=config,
                )
            if reservation.action == "reuse":
                return self._finish(
                    name,
                    args,
                    reservation.result or "",
                    # The logical invocation is satisfied by the previously
                    # verified execution; no external action happens here.
                    executed=True,
                    approval="journal_reuse",
                    risk=risk,
                    audit=audit,
                    config=config,
                )
            if reservation.action == "uncertain":
                return self._finish(
                    name,
                    args,
                    (
                        "[blocked: previous outcome unknown for side-effecting "
                        f"tool '{name}'; inspect state before retry]"
                    ),
                    executed=False,
                    approval="journal_pending",
                    risk=risk,
                    audit=audit,
                    config=config,
                )

        async def invoke() -> str:
            if getattr(risk, "name", "") == "READ" and retry_attempts > 1:
                from ..recovery.error_recovery import retry_with_backoff

                return await retry_with_backoff(
                    lambda: self._invoke_async_strict(tool, args),
                    max_attempts=retry_attempts,
                    wait_multiplier=retry_wait,
                )
            return await self._invoke_async(tool, args)

        try:
            invocation = invoke()
            if timeout > 0:
                result = await asyncio.wait_for(invocation, timeout=timeout)
            else:
                result = await invocation
        except asyncio.TimeoutError:
            return self._finish(
                name,
                args,
                f"[error: tool '{name}' timed out after {timeout:g}s]",
                executed=True,
                approval=approval,
                risk=risk,
                audit=audit,
                config=config,
            )
        except asyncio.CancelledError:
            self._finish(
                name,
                args,
                f"[cancelled: tool '{name}']",
                executed=True,
                approval=approval,
                risk=risk,
                audit=audit,
                config=config,
            )
            raise
        except Exception as exc:
            return self._finish(
                name,
                args,
                f"[error executing {name}: {type(exc).__name__}: {exc}]",
                executed=True,
                approval=approval,
                risk=risk,
                audit=audit,
                config=config,
            )
        finished = self._finish(
            name,
            args,
            result,
            executed=True,
            approval=approval,
            risk=risk,
            audit=audit,
            config=config,
        )
        if journal_call is not None:
            verified = build_tool_evidence(
                name,
                args,
                finished,
                executed=True,
                approval=approval,
                risk=risk,
            )
            if verified.passed:
                try:
                    journal_binding.journal.complete(
                        journal_binding.attempt_id,
                        journal_call,
                        finished,
                    )
                except Exception:
                    # The side effect may have happened, but its durable commit
                    # did not.  Leave the entry pending and fail closed.
                    return (
                        "[error: side-effect completed but journal commit failed; "
                        "outcome is now unknown and will not be replayed]"
                    )
        return finished

    async def execute_tool(
        self,
        name: str,
        args: Any,
        config: dict | None = None,
        *,
        approval_source: str | None = None,
        mode: str | None = None,
        call_id: str | None = None,
        event_tui: Any | None = None,
    ) -> str:
        """Execute through the gate and emit exactly one correlated lifecycle.

        The event sink is request-local so concurrent graph branches cannot
        leak events into another API/CLI run. The configured execution timeout
        is enforced inside this public choke point, so direct and graph-proxy
        calls share one deadline. Event failures are observational only and
        never change the underlying safety-gate result.
        """
        tui = event_tui if event_tui is not None else self.get_event_tui()
        resolved_call_id = str(call_id or uuid.uuid4().hex)
        await self._emit_event_hooks(
            "before",
            tool=name,
            call_id=resolved_call_id,
            mode=mode or "build",
        )
        tracer = self.get_event_tracer()
        span = tracer.start_span(f"tool:{name}") if tracer is not None else None
        if span is not None:
            from ..utils.streaming import token_stats

            token_before = (token_stats.input_tokens, token_stats.output_tokens)
        else:
            token_before = (0, 0)

        def finish_span(status: str, error_msg: str = "") -> None:
            if span is None:
                return
            from ..utils.streaming import token_stats

            prompt_tokens = max(0, token_stats.input_tokens - token_before[0])
            completion_tokens = max(0, token_stats.output_tokens - token_before[1])
            tracer.end_span(
                span,
                status=status,
                error_msg=error_msg,
                token_usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )
        event_started = False
        if tui is not None and hasattr(tui, "write_tool_call"):
            try:
                returned_id = tui.write_tool_call(
                    name, args, call_id=resolved_call_id
                )
                if returned_id:
                    resolved_call_id = str(returned_id)
                event_started = True
            except Exception:
                pass
        trajectory = self.get_event_trajectory()
        if trajectory is not None:
            trajectory.record(
                "tool.started",
                {
                    "tool": name,
                    "call_id": resolved_call_id,
                    "mode": mode or "build",
                    "arguments": args,
                },
            )

        try:
            cache = _live_tool_dedup.get()
            if cache is None:
                cache = {}
                _live_tool_dedup.set(cache)
            key = self._dedup_key(name, args)
            if key in cache:
                skipped = (
                    f"[重复调用已跳过: {name} 参数与本轮先前调用相同；"
                    f"上次结果摘要: {str(cache[key])[:200]}]"
                )
                if event_started and hasattr(tui, "write_tool_result"):
                    try:
                        tui.write_tool_result(
                            skipped, "success", call_id=resolved_call_id
                        )
                    except Exception:
                        pass
                finish_span("ok")
                return skipped

            result = await self._execute_tool_gated(
                name,
                args,
                config,
                approval_source=approval_source,
                mode=mode,
            )
            cache[key] = str(result)
        except asyncio.CancelledError:
            if trajectory is not None:
                trajectory.record(
                    "tool.cancelled",
                    {"tool": name, "call_id": resolved_call_id},
                )
            await self._emit_event_hooks(
                "error",
                tool=name,
                call_id=resolved_call_id,
                error_type="CancelledError",
            )
            finish_span("cancelled")
            if event_started and hasattr(tui, "write_tool_result"):
                try:
                    tui.write_tool_result(
                        f"[cancelled: tool '{name}']",
                        "cancelled",
                        call_id=resolved_call_id,
                    )
                except Exception:
                    pass
            raise
        except Exception as exc:
            if trajectory is not None:
                trajectory.record(
                    "tool.failed",
                    {
                        "tool": name,
                        "call_id": resolved_call_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                )
            await self._emit_event_hooks(
                "error",
                tool=name,
                call_id=resolved_call_id,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            finish_span("error", str(exc)[:200])
            if event_started and hasattr(tui, "write_tool_result"):
                try:
                    tui.write_tool_result(
                        f"[error executing {name}: {exc}]",
                        "error",
                        call_id=resolved_call_id,
                    )
                except Exception:
                    pass
            raise

        from ..log.log_helpers import trace_status_for_result

        trace_status, trace_detail = trace_status_for_result(result)
        if trajectory is not None:
            trajectory.record(
                "tool.completed",
                {
                    "tool": name,
                    "call_id": resolved_call_id,
                    "status": trace_status,
                    "result": result,
                },
            )
        await self._emit_event_hooks(
            "after",
            tool=name,
            call_id=resolved_call_id,
            status=trace_status,
        )
        finish_span(
            trace_status,
            trace_detail[:200] if trace_status != "ok" else "",
        )
        if event_started and hasattr(tui, "write_tool_result"):
            try:
                from ..log.log_helpers import tool_display_status

                tui.write_tool_result(
                    result,
                    tool_display_status(result),
                    call_id=resolved_call_id,
                )
            except Exception:
                pass
        return result

    async def _execute_tool_gated(
        self,
        name: str,
        args: Any,
        config: dict | None = None,
        *,
        approval_source: str | None = None,
        mode: str | None = None,
    ) -> str:
        """Execute a tool through the safety gate.

        Order of checks (fail-closed at every step):
        1. policy classification (static table + bash dynamic escalation)
        2. write-path whitelist for write/patch-like tools
        3. dry-run simulation (WRITE/DANGER only)
        4. approval (READ exempt; WRITE/DANGER need approval unless the
           level is listed in ``safety.auto_approve`` or always-allowed)
        5. execute + audit
        """
        from ..core.safety.policy import (
            RiskLevel,
            is_write_allowed, is_dry_run, summarize_args,
        )
        from ..core.safety.approval import (
            ApprovalRequest, ApprovalDecision, get_approval_broker,
        )
        from ..core.governance import PolicyOutcome, SensitiveActionPolicy

        config = config or {}
        safety = (config.get("safety") or {})

        tool = self.get(name)
        if tool is None:
            return self._finish(
                name, args, f"[error: tool '{name}' not found]",
                executed=False, approval="not_found", config=config,
            )

        # The shared governance policy is the authoritative first decision;
        # the existing gate below performs approval and execution.
        policy_decision = SensitiveActionPolicy().decide(
            name,
            args,
            config,
            approval_source=approval_source,
            mode=mode,
            minimum_risk=self._risk_overrides.get(self._canonical_name(name)),
        )
        risk = policy_decision.risk
        if policy_decision.outcome is PolicyOutcome.DENY:
            audit = self._get_audit_logger()
            reason = policy_decision.reason
            if reason == "plan_mode_read_only":
                msg = f"[blocked: {name} is not available in Plan mode]"
            elif reason == "write_path_not_allowed":
                blocked_path = ""
                if isinstance(args, dict):
                    blocked_path = next(
                        (
                            str(args[key])
                            for key in self._PATH_ARG_KEYS
                            if isinstance(args.get(key), str) and args.get(key)
                        ),
                        "",
                    )
                msg = f"[blocked: write path not allowed: {blocked_path}]"
            else:
                msg = f"[blocked: governance policy denied {name}: {reason}]"
            return self._finish(
                name, args, msg, executed=False, approval="rejected",
                risk=risk, audit=audit, config=config,
            )
        if policy_decision.outcome is PolicyOutcome.DRY_RUN:
            audit = self._get_audit_logger()
            msg = f"[dry-run] not executed: {name}({summarize_args(args)})"
            return self._finish(
                name, args, msg, executed=False, approval="dry_run",
                risk=risk, audit=audit, config=config,
            )

        # Plan mode remains a hard capability boundary even when the optional
        # confirmation gate is disabled.
        if mode == "plan" and risk >= RiskLevel.WRITE:
            audit = self._get_audit_logger()
            msg = f"[blocked: {name} is not available in Plan mode]"
            return self._finish(
                name, args, msg, executed=False, approval="rejected",
                risk=risk, audit=audit,
            )

        # A legacy opt-out may bypass confirmation, but never the Plan boundary,
        # evidence capture, cancellation handling, or the append-only audit.
        if not safety.get("enabled", False):
            audit = self._get_audit_logger()
            return await self._invoke_and_finish(
                name,
                args,
                tool,
                config,
                approval="safety_disabled",
                risk=risk,
                audit=audit,
            )

        audit = self._get_audit_logger()

        # 2. write-path whitelist (only for tools that take a path arg and
        #    can write — i.e. WRITE/DANGER level)
        if risk >= RiskLevel.WRITE and isinstance(args, dict):
            for key in self._PATH_ARG_KEYS:
                p = args.get(key)
                if isinstance(p, str) and p and not is_write_allowed(p, config):
                    msg = f"[blocked: write path not allowed: {p}]"
                    return self._finish(
                        name, args, msg, executed=False, approval="rejected",
                        risk=risk, audit=audit,
                    )

        # 3. dry-run
        if risk >= RiskLevel.WRITE and is_dry_run(config):
            msg = f"[dry-run] 未实际执行: {name}({summarize_args(args)})"
            return self._finish(
                name, args, msg, executed=False, approval="dry_run",
                risk=risk, audit=audit,
            )

        # 4. approval
        approval_state = "auto"
        if risk >= RiskLevel.WRITE:
            auto_levels = {str(x).lower() for x in (safety.get("auto_approve") or [])}
            if approval_source == "explicit_command":
                # A literal CLI/API slash command is itself an explicit user
                # authorization. It still passes policy, dry-run and audit.
                approval_state = "explicit_command"
            elif risk.name.lower() in auto_levels:
                approval_state = "auto"
            else:
                broker = get_approval_broker()
                if broker is None:
                    msg = f"[rejected: no approval broker available for {risk.name} tool '{name}']"
                    return self._finish(
                        name, args, msg, executed=False, approval="rejected",
                        risk=risk, audit=audit,
                    )
                req = ApprovalRequest(tool_name=name, args_summary=args, risk=risk)
                decision = await broker.request_approval(req)
                if decision == ApprovalDecision.REJECTED:
                    msg = f"[rejected by user: {name}]"
                    return self._finish(
                        name, args, msg, executed=False, approval="rejected",
                        risk=risk, audit=audit,
                    )
                approval_state = (
                    "always" if decision == ApprovalDecision.ALWAYS_ALLOW_LEVEL
                    else "approved"
                )

        # 5. execute + audit. Tools with a native coroutine get cooperative
        # cancellation; legacy synchronous tools stay off the event loop.
        return await self._invoke_and_finish(
            name,
            args,
            tool,
            config,
            approval=approval_state,
            risk=risk,
            audit=audit,
        )

    @staticmethod
    def _invoke(tool: Any, args: Any) -> str:
        try:
            if isinstance(args, dict):
                result = tool.invoke(args)
            else:
                result = tool.invoke(str(args))
            return str(result)
        except Exception as e:
            return f"[error executing {getattr(tool, 'name', tool)}: {e}]"

    @classmethod
    async def _invoke_async(cls, tool: Any, args: Any) -> str:
        coroutine = getattr(tool, "coroutine", None)
        if not inspect.iscoroutinefunction(coroutine):
            return await asyncio.to_thread(cls._invoke, tool, args)
        try:
            payload = args if isinstance(args, dict) else str(args)
            result = await tool.ainvoke(payload)
            return str(result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"[error executing {getattr(tool, 'name', tool)}: {e}]"

    @staticmethod
    async def _invoke_async_strict(tool: Any, args: Any) -> str:
        """Invoke without converting exceptions so retry classification works."""
        payload = args if isinstance(args, dict) else str(args)
        coroutine = getattr(tool, "coroutine", None)
        if inspect.iscoroutinefunction(coroutine):
            return str(await tool.ainvoke(payload))

        def invoke_sync() -> str:
            if isinstance(args, dict):
                return str(tool.invoke(args))
            return str(tool.invoke(str(args)))

        return await asyncio.to_thread(invoke_sync)
