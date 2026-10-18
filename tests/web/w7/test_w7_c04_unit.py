"""WEB-W7-C04. OTel-convention spans correlate one run across layers.

Contract: a real cloud-mode run driven through the durable spine —
``create_run`` -> worker ``claim`` -> journaled ``event/agent_*`` ->
``record_terminal_usage`` -> ``commit_terminal`` — leaves ``telemetry.span``
rows in ``run_events`` under ONE W3C trace_id; HTTP-layer, worker-layer and
tool-layer spans each carry a real measured duration; the trace is
queryable by run_id; a foreign tenant reads nothing.

Negative: a secret string in a tool's stderr/attrs is masked before the
span is persisted — the raw secret never lands in the stored event payload.

Propagation: the server injects a W3C ``traceparent`` (32-hex trace_id,
16-hex span_id); the worker honors it as the remote parent; the tool/runner
span is parented correctly under the worker span.
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
    """One trace_id correlates server/worker/tool spans, each with duration."""
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
        publish_database_url,
        remember_web_run,
    )
    from rxycode_worker.supervisor import claim, commit_terminal
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    upgrade_head(postgres_url)
    app, owner, tenant_id, project_id, session_id = _provision_owner(postgres_url)
    exporter = telemetry.RunEventsSpanExporter(postgres_url, tenant_id)
    tracer = telemetry.Tracer(exporter, service="rxycode-web-c04")
    worker_id = f"w-c04-{uuid.uuid4().hex[:8]}"
    workdir = tmp_path / "c04-contract"
    workdir.mkdir(parents=True)
    message = "/solo write answer.txt with the marker"
    runtime_box: dict[str, object] = {}

    # -- HTTP layer: the real run-creation write inside a SERVER span -------
    http_span = tracer.start_span(
        "http POST /api/v1/runs",
        kind="server",
        attrs={
            "http.method": "POST",
            "http.route": "/api/v1/runs",
            # The full prompt is deliberately attached as an attr: the
            # sanitizer must drop the body and keep only safe metadata.
            "prompt": message,
            "message_len": len(message),
        },
    )
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
    http_span.run_id = run_id
    tracer.end_span(http_span)

    get_span = tracer.start_span(
        "http GET /api/v1/runs/{run_id}",
        kind="server",
        parent=http_span.context,
        run_id=run_id,
        attrs={"http.method": "GET"},
    )
    got = owner.get(f"/api/v1/runs/{run_id}")
    tracer.end_span(get_span, attrs={"http.status_code": got.status_code})
    assert got.status_code == 200
    assert got.json()["status"] == "pending"

    # -- Propagation: the server injects traceparent; the worker honors it --
    telemetry.inject_env(http_span.context)
    try:
        publish_database_url(postgres_url)
        remember_web_run(
            postgres_url, tenant_id, run_id, session_id=session_id
        )
        remote_parent = telemetry.extract_env()
        assert remote_parent is not None

        # -- Worker layer: claim + real agent lifecycle inside WORKER spans --
        claim_span = tracer.start_span(
            "worker.claim",
            kind="worker",
            parent=remote_parent,
            run_id=run_id,
            attrs={"worker.id": worker_id},
        )
        epoch = claim(postgres_url, run_id, worker_id, ttl_seconds=600)
        assert epoch is not None
        tracer.end_span(claim_span, attrs={"worker.epoch": epoch})

        agent_span = tracer.start_span(
            "graph.agent.eval-primary",
            kind="worker",
            parent=claim_span.context,
            run_id=run_id,
            attrs={
                "agent.id": "eval-primary",
                "model": "eval-stub",
                "price_version": PRICE_VERSION,
            },
        )

        async def _target(_task: str, checkpoint: object | None = None) -> str:
            runtime = runtime_box["runtime"]
            journal = ToolExecutionJournal(tmp_path / "tool-journal")
            attempt_id = new_attempt_id()
            call = journal.binding(attempt_id).next_call(
                "write_file", {"path": "answer.txt"}
            )
            # -- Tool layer: the real journaled tool call inside a TOOL span --
            tool_span = tracer.start_span(
                "tool.write_file",
                kind="tool",
                parent=agent_span.context,
                run_id=run_id,
                tool_call_id=call.key,
                attrs={"tool.name": "write_file", "attempt_id": attempt_id},
            )
            from rxycode_worker.supervisor import attempt_tool

            outcome = attempt_tool(
                journal,
                attempt_id,
                "write_file",
                {"path": "answer.txt"},
                lambda: Path(workdir, "answer.txt").write_text(
                    "present-marker", encoding="utf-8"
                ),
            )
            assert outcome["executed"] is True
            tracer.end_span(tool_span, attrs={"tool.executed": True})
            ctx = runtime.contexts["eval-primary"]
            ctx.record_cache(True)
            ctx.record_cache(False)
            runtime.record_token_usage("eval-primary", 1234)
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
        runtime = runtime_box["runtime"]
        session_cache = runtime._session_cache
        tracer.end_span(
            agent_span,
            attrs={
                "cache.hits": session_cache.hits,
                "cache.misses": session_cache.misses,
            },
        )

        # -- Finalize layer: verdict + ledger + terminal commit (SERVER) ----
        finalize_span = tracer.start_span(
            "server.run.finalize",
            kind="server",
            parent=http_span.context,
            run_id=run_id,
            attrs={"model": "eval-stub", "price_version": PRICE_VERSION},
        )
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
        tracer.end_span(finalize_span)
    finally:
        clear_web_run()
        os.environ.pop("RXYCODE_TRACEPARENT", None)

    assert usage["tokens"] == 1234
    assert usage["amount"] == "0.00246800"

    # -- Durable span rows: one trace_id, three layers, real durations ------
    spans = _spans(postgres_url, tenant_id, run_id)
    assert len(spans) >= 5, spans
    trace_ids = {span["trace_id"] for span in spans}
    assert trace_ids == {http_span.context.trace_id}
    assert len(http_span.context.trace_id) == 32
    by_name = {span["name"]: span for span in spans}
    for name in (
        "http POST /api/v1/runs",
        "http GET /api/v1/runs/{run_id}",
        "worker.claim",
        "graph.agent.eval-primary",
        "tool.write_file",
        "server.run.finalize",
    ):
        assert name in by_name, by_name
        span = by_name[name]
        assert span["duration_ms"] > 0, span
        assert span["status"] == "ok"
        assert len(span["span_id"]) == 16
        assert span["run_id"] == run_id

    # Parentage: http -> worker -> graph/agent -> tool (runner).
    tool_span = by_name["tool.write_file"]
    assert tool_span["parent_span_id"] == by_name["graph.agent.eval-primary"]["span_id"]
    assert (
        by_name["graph.agent.eval-primary"]["parent_span_id"]
        == by_name["worker.claim"]["span_id"]
    )
    assert by_name["worker.claim"]["parent_span_id"] == http_span.context.span_id
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
    assert summary["trace_id"] == http_span.context.trace_id
    assert summary["events_url"] == f"/api/v1/runs/{run_id}/events"
    assert summary["span_count"] == len(spans)
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
    # A fabricated-but-realistic secret (never a real key) in the tool's
    # stderr and in span attrs — the stored payload must mask both forms.
    api_secret = "sk-c04testsecret1234567890abcdef"
    password = "hunter2-super-secret"
    journal = ToolExecutionJournal(tmp_path / "neg-journal")
    attempt_id = new_attempt_id()
    call = journal.binding(attempt_id).next_call("bash", {"command": "deploy"})
    stderr = (
        f"fatal: authorization: bearer {api_secret} rejected; "
        f"deploy failed (password={password})"
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
    assert len(rows) == 1
    stored = json.dumps(rows[0].payload, ensure_ascii=False)
    assert api_secret not in stored
    assert password not in stored
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


def exporter_dropped(exporter) -> int:
    return int(getattr(exporter, "dropped", 0))
