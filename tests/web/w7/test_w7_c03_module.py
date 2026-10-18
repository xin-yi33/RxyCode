"""WEB-W7-C03. A real web run leaves durable evidence the report can audit.

The harness executes one task through the real durable-run spine —
``create_run`` -> worker ``claim`` -> journaled ``event/agent_*`` lifecycle ->
``record_terminal_usage`` -> ``commit_terminal`` — against the shared
PostgreSQL container. The prompt driver is a stub (no LLM), so the test is
deterministic: one task whose checks pass, one designed-to-fail oracle, and
one task that records an abnormally high token count, proving both the failure
denominator and the cost ledger surface honestly.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().resolve().parents[3]
RUN_PY = REPO / "evals" / "web" / "run.py"
REPORT_PY = REPO / "evals" / "web" / "report.py"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
for _entry in (str(_SERVER), str(_WORKER)):
    if _entry not in __import__("sys").path:
        __import__("sys").path.insert(0, _entry)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass string annotations resolve through sys.modules[cls.__module__]
    # — register before exec or dataclasses crashes on Optional[...] fields.
    __import__("sys").modules[name] = module
    spec.loader.exec_module(module)
    return module


web_run = _load_module("w7c03_web_run", RUN_PY)
web_report = _load_module("w7c03_web_report", REPORT_PY)


def _task(task_id: str, pattern: str, *, expect: str = "pass") -> object:
    return web_run.WebEvalTask.from_dict(
        {
            "task_id": task_id,
            "category": "coding",
            "prompt": f"create answer.txt containing the marker for {task_id}",
            "checks": [
                {"type": "file_exists", "path": "answer.txt"},
                {"type": "file_contains", "path": "answer.txt", "pattern": pattern},
            ],
            "source_commit": "w7c03-module",
            "expect": expect,
        }
    )


def _events(database_url: str, tenant_id: str, run_id: str) -> list[dict]:
    from rxycode_server.events.store import replay

    return list(replay(database_url, tenant_id=tenant_id, run_id=run_id, after_seq=0)["events"])


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


def _run_row(database_url: str, run_id: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Run

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            return db.get(Run, run_id)
    finally:
        engine.dispose()


def test_w7_c03_integration(postgres_url: str, tmp_path: Path) -> None:
    """Failure lands in the denominator and abnormal cost reaches the report."""
    from rxycode_server.persistence.migrate import upgrade_head
    from rxycode_server.usage.service import record_terminal_usage

    upgrade_head(postgres_url)
    org = web_run.seed_eval_tenant(postgres_url, "w7c03mod")
    nonce = uuid.uuid4().hex[:8]

    pass_task = _task("w7c03mod-pass", "present-marker")
    fail_task = _task("w7c03mod-fail", "never-written-sentinel", expect="fail")
    costly_task = _task("w7c03mod-costly", "present-marker")

    async def _pass_driver(ctx: object) -> str:
        Path(ctx.workdir, "answer.txt").write_text("present-marker", encoding="utf-8")
        ctx.runtime.record_token_usage(ctx.agent_id, 1234)
        return "wrote answer.txt"

    async def _fail_driver(ctx: object) -> str:
        Path(ctx.workdir, "answer.txt").write_text("present-marker", encoding="utf-8")
        ctx.runtime.record_token_usage(ctx.agent_id, 77)
        return "wrote answer.txt"

    async def _costly_driver(ctx: object) -> str:
        Path(ctx.workdir, "answer.txt").write_text("present-marker", encoding="utf-8")
        ctx.runtime.record_token_usage(ctx.agent_id, 9_876_543)
        return "wrote answer.txt"

    async def _drive() -> list[dict]:
        records = []
        for task, driver in (
            (pass_task, _pass_driver),
            (fail_task, _fail_driver),
            (costly_task, _costly_driver),
        ):
            workdir = tmp_path / task.task_id
            workdir.mkdir(parents=True)
            records.append(
                await web_run.run_web_task(
                    database_url=postgres_url,
                    org=org,
                    task=task,
                    workdir=workdir,
                    cell="web-solo",
                    model="eval-stub",
                    task_timeout=120,
                    request_nonce=nonce,
                    prompt_driver=driver,
                )
            )
        return records

    records = asyncio.run(_drive())
    by_id = {record["task_id"]: record for record in records}

    # The passing task: durable lifecycle + usage ledger evidence.
    passing = by_id["w7c03mod-pass"]
    assert passing["status"] == "passed", passing
    assert passing["token_usage"]["total"] == 1234
    assert passing["cost"]["amount"] == "0.00246800"
    assert passing["cost"]["source"] == "usage_records"
    assert passing["run_id"]

    events = _events(postgres_url, org["tenant_id"], passing["run_id"])
    kinds = [event["type"] for event in events]
    assert "run.created" in kinds
    assert "event/agent_started" in kinds
    assert "event/agent_done" in kinds
    done = next(event for event in events if event["type"] == "event/agent_done")
    assert int(done["payload"]["tokens_used"]) == 1234
    assert "usage.updated" in kinds
    assert "eval.checks" in kinds
    verdict = next(event for event in events if event["type"] == "eval.checks")
    assert verdict["payload"]["status"] == "passed"
    assert passing["trace"]["agent_done_seq"] == done["seq"]
    row = _run_row(postgres_url, passing["run_id"])
    assert row is not None and row.status == "succeeded"

    usage = _usage_row(postgres_url, passing["run_id"])
    assert usage is not None and int(usage.tokens) == 1234

    # The designed-to-fail oracle: record shows failed, durable verdict says failed,
    # and the run still reached a terminal state with cost evidence.
    failing = by_id["w7c03mod-fail"]
    assert failing["status"] == "failed", failing
    assert failing["expect"] == "fail"
    assert failing["expected_failure"] is True
    failing_events = _events(postgres_url, org["tenant_id"], failing["run_id"])
    failing_verdict = next(
        event for event in failing_events if event["type"] == "eval.checks"
    )
    assert failing_verdict["payload"]["status"] == "failed"
    failing_usage = _usage_row(postgres_url, failing["run_id"])
    assert failing_usage is not None and int(failing_usage.tokens) == 77
    assert failing_usage.amount == "0.00015400"

    # The abnormal cost task is preserved end-to-end: run event, usage row,
    # record cost — 9,876,543 tokens at USD 0.000002/token = 19.75308600.
    costly = by_id["w7c03mod-costly"]
    assert costly["status"] == "passed"
    assert costly["token_usage"]["total"] == 9_876_543
    assert costly["cost"]["amount"] == "19.75308600"
    costly_usage = _usage_row(postgres_url, costly["run_id"])
    assert costly_usage is not None
    assert Decimal(costly_usage.amount) == Decimal("19.75308600")

    # record_terminal_usage is idempotent: a replayed call returns the same row.
    again = record_terminal_usage(
        postgres_url,
        tenant_id=org["tenant_id"],
        run_id=costly["run_id"],
        model_id="eval-stub",
        price_version=web_run.PRICE_VERSION,
        tokens=9_876_543,
        event_id=uuid.uuid4().hex,
    )
    assert again["id"] == costly_usage.id
    assert again["amount"] == "19.75308600"

    # The report counts the failure in the denominator and surfaces the
    # abnormal cost row instead of hiding it.
    manifest = web_run.build_manifest(
        taskset_path=REPO / "evals" / "web" / "taskset.jsonl",
        tasks=web_run.load_taskset(REPO / "evals" / "web" / "taskset.jsonl"),
        cells=["web-solo"],
        budget=0,
        model="eval-stub",
        database_url=postgres_url,
    )
    results = {
        "schema": "evals-web-results/v1",
        "cells": ["web-solo"],
        "blocked_cells": {},
        "records": records,
        "manifest": manifest,
    }
    report = web_report.build_report(results)
    cell = report["cells"]["web-solo"]
    assert cell["n"] == 3
    assert cell["attempted"] == 3
    assert cell["passed"] == 2
    assert cell["failed"] == 1
    assert cell["success_rate"] == 2 / 3
    abnormal = cell["cost"]["abnormal"]
    assert abnormal and abnormal[0]["task_id"] == "w7c03mod-costly"
    assert abnormal[0]["amount"] == "19.75308600"

    rendered = web_report.render_markdown(report, results, manifest)
    assert "w7c03mod-costly" in rendered
    assert "19.75308600" in rendered

    # No gate violations for an honest 3-record run at min_tasks=3: the
    # designed-to-fail task *did* fail, and nothing is missing.
    violations = web_report.gate_report(
        results, manifest=manifest, taskset_path=None, min_tasks=3
    )
    assert violations == [], violations
