"""Park a turn on a Harness checkpoint: approval checkpoints, durable questions.

Revision ID: 005_harness_checkpoint
Revises: 004_waiting_approval
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_harness_checkpoint"
down_revision = "004_waiting_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("approvals")}
    if "kind" not in columns:
        op.add_column(
            "approvals",
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="approval"),
        )
    if "answer" not in columns:
        op.add_column("approvals", sa.Column("answer", sa.Text(), nullable=True))
    if "checkpoint" not in columns:
        op.add_column(
            "approvals",
            sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("approvals", "checkpoint")
    op.drop_column("approvals", "answer")
    op.drop_column("approvals", "kind")
