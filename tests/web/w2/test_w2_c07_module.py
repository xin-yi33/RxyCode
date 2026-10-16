"""WEB-W2-C07. Replaying a terminal usage event does not charge the run twice."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SERVER = REPO / "packages" / "rxycode-server" / "src"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from rxycode_server.persistence.migrate import upgrade_head  # noqa: E402
from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Project,
    SessionRow,
    UsageRecord,
    User,
)
from rxycode_server.runs.service import create_run  # noqa: E402
from rxycode_server.usage.service import record_terminal_usage  # noqa: E402


def test_w2_c07_integration(postgres_url: str):
    """The same terminal usage payload records one ledger row and one amount."""
    upgrade_head(postgres_url)
    engine = create_engine(postgres_url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c07u", github_id="gh-c07u", kind="github"))
        db.add(Organization(id="org-c07u", tenant_id="tenant-c07u"))
        db.add(Project(id="project-c07u", tenant_id="tenant-c07u", name="app", repo_config={}))
        db.add(
            SessionRow(
                id=session_id,
                tenant_id="tenant-c07u",
                project_id="project-c07u",
                title="cost",
            )
        )
        db.commit()
    engine.dispose()
    created = create_run(
        postgres_url,
        tenant_id="tenant-c07u",
        session_id=session_id,
        message="bill once",
        target_id="local:c07",
        permission_profile="workspace-write",
        request_id="req-c07-usage",
    )
    payload = {
        "tenant_id": "tenant-c07u",
        "run_id": created.run_id,
        "model_id": "gpt-test",
        "price_version": "2026-10",
        "tokens": 1200,
        "event_id": "evt-terminal-1",
    }
    first = record_terminal_usage(postgres_url, **payload)
    second = record_terminal_usage(postgres_url, **payload)
    inflated = record_terminal_usage(postgres_url, **{**payload, "tokens": 99999})
    assert second["id"] == first["id"]
    assert inflated["id"] == first["id"]
    assert second["amount"] == first["amount"]
    assert inflated["tokens"] == first["tokens"]
    assert first["price_version"] == "2026-10"
    assert first["model_id"] == "gpt-test"
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        count, total = db.execute(
            select(func.count(UsageRecord.id), func.sum(UsageRecord.tokens)).where(
                UsageRecord.run_id == created.run_id
            )
        ).one()
    engine.dispose()
    assert count == 1
    assert int(total) == 1200
