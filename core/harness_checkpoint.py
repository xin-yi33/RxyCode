"""Shared Harness pause point: durable message codec and whole-turn clock.

A turn that waits for a human (approval or an answer) parks its message
history as a checkpoint; the resumed turn restores it and continues the
same tool loop. The clock accrues only while the turn executes: waiting time
is not execution time, and a restored budget keeps what was already spent.
Renewal decisions stay with ``timeout_decision`` (``ExtensionLedger``); this
module only bounds how far a granted extension can move the limit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage


def _kind_of(message: BaseMessage) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "human"
    if isinstance(message, AIMessage):
        return "ai"
    if isinstance(message, ToolMessage):
        return "tool"
    raise TypeError(f"unsupported checkpoint message: {type(message).__name__}")


def encode_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message in messages:
        kind = _kind_of(message)
        row: dict[str, Any] = {"kind": kind, "content": message.content}
        if kind == "ai" and message.tool_calls:
            row["tool_calls"] = [dict(call) for call in message.tool_calls]
        if kind == "tool":
            row["tool_call_id"] = message.tool_call_id
            if message.name:
                row["name"] = message.name
        json.dumps(row, ensure_ascii=False)  # fail closed on non-JSON content
        rows.append(row)
    return rows


def decode_messages(rows: list[dict[str, Any]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        content = row.get("content", "")
        if kind == "ai":
            out.append(AIMessage(content=content, tool_calls=list(row.get("tool_calls") or [])))
        elif kind == "tool":
            out.append(
                ToolMessage(
                    content=content,
                    tool_call_id=str(row.get("tool_call_id") or ""),
                    name=row.get("name"),
                )
            )
        elif kind == "system":
            out.append(SystemMessage(content=content))
        elif kind == "human":
            out.append(HumanMessage(content=content))
        else:
            raise ValueError(f"unknown checkpoint message kind: {kind!r}")
    return out


@dataclass
class TurnBudget:
    """Wall-clock execution budget for one turn, pause-aware."""

    limit_seconds: float
    max_extensions: int = 0
    hard_cap_seconds: float | None = None
    consumed_seconds: float = 0.0
    extensions_used: int = 0
    clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)
    _started_at: float | None = field(default=None, repr=False, compare=False)

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = self.clock()

    def pause(self) -> None:
        if self._started_at is not None:
            self.consumed_seconds += self.clock() - self._started_at
            self._started_at = None

    def resume(self) -> None:
        self.start()

    def elapsed(self) -> float:
        running = 0.0 if self._started_at is None else self.clock() - self._started_at
        return self.consumed_seconds + running

    def exhausted(self) -> bool:
        return self.elapsed() >= self.limit_seconds

    def extend(self, seconds: float) -> bool:
        """Apply one granted extension. Refuses past the count or the cap."""
        if seconds <= 0 or self.extensions_used >= self.max_extensions:
            return False
        new_limit = self.limit_seconds + seconds
        if self.hard_cap_seconds is not None and new_limit > self.hard_cap_seconds:
            return False
        self.limit_seconds = new_limit
        self.extensions_used += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        """Checkpoint form: folds the running part in, so time spent parked
        after this point is never counted when the budget is restored."""
        return {
            "limit_seconds": self.limit_seconds,
            "max_extensions": self.max_extensions,
            "hard_cap_seconds": self.hard_cap_seconds,
            "consumed_seconds": self.elapsed(),
            "extensions_used": self.extensions_used,
        }

    @classmethod
    def restore(cls, data: dict[str, Any], *, clock: Callable[[], float] = time.monotonic) -> "TurnBudget":
        return cls(
            limit_seconds=float(data["limit_seconds"]),
            max_extensions=int(data.get("max_extensions") or 0),
            hard_cap_seconds=(
                None if data.get("hard_cap_seconds") is None else float(data["hard_cap_seconds"])
            ),
            consumed_seconds=float(data.get("consumed_seconds") or 0.0),
            extensions_used=int(data.get("extensions_used") or 0),
            clock=clock,
        )
