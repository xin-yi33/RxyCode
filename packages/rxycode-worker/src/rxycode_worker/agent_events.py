"""Map an existing team trace into a parent/child tree.

Plan changes are steer commands on the run. They are not written to EventStore.
"""

from __future__ import annotations

from typing import Any


_STEERS: dict[str, list[str]] = {}
_INTERMEDIATE = {"intermediate", "partial_result", "progress", "reasoning.summary"}


def project_run(*, spans: list[Any], events: list[Any]) -> dict[str, object]:
    """Project real spans. Parent ids stay the ids the tracer recorded."""
    nodes: list[dict[str, object]] = []
    for span in spans:
        nodes.append(
            {
                "id": str(getattr(span, "span_id", "") or ""),
                "parent_id": str(getattr(span, "parent_id", "") or ""),
                "role": str(getattr(span, "role", "") or getattr(span, "kind", "") or ""),
                "status": _status(span),
                "kind": str(getattr(span, "kind", "") or ""),
                "tokens": int(getattr(span, "tokens", 0) or 0),
            }
        )
    return {"run_id": _run_id(spans, events), "nodes": nodes}


def final_answer(*, parent_text: str, child_events: list[dict[str, str]]) -> dict[str, str]:
    """Keep the parent answer. Child intermediate text is not appended."""
    kept = parent_text
    for event in child_events:
        kind = event.get("kind", "")
        name = event.get("name", "")
        if kind in _INTERMEDIATE or name in _INTERMEDIATE:
            continue
        text = event.get("text", "")
        if text:
            kept = f"{kept}\n{text}"
    return {"text": kept}


def explain_spend(spans: list[Any]) -> dict[str, object]:
    """Solo and team token totals are the sum of the spans that produced them."""
    lines: list[dict[str, object]] = []
    solo = 0
    team = 0
    for span in spans:
        tokens = int(getattr(span, "tokens", 0) or 0)
        mode = str(getattr(span, "mode", "") or "")
        role = str(getattr(span, "role", "") or "")
        kind = str(getattr(span, "kind", "") or "")
        if mode == "solo":
            solo += tokens
        else:
            team += tokens
        lines.append({"role": role, "kind": kind, "tokens": tokens, "mode": mode or "team"})
    return {
        "total_tokens": solo + team,
        "solo_tokens": solo,
        "team_tokens": team,
        "lines": lines,
    }


def cancel_child(tree: dict[str, object], child_id: str) -> dict[str, object]:
    """Cancel one child. The parent status, role, and the other nodes stay."""
    nodes: list[dict[str, object]] = []
    for node in tree["nodes"]:  # type: ignore[index]
        copied = dict(node)
        if copied.get("id") == child_id:
            copied["status"] = "cancelled"
        nodes.append(copied)
    return {"run_id": tree["run_id"], "nodes": nodes}


def accept_steer(*, run_id: str, text: str, store: object | None = None) -> dict[str, object]:
    """Queue a steer on this run. EventStore is not updated."""
    del store
    applied = _STEERS.setdefault(run_id, [])
    applied.append(text)
    return {
        "run_id": run_id,
        "store_written": False,
        "applied": [{"text": item, "seq": index + 1} for index, item in enumerate(applied)],
    }


def _run_id(spans: list[Any], events: list[Any]) -> str:
    for event in events:
        session_id = str(getattr(event, "session_id", "") or "")
        if session_id:
            return session_id
    for span in spans:
        session_id = str(getattr(span, "session_id", "") or getattr(span, "run_id", "") or "")
        if session_id:
            return session_id
    return ""


def _status(span: Any) -> str:
    raw = str(getattr(span, "status", "") or "")
    if raw in {"failed", "error", "timeout"}:
        return "failed"
    if raw == "cancelled":
        return "cancelled"
    end_ts = float(getattr(span, "end_ts", 0) or 0)
    if end_ts > 0:
        return "completed"
    return "running"
