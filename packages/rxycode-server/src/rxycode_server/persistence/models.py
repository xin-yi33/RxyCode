"""SQLAlchemy 2 models for the web business database.

Cloud users are rows here, not JSON files. Every business row carries tenant_id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="local")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32))
    organization: Mapped[Organization] = relationship(
        primaryjoin="Membership.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )
    user: Mapped[User] = relationship()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    name: Mapped[str] = mapped_column(String(200))
    repo_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    organization: Mapped[Organization] = relationship(
        primaryjoin="Project.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(200), default="")
    organization: Mapped[Organization] = relationship(
        primaryjoin="SessionRow.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )
    project: Mapped[Project] = relationship()


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_runs_tenant_request"),
        Index(
            "uq_runs_one_active_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'leased')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    status: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(128), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    organization: Mapped[Organization] = relationship(
        primaryjoin="Run.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )
    session: Mapped[SessionRow] = relationship()


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[Run] = relationship()
    organization: Mapped[Organization] = relationship(
        primaryjoin="RunEvent.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("run_events.event_id"))
    dispatch_status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    event: Mapped[RunEvent] = relationship()


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    call_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    organization: Mapped[Organization] = relationship(
        primaryjoin="Approval.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )
    run: Mapped[Run] = relationship()


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (UniqueConstraint("run_id", "call_id", name="uq_tool_invocations_run_call"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    call_id: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(64), default="")
    attempt_id: Mapped[str] = mapped_column(String(64), default="")
    journal_state: Mapped[str] = mapped_column(String(32), default="unknown")
    digest: Mapped[str] = mapped_column(String(128), default="")
    run: Mapped[Run] = relationship()


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    credential_hash: Mapped[str] = mapped_column(String(128))
    organization: Mapped[Organization] = relationship(
        primaryjoin="Device.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )


class DeviceGrant(Base):
    __tablename__ = "device_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    grant_scope: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device: Mapped[Device] = relationship()
    organization: Mapped[Organization] = relationship(
        primaryjoin="DeviceGrant.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    object_key: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    run: Mapped[Run] = relationship()


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("run_id", "model_id", "price_version", name="uq_usage_once"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    model_id: Mapped[str] = mapped_column(String(128))
    price_version: Mapped[str] = mapped_column(String(32))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    amount: Mapped[str] = mapped_column(String(32), default="0")
    run: Mapped[Run] = relationship()


WEB_TABLES = (
    "users",
    "organizations",
    "memberships",
    "projects",
    "sessions",
    "runs",
    "run_events",
    "outbox",
    "approvals",
    "tool_invocations",
    "devices",
    "device_grants",
    "artifacts",
    "usage_records",
)


def apply_web_schema(connection) -> None:
    """Create the web tables. Callers own the transaction."""
    Base.metadata.create_all(connection)


def drop_web_schema(connection) -> None:
    """Drop only these tables. Never touches a desktop task directory."""
    Base.metadata.drop_all(connection)


def seed_demo(db: Session) -> Project:
    """Insert one demo tenant and project. A second call keeps the same row."""
    existing = db.query(Project).filter_by(tenant_id="demo", name="demo").one_or_none()
    if existing is not None:
        return existing
    db.add(User(id="user-demo", github_id=None, kind="local"))
    db.add(Organization(id="org-demo", tenant_id="demo"))
    project = Project(id="project-demo", tenant_id="demo", name="demo", repo_config={})
    db.add(project)
    db.flush()
    return project


def import_desktop_tasks(store: Any, db: Session, *, tenant_id: str, project_id: str) -> int:
    """Copy legacy task rows into sessions. Does not save the JSON store."""
    inserted = 0
    for row in store.read_legacy_rows():
        legacy_id = str(row.get("session_id") or row.get("id") or "")
        if not legacy_id:
            continue
        found = db.get(SessionRow, legacy_id)
        if found is not None:
            continue
        db.add(
            SessionRow(
                id=legacy_id,
                tenant_id=tenant_id,
                project_id=project_id,
                title=str(row.get("title") or ""),
            )
        )
        inserted += 1
    db.flush()
    return inserted
