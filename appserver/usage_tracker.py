"""GX7 session usage aggregation. Single source for event/agent_usage.

Consumes Phase 3 token fields and B10 model summaries. Never hardcodes 8192.
Cost is included only when a pricing snapshot is supplied (PENDING_PRICING otherwise).
Never lives under appserver/handlers/.
"""

from __future__ import annotations

from typing import Any, Callable

HEARTBEAT_SECONDS = 30


class UsageTracker:
    """Per-session token/context aggregation with monotonic seq."""

    def __init__(
        self,
        *,
        context_window_lookup: Callable[[str], int | None] | None = None,
    ) -> None:
        self._state: dict[str, dict[str, Any]] = {}
        self._context_window_lookup = context_window_lookup

    def ingest(
        self,
        session_id: str,
        usage: dict[str, Any],
        *,
        context_window: int | None = None,
        cost: float | None = None,
        currency: str | None = None,
        reason: str = "token_usage",
    ) -> dict[str, Any]:
        row = self._state.setdefault(
            session_id,
            {
                "seq": 0,
                "input_tokens": None,
                "output_tokens": None,
                "cache_hit_tokens": None,
                "cache_write_tokens": None,
                "cache_hit_rate": None,
                "reporting_status": "not_reported",
                "context_window": None,
                "cost": None,
                "currency": None,
                "cost_available": False,
            },
        )
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_hit_tokens",
            "cache_write_tokens",
            "cache_hit_rate",
            "reporting_status",
        ):
            if key in usage:
                row[key] = usage[key]
        window = context_window
        if window is None and self._context_window_lookup is not None:
            window = self._context_window_lookup(session_id)
        if window is not None:
            row["context_window"] = window
        if cost is not None:
            row["cost"] = cost
            row["currency"] = currency or "USD"
            row["cost_available"] = True
        row["seq"] = int(row["seq"]) + 1
        row["reason"] = reason
        return self.snapshot(session_id)

    def on_tool(self, session_id: str) -> dict[str, Any]:
        return self.ingest(session_id, {}, reason="tool")

    def heartbeat(self, session_id: str) -> dict[str, Any]:
        return self.ingest(session_id, {}, reason="heartbeat")

    def snapshot(self, session_id: str) -> dict[str, Any]:
        row = self._state.get(session_id)
        if row is None:
            return {
                "method": "event/agent_usage",
                "session_id": session_id,
                "seq": 0,
                "cost_available": False,
            }
        used = int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
        window = row.get("context_window")
        used_pct = None
        if isinstance(window, int) and window > 0:
            used_pct = min(100.0, max(0.0, used * 100.0 / window))
        payload = {
            "method": "event/agent_usage",
            "session_id": session_id,
            "seq": row["seq"],
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "cache_hit_tokens": row.get("cache_hit_tokens"),
            "cache_write_tokens": row.get("cache_write_tokens"),
            "cache_hit_rate": row.get("cache_hit_rate"),
            "reporting_status": row.get("reporting_status"),
            "context_used": used,
            "context_window": window,
            "used_pct": used_pct,
            "cost": row.get("cost") if row.get("cost_available") else None,
            "currency": row.get("currency") if row.get("cost_available") else None,
            "cost_available": bool(row.get("cost_available")),
            "reason": row.get("reason"),
        }
        return payload
