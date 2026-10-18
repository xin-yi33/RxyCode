"""WEB-W7-C04. OTel-convention spans correlate one run across layers.

Contract: a real cloud-mode run driven through the durable spine —
``create_run`` -> worker ``claim`` -> journaled ``event/agent_*`` ->
``record_terminal_usage`` -> ``commit_terminal`` — leaves ``telemetry.span``
rows in ``run_events`` under ONE W3C trace_id; HTTP-layer, worker-layer and
tool-layer spans each carry a real measured duration; the trace is
queryable by run_id; a foreign tenant reads nothing.

Negative: a secret string in a tool's stderr/attrs is masked before the
span is persisted — the raw secret never lands in the stored event payload.

Propagation: the server persists the http span's W3C ``traceparent``
(32-hex trace_id, 16-hex span_id) inside the ``run.created`` event
payload; the worker reads it back per run_id (``parent_for_run``) — never
the process-global env — and parents its ``worker.run`` span under it.
Tool spans are emitted by the REAL production path
(``ToolOrchestrator -> ProtocolTui.write_tool_call/write_tool_result ->
agent_events.tool_span_begin/tool_span_end``), and a failed tool exports
span status ``error``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
for _entry in (REPO, _SERVER, _WORKER, _RUNNER):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

ORIGIN = "https://cloud.example"
SECRET = "local-web-secret-value-32bytes!!"
PRICE_VERSION = "2026-10"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Cloud app helpers (same shape as the w7_c01 auth surface)
# ---------------------------------------------------------------------------


def _github(app, client, github_id: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(
                200, json={"access_token": f"ghs_{github_id}", "token_type": "bearer"}
            )
        return httpx.Response(200, json={"id": github_id, "login": f"user-{github_id}"})

    app.state.github_transport = httpx.MockTransport(handler)
    started = client.get("/api/v1/auth/github/start")
    assert started.status_code == 200
    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"state": started.json()["state"], "code": f"code-{github_id}"},
    )
    assert callback.status_code == 200
    assert f"ghs_{github_id}" not in callback.text


def _csrf(client) -> dict[str, str]:
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": ORIGIN}


def _cloud_app(postgres_url: str):
    from rxycode_server.main import create_app
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(postgres_url)
    return create_app(
        postgres_url,
        mode="cloud",
        secret=SECRET,
        allowed_origins=[ORIGIN],
        github_client_id="iv1.client",
        github_client_secret="github-secret-not-stored",
        github_redirect_uri="https://cloud.example/callback",
    )


def _provision_owner(postgres_url: str):
    """A signed-in cloud tenant with one project and one session row."""
    from fastapi.testclient import TestClient

    app = _cloud_app(postgres_url)
    owner = TestClient(app, base_url="https://cloud.example")
    _github(app, owner, 941)
    headers = _csrf(owner)
    project = owner.post(
        "/api/v1/projects",
        json={"name": "c04-own", "repo_config": {}},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["id"]
    tenant_id = project.json()["tenant_id"]
    session = owner.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"title": "c04-session"},
        headers=headers,
    )
    assert session.status_code == 200
    return app, owner, tenant_id, project_id, session.json()["id"]


def _events(database_url: str, tenant_id: str, run_id: str) -> list[dict]:
    from rxycode_server.events.store import replay

    return list(
        replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)["events"]
    )


def _spans(database_url: str, tenant_id: str, run_id: str) -> list[dict]:
    return [
        event["payload"]
        for event in _events(database_url, tenant_id, run_id)
        if event["type"] == "telemetry.span"
    ]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_w7_c04_contract(postgres_url: str, tmp_path: Path) -> None:
    """One trace_id correlates server/worker/tool spans, each with duration.

    Every span in this trace is emitted BY the production wiring — the
    http/server span by ``runs.service.create_run``, the worker run span by
    ``supervisor.claim`` / ``supervisor.commit_terminal``, and the
    graph/tool spans by ``agent_events.RunJournal.record`` — never
    constructed by the test itself.
    """
    from fastapi.testclient import TestClient

    from appserver.agent_runtime import AgentConfig, AgentRuntime
    from appserver.eventbus import AppendOnlyLog, EventBus
    from rxycode_server import metrics
    from rxycode_server.events.store import append_event, replay
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_server.usage.service import record_terminal_usage
    from rxycode_worker import telemetry
    from rxycode_worker.agent_events import (
        clear_web_run,
        default_run_journal,
        publish_database_url,
        remember_web_run,
    )
    from rxycode_worker.supervisor import attempt_tool, claim, commit_terminal
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    upgrade_head(postgres_url)
    app, owner, tenant_id, project_id, session_id = _provision_owner(postgres_url)
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    workdir = tmp_path / "c04-contract"
    workdir.mkdir(parents=True)
    message = "/solo write answer.txt with the marker"
    runtime_box: dict[str, object] = {}
    try:
        # -- HTTP layer: create_run itself emits the server span and
        # persists its W3C traceparent inside the run.created payload —
        # the run-scoped propagation channel the claiming worker reads.
        accepted = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_id,
            message=message,
            target_id="local:c04",
            permission_profile="full_auto",
            request_id=f"req-c04-{uuid.uuid4().hex[:12]}",
        )
        run_id = accepted.run_id
        lookup = telemetry.parent_for_run(postgres_url, run_id)
        assert lookup.run_event_found is True
        remote_parent = lookup.context
        assert remote_parent is not None
        assert len(remote_parent.trace_id) == 32
        created = next(
            event
            for event in _events(postgres_url, tenant_id, run_id)
            if event["type"] == "run.created"
        )
        persisted = telemetry.parse_traceparent(
            created["payload"]["traceparent"]
        )
        assert persisted is not None
        assert persisted.trace_id == remote_parent.trace_id

        got = owner.get(f"/api/v1/runs/{run_id}")
        assert got.status_code == 200
        assert got.json()["status"] == "pending"

        publish_database_url(postgres_url)
        remember_web_run(
            postgres_url, tenant_id, run_id, session_id=session_id
        )

        # -- Worker layer: claim opens the run span, parented on the
        # PERSISTED traceparent (read per run_id); commit_terminal closes
        # it -----------------------------------------------------------
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None

        async def _target(_task: str, checkpoint: object | None = None) -> str:
            from appserver.tui import ProtocolTui

            runtime = runtime_box["runtime"]
            journal = default_run_journal()
            assert journal is not None
            notifications: list[object] = []
            tui = ProtocolTui(
                session_id,
                lambda notification: notifications.append(notification),
                run_id=run_id,
            )
            tool_journal = ToolExecutionJournal(tmp_path / "tool-journal")
            attempt_id = new_attempt_id()
            call = tool_journal.binding(attempt_id).next_call(
                "write_file", {"path": "answer.txt"}
            )
            # -- Tool layer: the REAL production notification path —
            # ToolOrchestrator -> ProtocolTui.write_tool_call /
            # write_tool_result — emits the tool.<name> span through the
            # agent_events tool_span_begin/tool_span_end hooks, never by
            # this test journaling a span directly ---------------------
            returned_id = tui.write_tool_call(
                "write_file", {"path": "answer.txt"}, call_id=call.key
            )
            assert returned_id == call.key
            outcome = attempt_tool(
                tool_journal,
                attempt_id,
                "write_file",
                {"path": "answer.txt"},
                lambda: Path(workdir, "answer.txt").write_text(
                    "present-marker", encoding="utf-8"
                ),
            )
            assert outcome["executed"] is True
            ctx = runtime.contexts["eval-primary"]
            ctx.record_cache(True)
            ctx.record_cache(False)
            runtime.record_token_usage("eval-primary", 1234)
            cache = runtime._session_cache
            # A mid-call journaled event enriches the OPEN span (the
            # production merge path for deltas/progress); the span itself
            # stays opened/closed by the TUI hooks.
            journal.record(
                "event/tool_progress",
                "eval-primary",
                {
                    "call_id": call.key,
                    "tool_name": "write_file",
                    "attempt_id": attempt_id,
                    "cache.hits": cache.hits,
                    "cache.misses": cache.misses,
                },
            )
            tui.write_tool_result("wrote answer.txt", "success", call_id=call.key)
            assert any(
                getattr(note, "method", "") == "event/tool_end"
                for note in notifications
            )
            return "wrote answer.txt"

        async def _drive() -> object:
            runtime = AgentRuntime(
                EventBus(AppendOnlyLog()), run_factory=lambda _cfg: _target
            )
            runtime_box["runtime"] = runtime
            agent_task = await runtime.spawn(
                AgentConfig(
                    agent_id="eval-primary",
                    model="eval-stub",
                    budget_tokens=0,
                )
            )
            main_task = agent_task._main_task
            assert main_task is not None
            return await main_task

        answer = asyncio.run(_drive())
        assert answer == "wrote answer.txt"

        # -- Finalize: verdict + ledger + terminal commit (real spine) -----
        append_event(
            postgres_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="eval.checks",
            payload={"status": "passed", "task_id": "w7c04-contract"},
        )
        usage = record_terminal_usage(
            postgres_url,
            tenant_id=tenant_id,
            run_id=run_id,
            model_id="eval-stub",
            price_version=PRICE_VERSION,
            tokens=1234,
            event_id=uuid.uuid4().hex,
        )
        commit_terminal(postgres_url, run_id, worker_id, epoch, "succeeded")
    finally:
        clear_web_run()
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    assert usage["tokens"] == 1234
    assert usage["amount"] == "0.00246800"

    # -- Durable span rows: one trace_id, three layers, real durations ------
    # All four spans were emitted by the production wiring (create_run /
    # claim+commit_terminal / the ProtocolTui tool-span hook +
    # RunJournal.record), not constructed by this test.
    spans = _spans(postgres_url, tenant_id, run_id)
    assert len(spans) >= 4, spans
    trace_ids = {span["trace_id"] for span in spans}
    assert trace_ids == {remote_parent.trace_id}
    assert len(remote_parent.trace_id) == 32
    by_name = {span["name"]: span for span in spans}
    for name in (
        "http POST /api/v1/runs",
        "worker.run",
        "graph.agent.eval-primary",
        "tool.write_file",
    ):
        assert name in by_name, by_name
        span = by_name[name]
        assert span["duration_ms"] > 0, span
        assert span["status"] == "ok"
        assert len(span["span_id"]) == 16
        assert span["run_id"] == run_id

    # Parentage: http server span -> worker run -> graph/agent -> tool.
    tool_span = by_name["tool.write_file"]
    assert tool_span["parent_span_id"] == by_name["graph.agent.eval-primary"]["span_id"]
    assert (
        by_name["graph.agent.eval-primary"]["parent_span_id"]
        == by_name["worker.run"]["span_id"]
    )
    assert (
        by_name["worker.run"]["parent_span_id"]
        == by_name["http POST /api/v1/runs"]["span_id"]
    )
    assert tool_span["tool_call_id"].startswith("call_")

    # The lifecycle journal landed through the real RunJournal too.
    kinds = [event["type"] for event in _events(postgres_url, tenant_id, run_id)]
    for expected in (
        "run.created",
        "event/agent_started",
        "event/agent_done",
        "eval.checks",
        "usage.updated",
    ):
        assert expected in kinds, kinds

    # -- Trace queryable by run_id; the summary is owner-scoped -------------
    summary = metrics.run_trace_summary(
        postgres_url, tenant_id=tenant_id, run_id=run_id
    )
    assert summary["code"] is None
    assert summary["trace_id"] == remote_parent.trace_id
    assert summary["events_url"] == f"/api/v1/runs/{run_id}/events"
    assert summary["span_count"] == len(spans)
    # Honest duration accounting: the run's elapsed is the trace ENVELOPE
    # (min start_epoch -> max end_epoch across ALL spans) — the http root
    # ended when create_run committed, long before the worker finished, so
    # elapsed must extend well past any single span's duration. Summed
    # span durations are still reported separately as total_span_work_ms.
    assert summary["elapsed_ms"] > 0
    starts = [float(span["start_epoch"]) for span in summary["spans"]]
    ends = [float(span["end_epoch"]) for span in summary["spans"]]
    assert summary["elapsed_ms"] == pytest.approx(
        (max(ends) - min(starts)) * 1000.0, abs=0.01
    )
    assert (
        summary["elapsed_ms"]
        > by_name["http POST /api/v1/runs"]["duration_ms"]
    )
    assert summary["total_span_work_ms"] > 0
    for layer in ("server", "worker", "tool"):
        assert summary["layers"][layer]["count"] >= 1, summary["layers"]
        assert summary["layers"][layer]["duration_ms"] > 0
    assert summary["ledger"]["tokens"] == 1234
    assert summary["ledger"]["amount"] == "0.00246800"
    assert summary["ledger"]["price_version"] == PRICE_VERSION
    assert summary["ledger"]["model_id"] == "eval-stub"
    assert summary["provider"]["tokens_used"] == 1234
    assert summary["aligned"] is True
    assert summary["cache"]["hits"] == 1
    assert summary["cache"]["misses"] == 1
    assert summary["cost"]["abnormal"] is False

    # The full prompt never lands in any stored span payload.
    span_payloads = json.dumps(spans, ensure_ascii=False)
    assert message not in span_payloads
    assert "write answer.txt with the marker" not in span_payloads

    # -- A foreign tenant reads nothing: summary, replay, and the real HTTP
    # surface all refuse. Users see summaries of THEIR OWN traces only.
    foreign = metrics.run_trace_summary(
        postgres_url, tenant_id=f"foreign-{tenant_id}", run_id=run_id
    )
    assert foreign["code"] == "RUN_NOT_FOUND"
    assert foreign["spans"] == []
    assert (
        replay(
            postgres_url,
            tenant_id=f"foreign-{tenant_id}",
            run_id=run_id,
            after_seq=0,
        )["code"]
        == "RUN_NOT_FOUND"
    )
    attacker = TestClient(app, base_url="https://cloud.example")
    _github(app, attacker, 942)
    foreign_tenant = attacker.post(
        "/api/v1/projects",
        json={"name": "atk", "repo_config": {}},
        headers=_csrf(attacker),
    ).json()["tenant_id"]
    assert foreign_tenant != tenant_id
    events = attacker.get(f"/api/v1/runs/{run_id}/events")
    assert events.status_code == 404
    foreign_usage = attacker.get("/api/v1/usage")
    assert foreign_usage.status_code == 200
    assert foreign_usage.json()["tokens"] == 0


# ---------------------------------------------------------------------------
# Negative: secrets in tool output are masked before persistence
# ---------------------------------------------------------------------------


def test_w7_c04_negative(postgres_url: str, tmp_path: Path) -> None:
    """A secret in tool stderr/attrs is redacted in the stored span payload."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import (
        Organization,
        Project,
        RunEvent,
        SessionRow,
        User,
    )
    from rxycode_server.runs.service import create_run
    from rxycode_worker import telemetry
    from rxycode_worker.supervisor import attempt_tool
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    upgrade_head(postgres_url)
    tenant_id = f"tenant-c04neg-{uuid.uuid4().hex[:8]}"
    session_id = uuid.uuid4().hex
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(User(id=f"user-{tenant_id}", github_id=None, kind="local"))
            db.add(Organization(id=f"org-{tenant_id}", tenant_id=tenant_id))
            db.add(
                Project(
                    id=f"prj-{tenant_id}",
                    tenant_id=tenant_id,
                    name="c04-neg",
                    repo_config={},
                )
            )
            db.add(
                SessionRow(
                    id=session_id,
                    tenant_id=tenant_id,
                    project_id=f"prj-{tenant_id}",
                    title="c04-neg",
                )
            )
            db.commit()
    finally:
        engine.dispose()
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_id,
        message="run the tool",
        target_id="local:c04neg",
        permission_profile="full_auto",
        request_id=f"req-c04neg-{uuid.uuid4().hex[:12]}",
    )
    run_id = created.run_id

    exporter = telemetry.RunEventsSpanExporter(postgres_url, tenant_id)
    tracer = telemetry.Tracer(exporter, service="rxycode-web-c04-neg")
    # Fabricated-but-realistic secrets (never real keys) in the tool's
    # stderr, in span attrs, and nested inside a list of dicts — the stored
    # payload must mask or drop every form.
    api_secret = "sk-c04testsecret1234567890abcdef"
    password = "hunter2-super-secret"
    gh_token = "ghp_c04fakegithubtoken9Zxq"
    nested_secret = "nested-hunter3"
    inner_prompt = "inner prompt body never stored"
    system_prompt = "system prompt body must never be stored"
    journal = ToolExecutionJournal(tmp_path / "neg-journal")
    attempt_id = new_attempt_id()
    call = journal.binding(attempt_id).next_call("bash", {"command": "deploy"})
    stderr = (
        f"fatal: authorization: bearer {api_secret} rejected; "
        f"deploy failed (password={password}); remote used {gh_token}"
    )
    span = tracer.start_span(
        "tool.bash",
        kind="tool",
        run_id=run_id,
        tool_call_id=call.key,
        attrs={
            "tool.name": "bash",
            # These attrs model what a careless instrumenter would attach —
            # the sanitizer must mask or drop every one.
            "tool.stderr": stderr,
            "prompt": "the full user prompt must never be stored",
            "api_key": api_secret,
            "note": f"used password={password} to auth",
        },
    )
    # Extended probes ride the same sanitized merge path: a prompt-like key,
    # a message container, and a credential nested inside a LIST of dicts —
    # the sanitizer must recurse, never stringify the raw secret.
    span.set_attrs(
        {
            "system_prompt": system_prompt,
            "messages": [{"role": "user", "content": system_prompt}],
            "events": [{"password": nested_secret, "prompt": inner_prompt}],
        }
    )
    outcome = attempt_tool(
        journal,
        attempt_id,
        "bash",
        {"command": "deploy"},
        lambda: stderr,
    )
    tracer.end_span(
        span, status="error", detail=f"command failed: {outcome['result']}"
    )

    with Session(create_engine(postgres_url, poolclass=NullPool)) as db:
        rows = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.type == "telemetry.span"
            )
        ).all()
    # create_run emitted its own http/server span — the probe is the tool span.
    rows = [
        row for row in rows if (row.payload or {}).get("name") == "tool.bash"
    ]
    assert len(rows) == 1
    stored = json.dumps(rows[0].payload, ensure_ascii=False)
    assert api_secret not in stored
    assert password not in stored
    assert gh_token not in stored
    assert nested_secret not in stored
    assert inner_prompt not in stored
    assert system_prompt not in stored
    assert "[REDACTED]" in stored
    # The prompt body is dropped entirely, leaving only safe metadata.
    attrs = rows[0].payload["attrs"]
    assert "prompt" not in attrs
    assert attrs["prompt_len"] == len("the full user prompt must never be stored")
    assert "api_key" not in attrs
    # The masked stderr survives for diagnosis — redacted, not swallowed.
    assert "authorization: bearer [REDACTED]" in attrs["tool.stderr"]
    assert "password=[REDACTED]" in attrs["tool.stderr"]
    # The in-memory export payload was already sanitized too.
    assert api_secret not in json.dumps(span.to_dict(), ensure_ascii=False)
    assert gh_token not in json.dumps(span.to_dict(), ensure_ascii=False)
    assert "remote used [REDACTED]" in attrs["tool.stderr"]
    # Prompt-like keys dropped → only len/sha metadata; nested list recursed.
    assert "system_prompt" not in attrs
    assert attrs["system_prompt_len"] == len(system_prompt)
    assert "messages" not in attrs
    assert attrs["messages_len"] > 0 and "messages_sha256" in attrs
    events_attr = attrs["events"]
    assert isinstance(events_attr, list) and len(events_attr) == 1
    assert "password" not in events_attr[0]
    assert events_attr[0]["password_len"] == len(nested_secret)
    assert "prompt" not in events_attr[0]


# ---------------------------------------------------------------------------
# Propagation: W3C traceparent honored across the layers
# ---------------------------------------------------------------------------


def test_w7_c04_traceparent(postgres_url: str, tmp_path: Path) -> None:
    """Server injects, worker honors, runner parents — one W3C trace."""
    from rxycode_worker import telemetry

    memory = telemetry.InMemorySpanExporter()
    tracer = telemetry.Tracer(memory, service="propagation")

    root = tracer.start_span("http POST /api/v1/runs", kind="server")
    tracer.end_span(root)
    ctx = root.context
    header = telemetry.format_traceparent(ctx)
    # W3C: version-traceid(32)-spanid(16)-flags
    parts = header.split("-")
    assert parts[0] == "00" and parts[3] in {"00", "01"}
    assert len(parts[1]) == 32 and len(parts[2]) == 16

    # Inject through the environment — the same channel the worker uses to
    # inherit the run's database url and run coordinates.
    telemetry.inject_env(ctx)
    try:
        remote = telemetry.extract_env()
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)
    assert remote is not None
    assert remote.trace_id == ctx.trace_id
    assert remote.span_id == ctx.span_id

    worker = tracer.start_span("worker.claim", kind="worker", parent=remote)
    tool = tracer.start_span(
        "tool.bash", kind="tool", parent=worker.context, tool_call_id="call_x"
    )
    tracer.end_span(tool)
    tracer.end_span(worker)

    assert worker.context.trace_id == ctx.trace_id
    assert worker.context.parent_span_id == ctx.span_id
    assert tool.context.trace_id == ctx.trace_id
    assert tool.context.parent_span_id == worker.context.span_id
    assert tool.context.tool_call_id == "call_x"

    # parse_traceparent accepts the header form directly.
    parsed = telemetry.parse_traceparent(header)
    assert parsed is not None
    assert parsed.trace_id == ctx.trace_id
    assert parsed.span_id == ctx.span_id

    # Malformed headers are rejected, never guessed.
    for bad in ("", "00-abc-123-01", "not-a-traceparent", "zz-" + "a" * 32 + "-" + "b" * 16 + "-01"):
        assert telemetry.parse_traceparent(bad) is None

    # ContextVar propagation: an activated parent is picked up implicitly.
    with tracer.use_span(worker):
        implied = tracer.start_span("graph.node", kind="internal")
        tracer.end_span(implied)
    assert implied.context.parent_span_id == worker.context.span_id
    assert implied.context.trace_id == ctx.trace_id

    spans = memory.spans
    assert {span["trace_id"] for span in spans} == {ctx.trace_id}
    assert exporter_dropped(memory) == 0


def test_w7_c04_traceparent_edges(postgres_url: str, tmp_path: Path) -> None:
    """W3C edge cases: version ff rejected, sampled is bit 0x01, a malformed
    explicit parent inside an ambient context falls back to the ambient."""
    from rxycode_worker import telemetry

    trace_id = "a" * 32
    span_id = "b" * 16
    # Version ``ff`` is forbidden by the W3C spec; other versions parse.
    assert (
        telemetry.parse_traceparent(f"ff-{trace_id}-{span_id}-01") is None
    )
    parsed = telemetry.parse_traceparent(f"01-{trace_id}-{span_id}-01")
    assert parsed is not None and parsed.trace_id == trace_id

    # Flags: only the 0x01 SAMPLED bit means sampled — ``02`` is NOT sampled.
    assert (
        telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-01").sampled
        is True
    )
    assert (
        telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-00").sampled
        is False
    )
    assert (
        telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-02").sampled
        is False
    )
    assert (
        telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-03").sampled
        is True
    )
    # Flags must be exactly two hex chars — one or three chars is malformed.
    assert telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-1") is None
    assert telemetry.parse_traceparent(f"00-{trace_id}-{span_id}-123") is None

    # A malformed explicit parent inside an active use_span falls back to
    # the ambient context — it must NOT fork a new trace_id.
    tracer = telemetry.Tracer(telemetry.InMemorySpanExporter())
    root = tracer.start_span("ambient", kind="server")
    tracer.end_span(root)
    with tracer.use_span(root):
        child = tracer.start_span("child", parent="malformed-string")
        tracer.end_span(child)
    assert child.context.trace_id == root.context.trace_id
    assert child.context.parent_span_id == root.context.span_id
    # Outside any ambient context the same malformed parent starts a fresh
    # trace — there is nothing valid to fall back to.
    orphan = tracer.start_span("orphan", parent="malformed-string")
    tracer.end_span(orphan)
    assert orphan.context.trace_id != root.context.trace_id
    assert orphan.context.parent_span_id == ""


def exporter_dropped(exporter) -> int:
    return int(getattr(exporter, "dropped", 0))


# ---------------------------------------------------------------------------
# Audit-r2 regressions
# ---------------------------------------------------------------------------


def _seed_tenant_sessions(
    postgres_url: str, count: int = 1
) -> tuple[str, list[str]]:
    """Seed a tenant + org + project + ``count`` session rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import (
        Organization,
        Project,
        SessionRow,
        User,
    )

    tenant_id = f"tenant-c04-{uuid.uuid4().hex[:8]}"
    session_ids = [uuid.uuid4().hex for _ in range(count)]
    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(User(id=f"user-{tenant_id}", github_id=None, kind="local"))
            db.add(Organization(id=f"org-{tenant_id}", tenant_id=tenant_id))
            db.add(
                Project(
                    id=f"prj-{tenant_id}",
                    tenant_id=tenant_id,
                    name="c04-scoped",
                    repo_config={},
                )
            )
            for sid in session_ids:
                db.add(
                    SessionRow(
                        id=sid,
                        tenant_id=tenant_id,
                        project_id=f"prj-{tenant_id}",
                        title="c04-scoped",
                    )
                )
            db.commit()
    finally:
        engine.dispose()
    return tenant_id, session_ids


def test_w7_c04_run_scoped_traceparent(
    postgres_url: str, tmp_path: Path
) -> None:
    """Create A, create B, claim A — A's worker span parents under A's OWN
    http span even while the process env holds B's traceparent.

    Regression for the process-global ``RXYCODE_TRACEPARENT`` bug: the
    parent must come from the ``traceparent`` persisted in each run's
    ``run.created`` payload — read by run_id — so interleaved runs can
    never cross-parent and a worker started before the env write still
    finds its parent.
    """
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import telemetry
    from rxycode_worker.supervisor import (
        _OPEN_RUN_SPANS,
        claim,
        commit_terminal,
    )

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 2)
    session_a, session_b = session_ids
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    try:
        accepted_a = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_a,
            message="run A",
            target_id="local:c04a",
            permission_profile="full_auto",
            request_id=f"req-a-{uuid.uuid4().hex[:12]}",
        )
        accepted_b = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_b,
            message="run B",
            target_id="local:c04b",
            permission_profile="full_auto",
            request_id=f"req-b-{uuid.uuid4().hex[:12]}",
        )
        # The compat env channel still holds B's http traceparent — exactly
        # the stale state that cross-parented under the old process-global
        # read. claim() must ignore it in favor of the persisted payload.
        stale = telemetry.extract_env()
        assert stale is not None
        epoch_a = claim(
            postgres_url, accepted_a.run_id, worker_id, ttl_seconds=600
        )
        assert epoch_a is not None
        open_a = _OPEN_RUN_SPANS[accepted_a.run_id][1].context
        # env now holds A's re-published worker context — claiming B must
        # not see it either; it reads B's persisted parent.
        epoch_b = claim(
            postgres_url, accepted_b.run_id, worker_id, ttl_seconds=600
        )
        assert epoch_b is not None
        open_b = _OPEN_RUN_SPANS[accepted_b.run_id][1].context
        commit_terminal(
            postgres_url, accepted_a.run_id, worker_id, epoch_a, "succeeded"
        )
        commit_terminal(
            postgres_url, accepted_b.run_id, worker_id, epoch_b, "succeeded"
        )
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    spans_a = {
        s["name"]: s for s in _spans(postgres_url, tenant_id, accepted_a.run_id)
    }
    spans_b = {
        s["name"]: s for s in _spans(postgres_url, tenant_id, accepted_b.run_id)
    }
    http_a = spans_a["http POST /api/v1/runs"]
    http_b = spans_b["http POST /api/v1/runs"]
    worker_a = spans_a["worker.run"]
    worker_b = spans_b["worker.run"]
    assert http_a["trace_id"] != http_b["trace_id"]
    # The stale env context really was B's http span — proof claim ignored it.
    assert stale.trace_id == http_b["trace_id"]
    # In-process evidence at claim time agrees with the persisted rows.
    assert open_a.trace_id == http_a["trace_id"]
    assert open_a.parent_span_id == http_a["span_id"]
    assert open_b.trace_id == http_b["trace_id"]
    assert open_b.parent_span_id == http_b["span_id"]
    assert worker_a["trace_id"] == http_a["trace_id"]
    assert worker_a["parent_span_id"] == http_a["span_id"]
    assert worker_b["trace_id"] == http_b["trace_id"]
    assert worker_b["parent_span_id"] == http_b["span_id"]
    # The persisted run.created payload carries each run's own parent.
    for rid, http in ((accepted_a.run_id, http_a), (accepted_b.run_id, http_b)):
        created_event = next(
            event
            for event in _events(postgres_url, tenant_id, rid)
            if event["type"] == "run.created"
        )
        parsed = telemetry.parse_traceparent(
            created_event["payload"]["traceparent"]
        )
        assert parsed is not None
        assert parsed.trace_id == http["trace_id"]
        assert parsed.span_id == http["span_id"]


def test_w7_c04_terminal_export_savepoint(
    postgres_url: str, tmp_path: Path, monkeypatch
) -> None:
    """A REAL statement error inside the REAL ``export_conn`` must roll
    back only its own savepoint — the terminal status UPDATE still commits.

    Regression (audit-r3): the earlier version of this test swapped in a
    fake exporter whose SQL error propagated — which masked the real bug:
    the production ``export_conn`` caught statement exceptions and
    returned False INSIDE the ``begin_nested`` block, so the context
    manager emitted ``RELEASE SAVEPOINT`` on the aborted tx instead of
    rolling back to it, and the whole terminal commit still died. This
    test corrupts the span payload so the REAL export path's own INSERT
    (``CAST(:payload AS jsonb)``) raises a genuine PostgreSQL statement
    error (22P02) — ``export_conn`` must now let it propagate to the
    savepoint, and the run must still end ``succeeded``.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import telemetry
    from rxycode_worker.supervisor import claim, commit_terminal

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    try:
        accepted = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_ids[0],
            message="savepoint run",
            target_id="local:c04sp",
            permission_profile="full_auto",
            request_id=f"req-sp-{uuid.uuid4().hex[:12]}",
        )
        run_id = accepted.run_id
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None

        real_dumps = telemetry.json.dumps

        def _corrupt_span_dump(value, *args, **kwargs):
            # Corrupt ONLY the otel.span/v1 payload the real exporter
            # serializes: the INSERT's CAST(:payload AS jsonb) then fails
            # server-side inside the real export_conn — a true aborted-tx
            # statement error on the caller's open terminal transaction.
            if isinstance(value, dict) and value.get("schema") == "otel.span/v1":
                return "{not valid json"
            return real_dumps(value, *args, **kwargs)

        monkeypatch.setattr(telemetry.json, "dumps", _corrupt_span_dump)
        # Must not raise: the failed span write rolls back alone.
        commit_terminal(postgres_url, run_id, worker_id, epoch, "succeeded")
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    engine = create_engine(postgres_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM runs WHERE id = :rid"),
                {"rid": run_id},
            ).scalar_one()
            names = [
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT payload->>'name' FROM run_events "
                        "WHERE run_id = :rid AND type = 'telemetry.span' "
                        "ORDER BY seq"
                    ),
                    {"rid": run_id},
                ).all()
            ]
    finally:
        engine.dispose()
    assert status == "succeeded"
    # The http span (separate tx at create) survived; the aborted span
    # write inside the terminal tx rolled back alone — no worker.run row.
    assert names == ["http POST /api/v1/runs"]


def test_w7_c04_identifier_redaction(
    postgres_url: str, tmp_path: Path
) -> None:
    """A secret-shaped call_id / span name is masked in the persisted
    payload's TOP-LEVEL fields — not only inside attrs."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import RunEvent
    from rxycode_server.runs.service import create_run
    from rxycode_worker import telemetry

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_ids[0],
        message="identifier redaction",
        target_id="local:c04id",
        permission_profile="full_auto",
        request_id=f"req-id-{uuid.uuid4().hex[:12]}",
    )
    run_id = created.run_id
    try:
        # Fabricated-only secrets, split so no token-shaped literal lands
        # in the source (or in any manifest embedding this file's diff).
        gh_token = "ghp_" + "c04FakeToken0000000001"
        api_secret = "sk-" + "c04testsecret1234567890ab"
        exporter = telemetry.RunEventsSpanExporter(postgres_url, tenant_id)
        tracer = telemetry.Tracer(exporter, service="c04-ident")
        span = tracer.start_span(
            f"tool.{api_secret}",
            kind="tool",
            run_id=run_id,
            tool_call_id=gh_token,
        )
        tracer.end_span(span)
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    with Session(create_engine(postgres_url, poolclass=NullPool)) as db:
        rows = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.type == "telemetry.span"
            )
        ).all()
    probe = [
        row
        for row in rows
        if (row.payload or {}).get("name") != "http POST /api/v1/runs"
    ]
    assert len(probe) == 1
    payload = probe[0].payload
    stored = json.dumps(payload, ensure_ascii=False)
    assert gh_token not in stored
    assert api_secret not in stored
    assert payload["tool_call_id"] == "[REDACTED]"
    assert payload["name"] == "tool.[REDACTED]"
    # In-memory payload was masked at to_dict() too.
    assert gh_token not in json.dumps(span.to_dict(), ensure_ascii=False)


def test_w7_c04_tool_error_status(
    postgres_url: str, tmp_path: Path
) -> None:
    """A failing tool notification — journaled or via the real
    ProtocolTui path — exports span status ``error``, never ``ok``."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from appserver.tui import ProtocolTui
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.persistence.models import RunEvent
    from rxycode_server.runs.service import create_run
    from rxycode_worker.agent_events import (
        clear_web_run,
        default_run_journal,
        publish_database_url,
        remember_web_run,
    )

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_ids[0],
        message="tool errors",
        target_id="local:c04err",
        permission_profile="full_auto",
        request_id=f"req-err-{uuid.uuid4().hex[:12]}",
    )
    run_id = created.run_id
    try:
        publish_database_url(postgres_url)
        remember_web_run(
            postgres_url, tenant_id, run_id, session_id=session_ids[0]
        )
        journal = default_run_journal()
        assert journal is not None

        # Journaled path: tool_end with ok=False -> error span.
        call_a = "call_err_journal"
        journal.record(
            "event/tool_begin",
            "eval-primary",
            {"call_id": call_a, "tool_name": "bash"},
        )
        journal.record(
            "event/tool_end",
            "eval-primary",
            {"call_id": call_a, "tool_name": "bash", "ok": False},
        )
        # tool_error is a failure by method name alone -> error span.
        journal.record(
            "event/tool_error",
            "eval-primary",
            {"call_id": "call_err_oneshot", "tool_name": "bash"},
        )

        # Real TUI path: write_tool_result status="error" -> error span.
        tui = ProtocolTui(session_ids[0], lambda note: None, run_id=run_id)
        call_b = "call_err_tui"
        tui.write_tool_call("bash", {"command": "deploy"}, call_id=call_b)
        tui.write_tool_result("boom", "error", call_id=call_b)
    finally:
        clear_web_run()
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    with Session(create_engine(postgres_url, poolclass=NullPool)) as db:
        rows = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run_id, RunEvent.type == "telemetry.span"
            )
        ).all()
    by_call = {
        (row.payload or {}).get("tool_call_id"): (row.payload or {})
        for row in rows
    }
    for call in (call_a, "call_err_oneshot", call_b):
        assert call in by_call, by_call
        assert by_call[call]["status"] == "error", by_call[call]
        assert by_call[call]["name"] == "tool.bash"


# ---------------------------------------------------------------------------
# Audit-r3 regressions
# ---------------------------------------------------------------------------


def test_w7_c04_tool_span_dedup(postgres_url: str, tmp_path: Path) -> None:
    """The journaled tool path and the ProtocolTui open/close path share
    ONE open-span registry per ``(run_id, call_id)``: a journaled begin
    over an open span merges attrs instead of forking, the close keeps the
    span's REAL start, and a second end is a no-op — exactly one exported
    span per tool call."""
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import agent_events
    from rxycode_worker.agent_events import (
        clear_web_run,
        default_run_journal,
        publish_database_url,
        remember_web_run,
    )

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    created = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_ids[0],
        message="tool span dedup",
        target_id="local:c04dup",
        permission_profile="full_auto",
        request_id=f"req-dup-{uuid.uuid4().hex[:12]}",
    )
    run_id = created.run_id
    call_id = f"call_dedup_{uuid.uuid4().hex[:8]}"
    try:
        publish_database_url(postgres_url)
        remember_web_run(
            postgres_url, tenant_id, run_id, session_id=session_ids[0]
        )
        journal = default_run_journal()
        assert journal is not None

        # 1. The TUI path opens the span (production ordering: the
        #    orchestrator's begin lands before the journaled mirror).
        journal.open_tool_span(
            call_id, "write_file", attrs={"origin": "tui"}
        )
        key = (run_id, call_id)
        real_start = agent_events._OPEN_TOOL_SPANS[key][1].start_epoch
        time.sleep(0.005)
        # 2. A journaled begin over the OPEN span merges — never forks.
        t_journal_begin = time.time()
        journal.record(
            "event/tool_begin",
            "eval-primary",
            {
                "call_id": call_id,
                "tool_name": "write_file",
                "journaled": True,
            },
        )
        # The registry still holds the SAME open span (same start).
        assert (
            agent_events._OPEN_TOOL_SPANS[key][1].start_epoch == real_start
        )
        # 3. The TUI path closes it.
        journal.close_tool_span(call_id, True, attrs={"closed": "tui"})
        assert key not in agent_events._OPEN_TOOL_SPANS
        # 4. The journaled end arrives AFTER close — it must not emit a
        #    second one-shot span, and a second TUI end is a no-op too.
        journal.record(
            "event/tool_end",
            "eval-primary",
            {"call_id": call_id, "tool_name": "write_file", "ok": True},
        )
        journal.close_tool_span(call_id, True)
    finally:
        clear_web_run()
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    tool_spans = [
        span
        for span in _spans(postgres_url, tenant_id, run_id)
        if span["tool_call_id"] == call_id
    ]
    assert len(tool_spans) == 1, tool_spans
    span = tool_spans[0]
    assert span["name"] == "tool.write_file"
    assert span["status"] == "ok"
    # The exported span kept the REAL (open-time) start, not the journaled
    # begin's later start.
    assert span["start_epoch"] == pytest.approx(real_start, abs=0.001)
    assert span["start_epoch"] <= t_journal_begin
    assert span["end_epoch"] >= t_journal_begin
    # The journaled begin's attrs merged into the open span; the TUI
    # open/close attrs survived too.
    assert span["attrs"]["journaled"] is True
    assert span["attrs"]["origin"] == "tui"
    assert span["attrs"]["closed"] == "tui"


def test_w7_c04_parent_lookup_tri_state(
    postgres_url: str, tmp_path: Path
) -> None:
    """``parent_for_run`` separates 'run predates persisted traceparents'
    (its ``run.created`` EXISTS without one — proven legacy, env fallback
    acceptable) from 'run.created NOT FOUND / lookup errored' — where the
    process-global env is NEVER consulted because it can name ANOTHER
    run's span.

    Run A's ``run.created`` exists but lacks a traceparent while the env
    holds run B's context, plus a lookup-error case: in both, the emitted
    span's parent/trace_id must not equal B's.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import telemetry
    from rxycode_worker.agent_events import RunJournal
    from rxycode_worker.supervisor import (
        _OPEN_RUN_SPANS,
        claim,
        commit_terminal,
    )

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 4)
    sess_a, sess_b, sess_c, sess_d = session_ids
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    memory = telemetry.InMemorySpanExporter()
    run_c = f"run-nocreated-{uuid.uuid4().hex[:12]}"
    try:
        # Run B is ordinary: create_run re-publishes its http span's
        # traceparent through the compat env channel.
        create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=sess_b,
            message="run B",
            target_id="local:c04trib",
            permission_profile="full_auto",
            request_id=f"req-trib-{uuid.uuid4().hex[:12]}",
        )
        ctx_b = telemetry.extract_env()
        assert ctx_b is not None
        # Runs A and D get a run.created event that EXISTS but carries no
        # traceparent — the shape of a pre-traceparent (legacy) run.
        accepted_a = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=sess_a,
            message="run A",
            target_id="local:c04tria",
            permission_profile="full_auto",
            request_id=f"req-tria-{uuid.uuid4().hex[:12]}",
        )
        accepted_d = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=sess_d,
            message="run D",
            target_id="local:c04trid",
            permission_profile="full_auto",
            request_id=f"req-trid-{uuid.uuid4().hex[:12]}",
        )
        engine = create_engine(postgres_url, poolclass=NullPool)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE run_events "
                        "SET payload = payload - 'traceparent' "
                        "WHERE run_id IN (:ra, :rd) "
                        "AND type = 'run.created'"
                    ),
                    {"ra": accepted_a.run_id, "rd": accepted_d.run_id},
                )
                # Run C: a runs row with NO run.created event at all.
                conn.execute(
                    text(
                        "INSERT INTO runs (id, tenant_id, session_id,"
                        " status, revision, lease_epoch, request_id,"
                        " input_digest, event_seq, target_id)"
                        " VALUES (:id, :tid, :sid, 'pending', 0, 0, :req,"
                        " '', 0, 'local:c04tric')"
                    ),
                    {
                        "id": run_c,
                        "tid": tenant_id,
                        "sid": sess_c,
                        "req": f"req-tric-{uuid.uuid4().hex[:12]}",
                    },
                )
        finally:
            engine.dispose()
        # The process-global env provably holds run B's context — the
        # stale foreign value that must never cross-parent run A/C.
        telemetry.inject_env(ctx_b)

        def _journal(run_id: str, url: str = postgres_url) -> RunJournal:
            journal = RunJournal(url, tenant_id, run_id)
            journal._tracer = telemetry.Tracer(memory, service="c04-tri")
            return journal

        # -- RunJournal path ---------------------------------------------
        # Proven-legacy run D: the env channel is the sanctioned last
        # resort, so this span legitimately parents under B.
        journal_d = _journal(accepted_d.run_id)
        journal_d.open_tool_span("call-legacy-d", "bash")
        journal_d.close_tool_span("call-legacy-d", True)
        # Lookup ERROR (unreachable URL): env must not be consulted — the
        # span is emitted unparented instead of inheriting B's context.
        journal_bad = _journal(
            accepted_a.run_id,
            url="postgresql+psycopg://postgres@127.0.0.1:1/none",
        )
        journal_bad.open_tool_span("call-badurl", "bash")
        journal_bad.close_tool_span("call-badurl", True)
        # run.created NOT FOUND: env must not be consulted either.
        journal_x = _journal(f"run-missing-{uuid.uuid4().hex[:8]}")
        journal_x.open_tool_span("call-missing", "bash")
        journal_x.close_tool_span("call-missing", True)

        # -- claim path (worker.run span) ---------------------------------
        # Run A: run.created exists w/o traceparent — env=B ignored.
        epoch_a = claim(
            postgres_url, accepted_a.run_id, worker_id, ttl_seconds=600
        )
        assert epoch_a is not None
        worker_a = _OPEN_RUN_SPANS[accepted_a.run_id][1].context
        assert worker_a.trace_id != ctx_b.trace_id
        assert worker_a.parent_span_id != ctx_b.span_id
        # Run C: no run.created at all — env=B ignored as well.
        epoch_c = claim(postgres_url, run_c, worker_id, ttl_seconds=600)
        assert epoch_c is not None
        worker_c = _OPEN_RUN_SPANS[run_c][1].context
        assert worker_c.trace_id != ctx_b.trace_id
        assert worker_c.parent_span_id == ""
        commit_terminal(
            postgres_url, accepted_a.run_id, worker_id, epoch_a, "succeeded"
        )
        commit_terminal(postgres_url, run_c, worker_id, epoch_c, "succeeded")
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    by_call = {span["tool_call_id"]: span for span in memory.spans}
    assert set(by_call) == {"call-legacy-d", "call-badurl", "call-missing"}
    legacy = by_call["call-legacy-d"]
    assert legacy["trace_id"] == ctx_b.trace_id
    assert legacy["parent_span_id"] == ctx_b.span_id
    for key in ("call-badurl", "call-missing"):
        span = by_call[key]
        assert span["trace_id"] != ctx_b.trace_id
        # Unparented — the env fallback was NOT consulted.
        assert span["parent_span_id"] == ""
    # The persisted worker.run spans agree: neither cross-parented to B.
    for run_id in (accepted_a.run_id, run_c):
        worker = next(
            span
            for span in _spans(postgres_url, tenant_id, run_id)
            if span["name"] == "worker.run"
        )
        assert worker["trace_id"] != ctx_b.trace_id
        assert worker["parent_span_id"] != ctx_b.span_id


# ---------------------------------------------------------------------------
# Audit-r4 regressions
# ---------------------------------------------------------------------------


def test_w7_c04_terminal_sweep_unclosed_spans(
    postgres_url: str, tmp_path: Path
) -> None:
    """A FAILED agent that never journals its close no longer leaks the
    span: ``commit_terminal`` sweeps still-open agent/tool spans for the
    run BEFORE ending ``worker.run`` — exported inside the same terminal
    transaction, with the mapped terminal status and ``unclosed=True`` —
    and the registries no longer hold them.

    Reproduces the audit probe: ``AgentTask._run_main`` moves to FAILED
    with no ``event/agent_failed`` event, so ``_OPEN_AGENT_SPANS`` kept
    the entry forever and no agent span was ever exported.
    """
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import agent_events
    from rxycode_worker.agent_events import RunJournal
    from rxycode_worker.supervisor import claim, commit_terminal

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 2)
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    run_ids: list[str] = []
    try:
        # Run 1 — FAILED: agent span open (+ a tool span under it), then
        # the agent task fails: NO event/agent_failed, NO tool_end —
        # exactly the gap that leaked the registry entry.
        accepted = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_ids[0],
            message="sweep failed run",
            target_id="local:c04sw1",
            permission_profile="full_auto",
            request_id=f"req-sw1-{uuid.uuid4().hex[:12]}",
        )
        run_id = accepted.run_id
        run_ids.append(run_id)
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None
        journal = RunJournal(postgres_url, tenant_id, run_id)
        journal.record("event/agent_started", "eval-primary", {})
        journal.record(
            "event/tool_begin",
            "eval-primary",
            {"call_id": "call-sweep-1", "tool_name": "bash"},
        )
        assert (run_id, "eval-primary") in agent_events._OPEN_AGENT_SPANS
        commit_terminal(postgres_url, run_id, worker_id, epoch, "failed")
        # The sweep ran inside the terminal close — registries are empty.
        assert (run_id, "eval-primary") not in agent_events._OPEN_AGENT_SPANS
        assert (run_id, "call-sweep-1") not in agent_events._OPEN_TOOL_SPANS

        # Run 2 — SUCCEEDED but an agent span was still open: an anomaly,
        # honestly exported as ok + unclosed rather than dropped.
        accepted2 = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_ids[1],
            message="sweep succeeded run",
            target_id="local:c04sw2",
            permission_profile="full_auto",
            request_id=f"req-sw2-{uuid.uuid4().hex[:12]}",
        )
        run2 = accepted2.run_id
        run_ids.append(run2)
        epoch2 = claim(postgres_url, run2, worker_id, ttl_seconds=600)
        assert epoch2 is not None
        journal2 = RunJournal(postgres_url, tenant_id, run2)
        journal2.record("event/agent_started", "eval-second", {})
        commit_terminal(postgres_url, run2, worker_id, epoch2, "succeeded")
        assert (run2, "eval-second") not in agent_events._OPEN_AGENT_SPANS
    finally:
        for rid in run_ids:
            agent_events.sweep_open_spans(rid, "error")  # leftover cleanup
        agent_events._BOUND_AGENT_SPAN.set(None)
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    # Run 1: swept children export BEFORE the worker.run they parent under.
    span_events = [
        event
        for event in _events(postgres_url, tenant_id, run_id)
        if event["type"] == "telemetry.span"
    ]
    names = [event["payload"]["name"] for event in span_events]
    assert names.index("tool.bash") < names.index("graph.agent.eval-primary")
    assert names.index("graph.agent.eval-primary") < names.index("worker.run")
    by_name = {event["payload"]["name"]: event["payload"] for event in span_events}
    agent = by_name["graph.agent.eval-primary"]
    tool = by_name["tool.bash"]
    worker = by_name["worker.run"]
    assert agent["status"] == "error"  # failed terminal -> error
    assert agent["attrs"]["unclosed"] is True
    assert agent["attrs"]["run.terminal_status"] == "failed"
    assert tool["status"] == "error"
    assert tool["attrs"]["unclosed"] is True
    # The recorded parent chain survived the sweep.
    assert tool["parent_span_id"] == agent["span_id"]
    assert agent["parent_span_id"] == worker["span_id"]
    assert worker["status"] == "error"

    # Run 2: succeeded -> mapped "ok" but still flagged unclosed.
    spans2 = {s["name"]: s for s in _spans(postgres_url, tenant_id, run2)}
    agent2 = spans2["graph.agent.eval-second"]
    assert agent2["status"] == "ok"
    assert agent2["attrs"]["unclosed"] is True
    assert agent2["attrs"]["run.terminal_status"] == "succeeded"


def test_w7_c04_agent_scoped_tool_parenting(
    postgres_url: str, tmp_path: Path
) -> None:
    """Concurrent agents no longer cross-parent tool spans.

    (a) A journaled ``tool_begin`` carries its agent_id and parents under
    THAT agent's open span — never the run's latest.  (b) The TUI hook
    path carries no agent_id: it resolves through the ContextVar bound
    when the agent span opened in the executing context, so a tool span
    created inside agent A's context parents under A while agent B — the
    run's most-recently-opened span — is unaffected.  With no bound agent
    the parent is the run's ``worker.run`` span, never a guessed sibling.
    """
    import contextvars

    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker import agent_events, telemetry
    from rxycode_worker.agent_events import RunJournal
    from rxycode_worker.supervisor import _OPEN_RUN_SPANS, claim, commit_terminal

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    memory = telemetry.InMemorySpanExporter()
    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=session_ids[0],
        message="concurrent agents",
        target_id="local:c04conc",
        permission_profile="full_auto",
        request_id=f"req-conc-{uuid.uuid4().hex[:12]}",
    )
    run_id = accepted.run_id
    try:
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None
        worker_ctx = _OPEN_RUN_SPANS[run_id][1].context
        journal = RunJournal(postgres_url, tenant_id, run_id)
        journal._tracer = telemetry.Tracer(memory, service="c04-scope")

        journal.record("event/agent_started", "agent-a", {})
        ctx_a = contextvars.copy_context()  # executing context bound to A
        journal.record("event/agent_started", "agent-b", {})
        ctx_b = contextvars.copy_context()  # executing context bound to B
        span_a = agent_events._OPEN_AGENT_SPANS[(run_id, "agent-a")][1]
        span_b = agent_events._OPEN_AGENT_SPANS[(run_id, "agent-b")][1]
        # The ambient context here is bound to B (opened most recently) —
        # exactly the state that used to cross-parent A's tools under B.

        # (a) The journaled tool_begin for A — the explicit agent_id wins.
        journal.record(
            "event/tool_begin",
            "agent-a",
            {"call_id": "call-a-j", "tool_name": "bash"},
        )
        # (b) TUI hook path inside each agent's bound executing context.
        ctx_a.run(journal.open_tool_span, "call-a-tui", "write_file")
        ctx_b.run(journal.open_tool_span, "call-b-tui", "read_file")
        # No bound agent at all: the run's worker span is the parent.
        contextvars.Context().run(journal.open_tool_span, "call-none", "ls")

        parent_of = {
            key[1]: pair[1].context.parent_span_id
            for key, pair in agent_events._OPEN_TOOL_SPANS.items()
            if key[0] == run_id
        }
        assert parent_of["call-a-j"] == span_a.context.span_id
        assert parent_of["call-a-tui"] == span_a.context.span_id
        assert parent_of["call-b-tui"] == span_b.context.span_id
        assert parent_of["call-none"] == worker_ctx.span_id
        assert parent_of["call-none"] not in {
            span_a.context.span_id,
            span_b.context.span_id,
        }

        # Close A's tool and A itself inside A's own context; B's context
        # stays bound to B — a new TUI-path tool still parents under B.
        journal.record(
            "event/tool_end",
            "agent-a",
            {"call_id": "call-a-j", "tool_name": "bash", "ok": True},
        )
        ctx_a.run(journal.close_tool_span, "call-a-tui", True)
        ctx_a.run(
            journal.record, "event/agent_done", "agent-a", {"tokens_used": 1}
        )
        ctx_b.run(journal.open_tool_span, "call-b-tui2", "grep")
        assert (
            agent_events._OPEN_TOOL_SPANS[(run_id, "call-b-tui2")][1]
            .context.parent_span_id
            == span_b.context.span_id
        )
        # …while A's own context — its agent span now closed — falls back
        # to the run's worker span rather than the stale closed binding.
        ctx_a.run(journal.open_tool_span, "call-a-late", "ls")
        assert (
            agent_events._OPEN_TOOL_SPANS[(run_id, "call-a-late")][1]
            .context.parent_span_id
            == worker_ctx.span_id
        )

        ctx_b.run(journal.close_tool_span, "call-b-tui", True)
        ctx_b.run(journal.close_tool_span, "call-b-tui2", True)
        ctx_a.run(journal.close_tool_span, "call-a-late", True)
        contextvars.Context().run(journal.close_tool_span, "call-none", True)
        ctx_b.run(
            journal.record, "event/agent_done", "agent-b", {"tokens_used": 1}
        )
        commit_terminal(postgres_url, run_id, worker_id, epoch, "succeeded")
    finally:
        for registry in (
            agent_events._OPEN_TOOL_SPANS,
            agent_events._OPEN_AGENT_SPANS,
        ):
            for key in [key for key in registry if key[0] == run_id]:
                registry.pop(key, None)
        agent_events._BOUND_AGENT_SPAN.set(None)
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    # The exported payloads carry the same honest parentage.
    by_call = {
        span["tool_call_id"]: span
        for span in memory.spans
        if span.get("tool_call_id")
    }
    assert by_call["call-a-tui"]["parent_span_id"] == span_a.context.span_id
    assert by_call["call-b-tui"]["parent_span_id"] == span_b.context.span_id
    assert by_call["call-none"]["parent_span_id"] == worker_ctx.span_id
    names = {span["name"] for span in memory.spans}
    assert "graph.agent.agent-a" in names
    assert "graph.agent.agent-b" in names


def test_w7_c04_post_terminal_retry_elapsed(
    postgres_url: str, tmp_path: Path
) -> None:
    """An idempotent ``create_run`` retry exports its http span onto the
    ORIGINAL run — post-terminal telemetry — but ``elapsed_ms`` stays
    bounded by the run's terminal boundary (the worker.run span's own
    end): the retry is listed under ``post_terminal``, not folded into
    the run's elapsed envelope.

    Regression: a 120ms run reported 60010ms after a same-request_id
    retry landed 60s later — the envelope counted a span STARTED after
    the run ended.
    """
    from rxycode_server import metrics
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.runs.service import create_run
    from rxycode_worker.supervisor import claim, commit_terminal

    upgrade_head(postgres_url)
    tenant_id, session_ids = _seed_tenant_sessions(postgres_url, 1)
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    request_id = f"req-r4-{uuid.uuid4().hex[:12]}"
    try:
        accepted = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_ids[0],
            message="run with idempotent retry",
            target_id="local:c04r4",
            permission_profile="full_auto",
            request_id=request_id,
        )
        run_id = accepted.run_id
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None
        commit_terminal(postgres_url, run_id, worker_id, epoch, "succeeded")
        before = metrics.run_trace_summary(
            postgres_url, tenant_id=tenant_id, run_id=run_id
        )
        assert before["code"] is None
        assert before["post_terminal"] == []
        boundary = before["terminal_boundary_epoch"]
        assert boundary and boundary > 0

        time.sleep(0.05)  # a measurable gap past the terminal boundary
        # Idempotent retry: same request_id + same inputs -> the existing
        # run, and a SECOND http span lands on its event log.
        retried = create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id=session_ids[0],
            message="run with idempotent retry",
            target_id="local:c04r4",
            permission_profile="full_auto",
            request_id=request_id,
        )
        assert retried.run_id == run_id
    finally:
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    spans = _spans(postgres_url, tenant_id, run_id)
    http_spans = [
        span for span in spans if span["name"] == "http POST /api/v1/runs"
    ]
    assert len(http_spans) == 2
    retry = max(http_spans, key=lambda span: float(span["start_epoch"]))
    assert retry["attrs"].get("run.idempotent_retry") is True
    assert float(retry["start_epoch"]) > boundary

    summary = metrics.run_trace_summary(
        postgres_url, tenant_id=tenant_id, run_id=run_id
    )
    assert summary["code"] is None
    # The retry span is observable — exported, marked, listed — but it
    # cannot stretch the run's elapsed envelope past the boundary.
    assert summary["span_count"] == len(spans)
    assert len(summary["post_terminal"]) == 1
    post = summary["post_terminal"][0]
    assert post["span_id"] == retry["span_id"]
    assert float(post["start_epoch"]) > boundary
    assert summary["elapsed_ms"] == pytest.approx(
        before["elapsed_ms"], abs=0.001
    )
    # …and the run's primary trace is still its own execution window —
    # the retry's fresh trace_id does not claim it.
    assert summary["trace_id"] == before["trace_id"]
    assert summary["trace_ids"] == before["trace_ids"]
