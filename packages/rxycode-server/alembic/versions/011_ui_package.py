"""UI-2026-10-22 package: session lifecycle, projects, preferences, schedules.

``sessions`` gains the lifecycle columns (archived/deleted tombstones, origin,
source, created_at, revision). ``projects`` gains memory_mode/is_default/
revision. Per-user navigation preference lives in ``user_session_meta`` /
``user_project_meta`` (pin + order), ``user_preferences`` (locale, sidebar,
appearance) and ``sidebar_orders`` (manual ordering per scope).

``web_schedules`` gains the real task fields (name, message, timezone,
model_ref, permission_profile, request_id dedupe, revision) and
``schedule_executions`` records each firing with the (schedule_id,
scheduled_for) idempotency key. Notification categories, push subscriptions
and email deliveries close the notify loop. Security extension tables cover
reauth tickets, WebAuthn credentials, TOTP enrollment, recovery codes and
the per-user security event log.

All DDL is guarded so a partially-applied earlier attempt can be re-run.

Revision ID: 011_ui_package
Revises: 010_device_locks
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011_ui_package"
down_revision = "010_device_locks"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()

    # -- sessions lifecycle -------------------------------------------------
    if "sessions" in tables:
        cols = _columns("sessions")
        with op.batch_alter_table("sessions") as batch:
            if "created_at" not in cols:
                batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
            if "archived_at" not in cols:
                batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
            if "deleted_at" not in cols:
                batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
            if "origin" not in cols:
                batch.add_column(
                    sa.Column("origin", sa.String(length=16), server_default="cloud", nullable=False)
                )
            if "source" not in cols:
                batch.add_column(
                    sa.Column("source", sa.String(length=16), server_default="chat", nullable=False)
                )
            if "revision" not in cols:
                batch.add_column(
                    sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
                )

    # -- projects ------------------------------------------------------------
    if "projects" in tables:
        cols = _columns("projects")
        with op.batch_alter_table("projects") as batch:
            if "memory_mode" not in cols:
                batch.add_column(
                    sa.Column(
                        "memory_mode", sa.String(length=16), server_default="default", nullable=False
                    )
                )
            if "is_default" not in cols:
                batch.add_column(
                    sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False)
                )
            if "revision" not in cols:
                batch.add_column(
                    sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
                )
            if "created_at" not in cols:
                batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
            if "request_id" not in cols:
                batch.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        if "uq_projects_request" not in _indexes("projects"):
            op.create_index(
                "uq_projects_request",
                "projects",
                ["tenant_id", "request_id"],
                unique=True,
                postgresql_where=sa.text("request_id IS NOT NULL AND request_id <> ''"),
            )
        # Mark each user's stored default project as the default container.
        op.execute(
            sa.text(
                """
                UPDATE projects SET is_default = true
                FROM users u, memberships m
                WHERE projects.id = u.default_project_id
                  AND u.id = m.user_id
                  AND projects.tenant_id = m.tenant_id
                """
            )
        )

    # -- per-user navigation state ------------------------------------------
    if "user_session_meta" not in tables:
        op.create_table(
            "user_session_meta",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("session_id", sa.String(length=64), primary_key=True),
            sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("pin_order", sa.Integer(), nullable=True),
            sa.Column("manual_order", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    if "user_project_meta" not in tables:
        op.create_table(
            "user_project_meta",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("project_id", sa.String(length=64), primary_key=True),
            sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("pin_order", sa.Integer(), nullable=True),
            sa.Column("manual_order", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    else:
        op.execute("ALTER TABLE user_project_meta ADD COLUMN IF NOT EXISTS manual_order integer")

    # -- preferences + manual ordering ---------------------------------------
    if "user_preferences" not in tables:
        op.create_table(
            "user_preferences",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column("locale", sa.String(length=16), server_default="auto", nullable=False),
            sa.Column("sidebar", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column("appearance", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    if "sidebar_orders" not in tables:
        op.create_table(
            "sidebar_orders",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("scope", sa.String(length=32), primary_key=True),
            sa.Column("project_id", sa.String(length=64), primary_key=True, server_default=""),
            sa.Column("ordered_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    # -- product tables previously created by ensure_tables() ----------------
    # Alembic now owns them so ordering with the new FK is deterministic;
    # ensure_tables stays as an idempotent safety net.
    if "web_memories" not in tables:
        op.create_table(
            "web_memories",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.String(length=64), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
    if "web_schedules" not in tables:
        op.create_table(
            "web_schedules",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), server_default="", nullable=False),
            sa.Column("rule", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("notify", sa.Boolean(), nullable=False),
            sa.Column("next_fire", sa.String(length=40), nullable=True),
            sa.Column("last_run_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
    if "web_notifications" not in tables:
        op.create_table(
            "web_notifications",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
        )
    if "web_unsubscribes" not in tables:
        op.create_table(
            "web_unsubscribes",
            sa.Column("tenant_id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), primary_key=True),
            sa.Column("kind", sa.String(length=64), primary_key=True),
        )
    if (
        "web_notifications" in _tables()
        and "uq_web_notifications_once" not in _indexes("web_notifications")
    ):
        op.create_index(
            "uq_web_notifications_once",
            "web_notifications",
            ["tenant_id", "user_id", "run_id", "kind"],
            unique=True,
        )
    tables = _tables()

    # -- schedules: real task fields + firing ledger --------------------------
    if "web_schedules" in tables:
        cols = _columns("web_schedules")
        with op.batch_alter_table("web_schedules") as batch:
            if "name" not in cols:
                batch.add_column(
                    sa.Column("name", sa.String(length=100), server_default="", nullable=False)
                )
            if "message" not in cols:
                batch.add_column(sa.Column("message", sa.Text(), server_default="", nullable=False))
            if "timezone" not in cols:
                batch.add_column(
                    sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False)
                )
            if "model_ref" not in cols:
                batch.add_column(sa.Column("model_ref", sa.String(length=64), nullable=True))
            if "permission_profile" not in cols:
                batch.add_column(
                    sa.Column(
                        "permission_profile",
                        sa.String(length=16),
                        server_default="confirm",
                        nullable=False,
                    )
                )
            if "request_id" not in cols:
                batch.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
            if "revision" not in cols:
                batch.add_column(
                    sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
                )
            if "blocked_reason" not in cols:
                batch.add_column(
                    sa.Column("blocked_reason", sa.String(length=64), server_default="", nullable=False)
                )
        if "uq_web_schedules_request" not in _indexes("web_schedules"):
            op.create_index(
                "uq_web_schedules_request",
                "web_schedules",
                ["tenant_id", "user_id", "request_id"],
                unique=True,
                postgresql_where=sa.text("request_id IS NOT NULL AND request_id <> ''"),
            )

    if "schedule_executions" not in tables:
        op.create_table(
            "schedule_executions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column(
                "schedule_id",
                sa.String(length=64),
                sa.ForeignKey("web_schedules.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
            sa.Column("schedule_revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
            sa.Column("reason", sa.Text(), server_default="", nullable=False),
            sa.Column(
                "notification_status", sa.String(length=16), server_default="none", nullable=False
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint("schedule_id", "scheduled_for", name="uq_schedule_fire_once"),
        )
        op.create_index(
            "ix_schedule_executions_schedule",
            "schedule_executions",
            ["schedule_id", "scheduled_for"],
        )

    # -- notification preferences, push, email delivery -----------------------
    if "notification_preferences" not in tables:
        op.create_table(
            "notification_preferences",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("category", sa.String(length=32), primary_key=True),
            sa.Column("channels", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
    if "push_subscriptions" not in tables:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("endpoint_hash", sa.String(length=128), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("keys", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint("user_id", "endpoint_hash", name="uq_push_user_endpoint"),
        )
    if "email_deliveries" not in tables:
        op.create_table(
            "email_deliveries",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("notification_id", sa.String(length=64), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("schedule_id", sa.String(length=64), nullable=True),
            sa.Column("recipient", sa.String(length=320), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error", sa.Text(), server_default="", nullable=False),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "run_id", "recipient", "kind", name="uq_email_delivery_once"
            ),
        )

    # -- web_notifications extra columns (raw-SQL table owned by W9) ----------
    if "web_notifications" in tables:
        cols = _columns("web_notifications")
        with op.batch_alter_table("web_notifications") as batch:
            if "title" not in cols:
                batch.add_column(
                    sa.Column("title", sa.String(length=200), server_default="", nullable=False)
                )
            if "read_at" not in cols:
                batch.add_column(sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
            if "category" not in cols:
                batch.add_column(
                    sa.Column(
                        "category",
                        sa.String(length=32),
                        server_default="agent_tasks",
                        nullable=False,
                    )
                )
            if "delivery" not in cols:
                batch.add_column(
                    sa.Column(
                        "delivery", sa.String(length=16), server_default="in_app", nullable=False
                    )
                )
            if "created_at" not in cols:
                batch.add_column(
                    sa.Column(
                        "created_at",
                        sa.DateTime(timezone=True),
                        server_default=sa.text("now()"),
                        nullable=True,
                    )
                )

    # -- security extension ----------------------------------------------------
    if "reauth_tickets" not in tables:
        op.create_table(
            "reauth_tickets",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_reauth_tickets_user", "reauth_tickets", ["user_id"])

    if "webauthn_credentials" not in tables:
        op.create_table(
            "webauthn_credentials",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("credential_id", sa.String(length=512), server_default="", nullable=False),
            sa.Column("credential_id_hash", sa.String(length=128), nullable=False),
            sa.Column("public_key", sa.LargeBinary(), nullable=False),
            sa.Column("sign_count", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column("name", sa.String(length=128), server_default="", nullable=False),
            sa.Column("transports", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column("aaguid", sa.String(length=64), server_default="", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("credential_id_hash", name="uq_webauthn_credential"),
        )
        op.create_index("ix_webauthn_user", "webauthn_credentials", ["user_id"])

    if "webauthn_challenges" not in tables:
        op.create_table(
            "webauthn_challenges",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("challenge_hash", sa.String(length=128), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_webauthn_challenges_user", "webauthn_challenges", ["user_id"])

    if "totp_enrollments" not in tables:
        op.create_table(
            "totp_enrollments",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
            sa.Column("nonce", sa.LargeBinary(), nullable=False),
            sa.Column("key_id", sa.String(length=32), server_default="", nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "recovery_codes" not in tables:
        op.create_table(
            "recovery_codes",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("code_hash", sa.String(length=128), primary_key=True),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    if "security_events" not in tables:
        op.create_table(
            "security_events",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column(
                "at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("result", sa.String(length=16), server_default="ok", nullable=False),
            sa.Column("device_label", sa.String(length=128), server_default="", nullable=False),
            sa.Column("ip_hint", sa.String(length=64), server_default="", nullable=False),
        )
        op.create_index("ix_security_events_user", "security_events", ["user_id", "at"])

    # auth_sessions: label + ip hint for the sessions list.
    if "auth_sessions" in tables:
        cols = _columns("auth_sessions")
        with op.batch_alter_table("auth_sessions") as batch:
            if "device_label" not in cols:
                batch.add_column(
                    sa.Column("device_label", sa.String(length=128), server_default="", nullable=False)
                )
            if "ip_hint" not in cols:
                batch.add_column(
                    sa.Column("ip_hint", sa.String(length=64), server_default="", nullable=False)
                )

    if "sms_enrollments" not in tables:
        op.create_table(
            "sms_enrollments",
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("phone_e164", sa.String(length=32), server_default="", nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Third-party app grants — rows only appear once an IdP/authorization
    # service exists; the capability flag gates the UI until then.
    if "authorized_apps" not in tables:
        op.create_table(
            "authorized_apps",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("scopes", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
        op.create_index("ix_authorized_apps_user", "authorized_apps", ["user_id"])


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
