"""WEB-W2-C04. A lost Redis notify still delivers the committed seq, and disconnect does not cancel."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.events.outbox import heartbeat_catchup
from rxycode_server.events.sse import follow_after_subscribe
from rxycode_server.events.store import append_event
from rxycode_server.persistence.migrate import upgrade_head
from rxycode_server.persistence.models import Organization, Project, SessionRow, User
from rxycode_server.runs.service import create_run


def _run(url: str) -> tuple[str, str]:
    upgrade_head(url)
    engine = create_engine(url)
    session_id = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(id="user-c04m", github_id="gh-c04m", kind="github"))
        db.add(Organization(id="org-c04m", tenant_id="tenant-c04m"))
        db.add(Project(id="project-c04m", tenant_id="tenant-c04m", name="app", repo_config={}))
        db.add(SessionRow(id=session_id, tenant_id="tenant-c04m", project_id="project-c04m", title="m"))
        db.commit()
    engine.dispose()
    created = create_run(
        url,
        tenant_id="tenant-c04m",
        session_id=session_id,
        message="follow",
        target_id="local:1",
        permission_profile="workspace-write",
        request_id="req-follow",
    )
    for seq in range(2, 43):
        append_event(
            url,
            tenant_id="tenant-c04m",
            run_id=created.run_id,
            event_type="assistant.delta",
            payload={"n": seq},
        )
    return "tenant-c04m", created.run_id


def test_w2_c04_integration(postgres_url: str):
    """seq 43 committed during the subscribe gap, and again after a lost notify, is delivered once."""
    tenant_id, run_id = _run(postgres_url)

    def during_gap() -> None:
        append_event(
            postgres_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="assistant.delta",
            payload={"n": 43, "gap": True},
        )

    followed = follow_after_subscribe(
        postgres_url,
        tenant_id=tenant_id,
        run_id=run_id,
        after_seq=42,
        during_gap=during_gap,
    )
    assert [item["seq"] for item in followed] == [43]
    again = heartbeat_catchup(
        postgres_url,
        tenant_id=tenant_id,
        run_id=run_id,
        after_seq=43,
    )
    assert again == []
    engine = create_engine(postgres_url)
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM runs WHERE id = :id"),
            {"id": run_id},
        ).scalar()
        outbox = conn.execute(
            text(
                "SELECT count(*) FROM outbox o JOIN run_events e ON e.event_id = o.event_id "
                "WHERE e.run_id = :id AND e.seq = 43"
            ),
            {"id": run_id},
        ).scalar()
    engine.dispose()
    assert status == "pending"
    assert outbox == 1
