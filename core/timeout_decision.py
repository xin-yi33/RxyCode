"""JSON boundary for a timeout decision. The engine arrives in P2."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from RxyCode.RxyCode1_1_0.protocol.timeout_decision import (
    TimeoutDecisionEvent,
    TimeoutDecisionResponse,
    TimeoutEvidence,
)


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
