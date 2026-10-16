"""Map an existing team trace into a parent/child tree.

Plan changes are steer commands on the run. They are not written to EventStore.
"""

from __future__ import annotations

from typing import Any


_INTERMEDIATE = {"intermediate", "partial_result", "progress", "reasoning.summary"}
_BOUND: dict[str, dict[str, Any]] = {}
_CURRENT: dict[str, str] = {}
_APPLIED: dict[str, int] = {}


def publish_database_url(database_url: str) -> None:
    """Remember the web database for this process and its worker children."""
    import os

    os.environ["RXYCODE_WEB_DATABASE_URL"] = database_url
    _CURRENT["database_url"] = database_url


def clear_web_run() -> None:
    """Drop the process-local run coordinates. The database URL stays published."""
    for key in ("tenant_id", "run_id", "parent_id", "session_id"):
        _CURRENT.pop(key, None)
    _APPLIED.clear()


def remember_web_run(
    database_url: str,
    tenant_id: str,
    run_id: str,
    parent_id: str = "",
    session_id: str = "",
) -> None:
    """Record the run a worker is executing so spawn can write its log."""
    _CURRENT["database_url"] = database_url
    _CURRENT["tenant_id"] = tenant_id
    _CURRENT["run_id"] = run_id
    _CURRENT["parent_id"] = parent_id or session_id or run_id
    if session_id:
        _CURRENT["session_id"] = session_id


def bind_run(
    run_id: str,
    *,
    worker: Any | None = None,
    manager: Any | None = None,
    tree_root: str | None = None,
) -> None:
    """Attach the live worker and child manager that should receive this run's commands."""
    slot = _BOUND.setdefault(run_id, {})
    if worker is not None:
        slot["worker"] = worker
    if manager is not None:
        slot["manager"] = manager
    if tree_root:
        slot["tree_root"] = tree_root


def bind_manager_for_active_run(tree_root: str, manager: Any) -> None:
    """Also register the session tree under the web run id when they differ."""
    run_id = _CURRENT.get("run_id", "")
    session_id = _CURRENT.get("session_id", "")
    if run_id and tree_root in {run_id, session_id}:
        bind_run(run_id, manager=manager, tree_root=session_id or tree_root)


def run_matches_session(run_id: str, root: str, child_id: str) -> bool:
    """True when this child tree belongs to the active web run."""
    if run_id in {root, child_id}:
        return True
    return bool(root) and root == _CURRENT.get("session_id", "") and _CURRENT.get("run_id") == run_id


async def deliver_persisted_command(run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, object]:
    """Run a committed steer or child-cancel command on the bound worker."""
    slot = _BOUND.get(run_id, {})
    if event_type == "steer.accepted":
        worker = slot.get("worker")
        if worker is None:
            return {"delivered": False, "reason": "no worker", "run_id": run_id}
        return await accept_steer(
            run_id=run_id,
            text=str(payload.get("text") or ""),
            worker=worker,
        )
    if event_type == "child.cancel":
        manager = slot.get("manager")
        if manager is None:
            return {"delivered": False, "reason": "no manager", "run_id": run_id}
        session_id = str(payload.get("session_id") or "")
        root = str(slot.get("tree_root") or run_id)
        tree = {
            "run_id": root,
            "nodes": [{"id": session_id, "parent_id": root, "status": "running", "role": ""}],
        }
        result = cancel_child(tree, session_id, manager=manager)
        return {"delivered": str(result["outcome"]).startswith("cancelled"), "run_id": run_id, "outcome": result["outcome"]}
    return {"delivered": False, "reason": "unknown command", "run_id": run_id}


def default_run_journal() -> RunJournal | None:
    """Journal for the run this process is executing."""
    import os

    database_url = _CURRENT.get("database_url") or os.environ.get("RXYCODE_WEB_DATABASE_URL", "")
    tenant_id = _CURRENT.get("tenant_id") or os.environ.get("RXYCODE_WEB_TENANT_ID", "")
    run_id = _CURRENT.get("run_id") or os.environ.get("RXYCODE_WEB_RUN_ID", "")
    if not database_url or not tenant_id or not run_id:
        return None
    return RunJournal(database_url, tenant_id, run_id)


def default_parent_id() -> str:
    import os

    return _CURRENT.get("parent_id") or os.environ.get("RXYCODE_WEB_PARENT_ID", "")


def lookup_web_run(database_url: str, session_id: str) -> dict[str, str] | None:
    """Find the run row for this worker session. The id or the session id matches."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    if not database_url or not session_id:
        return None
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, tenant_id, session_id
                    FROM runs
                    WHERE (id = :session OR session_id = :session)
                      AND status IN (
                        'pending', 'leased', 'running', 'cancel_requested'
                      )
                    ORDER BY revision DESC
                    LIMIT 1
                    """
                ),
                {"session": session_id},
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return None
    return {
        "run_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "session_id": str(row.session_id or ""),
    }


def load_command_events(database_url: str, run_id: str, after_seq: int) -> list[dict[str, Any]]:
    """Read steer and child-cancel commands committed after the last applied seq."""
    import json

    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT seq, type, payload
                    FROM run_events
                    WHERE run_id = :run_id
                      AND seq > :after_seq
                      AND type IN ('steer.accepted', 'child.cancel')
                    ORDER BY seq
                    """
                ),
                {"run_id": run_id, "after_seq": after_seq},
            ).all()
    finally:
        engine.dispose()
    events: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append({"seq": int(row.seq), "type": str(row.type), "payload": dict(payload or {})})
    return events


async def consume_persisted_commands(database_url: str, run_id: str) -> list[dict[str, object]]:
    """Deliver committed commands to the worker bound in this process."""
    applied: list[dict[str, object]] = []
    after = _APPLIED.get(run_id, 0)
    for event in load_command_events(database_url, run_id, after):
        result = await deliver_persisted_command(
            run_id,
            str(event["type"]),
            dict(event["payload"]),
        )
        delivered = bool(result.get("delivered") or result.get("accepted"))
        if not delivered:
            break
        _APPLIED[run_id] = int(event["seq"])
        applied.append(result)
    return applied


class RunJournal:
    """Write agent lifecycle notifications into the web run log."""

    def __init__(self, database_url: str, tenant_id: str, run_id: str) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.run_id = run_id

    def record(self, method: str, agent_id: str, payload: dict[str, Any], *, parent_id: str = "") -> int:
        from rxycode_server.events.store import append_event

        body = dict(payload)
        body["agent_id"] = agent_id
        if parent_id:
            body["parent_id"] = parent_id
        if "tokens" not in body and "total_tokens" in body:
            body["tokens"] = body["total_tokens"]
        return append_event(
            self.database_url,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            event_type=method,
            payload=body,
        )


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


def cancel_child(
    tree: dict[str, object],
    child_id: str,
    *,
    manager: Any,
) -> dict[str, object]:
    """Cancel the live child session, then reflect that status on the tree."""
    root_id = str(tree.get("run_id") or "")
    manager.cancel_session(root_id, child_id)
    runtime = getattr(manager, "_live_runtimes", {}).get(child_id)
    cancel = getattr(runtime, "cancel", None)
    if callable(cancel):
        cancel()
    outcome = f"cancelled: {child_id}"
    nodes: list[dict[str, object]] = []
    for node in tree["nodes"]:  # type: ignore[index]
        copied = dict(node)
        if copied.get("id") == child_id and outcome.startswith("cancelled"):
            copied["status"] = "cancelled"
        nodes.append(copied)
    return {"run_id": tree["run_id"], "nodes": nodes, "outcome": outcome}


async def accept_steer(
    *,
    run_id: str,
    text: str,
    worker: Any,
    store: object | None = None,
) -> dict[str, object]:
    """Hand the text to the running worker's prompt/steer handler."""
    del store
    session_id = str(getattr(worker, "_session_id", "") or "")
    web_run = str(getattr(worker, "_web_run_id", "") or "")
    if run_id not in {session_id, web_run}:
        return {
            "run_id": run_id,
            "store_written": False,
            "accepted": False,
            "applied": [],
            "reason": "run mismatch",
        }
    request_id = int(getattr(worker, "_next_id", 1) or 1)
    worker._next_id = request_id + 1
    await worker._handle_steer({"text": text, "session_id": run_id}, request_id)
    queued = [str(item) for item in getattr(worker, "_steer_queue", [])]
    return {
        "run_id": run_id,
        "store_written": False,
        "accepted": text in queued,
        "applied": [{"text": item, "seq": index + 1} for index, item in enumerate(queued)],
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
