"""Approval brokers: ask the user before running WRITE/DANGER tools.

Adapted from OpenHands (MIT) openhands/security/ confirmation-mode design:
a pending-action registry resolved by an external decision channel. Two
transports are provided:

- ``TuiApproval``  — CLI mode: asks via the TUI channel; the blocking
  ``input()`` call runs in a worker thread so the event loop stays alive.
- ``SseApproval``  — API mode: emits an ``approval_request`` SSE event and
  waits on an ``asyncio.Event`` resolved by ``POST /approve``; times out
  to REJECTED (fail-closed).
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .policy import RiskLevel, summarize_args


class ApprovalDecision(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ALLOW_ONCE = "allow_once"
    ALWAYS_ALLOW_LEVEL = "always_allow_level"


@dataclass
class ApprovalRequest:
    tool_name: str
    args_summary: Any
    risk: RiskLevel
    approval_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        # Cap the summary size so prompts/SSE payloads stay small.
        self.args_summary = summarize_args(self.args_summary)

    def to_event(self) -> dict:
        return {
            "type": "approval_request",
            "approval_id": self.approval_id,
            "tool": self.tool_name,
            "risk": self.risk.name,
            "args": self.args_summary,
        }


class ApprovalBroker(ABC):
    """Abstract approval channel with a session-level always-allow cache."""

    def __init__(self):
        self._always_allowed: set[RiskLevel] = set()

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        if request.risk in self._always_allowed:
            return ApprovalDecision.ALWAYS_ALLOW_LEVEL
        decision = await self._ask(request)
        # ALLOW_ONCE approves this single call without caching the risk level;
        # it behaves as APPROVED for the current request but is not remembered.
        if decision == ApprovalDecision.ALWAYS_ALLOW_LEVEL:
            self._always_allowed.add(request.risk)
        return decision

    def is_level_always_allowed(self, level: RiskLevel) -> bool:
        return level in self._always_allowed

    @abstractmethod
    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        """Transport-specific prompt. Must return a decision."""


class TuiApproval(ApprovalBroker):
    """CLI-mode approval. Displays the request through the TUI channel and
    reads y/n/a from stdin in a worker thread (never blocks the loop)."""

    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        try:
            from ...utils.tui import get_tui
            tui = get_tui()
        except Exception:
            tui = None

        lines = [
            f"[approval] tool={request.tool_name} risk={request.risk.name}",
            f"[approval] args={request.args_summary}",
        ]
        for line in lines:
            if tui and hasattr(tui, "write_warning"):
                try:
                    tui.write_warning(line)
                except Exception:
                    pass

        prompt = "Approve? [y]es / [n]o / [o]nce / [a]lways this level: "

        def _read() -> str:
            try:
                return input(prompt).strip().lower()
            except (EOFError, OSError):
                return "n"

        answer = await asyncio.to_thread(_read)
        if answer in ("y", "yes"):
            return ApprovalDecision.APPROVED
        if answer in ("o", "once"):
            return ApprovalDecision.ALLOW_ONCE
        if answer in ("a", "always"):
            return ApprovalDecision.ALWAYS_ALLOW_LEVEL
        return ApprovalDecision.REJECTED


class SseApproval(ApprovalBroker):
    """API-mode approval. Pushes an ``approval_request`` event to the sink
    (the SSE queue) and waits for ``resolve()`` from ``POST /approve``.
    Timeout defaults to REJECTED (fail-closed)."""

    def __init__(self, timeout: float = 120.0):
        super().__init__()
        self.timeout = timeout
        self._pending: dict[str, asyncio.Event] = {}
        self._pending_loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._sink: Optional[Callable[[dict], None]] = None

    def set_event_sink(self, sink: Optional[Callable[[dict], None]]) -> None:
        """Register the callback used to publish approval_request events."""
        self._sink = sink

    def wait_for_request(self, timeout: float = 30.0) -> Optional[str]:
        """Block until a request becomes pending and return its id.

        Test/utility hook: lets a caller (e.g. a test thread) synchronize
        with the moment an approval_request is published, without having
        to consume the SSE stream.
        """
        import threading
        got = threading.Event()
        holder: dict[str, str] = {}
        prev = self._sink

        def tap(ev: dict):
            holder["id"] = ev.get("approval_id", "")
            got.set()
            if prev:
                try:
                    prev(ev)
                except Exception:
                    pass

        self._sink = tap
        try:
            if got.wait(timeout=timeout):
                return holder.get("id")
            return None
        finally:
            # Only restore if nobody else replaced the sink meanwhile.
            if self._sink is tap:
                self._sink = prev

    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        event = asyncio.Event()
        owner_loop = asyncio.get_running_loop()
        self._pending[request.approval_id] = event
        self._pending_loops[request.approval_id] = owner_loop
        if self._sink:
            try:
                self._sink(request.to_event())
            except Exception:
                pass
        try:
            # Slice the wait so the event loop can keep flushing SSE while we
            # block on the user's decision (avoids a single long wait_for that
            # starves interactive prompts on some ASGI write buffers).
            loop = asyncio.get_running_loop()
            deadline = loop.time() + max(0.0, float(self.timeout))
            while True:
                if event.is_set():
                    break
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return ApprovalDecision.REJECTED
                try:
                    await asyncio.wait_for(
                        event.wait(), timeout=min(5.0, remaining)
                    )
                    break
                except asyncio.TimeoutError:
                    continue
            return self._decisions.get(
                request.approval_id, ApprovalDecision.REJECTED
            )
        finally:
            self._pending.pop(request.approval_id, None)
            self._pending_loops.pop(request.approval_id, None)
            # Cancellation can arrive after resolve() but before _ask() reads
            # the decision. Always remove it here so no orphan survives.
            self._decisions.pop(request.approval_id, None)

    def _resolve_on_owner_loop(
        self, approval_id: str, decision: ApprovalDecision
    ) -> None:
        event = self._pending.get(approval_id)
        if event is None:
            return
        self._decisions[approval_id] = decision
        event.set()

    def resolve(self, approval_id: str, decision: str) -> bool:
        """Resolve a pending request. Returns False for unknown ids."""
        event = self._pending.get(approval_id)
        if event is None:
            return False
        try:
            resolved = ApprovalDecision(decision)
        except ValueError:
            resolved = ApprovalDecision.REJECTED

        owner_loop = self._pending_loops.get(approval_id)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if owner_loop is not None and owner_loop is not current_loop:
            if not owner_loop.is_running():
                return False
            owner_loop.call_soon_threadsafe(
                self._resolve_on_owner_loop, approval_id, resolved
            )
        else:
            self._resolve_on_owner_loop(approval_id, resolved)
        return True


# ---- global singleton ----

_broker: Optional[ApprovalBroker] = None


def get_approval_broker() -> Optional[ApprovalBroker]:
    return _broker


def set_approval_broker(broker: Optional[ApprovalBroker]) -> None:
    global _broker
    _broker = broker
