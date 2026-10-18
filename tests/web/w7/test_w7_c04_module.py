"""WEB-W7-C04. The metrics summary reconciles billing, provider, and spans.

Two tasks run through the real durable web spine (``run_web_task``:
``create_run`` -> worker ``claim`` -> journaled ``event/agent_*`` ->
``eval.checks`` -> ``record_terminal_usage`` -> ``commit_terminal``) with a
stub prompt driver — one ordinary spend, one abnormal spend. The
``rxycode_server.metrics`` summaries must then:

* align per-run tokens+amount with the ``usage_records`` ledger AND with
  the provider's ``event/agent_done`` token_snapshot payload,
* surface the abnormal-cost run verbatim instead of averaging it away,
* expose the run's trace_id and per-layer span durations for the cost
  dashboard, with the model price version and cache statistics attached.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().resolve().parents[3]
RUN_PY = REPO / "evals" / "web" / "run.py"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _entry in (str(_SERVER), str(_WORKER)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


web_run = _load_module("w7c04_web_run", RUN_PY)


def _task(task_id: str, pattern: str) -> object:
    return web_run.WebEvalTask.from_dict(
        {
            "task_id": task_id,
            "category": "coding",
            "prompt": f"create answer.txt containing the marker for {task_id}",
            "checks": [
                {"type": "file_exists", "path": "answer.txt"},
                {"type": "file_contains", "path": "answer.txt", "pattern": pattern},
            ],
            "source_commit": "w7c04-module",
            "expect": "pass",
        }
    )


def _events(database_url: str, tenant_id: str, run_id: str) -> list[dict]:
    from rxycode_server.events.store import replay

    return list(
        replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)["events"]
    )


def _usage_row(database_url: str, run_id: str):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import UsageRecord

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            return db.scalars(
                select(UsageRecord).where(UsageRecord.run_id == run_id)
            ).one_or_none()
    finally:
        engine.dispose()


def test_w7_c04_integration(postgres_url: str, tmp_path: Path) -> None:
    """Ledger, provider snapshot, and spans reconcile per run; abnormal shows."""
    from rxycode_server import metrics
    from rxycode_server.notifications.service import usage_statement
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_worker import telemetry
    from rxycode_worker.supervisor import attempt_tool
    from RxyCode.RxyCode1_1_0.execution.tool_journal import (
        ToolExecutionJournal,
        new_attempt_id,
    )

    upgrade_head(postgres_url)
    org = web_run.seed_eval_tenant(postgres_url, "w7c04mod")
    tenant_id = org["tenant_id"]
    nonce = uuid.uuid4().hex[:8]
    exporter = telemetry.RunEventsSpanExporter(postgres_url, tenant_id)
    tracer = telemetry.Tracer(exporter, service="rxycode-web-c04-module")

    pass_task = _task("w7c04mod-pass", "present-marker")
    costly_task = _task("w7c04mod-costly", "present-marker")

    def _driver(tokens: int, tag: str):
        async def _run(ctx: object) -> str:
            Path(ctx.workdir, "answer.txt").write_text(
                "present-marker", encoding="utf-8"
            )
            agent_span = tracer.start_span(
                f"graph.agent.{ctx.agent_id}",
                kind="worker",
                parent=http_ctx[tag],
                run_id=ctx.run_id,
                attrs={
                    "agent.id": ctx.agent_id,
                    "model": "eval-stub",
                    "price_version": web_run.PRICE_VERSION,
                },
            )
            journal = ToolExecutionJournal(tmp_path / f"journal-{tag}")
            attempt_id = new_attempt_id()
            call = journal.binding(attempt_id).next_call(
                "write_file", {"path": "answer.txt"}
            )
            tool_span = tracer.start_span(
                "tool.write_file",
                kind="tool",
                parent=agent_span.context,
                run_id=ctx.run_id,
                tool_call_id=call.key,
                attrs={"tool.name": "write_file"},
            )
            outcome = attempt_tool(
                journal,
                attempt_id,
                "write_file",
                {"path": "answer.txt"},
                lambda: Path(ctx.workdir, "answer.txt").write_text(
                    "present-marker", encoding="utf-8"
                ),
            )
            tracer.end_span(tool_span, attrs={"tool.executed": outcome["executed"]})
            agent_ctx = ctx.runtime.contexts[ctx.agent_id]
            agent_ctx.record_cache(True)
            agent_ctx.record_cache(True)
            agent_ctx.record_cache(False)
            ctx.runtime.record_token_usage(ctx.agent_id, tokens)
            cache = ctx.runtime._session_cache
            tracer.end_span(
                agent_span,
                attrs={"cache.hits": cache.hits, "cache.misses": cache.misses},
            )
            return "wrote answer.txt"

        return _run

    # One HTTP-layer span per run, measured around the REAL durable spine
    # call; the run id is bound the moment create_run lands (spend_sink).
    http_ctx: dict[str, object] = {}

    async def _drive() -> list[dict]:
        records = []
        for task, tokens, tag in (
            (pass_task, 1234, "pass"),
            (costly_task, 9_876_543, "costly"),
        ):
            workdir = tmp_path / task.task_id
            workdir.mkdir(parents=True)
            server_span = tracer.start_span(
                "http POST /api/v1/runs",
                kind="server",
                attrs={"http.method": "POST", "http.route": "/api/v1/runs"},
            )
            http_ctx[tag] = server_span.context
            sink: dict[str, object] = {}
            try:
                record = await web_run.run_web_task(
                    database_url=postgres_url,
                    org=org,
                    task=task,
                    workdir=workdir,
                    cell="web-solo",
                    model="eval-stub",
                    task_timeout=120,
                    request_nonce=nonce,
                    prompt_driver=_driver(tokens, tag),
                    spend_sink=sink,
                )
            finally:
                server_span.run_id = str(sink.get("run_id") or "")
                tracer.end_span(
                    server_span,
                    attrs={"http.status_code": 202, "spine": "run_web_task"},
                )
            records.append(record)
        return records

    records = asyncio.run(_drive())
    by_id = {record["task_id"]: record for record in records}
    passing = by_id["w7c04mod-pass"]
    costly = by_id["w7c04mod-costly"]
    assert passing["status"] == "passed", passing
    assert costly["status"] == "passed", costly
    assert passing["token_usage"]["total"] == 1234
    assert costly["token_usage"]["total"] == 9_876_543
    assert exporter.dropped == 0

    # -- The summary aligns ledger <-> provider usage per run ----------------
    tenant_metrics = metrics.tenant_cost_metrics(postgres_url, tenant_id)
    assert tenant_metrics["tenant_id"] == tenant_id
    lines = {line["run_id"]: line for line in tenant_metrics["runs"]}
    assert set(lines) == {passing["run_id"], costly["run_id"]}

    for record, tokens, amount in (
        (passing, 1234, "0.00246800"),
        (costly, 9_876_543, "19.75308600"),
    ):
        run_id = record["run_id"]
        line = lines[run_id]
        # Ledger row is the source of truth for tokens+amount.
        row = _usage_row(postgres_url, run_id)
        assert row is not None
        assert int(row.tokens) == tokens
        assert row.amount == amount
        assert line["tokens"] == tokens
        assert line["amount"] == amount
        assert line["price_version"] == web_run.PRICE_VERSION
        assert line["cost_kind"] == "confirmed"
        # Provider usage = the event/agent_done token_snapshot payload.
        done = next(
            event
            for event in _events(postgres_url, tenant_id, run_id)
            if event["type"] == "event/agent_done"
        )
        assert int(done["payload"]["tokens_used"]) == tokens
        assert line["provider_tokens"] == tokens
        assert line["aligned"] is True
        # The per-run trace summary exposes the same picture.
        summary = metrics.run_trace_summary(
            postgres_url, tenant_id=tenant_id, run_id=run_id
        )
        assert summary["code"] is None
        assert len(summary["trace_id"]) == 32
        span_names = {span["name"] for span in summary["spans"]}
        assert "http POST /api/v1/runs" in span_names
        assert "graph.agent.eval-primary" in span_names
        assert "tool.write_file" in span_names
        assert summary["layers"]["server"]["duration_ms"] > 0
        assert summary["layers"]["tool"]["count"] == 1
        tool = next(
            span for span in summary["spans"] if span["name"] == "tool.write_file"
        )
        assert tool["tool_call_id"].startswith("call_")
        assert tool["parent_span_id"] == next(
            span["span_id"]
            for span in summary["spans"]
            if span["name"] == "graph.agent.eval-primary"
        )
        assert summary["ledger"]["tokens"] == tokens
        assert summary["provider"]["tokens_used"] == tokens
        assert summary["aligned"] is True
        assert summary["cache"]["hits"] == 2
        assert summary["cache"]["misses"] == 1
        assert summary["cache"]["hit_rate"] == 2 / 3

    # -- Abnormal cost is surfaced, never averaged into silence --------------
    assert lines[passing["run_id"]]["abnormal"] is False
    assert lines[costly["run_id"]]["abnormal"] is True
    abnormal = tenant_metrics["abnormal"]
    assert [item["run_id"] for item in abnormal] == [costly["run_id"]]
    assert abnormal[0]["amount"] == "19.75308600"
    # Totals still carry every cent of real spend — the abnormal row is
    # both counted in totals AND surfaced verbatim.
    assert tenant_metrics["totals"]["tokens"] == 1234 + 9_876_543
    assert Decimal(tenant_metrics["totals"]["amount"]) == Decimal("19.75555400")
    assert tenant_metrics["mismatches"] == []

    # -- The existing usage statement agrees with the metrics rollup ---------
    statement = usage_statement(postgres_url, tenant_id)
    assert statement["tokens"] == 1234 + 9_876_543
    assert Decimal(str(statement["amount"])) == Decimal("19.75555400")
    statement_lines = {line["run_id"]: line for line in statement["lines"]}
    assert Decimal(statement_lines[costly["run_id"]]["amount"]) == Decimal(
        "19.75308600"
    )

    # -- Trace-id evidence: one real trace_id with correlated spans ----------
    summary = metrics.run_trace_summary(
        postgres_url, tenant_id=tenant_id, run_id=costly["run_id"]
    )
    dump = {
        "run_id": costly["run_id"],
        "trace_id": summary["trace_id"],
        "spans": summary["spans"],
        "ledger": summary["ledger"],
        "provider": summary["provider"],
        "cache": summary["cache"],
        "abnormal": abnormal,
    }
    evidence = tmp_path / "trace_dump.json"
    evidence.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    assert summary["trace_id"] in evidence.read_text(encoding="utf-8")
