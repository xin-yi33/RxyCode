"""UI-2026-10-22 files batch: prompt attachments, artifact manifest columns, preview jobs.

``attachments`` stages user files before they are bound to a run. ``artifacts``
gains the manifest columns (filename, relative_path, availability, partial,
preview_kind) so the run artifact list can describe every deliverable.
``preview_jobs`` records each artifact → preview conversion with an honest
failure reason.

All DDL is guarded so a partially-applied earlier attempt can be re-run.

Revision ID: 012_files_batch
Revises: 011_ui_package
Create Date: 2026-10-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012_files_batch"
down_revision = "011_ui_package"
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

    # -- artifacts manifest columns ------------------------------------------
    if "artifacts" in tables:
        cols = _columns("artifacts")
        with op.batch_alter_table("artifacts") as batch:
            if "filename" not in cols:
                batch.add_column(
                    sa.Column("filename", sa.String(length=400), server_default="", nullable=False)
                )
            if "relative_path" not in cols:
                batch.add_column(
                    sa.Column(
                        "relative_path", sa.String(length=500), server_default="", nullable=False
                    )
                )
            if "availability" not in cols:
                batch.add_column(
                    sa.Column(
                        "availability",
                        sa.String(length=24),
                        server_default="available",
                        nullable=False,
                    )
                )
            if "partial" not in cols:
                batch.add_column(
                    sa.Column("partial", sa.Boolean(), server_default=sa.false(), nullable=False)
                )
            if "preview_kind" not in cols:
                batch.add_column(sa.Column("preview_kind", sa.String(length=24), nullable=True))
            if "created_at" not in cols:
                batch.add_column(
                    sa.Column(
                        "created_at", sa.String(length=40), server_default="", nullable=False
                    )
                )

    # -- attachments -----------------------------------------------------------
    if "attachments" not in tables:
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("owner_user_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("filename", sa.String(length=400), nullable=False),
            sa.Column(
                "content_type",
                sa.String(length=128),
                server_default="application/octet-stream",
                nullable=False,
            ),
            sa.Column("declared_size", sa.Integer(), nullable=True),
            sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("received_bytes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=True),
            sa.Column("state", sa.String(length=24), server_default="created", nullable=False),
            sa.Column("stage", sa.String(length=24), nullable=True),
            sa.Column("object_key", sa.String(length=500), server_default="", nullable=False),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column("expires_at", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
        op.create_index(
            "uq_attachments_request",
            "attachments",
            ["owner_user_id", "request_id"],
            unique=True,
            postgresql_where=sa.text("request_id IS NOT NULL AND request_id <> ''"),
        )
        op.create_index("ix_attachments_user", "attachments", ["owner_user_id", "created_at"])
        op.create_index(
            "ix_attachments_session", "attachments", ["tenant_id", "session_id"]
        )
        op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])
        op.create_index("ix_attachments_owner_user_id", "attachments", ["owner_user_id"])

    # -- preview jobs -----------------------------------------------------------
    if "preview_jobs" not in tables:
        op.create_table(
            "preview_jobs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column(
                "artifact_id",
                sa.String(length=64),
                sa.ForeignKey("artifacts.id"),
                nullable=False,
            ),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
            sa.Column("entrypoint", sa.String(length=400), nullable=True),
            sa.Column("preview_url", sa.String(length=400), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column("expires_at", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
        op.create_index("ix_preview_jobs_run", "preview_jobs", ["run_id"])
        op.create_index("ix_preview_jobs_artifact", "preview_jobs", ["artifact_id"])
        op.create_index("ix_preview_jobs_tenant_id", "preview_jobs", ["tenant_id"])


def downgrade() -> None:
    tables = _tables()
    if "preview_jobs" in tables:
        op.drop_table("preview_jobs")
    if "attachments" in tables:
        op.drop_table("attachments")
    if "artifacts" in tables:
        cols = _columns("artifacts")
        with op.batch_alter_table("artifacts") as batch:
            for name in (
                "created_at",
                "preview_kind",
                "partial",
                "availability",
                "relative_path",
                "filename",
            ):
                if name in cols:
                    batch.drop_column(name)
