"""GX13 needs_input vs response classification on real B12 event names.

Probe (not placeholders):
  needs_input: approval/request, question/request
  response:    event/done, event/final, event/task_complete
  ignore:      event/message_delta and other token-stream events
"""

from __future__ import annotations

from typing import Any

# B12 / protocol actual names (see protocol/server_requests.py and notifications.py)
NEEDS_INPUT_EVENTS = frozenset({"approval/request", "question/request"})
RESPONSE_EVENTS = frozenset({"event/done", "event/final", "event/task_complete"})
STREAM_EVENTS = frozenset(
    {
        "event/message_delta",
        "event/progress",
        "event/reasoning_snapshot",
        "event/token_usage",
    }
)


class NeedsInputClassifier:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def classify(self, event: dict[str, Any]) -> str | None:
        name = str(event.get("method") or event.get("type") or "")
        if name in STREAM_EVENTS:
            return None
        if name in NEEDS_INPUT_EVENTS:
            return "needs_input"
        if name in RESPONSE_EVENTS:
            return "response"
        return None

    def emit_payload(self, event: dict[str, Any]) -> dict[str, Any] | None:
        kind = self.classify(event)
        if kind is None:
            return None
        params = event.get("params") if isinstance(event.get("params"), dict) else event
        request_id = str(params.get("request_id") or params.get("approval_id") or params.get("question_id") or params.get("session_id") or "")
        turn = str(params.get("turn_id") or params.get("session_id") or "")
        dedupe = f"{kind}:{request_id}:{turn}"
        if dedupe in self._seen:
            return None
        self._seen.add(dedupe)
        preview = str(params.get("preview") or params.get("text") or params.get("question") or params.get("message") or "")
        preview = preview.replace("\n", " ")[:80]
        return {
            "method": "event/agent_needs_input" if kind == "needs_input" else "event/agent_response",
            "kind": kind,
            "session_id": params.get("session_id"),
            "request_id": request_id or None,
            "preview": preview,
        }
