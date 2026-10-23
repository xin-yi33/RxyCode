"""auth and run-history schema (WEB-W9-B1/B2)

Persistent auth sessions, OAuth states, invites, richer user rows, and the
``runs.created_at`` / ``sessions.updated_at`` timestamps the task and history
contracts need. All DDL is guarded so it survives a partially-applied earlier
attempt.

Revision ID: 006_auth_and_runs
Revises: 005_harness_checkpoint
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006_auth_and_runs"
down_revision = "005_harness_checkpoint"
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
    columns = _columns("users") if "users" in tables else set()
    with op.batch_alter_table("users") as batch:
        if "email" not in columns:
            batch.add_column(sa.Column("email", sa.String(length=320), nullable=True))
        if "password_hash" not in columns:
            batch.add_column(sa.Column("password_hash", sa.String(length=200), nullable=True))
        if "display_name" not in columns:
            batch.add_column(sa.Column("display_name", sa.String(length=200), nullable=True))
        if "created_at" not in columns:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                )
            )
        if "default_project_id" not in columns:
            batch.add_column(sa.Column("default_project_id", sa.String(length=64), nullable=True))
        if "disabled_at" not in columns:
            batch.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
        if "email" not in columns:
            batch.create_unique_constraint("uq_users_email", ["email"])

    tables = _tables()
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("token_hash", sa.String(length=128), primary_key=True),
            sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])

    if "oauth_states" not in tables:
        op.create_table(
            "oauth_states",
            sa.Column("state", sa.String(length=128), primary_key=True),
            sa.Column("verifier", sa.String(length=128), nullable=False),
            sa.Column("browser_hash", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "invites" not in tables:
        op.create_table(
            "invites",
            sa.Column("code_hash", sa.String(length=128), primary_key=True),
            sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        )

    if "runs" in _tables():
        columns = _columns("runs")
        if "target_id" in columns:
            # cloud:{tenant_id}:{project_id} needs more than varchar(64).
            op.alter_column(
                "runs",
                "target_id",
                existing_type=sa.String(length=64),
                type_=sa.String(length=128),
            )
        if "created_at" not in columns:
            op.add_column(
                "runs",
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
            )
        if "ix_runs_session_created" not in _indexes("runs"):
            op.create_index("ix_runs_session_created", "runs", ["session_id", "created_at"])

    if "sessions" in _tables() and "updated_at" not in _columns("sessions"):
        op.add_column(
            "sessions",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
