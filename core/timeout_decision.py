"""Timeout decision boundary.

P1 owns JSON parsing. P2 owns the policy, the ledger, and the engine.
Later cards call ``decide``; this module does not wire those call sites.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM, build_routed_llm
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import (
    ALLOWED_ACTIONS,
    TimeoutDecisionEvent,
    TimeoutDecisionResponse,
    TimeoutEvidence,
    begin_decision_events as _begin_decision_events,
    end_decision_events as _end_decision_events,
    forward_decision_event as _forward_decision_event,
    note_published_event,
)
from RxyCode.RxyCode1_1_0.tools.todo_events import (
    todo_progress_for_session as _todo_progress_for_session,
    todo_progress_snapshot as _todo_progress_snapshot,
)


def begin_decision_events():
    """Per-call event bucket. Graph reaches this through ``_decision_api``."""
    return _begin_decision_events()


def end_decision_events(token) -> None:
    _end_decision_events(token)


def forward_decision_event(engine, tui) -> None:
    _forward_decision_event(engine, tui)
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

# Module global so tests can monkeypatch this name before from_config.
# Imported at module top: a function-local import would raise the lazy-import
# count, and a local binding would hide the monkeypatch.

TIMEOUT_DECISION_DEFAULTS = {
    "enabled": False,
    "max_extensions_per_point": 2,
    "extension_growth": 2,
    "decision_timeout_seconds": 15.0,
    "decision_model": None,
    "fail_closed": True,
    "max_restarts": 2,
    "restart_total_wall_seconds": 7200.0,
    "restart_grant_base_seconds": 900.0,
    "absolute_cap_seconds": {
        "graph_task_max_time": 21600.0,
        "pipeline_soft_budget": 10800.0,
        "watchdog_stall": 1800.0,
        "tool_timeout": 7200.0,
    },
}

_CAP_KEYS = (
    "graph_task_max_time",
    "pipeline_soft_budget",
    "watchdog_stall",
    "tool_timeout",
)

Scope = tuple[str, str]


class Grant(NamedTuple):
    granted_seconds: float
    new_budget: float


def _reject_json_constant(name: str) -> None:
    raise ValueError(f"decision response must be JSON, not {name}")


def parse_decision_response(text: str) -> TimeoutDecisionResponse:
    """Parse a JSON-only decision. Only a complete ```json fence is stripped."""
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "```json" or lines[-1].strip() != "```":
            raise ValueError("decision response fence must be a closed JSON block")
        raw = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(raw, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ValueError("decision response must be JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("decision response must be a JSON object")
    return TimeoutDecisionResponse.model_validate(payload)


def build_decision_prompt(evidence: TimeoutEvidence) -> str:
    """Ask for a JSON decision and include the evidence object."""
    payload = json.dumps(evidence.model_dump(), ensure_ascii=False)
    return "Reply with JSON only.\n" + payload


def event_from_decision(
    resp: TimeoutDecisionResponse,
    evidence: TimeoutEvidence,
    *,
    extension_index: int,
    fail_closed: bool,
    decision_model: str | None,
    cost: float,
) -> TimeoutDecisionEvent:
    """Copy one settled decision onto the 16-field timeout event."""
    return TimeoutDecisionEvent(
        session_id=evidence.session_id,
        run_id=evidence.run_id,
        event_id=uuid.uuid4().hex,
        seq=int(extension_index),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        trigger_point=evidence.trigger_point,
        action=resp.action,
        extend_seconds=float(resp.extend_seconds),
        note=resp.note,
        confidence=float(resp.confidence),
        extension_index=int(extension_index),
        elapsed_seconds=float(evidence.elapsed_seconds),
        fail_closed=bool(fail_closed),
        decision_model=decision_model or "unknown",
        cost=float(cost),
    )


def timeout_decision_config(cfg: dict | None) -> dict:
    """Return the timeout_decision section itself, not a wrapped config.

    Deep-copy the defaults, overlay known keys, and drop unknown keys.
    ``absolute_cap_seconds`` is optional. When the caller supplies it, all
    four trigger keys must be present.
    """
    source = cfg if isinstance(cfg, dict) else {}
    raw_section = source.get("timeout_decision", {})
    if raw_section is None:
        raw_section = {}
    if not isinstance(raw_section, dict):
        raise ValueError("timeout_decision section must be a mapping")
    merged = copy.deepcopy(TIMEOUT_DECISION_DEFAULTS)
    if "absolute_cap_seconds" in raw_section:
        caps = raw_section.get("absolute_cap_seconds")
        if not isinstance(caps, dict) or any(key not in caps for key in _CAP_KEYS):
            raise ValueError(
                "absolute_cap_seconds must define every trigger point"
            )
        merged["absolute_cap_seconds"] = {
            key: float(caps[key]) for key in _CAP_KEYS
        }
    for key, value in raw_section.items():
        if key == "absolute_cap_seconds" or key not in merged:
            continue
        merged[key] = copy.deepcopy(value)
    # The card pins this switch. A caller cannot configure it off.
    merged["fail_closed"] = True
    return merged


def restart_gate_verdict(restarts_state, section, *, now) -> str | None:
    """Persistent stall-restart gate. None means a decision may run.

    The count and the wall clock live on the session, so a new job id does
    not clear them. ``now`` and ``first_restart_at`` must share one clock.
    """
    state = restarts_state if isinstance(restarts_state, dict) else {}
    limits = section if isinstance(section, dict) else {}
    try:
        max_restarts = int(limits.get("max_restarts", 2))
    except (TypeError, ValueError):
        max_restarts = 2
    try:
        wall = float(limits.get("restart_total_wall_seconds", 7200.0))
    except (TypeError, ValueError):
        wall = 7200.0
    try:
        count = int(state.get("restart_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count >= max_restarts:
        return "max_restarts"
    first = state.get("first_restart_at")
    if first is None:
        return None
    try:
        elapsed = float(now) - float(first)
    except (TypeError, ValueError):
        return None
    if elapsed > wall:
        return "total_wall"
    return None


def record_decision_cost(session_id: str, cost: float) -> None:
    """Record one decision's USD cost once, on the process token stats."""
    token_stats.record_decision_cost(session_id, cost)


def todo_progress_snapshot(snapshot_or_handle) -> str:
    """Project a TodoSnapshot-shaped handle. Empty or malformed input is ""."""
    return _todo_progress_snapshot(snapshot_or_handle)


def todo_progress_for_session(
    session_id: str | None,
    *,
    root_session_id: str | None = None,
    list_id: str = "default",
    scope: str = "turn",
) -> str:
    """Read and project the latest authoritative snapshot for evidence."""
    return _todo_progress_for_session(
        session_id,
        root_session_id=root_session_id,
        list_id=list_id,
        scope=scope,
    )


def _scope_of(evidence: TimeoutEvidence) -> Scope:
    """The only place a ledger scope is derived."""
    return (evidence.session_id, evidence.subject_id)


def decision_base_llm(cfg: dict | None):
    """Unwrapped chat model selected from the timeout_decision config.

    ``from_config`` wraps this once. A client that is already a
    ``UsageTrackingLLM`` is unwrapped so usage is not recorded twice.
    The executor model is not a shortcut for this choice.
    """
    built = build_routed_llm(cfg if isinstance(cfg, dict) else None)
    if isinstance(built, UsageTrackingLLM):
        return built._llm
    return built


def from_config(cfg, *, base_llm, ledger=None, sink=None, hooks=None):
    """Build an engine from the whole config. Disabled config returns None."""
    section = timeout_decision_config(cfg)
    if not section["enabled"]:
        return None
    llm = UsageTrackingLLM(base_llm)
    return TimeoutDecisionEngine(
        llm,
        DecisionPolicy(section),
        ledger=ledger,
        sink=sink,
        hooks=hooks,
    )


class DecisionPolicy:
    """Pure grant rules. The engine passes ``k``; this class does not derive it."""

    def __init__(self, section: dict):
        self._cfg = section

    def pre_check(self, evidence, *, k: int) -> TimeoutDecisionResponse | None:
        """Return a forced stop, or None when the LLM may be asked."""
        if k > int(self._cfg["max_extensions_per_point"]):
            return TimeoutDecisionResponse(
                action="stop",
                extend_seconds=0.0,
                note="[policy] max extensions reached",
                confidence=0.0,
            )
        cap = float(self._cfg["absolute_cap_seconds"][evidence.trigger_point])
        if float(evidence.budget_seconds) >= cap:
            return TimeoutDecisionResponse(
                action="stop",
                extend_seconds=0.0,
                note="[policy] absolute cap reached",
                confidence=0.0,
            )
        return None

    def grant(self, *, trigger_point, budget, k, extend_seconds) -> Grant:
        """Truncate the request so the new budget never passes the cap."""
        growth = self._cfg["extension_growth"]
        requested = float(extend_seconds) * (float(growth) ** (int(k) - 1))
        cap = float(self._cfg["absolute_cap_seconds"][trigger_point])
        room = max(0.0, cap - float(budget))
        granted = min(requested, room)
        return Grant(
            granted_seconds=float(granted),
            new_budget=float(budget) + float(granted),
        )


class ExtensionLedger:
    """In-memory grants keyed by (session_id, subject_id). Not persisted."""

    def __init__(self) -> None:
        self._ext: dict[Scope, list[float]] = {}

    def record(self, scope: Scope, granted_seconds: float) -> None:
        self._ext.setdefault(scope, []).append(float(granted_seconds))

    def count(self, scope: Scope) -> int:
        return len(self._ext.get(scope, ()))

    def total_extended(self, scope: Scope) -> float:
        return float(sum(self._ext.get(scope, ())))


class TimeoutDecisionEngine:
    """One decision entry. Failures become a stop with a fail-closed note."""

    def __init__(self, llm, policy, *, ledger=None, sink=None, hooks=None):
        self._llm = llm
        self._policy = policy
        self._ledger = ledger or ExtensionLedger()
        self.ledger = self._ledger
        self._sink = sink
        self._hooks = hooks
        self.total_cost: float = 0.0
        self.trajectory: list[tuple[str, float]] = []
        self.pending_decisions: int = 0
        self._events: list[dict] = []
        self._hook_audits: list[dict] = []
        self._last_grants: dict[Scope, Grant] = {}
        self._last_trigger: dict[Scope, str] = {}
        self._inflight: set[asyncio.Task] = set()
        self._active_evidence: TimeoutEvidence | None = None
        self._active_settled = False
        self._void_token = 0
        self._account_lock = asyncio.Lock()

    async def decide(self, evidence: TimeoutEvidence) -> TimeoutDecisionResponse:
        """Settle one decision. Overlapping calls share one accounting lock."""
        my_token = self._void_token
        async with self._account_lock:
            self.pending_decisions += 1
            try:
                return await self._decide_locked(evidence, my_token)
            finally:
                self.pending_decisions = max(0, self.pending_decisions - 1)
                self._active_evidence = None
                self._active_settled = False

    async def _decide_locked(
        self,
        evidence: TimeoutEvidence,
        my_token: int,
    ) -> TimeoutDecisionResponse:
        if self._void_token != my_token:
            resp = self._publish_interrupted(
                evidence, decision_model=self._named_model("unknown"),
            )
            await self._emit_hook("after", evidence)
            return resp
        scope = _scope_of(evidence)
        k = self._ledger.count(scope) + 1
        last = self._last_grants.get(scope)
        if last is not None:
            budget_base = last.new_budget
        else:
            budget_base = evidence.budget_seconds
        evidence = evidence.model_copy(update={"budget_seconds": float(budget_base)})
        self._active_evidence = evidence
        self._active_settled = False
        pre = self._policy.pre_check(evidence, k=k)
        if pre is not None:
            self._publish(
                pre,
                evidence,
                extension_index=self._ledger.count(scope),
                fail_closed=False,
                cost=0.0,
                kind="decision.stop",
                decision_model=self._named_model("unknown"),
            )
            await self._emit_hook("after", evidence)
            return pre
        await self._emit_hook("before", evidence)
        if self._void_token != my_token:
            resp = self._publish_interrupted(
                evidence, decision_model=self._named_model("unknown"),
            )
            await self._emit_hook("after", evidence)
            return resp
        try:
            raw = await self._await_model(evidence)
        except asyncio.CancelledError:
            if self._void_token != my_token:
                resp = self._publish_interrupted(
                    evidence, decision_model=self._named_model("unknown"),
                )
                await self._emit_hook("after", evidence)
                return resp
            raise
        except Exception as exc:
            resp = self._fail_closed(
                evidence, scope, exc, cost=0.0,
                decision_model=self._named_model("unknown"),
            )
            await self._emit_hook("after", evidence)
            return resp
        cost = _response_cost(raw)
        model = self._named_model(_decision_model(self._policy, raw))
        if self._void_token != my_token:
            resp = self._publish_interrupted(
                evidence, cost=cost, decision_model=model,
            )
            await self._emit_hook("after", evidence)
            return resp
        try:
            resp = self._accept(
                raw, evidence, scope, k, cost=cost, decision_model=model,
            )
        except Exception as exc:
            resp = self._fail_closed(evidence, scope, exc, cost=cost, decision_model=model)
            await self._emit_hook("after", evidence)
            return resp
        await self._emit_hook("after", evidence)
        return resp

    def _named_model(self, resolved: str) -> str:
        """Config name wins. Otherwise the response name, then the client."""
        configured = self._policy._cfg.get("decision_model")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        if resolved and resolved != "unknown":
            return resolved
        inner = getattr(self._llm, "_llm", self._llm)
        for attr in ("model_name", "model"):
            value = getattr(inner, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return resolved or "unknown"

    def last_grant(self, scope: Scope) -> Grant | None:
        """Grant the caller must apply. Use ``new_budget`` as the new ceiling."""
        return self._last_grants.get(scope)

    def granted_budget(self, scope: Scope, original_budget: float) -> float:
        """Query port. ``original_budget`` is the first configured budget.

        Passing an already extended budget double-counts
        (7200 → 7800 → 9600 instead of 9000).
        """
        extended = float(original_budget) + self._ledger.total_extended(scope)
        trigger = self._last_trigger.get(scope)
        caps = self._policy._cfg.get("absolute_cap_seconds") or {}
        if trigger not in caps:
            return extended
        return min(extended, float(caps[trigger]))

    def drain_events(self) -> list[dict]:
        """Return the internal buffer used when ``sink`` is None."""
        drained = list(self._events)
        self._events.clear()
        return drained

    def interrupt(self) -> None:
        """Void in-flight model calls. An idle engine only records the mark."""
        self.trajectory.append(("interrupt", time.monotonic()))
        self._void_token += 1
        for task in list(self._inflight):
            if not task.done():
                task.cancel()

    def drain_hook_audits(self) -> list[dict]:
        drained = list(self._hook_audits)
        self._hook_audits.clear()
        return drained

    async def _emit_hook(self, phase: str, evidence: TimeoutEvidence) -> None:
        if self._hooks is None:
            return
        results = await self._hooks.emit(
            phase,
            "timeout_decision",
            {"evidence": evidence.model_dump()},
        )
        for item in results or ():
            as_dict = item.to_dict() if hasattr(item, "to_dict") else item
            if isinstance(as_dict, dict):
                self._hook_audits.append(as_dict)

    async def _await_model(self, evidence: TimeoutEvidence):
        timeout = float(self._policy._cfg["decision_timeout_seconds"])
        call = asyncio.create_task(self._llm.ainvoke(build_decision_prompt(evidence)))
        self._inflight.add(call)
        try:
            return await asyncio.wait_for(call, timeout)
        finally:
            self._inflight.discard(call)
            if not call.done():
                call.cancel()
                try:
                    await call
                except (asyncio.CancelledError, Exception):
                    pass

    def _accept(
        self,
        raw,
        evidence: TimeoutEvidence,
        scope: Scope,
        k: int,
        *,
        cost: float,
        decision_model: str,
    ):
        text = getattr(raw, "content", raw)
        if not isinstance(text, str):
            text = str(text)
        resp = parse_decision_response(text)
        allowed = ALLOWED_ACTIONS[evidence.trigger_point]
        if resp.action not in allowed:
            raise ValueError(f"action {resp.action!r} not allowed")
        if resp.action == "steer" and not str(resp.note).strip():
            raise ValueError("steer note must be non-empty")
        grant: Grant | None = None
        extension_index = self._ledger.count(scope)
        if resp.action == "stop":
            resp = resp.model_copy(update={"extend_seconds": 0.0})
        elif resp.action in ("continue", "steer"):
            grant = self._policy.grant(
                trigger_point=evidence.trigger_point,
                budget=evidence.budget_seconds,
                k=k,
                extend_seconds=resp.extend_seconds,
            )
            if grant.granted_seconds <= 0:
                raise ValueError("no room left under the absolute cap")
            resp = resp.model_copy(update={"extend_seconds": grant.granted_seconds})
            extension_index = k
        self._publish(
            resp,
            evidence,
            extension_index=extension_index,
            fail_closed=False,
            cost=cost,
            decision_model=decision_model,
            kind=f"decision.{resp.action}",
        )
        if grant is not None:
            self._ledger.record(scope, grant.granted_seconds)
            self._last_grants[scope] = grant
            self._last_trigger[scope] = evidence.trigger_point
        return resp

    def _fail_closed(
        self,
        evidence,
        scope: Scope,
        exc: BaseException,
        *,
        cost: float,
        decision_model: str | None = None,
    ):
        reason = f"{type(exc).__name__}: {exc}".strip()
        resp = TimeoutDecisionResponse(
            action="stop",
            extend_seconds=0.0,
            note=f"[fail-closed] {reason}",
            confidence=0.0,
        )
        self._publish(
            resp,
            evidence,
            extension_index=self._ledger.count(scope),
            fail_closed=True,
            cost=cost,
            decision_model=decision_model,
            kind="decision.fail_closed",
        )
        return resp

    def _publish_interrupted(
        self,
        evidence: TimeoutEvidence,
        *,
        cost: float = 0.0,
        decision_model: str | None = None,
    ) -> TimeoutDecisionResponse:
        scope = _scope_of(evidence)
        resp = TimeoutDecisionResponse(
            action="stop",
            extend_seconds=0.0,
            note="[fail-closed] interrupted",
            confidence=0.0,
        )
        if not self._active_settled:
            self._publish(
                resp,
                evidence,
                extension_index=self._ledger.count(scope),
                fail_closed=True,
                cost=cost,
                decision_model=decision_model,
                kind="decision.fail_closed",
            )
        return resp

    def _publish(
        self,
        resp: TimeoutDecisionResponse,
        evidence: TimeoutEvidence,
        *,
        extension_index: int,
        fail_closed: bool,
        cost: float,
        kind: str,
        decision_model: str | None = None,
    ) -> None:
        if decision_model is None:
            configured = self._policy._cfg.get("decision_model")
            decision_model = configured if isinstance(configured, str) and configured else None
        amount = float(cost) if math.isfinite(float(cost)) and float(cost) >= 0 else 0.0
        event = event_from_decision(
            resp,
            evidence,
            extension_index=int(extension_index),
            fail_closed=fail_closed,
            decision_model=decision_model,
            cost=amount,
        )
        payload = event.model_dump()
        if self._sink is None:
            self._events.append(payload)
        else:
            self._sink.append(payload)
        record_decision_cost(evidence.session_id, amount)
        self.total_cost += amount
        self.trajectory.append((kind, time.monotonic()))
        self._active_settled = True
        note_published_event(event)


def _response_cost(raw) -> float:
    explicit = getattr(raw, "cost", None)
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        if math.isfinite(float(explicit)) and float(explicit) >= 0:
            return float(explicit)
    meta = getattr(raw, "usage_metadata", None)
    if isinstance(meta, dict):
        for key in ("cost", "total_cost"):
            value = meta.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if math.isfinite(float(value)) and float(value) >= 0:
                    return float(value)
    return 0.0


def _decision_model(policy: DecisionPolicy, raw) -> str:
    configured = policy._cfg.get("decision_model")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    for attr in ("model_name", "model"):
        value = getattr(raw, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    meta = getattr(raw, "response_metadata", None)
    if isinstance(meta, dict):
        for key in ("model_name", "model"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "unknown"
