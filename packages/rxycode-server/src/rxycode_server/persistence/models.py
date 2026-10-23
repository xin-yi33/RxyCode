"""SQLAlchemy 2 models for the web business database.

Cloud users are rows here, not JSON files. Every business row carries tenant_id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
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
    default_model_ref: Mapped[str | None] = mapped_column(String(64))
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
    # Display-only metadata captured at login — never a credential.
    device_label: Mapped[str] = mapped_column(String(128), default="")
    ip_hint: Mapped[str] = mapped_column(String(64), default="")
    user: Mapped[User] = relationship()


class DeviceLock(Base):
    """Single active-device lock — one session holds the data plane at a time.

    ``token_hash`` names the holding ``auth_sessions`` row; ``last_seen_at``
    is the keepalive — a lock idle past 10 minutes is implicitly released
    (next claim or non-holder request takes it). Sessions themselves are
    never revoked: the displaced device keeps auto-login and can re-claim.
    """

    __tablename__ = "device_locks"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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


class EmailCode(Base):
    """One-time 6-digit email code — register / login / password-reset.

    Only the HMAC digest of ``{purpose}:{email}:{code}`` is stored, so a
    database read never yields a usable code. ``user_id`` is nullable:
    register codes are issued before the account exists.
    """

    __tablename__ = "email_codes"
    __table_args__ = (Index("ix_email_codes_purpose_email", "purpose", "email"),)

    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16))
    email: Mapped[str] = mapped_column(String(320))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User | None] = relationship()


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
    # default = shared memory scope; project_only = memory stays in-project.
    memory_mode: Mapped[str] = mapped_column(String(16), default="default")
    # The tenant's catch-all "无项目" container — never listed as a user
    # project and never deletable.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    # Idempotent-create key — partial unique index lives in migration 011.
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
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
    # Unknown for pre-migration rows — null is honest, never fabricated.
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # archived = server-side execution freeze; deleted_at = sealed tombstone
    # that every read path must exclude before async content cleanup runs.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="cloud")
    source: Mapped[str] = mapped_column(String(16), default="chat")
    revision: Mapped[int] = mapped_column(Integer, default=0)
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
    # BYOK run snapshot — the model this run was submitted with. Immutable
    # after creation; survives connection deletion (no FK on purpose).
    # Never carries key material.
    model_ref: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(256))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    provider_name: Mapped[str | None] = mapped_column(String(128))
    credential_source: Mapped[str | None] = mapped_column(String(16))
    connection_id: Mapped[str | None] = mapped_column(String(64))
    credential_version: Mapped[int | None] = mapped_column(Integer)
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


class ModelConnection(Base):
    """A user's BYOK provider connection — encrypted credential holder.

    ``ciphertext``/``nonce``/``key_id`` are AES-256-GCM sealed under the
    deployment keyring with AAD binding (tenant, owner, connection,
    credential_version); the plaintext key never touches the database,
    events, logs, or any response.
    """

    __tablename__ = "model_connections"
    __table_args__ = (Index("ix_model_connections_tenant_owner", "tenant_id", "owner_user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    provider_id: Mapped[str] = mapped_column(String(64), default="")
    provider_name: Mapped[str] = mapped_column(String(128), default="")
    display_name: Mapped[str] = mapped_column(String(128), default="")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    api_transport: Mapped[str | None] = mapped_column(String(32))
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(String(32))
    encryption_version: Mapped[int] = mapped_column(Integer, default=1)
    credential_version: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="active")
    test_status: Mapped[str] = mapped_column(String(16), default="untested")
    test_error: Mapped[str | None] = mapped_column(String(256))
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    organization: Mapped[Organization] = relationship(
        primaryjoin="ModelConnection.tenant_id == Organization.tenant_id",
        foreign_keys=[tenant_id],
    )
    owner: Mapped[User] = relationship()


class UserModel(Base):
    """One catalogued model on a user's connection. ``id`` is the
    ``model_ref`` clients submit runs with."""

    __tablename__ = "user_models"
    __table_args__ = (
        UniqueConstraint("connection_id", "model_id", name="uq_user_models_connection_model"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("organizations.tenant_id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("model_connections.id", ondelete="CASCADE")
    )
    model_id: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(256), default="")
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    connection: Mapped[ModelConnection] = relationship()


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
    filename: Mapped[str] = mapped_column(String(400), server_default="", default="")
    relative_path: Mapped[str] = mapped_column(String(500), server_default="", default="")
    availability: Mapped[str] = mapped_column(String(24), server_default="available", default="available")
    partial: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    preview_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), server_default="", default="")
    run: Mapped[Run] = relationship()


class Attachment(Base):
    """A file the user attached to a run. Staged bytes live in the attachment
    store; the row carries state, digest, and the run/session binding."""

    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_user", "owner_user_id", "created_at"),
        Index("ix_attachments_session", "tenant_id", "session_id"),
        Index(
            "uq_attachments_request",
            "owner_user_id",
            "request_id",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL AND request_id <> ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str] = mapped_column(String(400))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    declared_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    received_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(24), server_default="created", default="created")
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    object_key: Mapped[str] = mapped_column(String(500), server_default="", default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class PreviewJob(Base):
    """One artifact → preview conversion. Status + location are the contract;
    a failed job carries an honest reason code."""

    __tablename__ = "preview_jobs"
    __table_args__ = (
        Index("ix_preview_jobs_run", "run_id"),
        Index("ix_preview_jobs_artifact", "artifact_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), server_default="queued", default="queued")
    entrypoint: Mapped[str | None] = mapped_column(String(400), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    artifact: Mapped[Artifact] = relationship()


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


class UserSessionMeta(Base):
    """Per-user navigation state for a session — pin is a preference, not a
    permission. Ordering positions are optional ints; null = unordered."""

    __tablename__ = "user_session_meta"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_order: Mapped[int | None] = mapped_column(Integer)
    manual_order: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserProjectMeta(Base):
    __tablename__ = "user_project_meta"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_order: Mapped[int | None] = mapped_column(Integer)
    # 手动排序（scope=projects）；与 pin_order 分开——置顶只决定排前面。
    manual_order: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserPreference(Base):
    """Server-authoritative user preferences — whitelist fields only."""

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    locale: Mapped[str] = mapped_column(String(16), default="auto")
    sidebar: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    appearance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SidebarOrder(Base):
    """Manual ordering for one sidebar scope. ``project_id`` is "" unless the
    scope is per-project session ordering."""

    __tablename__ = "sidebar_orders"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    ordered_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ScheduleExecution(Base):
    """One firing of a web schedule. ``(schedule_id, scheduled_for)`` is the
    idempotency key — concurrent ticks on different replicas can only ever
    create one run for one due slot."""

    __tablename__ = "schedule_executions"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_for", name="uq_schedule_fire_once"),
        Index("ix_schedule_executions_schedule", "schedule_id", "scheduled_for"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    schedule_id: Mapped[str] = mapped_column(String(64))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    schedule_revision: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(String(64))
    # queued/running/waiting/succeeded/failed/cancelled/skipped_busy/missed
    status: Mapped[str] = mapped_column(String(24), default="queued")
    reason: Mapped[str] = mapped_column(Text, default="")
    notification_status: Mapped[str] = mapped_column(String(16), default="none")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class NotificationPreference(Base):
    """Per-category channel choice; empty channel list = the category is off."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    channels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class PushSubscription(Base):
    """A registered Web Push endpoint. ``endpoint_hash`` dedupes without
    indexing the long URL."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "endpoint_hash", name="uq_push_user_endpoint"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    endpoint_hash: Mapped[str] = mapped_column(String(128))
    endpoint: Mapped[str] = mapped_column(Text)
    keys: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class EmailDelivery(Base):
    """Outbound task-result email. ``(run_id, recipient, kind)`` dedupes —
    one intended email per terminal run, regardless of retries."""

    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("run_id", "recipient", "kind", name="uq_email_delivery_once"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(64))
    notification_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64))
    schedule_id: Mapped[str | None] = mapped_column(String(64))
    recipient: Mapped[str] = mapped_column(String(320))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ReauthTicket(Base):
    """Short-lived step-up proof — the digest is stored, never the ticket."""

    __tablename__ = "reauth_tickets"
    __table_args__ = (Index("ix_reauth_tickets_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebAuthnCredential(Base):
    """Public credential metadata — credential_id/public_key are public key
    material, not secrets; the private key never leaves the authenticator."""

    __tablename__ = "webauthn_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id_hash", name="uq_webauthn_credential"),
        Index("ix_webauthn_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    credential_id: Mapped[str] = mapped_column(String(512), default="")
    credential_id_hash: Mapped[str] = mapped_column(String(128))
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(128), default="")
    transports: Mapped[list[str]] = mapped_column(JSONB, default=list)
    aaguid: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebAuthnChallenge(Base):
    """One-time, time-boxed challenge — the digest is stored."""

    __tablename__ = "webauthn_challenges"
    __table_args__ = (Index("ix_webauthn_challenges_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    challenge_hash: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TotpEnrollment(Base):
    """TOTP seed sealed with the deployment keyring — required at verify time,
    so it is encrypted (AES-256-GCM), not hashed. Never logged or returned."""

    __tablename__ = "totp_enrollments"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(Base):
    """One-time backup code — only the HMAC digest is stored."""

    __tablename__ = "recovery_codes"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SmsEnrollment(Base):
    """SMS MFA state — the phone number is personal data, not a secret."""

    __tablename__ = "sms_enrollments"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone_e164: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthorizedApp(Base):
    """Third-party grants — populated only once an IdP exists."""

    __tablename__ = "authorized_apps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SecurityEvent(Base):
    """Append-only login/security history — never secrets, codes or keys."""

    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_user", "user_id", "at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    result: Mapped[str] = mapped_column(String(16), default="ok")
    device_label: Mapped[str] = mapped_column(String(128), default="")
    ip_hint: Mapped[str] = mapped_column(String(64), default="")


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
    "attachments",
    "preview_jobs",
    "usage_records",
    "auth_sessions",
    "device_locks",
    "oauth_states",
    "invites",
    "password_resets",
    "email_codes",
    "model_connections",
    "user_models",
    "user_session_meta",
    "user_project_meta",
    "user_preferences",
    "sidebar_orders",
    "schedule_executions",
    "notification_preferences",
    "push_subscriptions",
    "email_deliveries",
    "reauth_tickets",
    "webauthn_credentials",
    "webauthn_challenges",
    "totp_enrollments",
    "sms_enrollments",
    "recovery_codes",
    "security_events",
    "authorized_apps",
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
