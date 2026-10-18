"""Map an existing team trace into a parent/child tree.

Plan changes are steer commands on the run. They are not written to EventStore.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping


_LOG = logging.getLogger(__name__)

_INTERMEDIATE = {"intermediate", "partial_result", "progress", "reasoning.summary"}
_BOUND: dict[str, dict[str, Any]] = {}
_CURRENT: dict[str, str] = {}
_APPLIED: dict[str, int] = {}

#: In-flight spans keyed at module level — each journal handle is a fresh
#: RunJournal, but one run's agent/tool spans must pair across instances.
_OPEN_AGENT_SPANS: dict[tuple[str, str], tuple[Any, Any]] = {}
_OPEN_TOOL_SPANS: dict[tuple[str, str], tuple[Any, Any]] = {}

#: ``(run_id, call_id)`` keys whose tool span already CLOSED (exported).
#: The shared dedup guard for BOTH emission paths — the journaled
#: ``event/tool_*`` path and the ProtocolTui ``open_tool_span`` /
#: ``close_tool_span`` path — so a second end (or a late/duplicate begin)
#: can never fork a second span for one tool call. Bounded FIFO.
_CLOSED_TOOL_SPANS: dict[tuple[str, str], None] = {}
_CLOSED_TOOL_SPANS_MAX = 4096


def _mark_tool_span_closed(key: tuple[str, str]) -> None:
    _CLOSED_TOOL_SPANS[key] = None
    while len(_CLOSED_TOOL_SPANS) > _CLOSED_TOOL_SPANS_MAX:
        _CLOSED_TOOL_SPANS.pop(next(iter(_CLOSED_TOOL_SPANS)), None)

_AGENT_OPEN_METHODS = {"event/agent_started"}
_AGENT_CLOSE_METHODS = {
    "event/agent_done": "ok",
    "event/agent_failed": "error",
    "event/agent_cancelled": "cancelled",
}

#: Tool notifications that close an open span — and the failure subset.
#: ``tool_end``/``tool_result`` still need the payload verdict (``ok`` /
#: ``status``); ``tool_error``/``tool_failed`` are failures by name alone.
_TOOL_CLOSE_SUFFIXES = ("tool_end", "tool_result", "tool_error", "tool_failed")
_TOOL_FAIL_SUFFIXES = ("tool_error", "tool_failed")


def _tool_span_status(method: str, body: Mapping[str, Any]) -> str:
    """Map a tool-close notification to the span status.

    An unsuccessful tool is an ERROR span — ``tool_error``/``tool_failed``
    outright, and ``tool_end``/``tool_result`` carrying ``ok=False`` or a
    non-success ``status`` (timeout, error, cancelled…)."""
    if method.endswith(_TOOL_FAIL_SUFFIXES):
        return "error"
    if "ok" in body and not bool(body.get("ok")):
        return "error"
    status = str(body.get("status") or "").strip().lower()
    if status and status not in {"success", "ok", "succeeded"}:
        return "error"
    return "ok"


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


def tool_span_begin(
    call_id: str, name: str, *, attrs: dict[str, Any] | None = None
) -> None:
    """Best-effort ``tool.<name>`` span open for the REAL tool path.

    Production tool notifications flow ``ToolOrchestrator ->
    ProtocolTui.write_tool_call`` — they never pass through
    ``RunJournal.record``, so the TUI hook calls this instead. The span
    is keyed by ``(run_id, call_id)`` in the same store the journaled
    path uses and parents under the in-flight agent span for this run
    when one exists. No-op without an active web run; never raises —
    telemetry must not break a tool call.
    """
    try:
        journal = default_run_journal()
        if journal is None or not call_id:
            return
        journal.open_tool_span(call_id, name, attrs=attrs)
    except Exception:
        _LOG.warning("tool span begin failed", exc_info=True)


def tool_span_end(
    call_id: str, ok: bool, *, attrs: dict[str, Any] | None = None
) -> None:
    """Close the span ``tool_span_begin`` opened for ``call_id``.

    ``ok`` is ``status == "success"`` at the TUI layer — a non-success
    tool result (error/timeout/cancelled) exports span status ``error``.
    No-op without a matching open span; never raises.
    """
    try:
        journal = default_run_journal()
        if journal is None or not call_id:
            return
        journal.close_tool_span(call_id, ok, attrs=attrs)
    except Exception:
        _LOG.warning("tool span end failed", exc_info=True)


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
                        'pending', 'running', 'leased',
                        'cancel_requested', 'waiting_approval'
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
        self._tracer: Any | None = None

    def record(self, method: str, agent_id: str, payload: dict[str, Any], *, parent_id: str = "") -> int:
        from rxycode_server.events.store import append_event

        body = dict(payload)
        body["agent_id"] = agent_id
        if parent_id:
            body["parent_id"] = parent_id
        if "tokens" not in body and "total_tokens" in body:
            body["tokens"] = body["total_tokens"]
        seq = append_event(
            self.database_url,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            event_type=method,
            payload=body,
        )
        try:
            self._emit_span(method, agent_id, body)
        except Exception:
            # Telemetry is best-effort: a span failure never blocks the
            # journaled event that just committed.
            _LOG.warning("run-journal span emit failed", exc_info=True)
        return seq

    # ------------------------------------------------------------------
    # telemetry: tool/agent spans emitted alongside the journaled events
    # ------------------------------------------------------------------

    def _span_tracer(self) -> Any:
        if self._tracer is None:
            from rxycode_worker import telemetry

            self._tracer = telemetry.Tracer(
                telemetry.RunEventsSpanExporter(self.database_url, self.tenant_id),
                service="rxycode-worker",
            )
        return self._tracer

    def _remote_parent(self) -> Any:
        """The run-scoped context this run's spans parent under.

        Resolution order, all scoped to THIS run — never a process-global
        guess: (1) the ``worker.run`` span opened by ``supervisor.claim``
        in this process; (2) the ``traceparent`` persisted in the run's
        ``run.created`` event (survives a cross-process handoff and a
        worker started before any env var existed); (3) the legacy env
        channel — last resort only, and only when the run's own
        ``run.created`` event PROVES it predates persisted traceparents
        (``ParentLookup.run_event_found``).  A missing row or a failed
        lookup returns ``None`` — an unparented span — because the env
        value could name ANOTHER run's span.
        """
        from rxycode_worker import supervisor, telemetry

        pair = supervisor._OPEN_RUN_SPANS.get(self.run_id)
        if pair is not None:
            return pair[1].context
        lookup = telemetry.parent_for_run(self.database_url, self.run_id)
        if lookup.context is not None:
            return lookup.context
        if not lookup.run_event_found:
            # The run's own run.created event could not be proven (row
            # absent or the lookup failed): the process-global env may
            # hold ANOTHER run's context, so it is never consulted here —
            # an unparented span is honest, a cross-parented one is wrong.
            return None
        # Proven legacy run (run.created exists, no traceparent persisted):
        # the env channel is the accepted last resort for a parent.
        return telemetry.extract_env()

    def _span_parent(self, agent_id: str) -> Any:
        """Tool spans nest under the in-flight agent span when one exists."""
        pair = _OPEN_AGENT_SPANS.get((self.run_id, agent_id))
        if pair is not None:
            return pair[1].context
        return self._remote_parent()

    def _span_parent_for_tool(self) -> Any:
        """Parent for a tool span that arrives WITHOUT an agent_id (the
        ``ProtocolTui`` path): the most recently opened in-flight agent
        span for this run, else the run-scoped remote parent."""
        for (run_id, _agent_id), (_tracer, span) in reversed(
            list(_OPEN_AGENT_SPANS.items())
        ):
            if run_id == self.run_id:
                return span.context
        return self._remote_parent()

    def _emit_span(self, method: str, agent_id: str, body: dict[str, Any]) -> None:
        """Emit one sanitized span for a journaled event when the method maps.

        Agent lifecycle events open/close a ``graph.agent.<id>`` span;
        tool-call-ish methods (``event/tool_*`` or any payload carrying a
        call id) emit a ``tool.<name>`` span carrying the ``tool_call_id``
        from the payload. Attrs pass through telemetry's sanitizer before
        leaving the process.
        """
        call_id = str(body.get("tool_call_id") or body.get("call_id") or "")
        if method in _AGENT_OPEN_METHODS:
            span = self._span_tracer().start_span(
                f"graph.agent.{agent_id}",
                kind="worker",
                parent=self._remote_parent(),
                run_id=self.run_id,
                attrs={"agent.id": agent_id, **body},
            )
            _OPEN_AGENT_SPANS[(self.run_id, agent_id)] = (self._tracer, span)
            return
        if method in _AGENT_CLOSE_METHODS:
            pair = _OPEN_AGENT_SPANS.pop((self.run_id, agent_id), None)
            if pair is None:
                return
            tracer, span = pair
            tracer.end_span(
                span,
                status=_AGENT_CLOSE_METHODS[method],
                attrs=dict(body),
            )
            return
        if "tool" not in method and not call_id:
            return
        tool_name = str(body.get("tool_name") or body.get("tool") or "call")
        key = (self.run_id, call_id)
        is_close = method.endswith(_TOOL_CLOSE_SUFFIXES)
        if method.endswith("tool_begin") and call_id:
            pair = _OPEN_TOOL_SPANS.get(key)
            if pair is not None:
                # Shared-registry dedup: a begin over an OPEN span (from
                # either emission path) merges attrs into it — it never
                # forks a second span and never loses the real start.
                _tracer, open_span = pair
                open_span.set_attrs(dict(body))
                return
            if key in _CLOSED_TOOL_SPANS:
                return  # duplicate begin after the call already closed
            span = self._span_tracer().start_span(
                f"tool.{tool_name}",
                kind="tool",
                parent=self._span_parent(agent_id),
                run_id=self.run_id,
                tool_call_id=call_id,
                attrs=dict(body),
            )
            _OPEN_TOOL_SPANS[key] = (self._tracer, span)
            return
        if call_id:
            pair = _OPEN_TOOL_SPANS.get(key)
            if pair is not None:
                tracer, span = pair
                if is_close:
                    _OPEN_TOOL_SPANS.pop(key, None)
                    _mark_tool_span_closed(key)
                    tracer.end_span(
                        span,
                        status=_tool_span_status(method, body),
                        attrs=dict(body),
                    )
                else:
                    # A mid-call event (delta/output/approval) enriches the
                    # open span — it must not end the tool's duration early.
                    span.set_attrs(dict(body))
                return
            if key in _CLOSED_TOOL_SPANS:
                # Second end / post-close noise: the span already exported
                # exactly once — a duplicate must not fork another.
                return
        # A one-shot tool event still yields a real (point-in-time) span —
        # with the failure status when the notification reports one.
        span = self._span_tracer().start_span(
            f"tool.{tool_name}",
            kind="tool",
            parent=self._span_parent(agent_id),
            run_id=self.run_id,
            tool_call_id=call_id,
            attrs=dict(body),
        )
        one_shot = _tool_span_status(method, body) if is_close else "ok"
        self._span_tracer().end_span(span, status=one_shot)
        if call_id and is_close:
            _mark_tool_span_closed(key)

    # ------------------------------------------------------------------
    # telemetry: spans for the REAL tool-notification path
    # (ToolOrchestrator -> ProtocolTui), which never calls record().
    # ------------------------------------------------------------------

    def open_tool_span(
        self, call_id: str, name: str, *, attrs: dict[str, Any] | None = None
    ) -> None:
        """Open a ``tool.<name>`` span keyed by ``call_id``.

        Emitted by ``tool_span_begin`` (the ProtocolTui hook). Keyed in
        the same ``_OPEN_TOOL_SPANS`` store the journaled path uses, so a
        journaled ``tool_end`` can still pair with it; a duplicate begin
        for the same call_id merges attrs into the open span — never a
        second span — and a begin after close is a no-op.
        """
        key = (self.run_id, str(call_id))
        pair = _OPEN_TOOL_SPANS.get(key)
        if pair is not None:
            _tracer, open_span = pair
            if attrs:
                open_span.set_attrs(dict(attrs))
            return
        if key in _CLOSED_TOOL_SPANS:
            return
        span = self._span_tracer().start_span(
            f"tool.{name or 'call'}",
            kind="tool",
            parent=self._span_parent_for_tool(),
            run_id=self.run_id,
            tool_call_id=str(call_id),
            attrs=dict(attrs or {}),
        )
        _OPEN_TOOL_SPANS[key] = (self._tracer, span)

    def close_tool_span(
        self, call_id: str, ok: bool, *, attrs: dict[str, Any] | None = None
    ) -> None:
        """Close the span ``open_tool_span`` started — ``ok=False``
        exports status ``error`` (a non-success tool result is a failed
        span). An end with no open span emits exactly ONE one-shot span
        (same dedup contract as the journaled path); a second end is a
        no-op."""
        key = (self.run_id, str(call_id))
        pair = _OPEN_TOOL_SPANS.pop(key, None)
        if pair is None:
            if not str(call_id) or key in _CLOSED_TOOL_SPANS:
                return
            _mark_tool_span_closed(key)
            attrs_map = dict(attrs or {})
            tracer = self._span_tracer()
            name = str(
                attrs_map.get("tool_name") or attrs_map.get("tool") or "call"
            )
            span = tracer.start_span(
                f"tool.{name}",
                kind="tool",
                parent=self._span_parent_for_tool(),
                run_id=self.run_id,
                tool_call_id=str(call_id),
                attrs=attrs_map,
            )
            tracer.end_span(span, status="ok" if ok else "error")
            return
        _mark_tool_span_closed(key)
        tracer, span = pair
        tracer.end_span(
            span,
            status="ok" if ok else "error",
            attrs=dict(attrs or {}),
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
