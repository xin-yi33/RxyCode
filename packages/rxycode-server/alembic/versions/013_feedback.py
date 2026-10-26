"""Feedback library: batches (quantitative, version-bucketed), items, images.

``feedback_batches`` 以部分唯一索引 ``uq_feedback_batches_open`` 保证任意
时刻至多一个 open 批次 —— 并发提交抢批时撞索引回滚重试。``feedback_items``
按 ``(user_id, request_id)`` 幂等、按 ``content_sha256`` 做 24h 去重键；
``feedback_images`` 暂存重编码后的截图（24h 过期），提交时绑定条目。

All DDL is guarded so a partially-applied earlier attempt can be re-run.

Revision ID: 013_feedback
Revises: 012_files_batch
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013_feedback"
down_revision = "012_files_batch"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()

    # -- feedback_batches -----------------------------------------------------
    if "feedback_batches" not in tables:
        op.create_table(
            "feedback_batches",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
            sa.Column("build_commit", sa.String(length=64), server_default="", nullable=False),
            sa.Column("capacity", sa.Integer(), server_default="20", nullable=False),
            sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("summary", postgresql.JSONB(), nullable=True),
            sa.UniqueConstraint("seq", name="uq_feedback_batches_seq"),
        )
    if "uq_feedback_batches_open" not in _indexes("feedback_batches"):
        op.create_index(
            "uq_feedback_batches_open",
            "feedback_batches",
            ["status"],
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
        )

    # -- feedback_items --------------------------------------------------------
    if "feedback_items" not in tables:
        op.create_table(
            "feedback_items",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "batch_id",
                sa.String(length=64),
                sa.ForeignKey("feedback_batches.id"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("request_id", sa.String(length=64), server_default="", nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("module", sa.String(length=32), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
            sa.Column("trigger_reasons", postgresql.JSONB(), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("session_id", sa.String(length=64), nullable=True),
            sa.Column("page_path", sa.String(length=300), server_default="", nullable=False),
            sa.Column("build_commit", sa.String(length=64), server_default="", nullable=False),
            sa.Column("client_build", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=300), server_default="", nullable=False),
            sa.Column("viewport", sa.String(length=32), nullable=True),
            sa.Column("locale", sa.String(length=16), nullable=True),
            sa.Column("content_sha256", sa.String(length=64), server_default="", nullable=False),
            sa.Column("ip_hmac", sa.String(length=64), server_default="", nullable=False),
            sa.Column("state", sa.String(length=16), server_default="new", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("user_id", "request_id", name="uq_feedback_user_request"),
        )
    indexes = _indexes("feedback_items")
    if "ix_feedback_items_user_created" not in indexes:
        op.create_index(
            "ix_feedback_items_user_created", "feedback_items", ["user_id", "created_at"]
        )
    if "ix_feedback_items_batch" not in indexes:
        op.create_index("ix_feedback_items_batch", "feedback_items", ["batch_id"])
    if "ix_feedback_items_sha" not in indexes:
        op.create_index("ix_feedback_items_sha", "feedback_items", ["content_sha256"])

    # -- feedback_images -------------------------------------------------------
    if "feedback_images" not in tables:
        op.create_table(
            "feedback_images",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column(
                "item_id",
                sa.String(length=64),
                sa.ForeignKey("feedback_items.id"),
                nullable=True,
            ),
            sa.Column("state", sa.String(length=16), server_default="staged", nullable=False),
            sa.Column("blob_key", sa.String(length=500), server_default="", nullable=False),
            sa.Column("sha256", sa.String(length=64), server_default="", nullable=False),
            sa.Column("content_type", sa.String(length=32), nullable=False),
            sa.Column("width", sa.Integer(), server_default="0", nullable=False),
            sa.Column("height", sa.Integer(), server_default="0", nullable=False),
            sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "ix_feedback_images_user" not in _indexes("feedback_images"):
        op.create_index("ix_feedback_images_user", "feedback_images", ["user_id", "state"])


def downgrade() -> None:
    tables = _tables()
    if "feedback_images" in tables:
        op.drop_index("ix_feedback_images_user", table_name="feedback_images")
        op.drop_table("feedback_images")
    if "feedback_items" in tables:
        op.drop_index("ix_feedback_items_sha", table_name="feedback_items")
        op.drop_index("ix_feedback_items_batch", table_name="feedback_items")
        op.drop_index("ix_feedback_items_user_created", table_name="feedback_items")
        op.drop_table("feedback_items")
    if "feedback_batches" in tables:
        op.drop_index("uq_feedback_batches_open", table_name="feedback_batches")
        op.drop_table("feedback_batches")
