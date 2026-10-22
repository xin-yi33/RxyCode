"""WEB-W6-C05. A schedule fires after the browser is gone and the run stays in the database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
from tests.support.pgurl import bun_path

BUN = bun_path()
_W6 = REPO / "tests" / "web" / "w6"
for _entry in (str(_SERVER), str(_WORKER), str(_W6)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from tests.support.pgurl import ensure_container, worker_url

_PG_BASE = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
ensure_container("rxy-w2c01-pg", 55432)
DATABASE = worker_url(_PG_BASE)


def test_w6_c05_integration(tmp_path: Path) -> None:
    """Closing the browser does not drop the scheduled run or its status notice."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.notifications.service import (
        create_web_schedule,
        fire_due_schedules,
        list_notifications,
    )
    from rxycode_server.persistence.models import Outbox, Run, RunEvent
    from rxycode_server.runs.service import load_run
    from rxycode_worker.supervisor import LeaseRejected, claim, commit_terminal
    from rxycode_server.usage.service import record_terminal_usage
    from test_w6_c05_unit import _get, _seed, _session, _wipe

    tenant = "ten-w6c05m-" + uuid.uuid4().hex[:8]
    ids = _seed(tenant)
    started = datetime(2026, 10, 16, 12, 0, 0)
    try:
        create_web_schedule(
            DATABASE,
            tenant_id=tenant,
            project_id=ids["project"],
            session_id=ids["session_a"],
            rule={"kind": "interval", "every": 1, "unit": "minutes"},
            now=started,
            notify=True,
            user_id="user-a",
        )
        fired = fire_due_schedules(DATABASE, now=started + timedelta(minutes=2))
        assert fired
        run_id = str(fired[0]["run_id"])
        engine = create_engine(DATABASE, poolclass=NullPool)
        try:
            with Session(engine) as db:
                row = db.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant))
                assert row is not None
                assert row.session_id == ids["session_a"]
                event = db.scalar(
                    select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.type == "run.created")
                )
                assert event is not None
                queued = db.scalar(select(Outbox).where(Outbox.event_id == event.event_id))
                assert queued is not None
                assert queued.dispatch_status == "pending"
            loaded = load_run(DATABASE, run_id)
            assert loaded["message"] == "scheduled run"
            assert loaded["permission_profile"] == "confirm"
            assert loaded["target_id"] == f"cloud:{tenant}:{ids['project']}"
            assert loaded["session_id"] == ids["session_a"]
        finally:
            engine.dispose()
        epoch = claim(DATABASE, run_id, "worker-c05")
        assert epoch is not None
        commit_terminal(DATABASE, run_id, "worker-c05", epoch, "succeeded")
        with pytest.raises(LeaseRejected):
            commit_terminal(DATABASE, run_id, "worker-c05", epoch, "succeeded")
        notes = list_notifications(_get(_session(tenant, ids["token"]), ids["token"]))
        matched = [item for item in notes["notifications"] if item["run_id"] == run_id]
        assert len(matched) == 1
        assert matched[0]["status"] == "succeeded"
        recorded = record_terminal_usage(
            DATABASE,
            tenant_id=tenant,
            run_id=ids["run_a"],
            model_id="model-a",
            price_version="2026-10",
            tokens=4,
            event_id="evt-page-" + ids["run_a"],
        )
        markup = _render_pages(int(recorded["tokens"]), str(recorded["amount"]))
        assert f'data-tokens="{recorded["tokens"]}"' in markup
        assert f'data-amount="{recorded["amount"]}"' in markup
        assert "data-notify" in markup
        assert "data-memory" in markup
        assert "<script>" not in markup
        assert "&lt;script&gt;" in markup
    finally:
        _wipe(tenant, ids)
        _wipe_run(run_id if "run_id" in locals() else "")


def _wipe_run(run_id: str) -> None:
    if not run_id:
        return
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import Outbox, Run, RunEvent

    engine = create_engine(DATABASE, poolclass=NullPool)
    try:
        with Session(engine) as db:
            event_ids = [row.event_id for row in db.query(RunEvent).filter(RunEvent.run_id == run_id).all()]
            if event_ids:
                db.query(Outbox).filter(Outbox.event_id.in_(event_ids)).delete(synchronize_session=False)
            db.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            db.execute(delete(Run).where(Run.id == run_id))
            db.commit()
    finally:
        engine.dispose()


def _render_pages(tokens: int, amount: str) -> str:
    if BUN is None:
        pytest.skip("bun is not installed")
    usage = REPO / "apps" / "web" / "src" / "features" / "usage" / "UsagePage.tsx"
    memory = REPO / "apps" / "web" / "src" / "features" / "memory" / "MemoryPage.tsx"
    schedule = REPO / "apps" / "web" / "src" / "features" / "schedule" / "SchedulePage.tsx"
    env = os.environ.copy()
    env["RXY_USAGE"] = str(usage)
    env["RXY_MEMORY"] = str(memory)
    env["RXY_SCHEDULE"] = str(schedule)
    env["RXY_TOKENS"] = str(tokens)
    env["RXY_AMOUNT"] = amount
    script = r"""
import { pathToFileURL } from "url"
const usage = await import(pathToFileURL(process.env.RXY_USAGE).href)
const memory = await import(pathToFileURL(process.env.RXY_MEMORY).href)
const schedule = await import(pathToFileURL(process.env.RXY_SCHEDULE).href)
const statement = {
  tokens: Number(process.env.RXY_TOKENS),
  amount: process.env.RXY_AMOUNT,
  lines: [{ model_id: "model-a", tokens: Number(process.env.RXY_TOKENS), amount: process.env.RXY_AMOUNT, cost_kind: "confirmed" }],
}
const html = [
  usage.usageMarkup(statement),
  memory.memoryMarkup([{ id: "mem-1", body: "<script>alert(1)</script>", project_id: "prj" }]),
  schedule.scheduleMarkup({ id: "sch-1", enabled: true, notify: true }),
].join("\n")
process.stdout.write(html)
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c05-")) / "pages.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [BUN, str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
        program.parent.rmdir()
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout
