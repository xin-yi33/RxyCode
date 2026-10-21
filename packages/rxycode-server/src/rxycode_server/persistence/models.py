"""SQLAlchemy 2 models for the web business database.

Cloud users are rows here, not JSON files. Every business row carries tenant_id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
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
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    default_project_id: Mapped[str | None] = mapped_column(String(64))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    verifier: Mapped[str] = mapped_column(String(128))
    browser_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    """One-time password-reset token — only the HMAC digest is ever stored."""

    __tablename__ = "password_resets"
    __table_args__ = (Index("ix_password_resets_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class Invite(Base):
    __tablename__ = "invites"

    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


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
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id"),
    )

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
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="fk_sessions_project_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sessions_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    project_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    organization: Mapped[Organization] = relationship(
        primaryjoin="SessionRow.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
        overlaps="project",
    )
    project: Mapped[Project] = relationship(
        primaryjoin="and_(SessionRow.project_id == Project.id, SessionRow.tenant_id == Project.tenant_id)",
        foreign_keys=[project_id, tenant_id],
        overlaps="organization",
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_runs_tenant_request"),
        UniqueConstraint("tenant_id", "id", name="uq_runs_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["sessions.tenant_id", "sessions.id"],
            name="fk_runs_session_tenant",
        ),
        Index(
            "uq_runs_one_active_per_session",
            "session_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running', 'leased', 'cancel_requested', 'waiting_approval')"
            ),
        ),
        Index("ix_runs_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    session_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(128), default="")
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    # cloud:{tenant_id}:{project_id} — 71 chars with hex uuids; needs >64.
    target_id: Mapped[str] = mapped_column(String(128), default="")
    organization: Mapped[Organization] = relationship(
        primaryjoin="Run.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
        overlaps="session",
    )
    session: Mapped[SessionRow] = relationship(
        primaryjoin="and_(Run.session_id == SessionRow.id, Run.tenant_id == SessionRow.tenant_id)",
        foreign_keys=[session_id, tenant_id],
        overlaps="organization",
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_run_events_run_tenant",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[Run] = relationship(
        primaryjoin="and_(RunEvent.run_id == Run.id, RunEvent.tenant_id == Run.tenant_id)",
        foreign_keys=[run_id, tenant_id],
        overlaps="organization",
    )
    organization: Mapped[Organization] = relationship(
        primaryjoin="RunEvent.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
        overlaps="run",
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_approvals_run_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    run_id: Mapped[str] = mapped_column(String(64))
    call_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="approval", server_default="approval")
    status: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    organization: Mapped[Organization] = relationship(
        primaryjoin="Approval.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
        overlaps="run",
    )
    run: Mapped[Run] = relationship(
        primaryjoin="and_(Approval.run_id == Run.id, Approval.tenant_id == Run.tenant_id)",
        foreign_keys=[run_id, tenant_id],
        overlaps="organization",
    )


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
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_devices_tenant_id"),)
    organization: Mapped[Organization] = relationship(
        primaryjoin="Device.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )


class DeviceGrant(Base):
    __tablename__ = "device_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "device_id"],
            ["devices.tenant_id", "devices.id"],
            name="fk_device_grants_device_tenant",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    grant_scope: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device: Mapped[Device] = relationship(
        primaryjoin="and_(DeviceGrant.device_id == Device.id, DeviceGrant.tenant_id == Device.tenant_id)",
        foreign_keys=[device_id, tenant_id],
        overlaps="organization",
    )
    organization: Mapped[Organization] = relationship(
        primaryjoin="DeviceGrant.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
        overlaps="device",
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
    "auth_sessions",
    "oauth_states",
    "invites",
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
