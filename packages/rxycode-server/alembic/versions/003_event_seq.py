"""Remember the highest event seq after old rows are pruned.

Revision ID: 003_event_seq
Revises: 002_cancel_active
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003_event_seq"
down_revision = "002_cancel_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("runs")}
    if "event_seq" not in columns:
        op.add_column("runs", sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE runs
        SET event_seq = GREATEST(
            event_seq,
            COALESCE((SELECT MAX(seq) FROM run_events WHERE run_events.run_id = runs.id), 0)
        )
        """
    )


def downgrade() -> None:
    op.drop_column("runs", "event_seq")
