"""WEB-W2-C01. Alembic upgrade creates the business constraints on PostgreSQL."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-server" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rxycode_server.persistence.migrate import downgrade_base, upgrade_head
from rxycode_server.persistence.models import (
    WEB_TABLES,
    Organization,
    Project,
    Run,
    SessionRow,
    User,
    apply_web_schema,
)


def _org(db: Session, tenant_id: str) -> None:
    db.add(User(id=f"user-{tenant_id}", github_id=f"gh-{tenant_id}", kind="github"))
    db.add(Organization(id=f"org-{tenant_id}", tenant_id=tenant_id))
    db.flush()


def test_w2_c01_contract(postgres_url: str, tmp_path: Path):
    """Upgrade an empty database, then downgrade without deleting a legacy directory."""
    legacy = tmp_path / "desktop-tasks"
    legacy.mkdir()
    (legacy / "tasks.json").write_text('{"tasks":{},"events":{}}', encoding="utf-8")
    upgrade_head(postgres_url)
    engine = create_engine(postgres_url)
    found = set(inspect(engine).get_table_names())
    assert set(WEB_TABLES) <= found
    uniques = {
        item["name"]
        for item in inspect(engine).get_unique_constraints("runs")
    }
    assert "uq_runs_tenant_request" in uniques
    indexes = {item["name"] for item in inspect(engine).get_indexes("runs")}
    assert "uq_runs_one_active_per_session" in indexes
    downgrade_base(postgres_url)
    assert "runs" not in set(inspect(engine).get_table_names())
    assert legacy.is_dir()
    assert (legacy / "tasks.json").is_file()
    with engine.connect() as conn:
        trans = conn.begin()
        apply_web_schema(conn)
        trans.rollback()
    assert "runs" not in set(inspect(engine).get_table_names())
    upgrade_head(postgres_url)
    encoded = postgres_url.replace("postgres@", "postgres:p%40ss@", 1)
    upgrade_head(encoded)


def test_w2_c01_negative(postgres_url: str):
    """The same tenant cannot create two runs with one request_id."""
    upgrade_head(postgres_url)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        _org(db, "tenant-a")
        db.add(Project(id="project-a", tenant_id="tenant-a", name="app", repo_config={}))
        db.add(SessionRow(id="session-a", tenant_id="tenant-a", project_id="project-a", title=""))
        db.add(
            Run(
                id="run-1",
                tenant_id="tenant-a",
                session_id="session-a",
                status="succeeded",
                request_id="req-1",
                revision=0,
                lease_epoch=0,
                input_digest="",
                target_id="",
            )
        )
        db.commit()
        db.add(
            Run(
                id="run-2",
                tenant_id="tenant-a",
                session_id="session-a",
                status="succeeded",
                request_id="req-1",
                revision=0,
                lease_epoch=0,
                input_digest="",
                target_id="",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(
            Run(
                id="run-active-1",
                tenant_id="tenant-a",
                session_id="session-a",
                status="running",
                request_id="req-active-1",
                revision=0,
                lease_epoch=0,
                input_digest="",
                target_id="",
            )
        )
        db.commit()
        db.add(
            Run(
                id="run-active-2",
                tenant_id="tenant-a",
                session_id="session-a",
                status="pending",
                request_id="req-active-2",
                revision=0,
                lease_epoch=0,
                input_digest="",
                target_id="",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM runs")).scalar()
    assert count == 2
